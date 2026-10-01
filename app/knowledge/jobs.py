"""Snapshot job execution with lease, retry bounds and crash recovery.

Designed to be driven by a worker loop (in-process thread now, separate OCR /
analysis workers later). One cross-process FileLock guards all knowledge
mutating commands, mirroring the first-layer ingest lock pattern.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from library.config import Config
from library.fileserve import PathNotAllowed, resolve_version_path
from library.locking import FileLock
from library.models import Version

from .config import KnowledgeConfig
from .snapshot import STAGE_CONFIG, SnapshotStore, SnapshotError, snapshot_version
from .store import JOB_DONE, JOB_FAILED, KnowledgeStore, config_digest


class JobRunner:
    def __init__(self, kb: KnowledgeStore, config: KnowledgeConfig,
                 library_config: Config, blobs: Optional[SnapshotStore] = None):
        self.kb = kb
        self.config = config
        self.library_config = library_config
        self.blobs = blobs or SnapshotStore(config.snapshot_root)
        self.stage_digest = config_digest(STAGE_CONFIG)

    def lock_path(self) -> str:
        return os.path.join(os.path.dirname(self.config.knowledge_db) or ".", "knowledge.lock")

    def run_snapshot_jobs(self, limit: Optional[int] = None) -> Dict[str, Any]:
        """Claim and execute pending snapshot jobs until the queue is empty."""
        recovered = self.kb.recover_stale_jobs("snapshot")
        done = failed = 0
        errors: list = []
        processed = 0
        while limit is None or processed < limit:
            job = self.kb.claim_next_job("snapshot", self.config.job_lease_seconds)
            if job is None:
                break
            processed += 1
            try:
                self._execute_snapshot(job)
                self.kb.finish_job(job["id"], ok=True)
                done += 1
            except SnapshotError as exc:
                # Identity conflicts are permanent for this version identity:
                # record as failed, never silently re-serve different bytes.
                self.kb.finish_job(job["id"], ok=False,
                                   error="%s: %s" % (type(exc).__name__, exc),
                                   max_attempts=0)
                failed += 1
                errors.append({
                    "job": job["id"], "source": job["source"], "doc_id": job["doc_id"],
                    "version_id": job["version_id"], "error": str(exc),
                })
            except Exception as exc:  # transient (I/O etc.) - bounded retries
                self.kb.finish_job(
                    job["id"], ok=False,
                    error="%s: %s" % (type(exc).__name__, exc),
                    max_attempts=self.config.job_max_attempts)
                failed += 1
                errors.append({
                    "job": job["id"], "source": job["source"], "doc_id": job["doc_id"],
                    "version_id": job["version_id"], "error": "%s: %s" % (type(exc).__name__, exc),
                })
        counts = self.kb.job_counts("snapshot")
        return {
            "ok": failed == 0,
            "recovered": recovered,
            "processed": processed,
            "done": done,
            "failed": failed,
            "errors": errors[:20],
            "job_counts": counts,
        }

    def _execute_snapshot(self, job: Dict[str, Any]) -> str:
        version_row = self.kb.get_version(job["source"], job["doc_id"], job["version_id"])
        if version_row is None:
            raise SnapshotError("version row missing in knowledge store")
        existing = self.kb.get_snapshot(job["source"], job["doc_id"], job["version_id"])
        if existing:
            # Already bound; idempotent no-op.
            return existing["sha256"]
        version = Version(
            version_id=version_row["version_id"],
            sha256=version_row["sha256"],
            bytes=version_row["bytes"],
            media_type=version_row["media_type"],
            rel_path=version_row["rel_path"],
            ext=version_row["ext"],
            is_current=bool(version_row["is_current"]),
            state=version_row["state"],
        )
        path = resolve_version_path(self.library_config, job["source"], version)
        with open(path, "rb") as handle:
            return snapshot_version(
                self.kb, self.blobs, handle,
                job["source"], job["doc_id"], job["version_id"],
                version_row["sha256"], version_row["bytes"],
            )

    def status(self) -> Dict[str, Any]:
        counts = self.kb.job_counts("snapshot")
        return {
            "stage": "snapshot",
            "config_digest": self.stage_digest,
            "job_counts": counts,
            "store_counts": self.kb.counts(),
        }


def run_knowledge_command(config: KnowledgeConfig, command: str,
                          limit: Optional[int] = None) -> Dict[str, Any]:
    """Shared entrypoint for CLI use: holds the knowledge lock while mutating."""
    from .sync import SyncService

    kb = KnowledgeStore(config.knowledge_db)
    try:
        lock = FileLock(os.path.join(os.path.dirname(config.knowledge_db) or ".",
                                     "knowledge.lock"))
        if command == "sync":
            sync = SyncService(kb, config)
            return sync.run()
        if command == "run-snapshots":
            if not lock.acquire(blocking=False):
                return {"ok": False, "skipped": True,
                        "reason": "another knowledge command holds the lock"}
            try:
                library_config = Config.load(config.library_config).resolve(
                    os.path.dirname(os.path.abspath(config.library_config)))
                runner = JobRunner(kb, config, library_config)
                return runner.run_snapshot_jobs(limit=limit)
            finally:
                lock.release()
        if command == "status":
            library_config = Config.load(config.library_config).resolve(
                os.path.dirname(os.path.abspath(config.library_config)))
            runner = JobRunner(kb, config, library_config)
            return runner.status()
        raise ValueError("unknown command: %s" % command)
    finally:
        kb.close()
