"""Single-document analysis pipeline (B2/B3) with models DISABLED by default.

Analysis tasks are registered on extraction completion for READY
extractions only (review/failed are excluded unless explicitly forced -
B4's "不把所有review正文盲目送模型"). Task identity =
(source, version, extraction, model, prompt_version, template) - the
same identity never re-pays (B2). With no chat provider configured the
tasks stay ``pending`` with ``blocked_reason=model_disabled`` - recorded,
not silently dropped; enabling a provider is a separate authorized step.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

from .store import KnowledgeStore, utc_now

ANALYSIS_TEMPLATE_VERSION = "single-doc-v1"
STATUS_PENDING = "pending"
STATUS_BLOCKED = "blocked"
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
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT,
    UNIQUE (source, doc_id, version_id, extraction_id, model_identity,
            prompt_version, template_version)
);
"""


def ensure_schema(kb: KnowledgeStore) -> None:
    with kb._tx() as conn:
        conn.executescript(SCHEMA)


def task_key(source: str, doc_id: str, version_id: str, extraction_id: str,
             model_identity: str, prompt_version: str, template: str) -> str:
    identity = "\x00".join((source, doc_id, version_id, extraction_id,
                            model_identity, prompt_version, template))
    return "anl-" + hashlib.sha256(identity.encode()).hexdigest()[:32]


def register_ready_analysis_tasks(kb: KnowledgeStore,
                                  prompt_version: str = "pv1") -> Dict[str, int]:
    """Register analysis tasks for READY extractions of CURRENT versions
    that have none yet. Review/failed are deliberately excluded (B4)."""
    ensure_schema(kb)
    registered = 0
    with kb._tx() as conn:
        rows = conn.execute(
            "SELECT v.source, v.doc_id, v.version_id, e.extraction_id"
            " FROM kb_versions v JOIN extractions e"
            " ON e.source=v.source AND e.doc_id=v.doc_id"
            " AND e.version_id=v.version_id"
            " WHERE v.is_current=1 AND e.status='ready'"
            " AND NOT EXISTS (SELECT 1 FROM analysis_tasks t"
            "  WHERE t.source=v.source AND t.doc_id=v.doc_id"
            "  AND t.version_id=v.version_id AND t.extraction_id=e.extraction_id)"
        ).fetchall()
        now = utc_now()
        for row in rows:
            key = task_key(row["source"], row["doc_id"], row["version_id"],
                           row["extraction_id"], PLANNED_MODEL_IDENTITY,
                           prompt_version, ANALYSIS_TEMPLATE_VERSION)
            conn.execute(
                "INSERT INTO analysis_tasks (task_key, source, doc_id,"
                " version_id, extraction_id, model_identity, prompt_version,"
                " template_version, status, blocked_reason, created_at,"
                " updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(task_key) DO NOTHING",
                (key, row["source"], row["doc_id"], row["version_id"],
                 row["extraction_id"], PLANNED_MODEL_IDENTITY, prompt_version,
                 ANALYSIS_TEMPLATE_VERSION, STATUS_BLOCKED,
                 "model_disabled", now, now))
            registered += 1
    return {"registered": registered}


def task_counts(kb: KnowledgeStore) -> Dict[str, int]:
    ensure_schema(kb)
    with kb._lock:
        rows = kb._conn.execute(
            "SELECT status, COUNT(*) c FROM analysis_tasks"
            " GROUP BY status").fetchall()
    return {r["status"]: r["c"] for r in rows}
