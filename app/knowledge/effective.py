"""Shared effective-extraction selection (S2/TA03/TA04/SF02).

Reading, the default search index and the governance planner must all
answer the SAME question the same way: which extraction of a version is
the currently effective one?

Rules (S2/SF02 - a newer result must EARN the entry):
1. an extraction qualifies when extraction/block quality is ready,
   every nonempty block passes the evidence-usable check, and recorded
   page coverage is complete: the NEWEST fully-usable extraction wins;
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

import json
from typing import Any, Dict, List, Optional

from .quality import block_evidence_usable


def _usable_flags(conn, extraction_id: str) -> List[bool]:
    rows = conn.execute(
        "SELECT text FROM blocks WHERE extraction_id=?"
        " AND LENGTH(TRIM(text))>0 ORDER BY ordinal",
        (extraction_id,)).fetchall()
    return [block_evidence_usable(row["text"])[0] for row in rows]


def _complete_quality(conn, candidate) -> bool:
    """Clean remaining text does not prove missing/low-confidence pages.

    Old formats without page counts rely on their recorded ready status;
    recorded page counts, when present, must agree with actual locators.
    """
    if candidate["status"] != "ready":
        return False
    rows = conn.execute(
        "SELECT locator_json, quality_status FROM blocks"
        " WHERE extraction_id=? AND LENGTH(TRIM(text))>0",
        (candidate["extraction_id"],)).fetchall()
    if any(row["quality_status"] != "ready" for row in rows):
        return False
    try:
        stats = json.loads(candidate["stats_json"] or "{}")
        if any(int(stats.get(key) or 0) > 0 for key in (
                "missing_content_pages", "unmet_ocr_pages", "low_confidence_pages")):
            return False
        count = int(stats.get("pages") or 0)
        if count > 0:
            pages = {int(json.loads(row["locator_json"] or "{}").get("page") or 0)
                     for row in rows}
            # Do not allocate a range proportional to an untrusted page count.
            if len({p for p in pages if 1 <= p <= count}) != count:
                return False
    except (ValueError, TypeError, AttributeError):
        return False
    return True


def effective_extraction(conn, source: str, doc_id: str,
                         version_id: str) -> Optional[Dict[str, Any]]:
    """The effective extraction of a version under the S2 rules.

    ``conn`` is a raw sqlite connection (writable store or read-only
    shim). Returns the extraction row (extraction_id/status) plus the
    newest attempt for display, or None when nothing qualifies."""
    extractions = conn.execute(
        "SELECT extraction_id, status, stats_json FROM extractions"
        " WHERE source=? AND doc_id=? AND version_id=?"
        " ORDER BY rowid DESC",
        (source, doc_id, version_id)).fetchall()
    chosen = None
    # pass 1: newest FULLY usable extraction
    for candidate in extractions:
        flags = _usable_flags(conn, candidate["extraction_id"])
        if flags and all(flags) and _complete_quality(conn, candidate):
            chosen = candidate
            break
    # pass 2 (degraded fallback): newest with ANY usable block - only
    # when no extraction is fully usable
    if chosen is None:
        for candidate in extractions:
            if candidate["status"] == "failed":
                continue
            flags = _usable_flags(conn, candidate["extraction_id"])
            if any(flags):
                chosen = candidate
                break
    if chosen is None:
        return None
    result = {"extraction_id": chosen["extraction_id"], "status": chosen["status"]}
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
