"""Research memory: claims, decisions, review state machine, impact analysis.

Three memory kinds (docs/05): evidence memory stays in blocks/extractions;
research memory lives here as versioned claims with review history; decision
memory freezes the claim revisions it referenced at decision time. Nothing
ever rewrites history - reviews append new revisions, decisions are
immutable, and updates only create review proposals for humans to accept.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

from .store import KnowledgeStore, utc_now

STATUS_PROPOSED = "proposed"
STATUS_ACCEPTED = "accepted"
STATUS_CHALLENGED = "challenged"
STATUS_SUPERSEDED = "superseded"
STATUS_REJECTED = "rejected"

VALID_ACTIONS = {
    "accept": STATUS_ACCEPTED,
    "reject": STATUS_REJECTED,
    "challenge": STATUS_CHALLENGED,
    "revise": STATUS_PROPOSED,
    "supersede": STATUS_SUPERSEDED,
}


def _claim_id(statement: str, evidence: List[Dict[str, Any]]) -> str:
    identity = "\x00".join((statement,
                            hashlib.sha256(str(evidence).encode()).hexdigest()))
    return "clm-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def create_claim(kb: KnowledgeStore, statement: str,
                 evidence: List[Dict[str, Any]], subject: Optional[str] = None,
                 author: str = "system", prompt_version: str = "pv1",
                 counterevidence: Optional[List[Dict[str, Any]]] = None
                 ) -> Dict[str, Any]:
    claim_id = _claim_id(statement, evidence)
    if kb.get_claim(claim_id):
        return {"claim_id": claim_id, "created": False}
    claim = {
        "claim_id": claim_id, "current_revision": 1, "subject": subject,
        "statement": statement, "status": STATUS_PROPOSED, "author": author,
        "prompt_version": prompt_version, "evidence": evidence,
        "counterevidence": counterevidence or [],
        "created_at": utc_now(),
    }
    kb.upsert_claim(claim)
    kb.add_claim_revision({
        "claim_id": claim_id, "revision": 1, "statement": statement,
        "status": STATUS_PROPOSED, "evidence": evidence,
        "counterevidence": counterevidence or [], "supersedes_revision": None,
    })
    return {"claim_id": claim_id, "created": True, "revision": 1}


def review_claim(kb: KnowledgeStore, claim_id: str, action: str,
                 reviewer: str, note: Optional[str] = None,
                 new_statement: Optional[str] = None,
                 new_evidence: Optional[List[Dict[str, Any]]] = None,
                 new_counterevidence: Optional[List[Dict[str, Any]]] = None
                 ) -> Dict[str, Any]:
    """Apply a review action; every action appends an immutable revision row."""
    if action not in VALID_ACTIONS:
        raise ValueError("action must be one of %s" % sorted(VALID_ACTIONS))
    claim = kb.get_claim(claim_id)
    if claim is None:
        raise ValueError("claim %r not found" % claim_id)
    new_status = VALID_ACTIONS[action]
    # every action appends a new revision row (A19: 确认/拒绝/质疑/替代均留历史);
    # content-carrying actions may replace statement/evidence on top of that
    if action in ("revise", "supersede"):
        statement = new_statement or claim["statement"]
        evidence = new_evidence if new_evidence is not None else claim["evidence"]
        counterevidence = (new_counterevidence if new_counterevidence is not None
                           else claim["counterevidence"])
    else:
        statement = claim["statement"]
        evidence = claim["evidence"]
        counterevidence = claim["counterevidence"]
    revision = claim["current_revision"] + 1

    now = utc_now()
    kb.add_claim_revision({
        "claim_id": claim_id, "revision": revision, "statement": statement,
        "status": new_status, "evidence": evidence,
        "counterevidence": counterevidence, "reviewer": reviewer,
        "reviewed_at": now, "review_note": note,
        "supersedes_revision": (claim["current_revision"]
                                if action in ("revise", "supersede") else None),
    })
    kb.upsert_claim({
        "claim_id": claim_id, "current_revision": revision,
        "subject": claim.get("subject"), "statement": statement,
        "status": new_status, "author": claim.get("author"),
        "prompt_version": claim.get("prompt_version"), "evidence": evidence,
        "counterevidence": counterevidence, "created_at": claim.get("created_at"),
    })
    return {"claim_id": claim_id, "revision": revision, "status": new_status}


def record_decision(kb: KnowledgeStore, context: str, rationale: str,
                    claim_refs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Freeze a decision with explicit claim revisions; never rewritten."""
    resolved = []
    for ref in claim_refs:
        claim_id = ref.get("claim_id")
        claim = kb.get_claim(claim_id)
        if claim is None:
            raise ValueError("claim %r not found" % claim_id)
        revision = ref.get("revision") or claim["current_revision"]
        resolved.append({
            "claim_id": claim_id, "revision": revision,
            "statement": _revision_statement(kb, claim_id, revision),
        })
    identity = "\x00".join((context, rationale, str(resolved), utc_now()))
    decision_id = "dec-" + hashlib.sha256(identity.encode()).hexdigest()[:24]
    kb.record_decision({
        "decision_id": decision_id, "recorded_at": utc_now(), "context": context,
        "rationale": rationale, "claim_refs": resolved,
    })
    return {"decision_id": decision_id, "claim_refs": resolved}


