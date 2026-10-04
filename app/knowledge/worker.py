"""Knowledge worker: periodic sync/snapshot/extract/index cycle (P6-01).

Mirrors the first-layer scheduler pattern (persisted honest state with a
heartbeat so monitoring can detect a dead worker) and shares the knowledge
file lock so a scheduled cycle never races a manual command.
"""

from __future__ import annotations

import json
import os
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from library.config import Config
from library.locking import FileLock

from .config import KnowledgeConfig
from .extract import STAGE_EXTRACT
from .indexing import build_generation
from .jobs import JobRunner
from .memory import impact_analysis
from .snapshot import SnapshotStore
from .store import KnowledgeStore, utc_now
from .sync import SyncService

HEARTBEAT_SECONDS = 15


def consume_impact_outbox(kb, limit: int = 25) -> int:
    """R15: drain the durable impact outbox in batches.

    Each pending (source, doc_id, version_id) becomes review proposals for
    claims citing the document; the row is consumed only after the
    (idempotent) analysis ran. Crash at any point leaves unconsumed rows
    for the next cycle - nothing is inferred from sync timestamps.
    """
    from .memory import impact_analysis as _impact

    created = 0
    while True:
        batch = kb.pending_impacts(limit=limit)
        if not batch:
            return created
        for row in batch:
            impact = _impact(kb, row["source"], row["doc_id"],
                             row["version_id"])
            created += len(impact["new_proposals"])
            kb.mark_impact_consumed(row["id"])


def _extraction_for(kb, row) -> Optional[str]:
    extraction = kb.latest_extraction(row["source"], row["doc_id"],
                                      row["version_id"])
    return extraction["extraction_id"] if extraction else None


def worker_state_path(knowledge_db: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(knowledge_db)) or ".",
                        "knowledge-worker.json")


def write_state(path: str, state: Dict[str, Any]) -> None:
    state = dict(state)
    state["updated_at"] = utc_now()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(tmp, path)


