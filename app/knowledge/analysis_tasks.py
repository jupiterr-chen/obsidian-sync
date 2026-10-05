"""Single-document analysis pipeline (B2/B3).

N2 (Q02) closes the loop that previously ended at registration:

- registration targets the LATEST extraction of each current version
  (never an older ready extraction hiding under a newer review one) and
  uses the FULL identity (source, doc, version, extraction, model,
  prompt, template) for duplicate detection, so a prompt change
  registers a new task while an identical identity never re-registers;
- a lease-based executor claims pending tasks, analyses the document's
  OWN blocks (not a corpus search) through the budgeted
  execute_analysis_run (citation verification included), persists the
  run, and enqueues a durable publish event;
- crash recovery returns expired leases to pending; retryable failures
  re-queue, non-retryable ones fail honestly; budget exhaustion leaves
  the task pending for the next cycle (never a paid call past the cap);
- with no provider authorized, tasks stay ``blocked(model_disabled)``
  exactly as before - enabling is a separate, explicit step.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

from .store import KnowledgeStore, utc_now

ANALYSIS_TEMPLATE_VERSION = "single-doc-v1"
STATUS_PENDING = "pending"
STATUS_BLOCKED = "blocked"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"

# model/prompt identity used BEFORE any provider exists; changing the
# planned model bumps the identity so re-analysis is explicit
PLANNED_MODEL_IDENTITY = "disabled/no-provider"

SCHEMA = """
CREATE TABLE IF NOT EXISTS analysis_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_key TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    extraction_id TEXT NOT NULL,
    model_identity TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    template_version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    blocked_reason TEXT,
    result_note TEXT,
    run_id TEXT,
    model_name TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    lease_until TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT,
    UNIQUE (source, doc_id, version_id, extraction_id, model_identity,
            prompt_version, template_version)
);
CREATE TABLE IF NOT EXISTS analysis_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    consumed_at TEXT
);
"""

_EXTRA_COLUMNS = (("model_name", "TEXT"),
                  ("attempts", "INTEGER NOT NULL DEFAULT 0"),
                  ("lease_until", "TEXT"),
                  ("error", "TEXT"))


def ensure_schema(kb: KnowledgeStore) -> None:
    with kb._tx() as conn:
        conn.executescript(SCHEMA)
        # stores created by the first A-E delivery lack the executor
        # columns; add them idempotently (existing rows: attempts=0)
        for column, decl in _EXTRA_COLUMNS:
            cols = [r[1] for r in conn.execute(
                "PRAGMA table_info(analysis_tasks)").fetchall()]
            if column not in cols:
                conn.execute("ALTER TABLE analysis_tasks ADD COLUMN %s %s"
                             % (column, decl))


def task_key(source: str, doc_id: str, version_id: str, extraction_id: str,
             model_identity: str, prompt_version: str, template: str) -> str:
    identity = "\x00".join((source, doc_id, version_id, extraction_id,
                            model_identity, prompt_version, template))
    return "anl-" + hashlib.sha256(identity.encode()).hexdigest()[:32]


def register_ready_analysis_tasks(
        kb: KnowledgeStore, prompt_version: str = "pv1",
        model_identity: str = PLANNED_MODEL_IDENTITY,
        model_name: Optional[str] = None,
        blocked_reason: Optional[str] = "model_disabled") -> Dict[str, int]:
    """Register analysis tasks for the LATEST extraction of CURRENT
    versions when that latest extraction is READY (review/failed on the
    latest row excludes the document - B4; an older ready extraction
    must never be analysed as if it were current). Duplicate detection
    uses the FULL identity, so a new prompt/model/template registers a
    new task while an existing identity never re-registers."""
    ensure_schema(kb)
    registered = 0
    with kb._tx() as conn:
        rows = conn.execute(
            "SELECT v.source, v.doc_id, v.version_id, e.extraction_id,"
            " e.status FROM kb_versions v JOIN extractions e"
            " ON e.rowid = (SELECT MAX(e2.rowid) FROM extractions e2"
            "  WHERE e2.source=v.source AND e2.doc_id=v.doc_id"
            "  AND e2.version_id=v.version_id)"
            " WHERE v.is_current=1 AND e.status='ready'"
            " AND NOT EXISTS (SELECT 1 FROM analysis_tasks t"
            "  WHERE t.source=v.source AND t.doc_id=v.doc_id"
            "  AND t.version_id=v.version_id AND t.extraction_id=e.extraction_id"
            "  AND t.model_identity=? AND t.prompt_version=?"
            "  AND t.template_version=?)",
            (model_identity, prompt_version, ANALYSIS_TEMPLATE_VERSION)
        ).fetchall()
        now = utc_now()
        status = STATUS_BLOCKED if blocked_reason else STATUS_PENDING
        for row in rows:
            key = task_key(row["source"], row["doc_id"], row["version_id"],
                           row["extraction_id"], model_identity,
                           prompt_version, ANALYSIS_TEMPLATE_VERSION)
            conn.execute(
                "INSERT INTO analysis_tasks (task_key, source, doc_id,"
                " version_id, extraction_id, model_identity, prompt_version,"
                " template_version, status, blocked_reason, model_name,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(task_key) DO NOTHING",
                (key, row["source"], row["doc_id"], row["version_id"],
                 row["extraction_id"], model_identity, prompt_version,
                 ANALYSIS_TEMPLATE_VERSION, status, blocked_reason,
                 model_name, now, now))
            registered += 1
    return {"registered": registered}


# ------------------------------------------------------------- executor
def release_expired_analysis_tasks(kb: KnowledgeStore) -> int:
    """Crash recovery: a 'running' task whose lease expired returns to
    pending so the next cycle re-claims it (attempts keep counting)."""
    ensure_schema(kb)
    with kb._tx() as conn:
        cursor = conn.execute(
            "UPDATE analysis_tasks SET status=?, lease_until=NULL,"
            " updated_at=? WHERE status=? AND lease_until IS NOT NULL"
            " AND lease_until < ?",
            (STATUS_PENDING, utc_now(), STATUS_RUNNING, utc_now()))
        return cursor.rowcount


def claim_pending_analysis_tasks(kb: KnowledgeStore, limit: int = 5,
                                 lease_seconds: int = 900
                                 ) -> List[Dict[str, Any]]:
    """Atomically claim up to `limit` pending tasks under a lease."""
    ensure_schema(kb)
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    lease_until = (now + timedelta(seconds=lease_seconds)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    claimed: List[Dict[str, Any]] = []
    with kb._tx() as conn:
        rows = conn.execute(
            "SELECT * FROM analysis_tasks WHERE status=?"
            " AND (lease_until IS NULL OR lease_until < ?)"
            " ORDER BY created_at LIMIT ?",
            (STATUS_PENDING, utc_now(), max(1, int(limit)))).fetchall()
        for row in rows:
            cursor = conn.execute(
                "UPDATE analysis_tasks SET status=?, lease_until=?,"
                " attempts=attempts+1, updated_at=? WHERE task_key=?"
                " AND status=?",
                (STATUS_RUNNING, lease_until, utc_now(), row["task_key"],
                 STATUS_PENDING))
            if cursor.rowcount:
                task = dict(row)
                task["status"] = STATUS_RUNNING
                task["attempts"] = (task.get("attempts") or 0) + 1
                claimed.append(task)
    return claimed


def _document_query(kb: KnowledgeStore, source: str, doc_id: str) -> str:
    with kb._lock:
        row = kb._conn.execute(
            "SELECT title, display_title FROM kb_documents"
            " WHERE source=? AND doc_id=?", (source, doc_id)).fetchone()
    from urllib.parse import unquote

    if row and (row["title"] or row["display_title"]):
        return unquote(row["title"] or row["display_title"])
    return doc_id


def _own_blocks_retriever(kb: KnowledgeStore, source: str, doc_id: str,
                          extraction_id: str, max_blocks: int = 40):
    """Single-document analysis reads the document's OWN extracted blocks
    (B2), not a corpus search; long documents are bounded by blocks.
    Blocks are enriched with source/doc_id (build_analysis_prompt's
    provenance line needs them) and returned keyword-search-shaped so
    execute_analysis_run's hit unwrapping works unchanged."""
    def retriever(query, top_k):
        limit = min(max_blocks, int(top_k) if top_k else max_blocks)
        hits = []
        for block in kb.get_blocks(extraction_id)[:limit]:
            block = dict(block)
            block.setdefault("source", source)
            block.setdefault("doc_id", doc_id)
            hits.append({"block": block, "score": 1.0})
        return hits
    return retriever


