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
from .extract import (
    EXTRACT_CONFIG,
    STAGE_EXTRACT,
    compute_extraction_id,
    extract_config_digest,
    get_extractor,
)
from .extract import ExtractorMissing
from .sampling import format_of
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
        self.extract_digest = extract_config_digest()

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
            # Already bound; idempotent no-op (still ensure the extract job exists).
            self._ensure_extract_job(job["source"], job["doc_id"], job["version_id"])
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
            sha = snapshot_version(
                self.kb, self.blobs, handle,
                job["source"], job["doc_id"], job["version_id"],
                version_row["sha256"], version_row["bytes"],
            )
        self._ensure_extract_job(job["source"], job["doc_id"], job["version_id"])
        return sha

    def _ensure_extract_job(self, source: str, doc_id: str, version_id: str) -> None:
        if STAGE_EXTRACT not in self.config.register_stages:
            return
        self.kb.register_job(source, doc_id, version_id, STAGE_EXTRACT,
                             self.extract_digest)

    def run_extract_jobs(self, limit: Optional[int] = None) -> Dict[str, Any]:
        """Extract pending snapshot versions into evidence blocks."""
        registered = 0
        if STAGE_EXTRACT in self.config.register_stages:
            for row in self.kb.snapshots_missing_extract_jobs(self.extract_digest):
                if self.kb.register_job(row["source"], row["doc_id"], row["version_id"],
                                        STAGE_EXTRACT, self.extract_digest):
                    registered += 1
        recovered = self.kb.recover_stale_jobs(STAGE_EXTRACT)
        done = failed = 0
        errors: list = []
        processed = 0
        while limit is None or processed < limit:
            job = self.kb.claim_next_job(STAGE_EXTRACT, self.config.job_lease_seconds)
            if job is None:
                break
            processed += 1
            try:
                self._execute_extract(job)
                self.kb.finish_job(job["id"], ok=True)
                done += 1
            except Exception as exc:
                permanent = isinstance(exc, (SnapshotError, ExtractorMissing))
                self.kb.finish_job(
                    job["id"], ok=False,
                    error="%s: %s" % (type(exc).__name__, exc),
                    max_attempts=0 if permanent else self.config.job_max_attempts)
                failed += 1
                errors.append({
                    "job": job["id"], "source": job["source"], "doc_id": job["doc_id"],
                    "version_id": job["version_id"],
                    "error": "%s: %s" % (type(exc).__name__, exc),
                })
        counts = self.kb.job_counts(STAGE_EXTRACT)
        return {
            "ok": failed == 0,
            "registered": registered,
            "recovered": recovered,
            "processed": processed,
            "done": done,
            "failed": failed,
            "errors": errors[:20],
            "job_counts": counts,
        }

    def _execute_extract(self, job: Dict[str, Any]) -> str:
        version_row = self.kb.get_version(job["source"], job["doc_id"], job["version_id"])
        if version_row is None:
            raise SnapshotError("version row missing in knowledge store")
        snap = self.kb.get_snapshot(job["source"], job["doc_id"], job["version_id"])
        if snap is None:
            raise SnapshotError("snapshot missing; snapshot stage must complete first")
        blob_path = os.path.join(self.blobs.root, *snap["store_path"].split("/"))
        fmt = format_of(version_row["media_type"], version_row["ext"])
        extractor = get_extractor(fmt)  # ExtractorMissing -> permanent fail
        with open(blob_path, "rb") as handle:
            raw = handle.read()
        ocr_engine = self.ocr_engine()
        result = extractor(raw, ocr=ocr_engine,
                           ocr_config=self.config.ocr_config())
        extraction_id = compute_extraction_id(
            job["source"], job["doc_id"], job["version_id"], snap["sha256"],
            result.parser_id, result.parser_version, self.extract_digest,
        )
        if self.kb.has_extraction(extraction_id):
            return extraction_id  # immutable no-op
        blocks = [{
            "block_type": block.block_type,
            "text": block.text,
            "locator": block.locator,
            "quality": {"status": block.quality.status, "issues": block.quality.issues},
        } for block in result.blocks]
        recorded = self.kb.record_extraction({
            "extraction_id": extraction_id,
            "source": job["source"], "doc_id": job["doc_id"],
            "version_id": job["version_id"], "snapshot_sha256": snap["sha256"],
            "parser_id": result.parser_id, "parser_version": result.parser_version,
            "config_digest": self.extract_digest,
            "status": result.status, "issues": result.issues,
            "stats": result.stats,
        }, blocks)
        if not recorded:  # pragma: no cover - guarded by has_extraction
            raise SnapshotError("extraction identity conflict")
        self.kb.emit_event(
            "extraction.completed", job["source"], job["doc_id"], job["version_id"],
            {"extraction_id": extraction_id, "status": result.status,
             "parser": "%s/%s" % (result.parser_id, result.parser_version),
             "blocks": len(result.blocks),
             "issues": result.issues[:10]},
            event_id="evt-extr-" + extraction_id[:32])
        return extraction_id

    def ocr_engine(self):
        from .ocr import build_ocr_engine

        try:
            return build_ocr_engine(
                self.config.ocr_config(),
                provider_specs=(self.config.extra.get("providers") or {}))
        except Exception:
            # vision-api selected but unfilled: run without OCR and let the
            # extraction flag needs_ocr honestly instead of failing the job
            return None

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
        if command == "run-extracts":
            if not lock.acquire(blocking=False):
                return {"ok": False, "skipped": True,
                        "reason": "another knowledge command holds the lock"}
            try:
                library_config = Config.load(config.library_config).resolve(
                    os.path.dirname(os.path.abspath(config.library_config)))
                runner = JobRunner(kb, config, library_config)
                return runner.run_extract_jobs(limit=limit)
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