def read_state(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def run_cycle(config: KnowledgeConfig, library_config: Config,
              max_impact_versions: int = 25) -> Dict[str, Any]:
    """One full knowledge cycle. Idempotent; safe to run back-to-back."""
    kb = KnowledgeStore(config.knowledge_db)
    lock = FileLock(os.path.join(os.path.dirname(config.knowledge_db) or ".",
                                 "knowledge.lock"))
    cycle: Dict[str, Any] = {"started_at": utc_now(), "ok": True}
    try:
        if not lock.acquire(blocking=False):
            return {"ok": False, "skipped": True,
                    "reason": "another knowledge command holds the lock"}
        try:
            # the worker owns extraction: ensure the extract stage is
            # registered even if the config only lists snapshot
            import copy as _copy

            worker_config = _copy.deepcopy(config)
            stages = list(worker_config.register_stages or ("snapshot",))
            if STAGE_EXTRACT not in stages:
                stages.append(STAGE_EXTRACT)
            worker_config.register_stages = tuple(stages)
            runner = JobRunner(kb, worker_config, library_config)
            sync = SyncService(kb, config)
            cycle["sync"] = sync.run()
            cycle["snapshots"] = runner.run_snapshot_jobs()

            # A2: bounded repair lane runs BEFORE extraction so its
            # re-registrations process in the same cycle
            from .repair import register_repair_jobs
            cycle["repair"] = register_repair_jobs(
                kb, runner.extract_digest, max_items=10)

            cycle["extracts"] = runner.run_extract_jobs()
            cycle["index"] = build_generation(kb)

            # A3: extraction commits become durable pending publishes; the
            # reading consumer renders notes + index after the (possibly
            # new) generation is live. Vault dir may be absent on hosts
            # that only run extraction - publishing is then skipped and
            # the outbox stays pending (consumed by the node that owns
            # the vault).
            vault_dir = (config.extra or {}).get("vault_dir")
            if vault_dir and os.path.isdir(vault_dir):
                from .reading import ReadingPublisher

                publisher = ReadingPublisher(
                    kb, vault_dir,
                    (config.extra or {}).get(
                        "public_base_url", "http://192.168.1.150:8765"))
                with kb._tx() as conn:
                    done = conn.execute(
                        "SELECT source, doc_id, version_id, extraction_id"
                        " FROM jobs WHERE stage='extract' AND status='done'"
                        " AND updated_at >= ?", (cycle["started_at"],)).fetchall()
                    for row in done:
                        publisher.enqueue(row["source"], row["doc_id"],
                                          row["version_id"],
                                          None or _extraction_for(kb, row))
                cycle["reading"] = publisher.consume()
            else:
                cycle["reading"] = {"skipped": True,
                                    "reason": "vault_dir not configured"}

            # A20 hooks (R15): durable outbox drives impact analysis -
            # paged until empty, no time-stamp heuristics, crash-safe.
            proposals = consume_impact_outbox(kb,
                                              limit=max_impact_versions)
            cycle["impact_proposals"] = proposals

            # B2: register analysis tasks for READY current extractions;
            # with models disabled they are recorded as blocked (never
            # silently queued for a paid call)
            from .analysis_tasks import (register_ready_analysis_tasks,
                                         task_counts)
            cycle["analysis_tasks"] = register_ready_analysis_tasks(kb)
            cycle["analysis_task_counts"] = task_counts(kb)

            # C: entities whose evidence changed (new claims/updates from
            # the impact lane) queue a summary revision; generation is
            # blocked until a provider is authorized
            from .summaries import consume_updates, enqueue_summary_update
            for proposal in kb.list_review_proposals(status="open"):
                detail = proposal.get("detail") or {}
                subject = None
                with kb._lock:
                    claim = kb._conn.execute(
                        "SELECT subject FROM claims WHERE claim_id=?",
                        (proposal["claim_id"],)).fetchone()
                    subject = claim["subject"] if claim else None
                if subject:
                    enqueue_summary_update(
                        kb, "company", subject,
                        "evidence_changed",
                        {"proposal_id": proposal["proposal_id"],
                         "source": detail.get("source"),
                         "doc_id": detail.get("doc_id")})
            cycle["summaries"] = consume_updates(kb)
            cycle["counts"] = kb.counts()
            generation = kb.active_generation()
            cycle["generation_id"] = generation["generation_id"] if generation else None
            cycle["ok"] = bool(cycle["sync"].get("ok")) and \
                bool(cycle["snapshots"].get("ok")) and \
                bool(cycle["extracts"].get("ok")) and bool(cycle["index"].get("ok"))
        finally:
            lock.release()
    except Exception as exc:
        cycle["ok"] = False
        cycle["error"] = "%s: %s" % (type(exc).__name__, exc)
        cycle["traceback"] = traceback.format_exc()[-2000:]
    finally:
        cycle["finished_at"] = utc_now()
        kb.close()
    return cycle


class KnowledgeWorker:
    """In-process hourly cycle with persisted heartbeat state."""

    def __init__(self, config: KnowledgeConfig, library_config: Config,
                 interval_seconds: int = 3600):
        self.config = config
        self.library_config = library_config
        self.interval = max(60, int(interval_seconds))
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.heartbeat_thread: Optional[threading.Thread] = None
        self._started_at = utc_now()

    def _state_path(self) -> str:
        return worker_state_path(self.config.knowledge_db)

    def _write(self, **updates: Any) -> None:
        state = read_state(self._state_path()) or {
            "kind": "knowledge-worker",
            "interval_seconds": self.interval,
            "started_at": self._started_at,
        }
        state.update(updates)
        try:
            write_state(self._state_path(), state)
        except OSError:
            pass

    def _heartbeat(self) -> None:
        while not self.stop_event.wait(HEARTBEAT_SECONDS):
            self._write()

    def _loop(self) -> None:
        self._write(state="idle")
        while not self.stop_event.is_set():
            attempt_started = utc_now()
            self._write(state="running", attempt_started_at=attempt_started)
            try:
                cycle = run_cycle(self.config, self.library_config)
                self._write(state="idle", last_ok=bool(cycle.get("ok")),
                            last_error=cycle.get("error"),
                            last_cycle=cycle,
                            last_finished_at=cycle.get("finished_at"))
            except Exception as exc:  # never kill the worker thread
                self._write(state="idle", last_ok=False,
                            last_error="%s: %s" % (type(exc).__name__, exc))
            moment = datetime.now(timezone.utc)
            next_at = (moment + timedelta(seconds=self.interval)).replace(
                microsecond=0).isoformat().replace("+00:00", "Z")
            self._write(next_check_at=next_at)
            self.stop_event.wait(self.interval)

    def start(self) -> None:
        self.thread = threading.Thread(target=self._loop,
                                       name="knowledge-worker", daemon=True)
        self.thread.start()
        self.heartbeat_thread = threading.Thread(
            target=self._heartbeat, name="knowledge-heartbeat", daemon=True)
        self.heartbeat_thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self._write(state="stopped", next_check_at=None)


def worker_is_stale(path: str, max_age_seconds: int = 120) -> Optional[bool]:
    """True/False freshness, None when no state file exists yet."""
    state = read_state(path)
    if not state:
        return None
    updated = state.get("updated_at")
    if not updated:
        return None
    try:
        moment = datetime.fromisoformat(updated.replace("Z", "+00:00"))
    except ValueError:
        return None
    age = (datetime.now(timezone.utc) - moment).total_seconds()
    return age > max_age_seconds