def _revision_statement(kb: KnowledgeStore, claim_id: str,
                        revision: int) -> Optional[str]:
    for row in kb.claim_history(claim_id):
        if row["revision"] == revision:
            return row["statement"]
    return None


def impact_analysis(kb: KnowledgeStore, source: str, doc_id: str,
                    version_id: str) -> Dict[str, Any]:
    """A20: new source version -> affected claims -> review proposals.

    Proposals never modify claims: accepted versions stay accepted until a
    human reviews (建议更新不自动覆盖接受版本).
    """
    affected = kb.claims_referencing_doc(source, doc_id)
    proposals = []
    for claim in affected:
        proposal_id = "rev-" + hashlib.sha256(
            "\x00".join((claim["claim_id"], "new_source_version", version_id))
            .encode("utf-8")).hexdigest()[:24]
        created = kb.add_review_proposal({
            "proposal_id": proposal_id, "claim_id": claim["claim_id"],
            "reason": "new_source_version",
            "detail": {"source": source, "doc_id": doc_id,
                       "new_version_id": version_id,
                       "affected_claim_revision": claim["current_revision"]},
        })
        if created:
            proposals.append(proposal_id)
            kb.emit_event(
                "review.proposed", source, doc_id, version_id,
                {"claim_id": claim["claim_id"], "proposal_id": proposal_id},
                event_id="evt-" + proposal_id)
    return {"affected_claims": [c["claim_id"] for c in affected],
            "new_proposals": proposals}


def resolve_proposal(kb: KnowledgeStore, proposal_id: str, action: str,
                     reviewer: str) -> Dict[str, Any]:
    """Resolve a review proposal: dismiss, or accept -> claim revision flow."""
    proposals = {p["proposal_id"]: p for p in kb.list_review_proposals()}
    if proposal_id not in proposals:
        # allow already-resolved lookups
        raise ValueError("proposal %r not found or not open" % proposal_id)
    if action == "dismiss":
        kb.update_review_proposal(proposal_id, "dismissed")
        return {"proposal_id": proposal_id, "status": "dismissed"}
    if action == "accept":
        # Accepting an impact proposal means the claim needs a new revision;
        # the human supplies the new statement via review_claim separately.
        kb.update_review_proposal(proposal_id, "resolved")
        return {"proposal_id": proposal_id, "status": "resolved",
                "next": "call review_claim(revise) with updated statement"}
    raise ValueError("action must be dismiss|accept")
