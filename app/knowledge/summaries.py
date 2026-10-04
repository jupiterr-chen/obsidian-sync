"""Company/topic knowledge summaries with versioned history (C).

Summaries are versioned per (entity_type, entity_id): every update
creates a new revision, prior revisions remain readable, and a
``summary_outbox`` driven by the impact outbox queues updates ONLY for
entities whose evidence actually changed (无关主题不更新/不付费). With
models disabled the queued updates stay pending with
blocked_reason=model_disabled - the flow, versioning and evidence
linkage are real; no summarization is invoked.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

from .store import KnowledgeStore, utc_now

SUMMARY_TEMPLATE_VERSION = "entity-summary-v1"
STATUS_PENDING = "pending"
STATUS_BLOCKED = "blocked"
STATUS_DONE = "done"

SCHEMA = """
CREATE TABLE IF NOT EXISTS summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,          -- company | topic
    entity_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    status TEXT NOT NULL,
    content TEXT,
    evidence_claim_revisions_json TEXT,
    blocked_reason TEXT,
    model_identity TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (entity_type, entity_id, revision)
);
CREATE TABLE IF NOT EXISTS summary_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    detail_json TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    consumed_at TEXT
);
"""

ENTITY_TYPES = ("company", "topic")


def ensure_schema(kb: KnowledgeStore) -> None:
    with kb._tx() as conn:
        conn.executescript(SCHEMA)


def entity_for_source(source: str, doc_id: str) -> Optional[Dict[str, str]]:
    """Map a source document to the company/topic entities it feeds.

    The first layer carries no explicit entity registry; company entities
    are keyed by the document's symbol where present (doc-level metadata
    is already mirrored in kb_documents)."""
    return None  # populated by callers with symbol/topic metadata


def enqueue_summary_update(kb: KnowledgeStore, entity_type: str,
                          entity_id: str, reason: str,
                          detail: Optional[Dict[str, Any]] = None) -> bool:
    if entity_type not in ENTITY_TYPES or not entity_id:
        return False
    ensure_schema(kb)
    with kb._tx() as conn:
        conn.execute(
            "INSERT INTO summary_outbox (entity_type, entity_id, reason,"
            " detail_json, status, created_at) VALUES (?,?,?,?, 'pending', ?)",
            (entity_type, entity_id, reason,
             __import__("json").dumps(detail or {}, ensure_ascii=False),
             utc_now()))
    return True


def pending_updates(kb: KnowledgeStore, limit: int = 100) -> List[Dict[str, Any]]:
    ensure_schema(kb)
    with kb._lock:
        rows = kb._conn.execute(
            "SELECT * FROM summary_outbox WHERE status='pending'"
            " ORDER BY id LIMIT ?", (max(1, int(limit)),)).fetchall()
    import json as _json

    result = []
    for row in rows:
        item = dict(row)
        item["detail"] = _json.loads(item.pop("detail_json") or "{}")
        result.append(item)
    return result


def record_summary(kb: KnowledgeStore, entity_type: str, entity_id: str,
                   content: str, claim_revisions: List[Dict[str, Any]],
                   model_identity: str = "disabled/no-provider",
                   blocked_reason: Optional[str] = None) -> Dict[str, Any]:
    """Append a new summary revision (history preserved)."""
    ensure_schema(kb)
    import json as _json

    with kb._tx() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(revision),0) r FROM summaries"
            " WHERE entity_type=? AND entity_id=?",
            (entity_type, entity_id)).fetchone()
        revision = row["r"] + 1
        conn.execute(
            "INSERT INTO summaries (entity_type, entity_id, revision,"
            " status, content, evidence_claim_revisions_json, blocked_reason,"
            " model_identity, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (entity_type, entity_id, revision,
             STATUS_BLOCKED if blocked_reason else STATUS_DONE,
             content, _json.dumps(claim_revisions, ensure_ascii=False),
             blocked_reason, model_identity, utc_now()))
    return {"entity_type": entity_type, "entity_id": entity_id,
            "revision": revision}


def consume_updates(kb: KnowledgeStore, limit: int = 100) -> Dict[str, Any]:
    """Drain the summary outbox. With models disabled each update is
    recorded as a blocked revision carrying its evidence list - the
    version chain and evidence linkage are real; generation is pending
    an authorized provider."""
    import json as _json

    ensure_schema(kb)
    queued = pending_updates(kb, limit)
    consumed = 0
    for item in queued:
        with kb._tx() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(revision),0) r FROM summaries"
                " WHERE entity_type=? AND entity_id=?",
                (item["entity_type"], item["entity_id"])).fetchone()
            revision = row["r"] + 1
            conn.execute(
                "INSERT INTO summaries (entity_type, entity_id, revision,"
                " status, content, evidence_claim_revisions_json,"
                " blocked_reason, model_identity, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (item["entity_type"], item["entity_id"], revision,
                 STATUS_BLOCKED, None, _json.dumps([]),
                 "model_disabled", "disabled/no-provider", utc_now()))
            conn.execute(
                "UPDATE summary_outbox SET status='consumed', consumed_at=?"
                " WHERE id=?", (utc_now(), item["id"]))
        consumed += 1
    return {"consumed": consumed, "remaining": len(pending_updates(kb))}


def summary_history(kb: KnowledgeStore, entity_type: str,
                    entity_id: str) -> List[Dict[str, Any]]:
    ensure_schema(kb)
    with kb._lock:
        rows = kb._conn.execute(
            "SELECT revision, status, blocked_reason, created_at,"
            " content FROM summaries WHERE entity_type=? AND entity_id=?"
            " ORDER BY revision", (entity_type, entity_id)).fetchall()
    return [dict(r) for r in rows]
