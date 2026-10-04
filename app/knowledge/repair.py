"""Bounded repair queue for missing/low-quality extractions (A2).

Builds an explicitly bounded queue (default max 25) of current versions
whose extraction is missing or has no readable text, or whose latest
extraction failed - re-registering ONLY those for extraction. This is a
repair lane, deliberately bounded so it can never degrade into an
implicit full-corpus re-extraction; the historical wave remains a
separately authorized pass (A1 ``historical`` flag).
"""

from __future__ import annotations

from typing import Any, Dict, List

from .store import KnowledgeStore, utc_now


def build_repair_queue(kb: KnowledgeStore, max_items: int = 25) -> List[Dict[str, Any]]:
    """Current versions with missing/empty/failed text, newest first."""
    with kb._lock:
        rows = kb._conn.execute(
            "SELECT v.source, v.doc_id, v.version_id, d.title,"
            " e.extraction_id, e.status AS extraction_status,"
            " (SELECT COUNT(*) FROM blocks b WHERE b.extraction_id ="
            "  e.extraction_id AND LENGTH(TRIM(b.text)) > 0) AS readable"
            " FROM kb_versions v JOIN kb_documents d"
            " ON d.source=v.source AND d.doc_id=v.doc_id"
            " LEFT JOIN extractions e ON e.extraction_id = ("
            "  SELECT e2.extraction_id FROM extractions e2"
            "  WHERE e2.source=v.source AND e2.doc_id=v.doc_id"
            "   AND e2.version_id=v.version_id ORDER BY e2.rowid DESC LIMIT 1)"
            " WHERE v.is_current=1"
            " ORDER BY v.source, v.doc_id").fetchall()
    queue = []
    for row in rows:
        item = dict(row)
        needs = (item["extraction_id"] is None
                 or item["extraction_status"] == "failed"
                 or not item["readable"])
        if needs:
            queue.append(item)
    return queue[:max_items]


def register_repair_jobs(kb: KnowledgeStore, digest: str,
                         max_items: int = 25) -> Dict[str, Any]:
    """(Re-)register extract jobs for the bounded repair queue."""
    queue = build_repair_queue(kb, max_items=max_items)
    registered = 0
    for item in queue:
        if kb.register_job(item["source"], item["doc_id"], item["version_id"],
                           "extract", digest):
            registered += 1
    return {"queue_size": len(queue), "registered": registered,
            "bounded_to": max_items}
