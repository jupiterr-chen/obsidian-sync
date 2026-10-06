"""Investment-framework background packages (D).

The knowledge API assembles a self-describing background package for a
company/topic query: structured facts (tables), research claims with
revisions, risks/counter-evidence, info cutoff (as_of semantics), source
list with extraction quality, missing information, and STABLE evidence
references pinned to (source, version, extraction, block). The caller
persists the package (query/filters/as_of_mode/generation/versions/
result digest) so a past decision can replay against the SAME evidence
even after knowledge updates.

N1 (Q01): as_of is now a real cutoff, not a returned field.

- system mode: a version is visible at T when the system had observed it
  (first_observed_at <= T); NULL observation time never counts (legacy
  rows cannot be proven to have existed at T).
- public mode: a version is visible at T only when a V03-bound
  public_available_at <= T exists; an unknown public time never
  masquerades as known and the version is excluded.
- the version returned for a document is the one visible at T (latest
  visibility time <= T), NOT today's is_current row; extractions must
  themselves have been created by T; claims appear at their latest
  revision created by T (public mode additionally requires the cited
  version to have been public at T).
- visibility filtering happens BEFORE the limit.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .store import KnowledgeStore


def _parse_cutoff(value: Optional[str]) -> Optional[datetime]:
    """Parse an as_of instant; None means 'no cutoff' (current view).

    Raises ValueError for malformed values so the API answers 400 instead
    of silently building a package with an unfiltered 'current' view.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("as_of must be an ISO-8601 timestamp string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        raise ValueError("as_of must be an ISO-8601 timestamp, got %r"
                         % value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    text = value[:-1] + "+00:00" if str(value).endswith("Z") else value
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _visible_at(first: Optional[str], public: Optional[str],
                cutoff: Optional[datetime], mode: str
                ) -> Optional[datetime]:
    """Visibility instant of one version under the cutoff semantics.

    Returns the instant that makes the version visible at `cutoff`, or
    None when the version is not provably visible. Without a cutoff
    every version is visible (current view).
    """
    if cutoff is None:
        return _parse_ts(first) or datetime(1, 1, 1, tzinfo=timezone.utc)
    if mode == "system":
        observed = _parse_ts(first)
        return observed if observed is not None and observed <= cutoff \
            else None
    if mode == "public":
        public_at = _parse_ts(public)
        return public_at if public_at is not None and public_at <= cutoff \
            else None
    raise ValueError("as_of_mode must be system|public")


def build_background_package(kb: KnowledgeStore, entity_type: str,
                             entity_id: str,
                             as_of: Optional[str] = None,
                             as_of_mode: str = "system",
                             limit: int = 50) -> Dict[str, Any]:
    """Assemble a background package for an entity (company by symbol or
    topic). Read-only over the knowledge store."""
    if entity_type not in ("company", "topic"):
        raise ValueError("entity_type must be company|topic")
    if as_of_mode not in ("system", "public"):
        raise ValueError("as_of_mode must be system|public")
    cutoff = _parse_cutoff(as_of)
    with kb._lock:
        if entity_type == "company":
            docs = kb._conn.execute(
                "SELECT source, doc_id, title, display_title, market, symbol,"
                " report_period, filing_date, published_at, first_seen_at,"
                " available FROM kb_documents WHERE UPPER(symbol)=UPPER(?)",
                (entity_id,)).fetchall()
        else:
            like = "%" + entity_id + "%"
            docs = kb._conn.execute(
                "SELECT source, doc_id, title, display_title, market, symbol,"
                " report_period, filing_date, published_at, first_seen_at,"
                " available FROM kb_documents WHERE title LIKE ? OR"
                " display_title LIKE ?",
                (like, like)).fetchall()

        sources: List[Dict[str, Any]] = []
        for doc in docs:
            versions = kb._conn.execute(
                "SELECT version_id, first_observed_at, public_available_at,"
                " synced_at, is_current FROM kb_versions"
                " WHERE source=? AND doc_id=?",
                (doc["source"], doc["doc_id"])).fetchall()
            # R5/AC05: with NO cutoff this is the CURRENT view - the
            # is_current=1 row decides, never a version_id ordering guess
            # between versions that share an observation timestamp
            if cutoff is None:
                current = [v for v in versions if v["is_current"]]
                chosen_version = current[0] if current else None
            else:
                chosen_version = None
            # version visible at the cutoff = latest visibility instant
            # among versions that qualify (NOT today's is_current row)
            chosen = None
            for version in versions:
                if cutoff is None and chosen_version is not None \
                        and version["version_id"] != \
                        chosen_version["version_id"]:
                    continue
                instant = _visible_at(version["first_observed_at"],
                                      version["public_available_at"],
                                      cutoff, as_of_mode)
                if instant is None:
                    continue
                synced = _parse_ts(version["synced_at"])
                rank = (instant, synced or instant, version["version_id"])
                if chosen is None or rank > chosen:
                    chosen = rank
            if chosen is None and chosen_version is not None:
                # no-cutoff fallback for stores without observation
                # stamps: the current row is still the current view
                chosen = (_parse_ts(chosen_version["first_observed_at"])
                          or datetime(1, 1, 1, tzinfo=timezone.utc),
                          _parse_ts(chosen_version["synced_at"])
                          or datetime(1, 1, 1, tzinfo=timezone.utc),
                          chosen_version["version_id"])
            if chosen is None:
                continue  # document not visible at the cutoff
            version_id = chosen[2]

            # the extraction must itself exist by the cutoff: a version
            # whose text was only extracted later is listed without text
            extraction = None
            if cutoff is None:
                extraction = kb._conn.execute(
                    "SELECT extraction_id, status, created_at FROM"
                    " extractions WHERE source=? AND doc_id=? AND"
                    " version_id=? ORDER BY rowid DESC LIMIT 1",
                    (doc["source"], doc["doc_id"], version_id)).fetchone()
            else:
                for row in kb._conn.execute(
                        "SELECT extraction_id, status, created_at FROM"
                        " extractions WHERE source=? AND doc_id=? AND"
                        " version_id=? ORDER BY rowid DESC",
                        (doc["source"], doc["doc_id"], version_id)):
                    created = _parse_ts(row["created_at"])
                    if created is not None and created <= cutoff:
                        extraction = row
                        break

            sources.append({
                "source": doc["source"], "doc_id": doc["doc_id"],
                "version_id": version_id,
                "extraction_id": (extraction["extraction_id"]
                                  if extraction else None),
                "title": doc["title"] or doc["display_title"],
                "available": bool(doc["available"]),
                "report_period": doc["report_period"],
                "first_seen_at": doc["first_seen_at"],
                "extraction_status": extraction["status"] if extraction
                else None,
                "evidence_refs": ([{
                    "extraction_id": extraction["extraction_id"],
                    "evidence_url": "/api/kb/v1/evidence/%s" % bid}
                    for bid in [r[0] for r in kb._conn.execute(
                        "SELECT block_id FROM blocks WHERE extraction_id=?"
                        " AND ordinal < 3",
                        (extraction["extraction_id"],)).fetchall()]
                ] if extraction else []),
            })

        # filter BEFORE the limit (Q01: limiting current material first
        # would hide nothing and mislabel the package as historical)
        if entity_type == "company":
            sources.sort(key=lambda s: (s["report_period"] is None,
                                        s["report_period"] or ""),
                         reverse=True)
        sources = sources[:max(1, min(int(limit), 200))]

        claims = []
        if entity_type == "company":
            for claim in kb.list_claims(subject=entity_id):
                claim_created = _parse_ts(claim["created_at"])
                if cutoff is not None and (claim_created is None
                                           or claim_created > cutoff):
                    continue  # claim did not exist at the cutoff
                revision_row = None
                for row in kb._conn.execute(
                        "SELECT revision, statement, status, evidence_json,"
                        " counterevidence_json, created_at FROM"
                        " claim_revisions WHERE claim_id=? ORDER BY revision"
                        " DESC", (claim["claim_id"],)):
                    created = _parse_ts(row["created_at"])
                    if cutoff is None or (created is not None
                                          and created <= cutoff):
                        revision_row = row
                        break
                if revision_row is None:
                    continue
                evidence = json.loads(revision_row["evidence_json"] or "[]")
                if cutoff is not None and as_of_mode == "public":
                    # public mode: the cited content must itself have been
                    # public at the cutoff; unknown public time excludes
                    if not evidence:
                        continue
                    evidence_public = True
                    for ref in evidence:
                        row = kb._conn.execute(
                            "SELECT public_available_at FROM kb_versions"
                            " WHERE source=? AND doc_id=? AND version_id=?",
                            (ref.get("source"), ref.get("doc_id"),
                             ref.get("version_id"))).fetchone()
                        public_at = _parse_ts(row["public_available_at"]) \
                            if row else None
                        if public_at is None or public_at > cutoff:
                            evidence_public = False
                            break
                    if not evidence_public:
                        continue
                claims.append({
                    "claim_id": claim["claim_id"],
                    "revision": revision_row["revision"],
                    "statement": revision_row["statement"],
                    "status": revision_row["status"],
                    "evidence": evidence,
                    "counterevidence": json.loads(
                        revision_row["counterevidence_json"] or "[]"),
                })

        generation = kb.active_generation()

    package = {
        "kind": "background-package",
        "schema": "researchkb.background/1",
        "entity": {"type": entity_type, "id": entity_id},
        "as_of": as_of, "as_of_mode": as_of_mode,
        "generation": generation["generation_id"] if generation else None,
        "sources": sources,
        "claims": claims,
        "risks_and_counter": [c for c in claims
                              if c["status"] in ("challenged",)],
        "missing_information": [
            "human quality gold-standard annotations NOT_RUN",
            "analysis generation model disabled",
        ],
        "cutoff_note": ("as_of=%s filters sources/extractions/claims by"
                        " %s visibility; unknown times are excluded, never"
                        " assumed" % (as_of, as_of_mode))
                       if as_of else
                       ("no cutoff: current system view"
                        if as_of_mode == "system" else
                        "no cutoff given for public mode: current system"
                        " view; pass as_of for public-time filtering"),
    }
    canonical = json.dumps(package, ensure_ascii=False, sort_keys=True)
    package["result_digest"] = "sha256:" + hashlib.sha256(
        canonical.encode("utf-8")).hexdigest()
    return package
