"""Shared effective-extraction selection (S2/TA03/TA04).

Reading, the default search index and the governance planner must all
answer the SAME question the same way: which extraction of a version is
the currently effective one? Answer: the NEWEST extraction that has at
least one block passing the evidence-usable check - a newer nonempty
but polluted (or empty/failed) extraction never displaces a better
older one. The newer attempt is surfaced separately with its status so
operations see it without losing the good text.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .quality import block_evidence_usable


def effective_extraction(conn, source: str, doc_id: str,
                         version_id: str) -> Optional[Dict[str, Any]]:
    """Newest extraction of the version with at least one USABLE block.

    ``conn`` is a raw sqlite connection (writable store or read-only
    shim). Returns the extraction row (extraction_id/status) plus the
    newest attempt for display, or None when nothing qualifies."""
    extractions = conn.execute(
        "SELECT extraction_id, status FROM extractions"
        " WHERE source=? AND doc_id=? AND version_id=?"
        " ORDER BY rowid DESC",
        (source, doc_id, version_id)).fetchall()
    chosen = None
    for candidate in extractions:
        # ANY usable block qualifies - a mixed extraction (first page
        # damaged, later pages healthy) is still the better, newer text
        texts = conn.execute(
            "SELECT text FROM blocks WHERE extraction_id=?"
            " AND LENGTH(TRIM(text))>0 ORDER BY ordinal",
            (candidate["extraction_id"],)).fetchall()
        if any(block_evidence_usable(row["text"])[0] for row in texts):
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