def execute_analysis_tasks(kb: KnowledgeStore, chat,
                           ledger=None, prompt_version: str = "pv1",
                           limit: int = 5,
                           max_attempts: int = 3) -> Dict[str, Any]:
    """Claim and run pending analysis tasks through the budgeted run
    pipeline. Provider/budget refusals leave tasks pending (queued, no
    paid call); retryable errors re-queue; non-retryable fail."""
    from .analysis import execute_analysis_run
    from .budget import Budget, BudgetLedger

    ensure_schema(kb)
    release_expired_analysis_tasks(kb)
    ledger = ledger or BudgetLedger(kb, Budget())
    done = failed = retried = 0
    errors: List[Dict[str, Any]] = []
    for task in claim_pending_analysis_tasks(kb, limit=limit):
        query = _document_query(kb, task["source"], task["doc_id"])
        run = kb.create_analysis_run(
            query, mode="single-doc", prompt_version=prompt_version)
        try:
            outcome = execute_analysis_run(
                kb, run["run_id"], query, chat,
                retriever=_own_blocks_retriever(
                    kb, task["source"], task["doc_id"],
                    task["extraction_id"]),
                prompt_version=prompt_version, ledger=ledger)
        except Exception as exc:  # transport/ledger edge cases
            outcome = {"status": "failed", "error": "%s: %s" % (
                type(exc).__name__, exc), "retryable": True}
        if outcome.get("status") == "done":
            with kb._tx() as conn:
                conn.execute(
                    "UPDATE analysis_tasks SET status=?, run_id=?,"
                    " result_note=?, finished_at=?, updated_at=?,"
                    " lease_until=NULL WHERE task_key=?",
                    (STATUS_DONE, run["run_id"],
                     outcome.get("draft"), utc_now(), utc_now(),
                     task["task_key"]))
                conn.execute(
                    "INSERT OR IGNORE INTO analysis_outbox (task_key,"
                    " status, created_at) VALUES (?, 'pending', ?)",
                    (task["task_key"], utc_now()))
            done += 1
            continue
        error = str(outcome.get("error") or "unknown")
        retryable = bool(outcome.get("retryable", True))
        budget_blocked = "budget" in error.lower()
        new_status = (STATUS_PENDING
                      if (retryable or budget_blocked)
                      and (task["attempts"] < max_attempts or budget_blocked)
                      else STATUS_FAILED)
        with kb._tx() as conn:
            conn.execute(
                "UPDATE analysis_tasks SET status=?, error=?,"
                " run_id=?, updated_at=?, lease_until=NULL"
                " WHERE task_key=?",
                (new_status, error[:500], run["run_id"], utc_now(),
                 task["task_key"]))
        if new_status == STATUS_PENDING:
            retried += 1
        else:
            failed += 1
        errors.append({"task_key": task["task_key"], "error": error[:300],
                       "status": new_status})
    return {"done": done, "failed": failed, "retried": retried,
            "errors": errors}


def task_counts(kb: KnowledgeStore) -> Dict[str, int]:
    ensure_schema(kb)
    with kb._lock:
        rows = kb._conn.execute(
            "SELECT status, COUNT(*) c FROM analysis_tasks"
            " GROUP BY status").fetchall()
    return {r["status"]: r["c"] for r in rows}
