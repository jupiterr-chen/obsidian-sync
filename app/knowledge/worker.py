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
from .indexing import build_generation
from .jobs import JobRunner
from .memory import impact_analysis
from .snapshot import SnapshotStore
from .store import KnowledgeStore, utc_now
from .sync import SyncService

HEARTBEAT_SECONDS = 15


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
            runner = JobRunner(kb, config, library_config)
            sync = SyncService(kb, config)
            cycle["sync"] = sync.run()
            cycle["snapshots"] = runner.run_snapshot_jobs()
            cycle["extracts"] = runner.run_extract_jobs()
            cycle["index"] = build_generation(kb)

            # A20 hooks: new versions discovered this cycle become review
            # proposals for claims citing the affected documents.
            proposals = 0
            new_versions = cycle["sync"].get("new_versions", 0)
            if new_versions:
                with kb._lock:
                    rows = kb._conn.execute(
                        "SELECT DISTINCT source, doc_id, version_id FROM kb_versions"
                        " WHERE synced_at = (SELECT MAX(synced_at) FROM kb_versions)"
                        " LIMIT ?", (max_impact_versions,)).fetchall()
                for row in rows:
                    impact = impact_analysis(kb, row["source"], row["doc_id"],
                                             row["version_id"])
                    proposals += len(impact["new_proposals"])
            cycle["impact_proposals"] = proposals
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
