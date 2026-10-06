"""Shared effective-extraction selection (S2/TA03/TA04/SF02).

Reading, the default search index and the governance planner must all
answer the SAME question the same way: which extraction of a version is
the currently effective one?

Rules (S2/SF02 - a newer result must EARN the entry):
1. an extraction qualifies when it has at least one block AND every
   block passes the evidence-usable check (fully usable - no damaged
   page, no missing content): the NEWEST fully-usable extraction is
   effective;
2. when NO extraction is fully usable, the newest extraction with at
   least one usable block is a degraded fallback (better than nothing);
   a partially damaged newer extraction never displaces a fully
   healthy older one, and a fully healthy older one keeps serving until
   a complete successor lands;
3. nothing qualifies -> no effective extraction (the entry shows
   待修复 rather than faking readiness).

The newer attempt is surfaced separately with its status so operations
see it without losing the good text.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .quality import block_evidence_usable


def _usable_flags(conn, extraction_id: str) -> List[bool]:
    rows = conn.execute(
        "SELECT text FROM blocks WHERE extraction_id=?"
        " AND LENGTH(TRIM(text))>0 ORDER BY ordinal",
        (extraction_id,)).fetchall()
    return [block_evidence_usable(row["text"])[0] for row in rows]


def effective_extraction(conn, source: str, doc_id: str,
                         version_id: str) -> Optional[Dict[str, Any]]:
    """The effective extraction of a version under the S2 rules.

    ``conn`` is a raw sqlite connection (writable store or read-only
    shim). Returns the extraction row (extraction_id/status) plus the
    newest attempt for display, or None when nothing qualifies."""
    extractions = conn.execute(
        "SELECT extraction_id, status FROM extractions"
        " WHERE source=? AND doc_id=? AND version_id=?"
        " ORDER BY rowid DESC",
        (source, doc_id, version_id)).fetchall()
    chosen = None
    # pass 1: newest FULLY usable extraction
    for candidate in extractions:
        flags = _usable_flags(conn, candidate["extraction_id"])
        if flags and all(flags):
            chosen = candidate
            break
    # pass 2 (degraded fallback): newest with ANY usable block - only
    # when no extraction is fully usable
    if chosen is None:
        for candidate in extractions:
            flags = _usable_flags(conn, candidate["extraction_id"])
            if any(flags):
                chosen = candidate
                break
    if chosen is None:
        return None
    result = dict(chosen)
    newest = extractions[0]
    result["is_newest"] = newest["extraction_id"] == \
        chosen["extraction_id"]
    result["newest_status"] = newest["status"]
    result["newest_extraction_id"] = newest["extraction_id"]
    return result


def effective_extraction_ids(conn) -> List[str]:
    """Effective extraction ids for every CURRENT version (used by the
    default search index so a polluted newer extraction cannot evict
    the older good text from search)."""
    versions = conn.execute(
        "SELECT source, doc_id, version_id FROM kb_versions"
        " WHERE is_current=1").fetchall()
    ids = []
    for version in versions:
        chosen = effective_extraction(
            conn, version["source"], version["doc_id"],
            version["version_id"])
        if chosen:
            ids.append(chosen["extraction_id"])
    return ids
