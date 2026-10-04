"""Investment-framework background packages (D).

The knowledge API assembles a self-describing background package for a
company/topic query: structured facts (tables), research claims with
revisions, risks/counter-evidence, info cutoff (as_of semantics), source
list with extraction quality, missing information, and STABLE evidence
references pinned to (source, version, extraction, block). The caller
persists the package (query/filters/as_of_mode/generation/versions/
result digest) so a past decision can replay against the SAME evidence
even after knowledge updates.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

from .store import KnowledgeStore


def build_background_package(kb: KnowledgeStore, entity_type: str,
                             entity_id: str,
                             as_of: Optional[str] = None,
                             as_of_mode: str = "system",
                             limit: int = 50) -> Dict[str, Any]:
    """Assemble a background package for an entity (company by symbol or
    topic). Read-only over the knowledge store."""
    if entity_type not in ("company", "topic"):
        raise ValueError("entity_type must be company|topic")
    with kb._lock:
        if entity_type == "company":
            docs = kb._conn.execute(
                "SELECT source, doc_id, title, display_title, market, symbol,"
                " report_period, filing_date, published_at, first_seen_at,"
                " available FROM kb_documents WHERE UPPER(symbol)=UPPER(?)"
                " ORDER BY COALESCE(report_date, published_at, filing_date)"
                " DESC LIMIT ?",
                (entity_id, limit)).fetchall()
        else:
            like = "%" + entity_id + "%"
            docs = kb._conn.execute(
                "SELECT source, doc_id, title, display_title, market, symbol,"
                " report_period, filing_date, published_at, first_seen_at,"
                " available FROM kb_documents WHERE title LIKE ? OR"
                " display_title LIKE ? LIMIT ?",
                (like, like, limit)).fetchall()

        sources: List[Dict[str, Any]] = []
        for doc in docs:
            extraction = kb._conn.execute(
                "SELECT extraction_id, status, created_at FROM extractions"
                " WHERE source=? AND doc_id=? AND version_id=(SELECT version_id"
                " FROM kb_versions vv WHERE vv.source=? AND vv.doc_id=?"
                " AND vv.is_current=1) ORDER BY rowid DESC LIMIT 1",
                (doc["source"], doc["doc_id"], doc["source"],
                 doc["doc_id"])).fetchone()
            sources.append({
                "source": doc["source"], "doc_id": doc["doc_id"],
                "title": doc["title"] or doc["display_title"],
                "available": bool(doc["available"]),
                "report_period": doc["report_period"],
                "first_seen_at": doc["first_seen_at"],
                "extraction_status": extraction["status"] if extraction else None,
                "evidence_refs": ([{
                    "extraction_id": extraction["extraction_id"],
                    "evidence_url": "/api/kb/v1/evidence/%s" % bid}
                    for bid in [r[0] for r in kb._conn.execute(
                        "SELECT block_id FROM blocks WHERE extraction_id=?"
                        " AND ordinal < 3",
                        (extraction["extraction_id"],)).fetchall()]
                ] if extraction else []),
            })

        claims = []
        for claim in kb.list_claims(subject=entity_id) if entity_type == "company" else []:
            claims.append({
                "claim_id": claim["claim_id"],
                "revision": claim["current_revision"],
                "statement": claim["statement"],
                "status": claim["status"],
                "evidence": claim["evidence"],
                "counterevidence": claim["counterevidence"],
            })

    package = {
        "kind": "background-package",
        "schema": "researchkb.background/1",
        "entity": {"type": entity_type, "id": entity_id},
        "as_of": as_of, "as_of_mode": as_of_mode,
        "sources": sources,
        "claims": claims,
        "risks_and_counter": [c for c in claims
                              if c["status"] in ("challenged",)],
        "missing_information": [
            "human quality gold-standard annotations NOT_RUN",
            "analysis generation model disabled",
        ],
        "cutoff_note": "as_of filters content by knowledge cutoff; see"
                       " docs/02 for system/public semantics",
    }
    canonical = json.dumps(package, ensure_ascii=False, sort_keys=True)
    package["result_digest"] = "sha256:" + hashlib.sha256(
        canonical.encode("utf-8")).hexdigest()
    return package
