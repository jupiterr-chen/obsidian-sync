"""Public-time misbinding audit and repair (V03).

The pre-U03 code copied document-level publication dates onto version rows
whose first observation was unknown (legacy NULL). New rows no longer do
that, but rows written by the old code keep the wrong value through
COALESCE. This module provides:

- audit_public_times(db_path): READ-ONLY scan identifying suspect rows -
  a row is suspect when its public basis claims to be inherited document
  evidence (`published_at`/`filing_date` basis) but the version's first
  observation is unknown or LATER than the claimed public time. Rows with
  explicit version-scoped evidence (any other basis, e.g. explicit_filing)
  are never suspect.
- repair_public_times(db_path, apply): idempotent correction - suspect
  rows are reset to unknown (public_available_at=NULL, basis='unknown'),
  with the prior value, reason and identifying evidence preserved in a
  public_time_corrections audit table. Explicit evidence is untouched.

The repair only ever changes the derived public-time fields; it never
modifies first_observed_at, extraction rows or evidence text.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List

# bases that mean "inherited from the DOCUMENT" (the misbinding path).
# Any other basis represents version-scoped evidence and is preserved.
INHERITED_BASES = {"published_at", "filing_date"}

CORRECTIONS_TABLE = """
CREATE TABLE IF NOT EXISTS public_time_corrections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    old_available_at TEXT,
    old_basis TEXT,
    new_available_at TEXT,
    new_basis TEXT,
    reason TEXT NOT NULL,
    evidence_json TEXT,
    corrected_at TEXT NOT NULL
);
"""


def _connect_ro(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _now() -> str:
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).replace(
        microsecond=0).isoformat().replace("+00:00", "Z")


def audit_public_times(db_path: str) -> Dict[str, Any]:
    """Read-only scan for misbound public times. Never writes."""
    conn = _connect_ro(db_path)
    try:
        rows = conn.execute(
            "SELECT v.source, v.doc_id, v.version_id,"
            " v.first_observed_at, v.public_available_at,"
            " v.public_time_basis, d.published_at, d.filing_date"
            " FROM kb_versions v JOIN kb_documents d"
            " ON d.source = v.source AND d.doc_id = v.doc_id"
            " WHERE v.public_available_at IS NOT NULL").fetchall()
    finally:
        conn.close()

    suspects: List[Dict[str, Any]] = []
    for row in rows:
        basis = row["public_time_basis"]
        if basis not in INHERITED_BASES:
            continue  # explicit version-scoped evidence - never suspect
        first = row["first_observed_at"]
        public_at = row["public_available_at"]
        # suspect when the version's observation is unknown, or the
        # claimed public time predates the first time we saw the version
        # (the doc's old date cannot prove this revision was public then)
        if first is None or public_at < first:
            suspects.append({
                "source": row["source"], "doc_id": row["doc_id"],
                "version_id": row["version_id"],
                "first_observed_at": first,
                "public_available_at": public_at,
                "public_time_basis": basis,
                "document_published_at": row["published_at"],
                "document_filing_date": row["filing_date"],
                "reason": "inherited_document_date_without_version_evidence",
            })
    return {"suspect_rows": len(suspects), "rows": suspects}


def repair_public_times(db_path: str, apply: bool = False) -> Dict[str, Any]:
    """Reset misbound public times to unknown, preserving an audit trail.

    Idempotent: a second run finds nothing to repair. Only suspect rows
    (see audit_public_times) are touched; explicit evidence survives.
    """
    audit = audit_public_times(db_path)
    if not apply or not audit["rows"]:
        return {"repaired": 0, "suspect_rows": audit["suspect_rows"],
                "applied": bool(apply)}

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(CORRECTIONS_TABLE)
        repaired = 0
        for row in audit["rows"]:
            existing = conn.execute(
                "SELECT 1 FROM public_time_corrections WHERE source=? AND"
                " doc_id=? AND version_id=? AND old_available_at=?",
                (row["source"], row["doc_id"], row["version_id"],
                 row["public_available_at"])).fetchone()
            if existing:
                continue
            evidence = {
                "first_observed_at": row["first_observed_at"],
                "document_published_at": row["document_published_at"],
                "document_filing_date": row["document_filing_date"],
                "audit_reason": row["reason"],
            }
            conn.execute(
                "INSERT INTO public_time_corrections (source, doc_id,"
                " version_id, old_available_at, old_basis, new_available_at,"
                " new_basis, reason, evidence_json, corrected_at)"
                " VALUES (?,?,?,?,?,?,?, ?,?,?)",
                (row["source"], row["doc_id"], row["version_id"],
                 row["public_available_at"], row["public_time_basis"],
                 None, "unknown",
                 "misbound_inherited_document_date_reset_to_unknown",
                 json.dumps(evidence, ensure_ascii=False), _now()))
            conn.execute(
                "UPDATE kb_versions SET public_available_at=NULL,"
                " public_time_basis='unknown'"
                " WHERE source=? AND doc_id=? AND version_id=?",
                (row["source"], row["doc_id"], row["version_id"]))
            repaired += 1
        conn.commit()
    finally:
        conn.close()
    return {"repaired": repaired, "suspect_rows": audit["suspect_rows"],
            "applied": True}
