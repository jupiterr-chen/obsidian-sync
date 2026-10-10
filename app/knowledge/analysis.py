"""Hybrid retrieval and citation-verified analysis runs (P4, ADR0006).

Everything here runs against whatever providers are injected. With no
providers configured the API keeps answering 422; with mocks, the protocol,
state machine, citation verification and budget gate are exercised - never
real quality or cost (docs/09, docs/13 V4).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .budget import Budget, BudgetExceeded, BudgetLedger, estimate_tokens
from .indexing import SearchFilters, search as keyword_search
from .providers import (
    ChatProvider,
    EmbeddingProvider,
    EgressNotAllowed,
    ProviderCallError,
    ProviderNotConfigured,
    Usage,
)
from .store import KnowledgeStore

RRF_K = 60
CITATION_RE = re.compile(r"\[(\d+)\]")


def budgeted_embed(embedder: EmbeddingProvider, texts: List[str],
                   ledger: Optional[BudgetLedger] = None,
                   kb: Optional[KnowledgeStore] = None):
    """Embed through the budget ledger when one is attached (R01).

    Without a ledger (offline/mock paths) usage is still recorded on the
    caller's store so spend stays observable. Returned vector shape is
    validated (R09): a provider answering with the wrong count or dimension
    fails loudly instead of corrupting the cache."""
    if ledger is None:
        vectors, usage = embedder.embed(texts)
        _validate_vectors(embedder, texts, vectors)
        if kb is not None:
            kb.record_usage(usage.provider, usage.model, "embedding",
                            usage.input_tokens, usage.output_tokens,
                            usage.cost_basis)
        return vectors, usage
    est = sum(estimate_tokens(t) for t in texts) + 8
    # T02: when the provider carries a per-attempt gate, requests are
    # counted per PHYSICAL attempt; the outer reservation then covers only
    # tokens so cap=1 allows exactly one attempt, not zero
    # V01: attempt-gated providers enforce the cap per PHYSICAL attempt;
    # the business reservation is token-only and its SETTLED usage row is
    # the persistent request of record
    gated = hasattr(embedder, "attempt_ledger")
    reservation = ledger.reserve("embedding", est, count_request=not gated)
    if hasattr(embedder, "attempt_ledger"):
        embedder.attempt_ledger = ledger
        embedder._attempt_count_requests = False
    try:
        vectors, usage = embedder.embed(texts)
    except Exception:
        ledger.fail_unknown(reservation)
        raise
    try:
        _validate_vectors(embedder, texts, vectors)
    except ValueError:
        # T02: the provider already billed this call (usage returned); a
        # bad SHAPE is a post-payment failure - settle the real usage, do
        # NOT release the reservation. The cache simply isn't written.
        ledger.settle(reservation, usage)
        raise
    ledger.settle(reservation, usage)
    return vectors, usage


def embedding_cache_key(embedder) -> str:
    """T06: cache identity = provider semantic name + model + dims.

    Two providers exposing the SAME model name at the SAME dimensions but
    different vector spaces must never share cache rows; the provider's
    stable semantic identity (name, optionally base_url host) keys the
    row alongside the model/revision and dimensions."""
    provider = getattr(embedder, "name", "") or ""
    model = getattr(embedder, "model", "") or ""
    dims = getattr(embedder, "dimensions", 0) or 0
    base = getattr(embedder, "base_url", "") or ""
    host = base.split("//")[-1].split("/")[0] if base else ""
    return "%s/%s/d%d%s" % (provider, model, dims, "@" + host if host else "")


def _validate_vectors(embedder, texts, vectors) -> None:
    if len(vectors) != len(texts):
        raise ValueError("embedding provider returned %d vectors for %d texts"
                         % (len(vectors), len(texts)))
    expected_dims = getattr(embedder, "dimensions", 0) or 0
    if vectors and expected_dims and len(vectors[0]) != expected_dims:
        raise ValueError("embedding dimension mismatch: %d != %d"
                         % (len(vectors[0]), expected_dims))


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    da = sum(x * x for x in a) ** 0.5 or 1.0
    db = sum(y * y for y in b) ** 0.5 or 1.0
    return num / (da * db)


def content_embedding_key(embedder, block):
    key = embedding_cache_key(embedder)
    return key + ":" + block["projection_id"] if block.get("projection_id") else key


def ensure_block_embeddings(kb: KnowledgeStore, embedder: EmbeddingProvider,
                            block_ids: Sequence[str],
                            ledger: Optional[BudgetLedger] = None) -> int:
    """Embed missing blocks (cache keyed by model). Returns newly embedded."""
    dims = getattr(embedder, "dimensions", 0) or None
    from .content import consumer_blocks
    blocks = consumer_blocks(kb, kb.blocks_by_ids(block_ids))
    blocks = [b for b in blocks if kb.get_embedding(content_embedding_key(embedder, b), b["block_id"], dimensions=dims) is None]
    if not blocks:
        return 0
    vectors, usage = budgeted_embed(embedder, [b["text"] for b in blocks],
                                    ledger=ledger, kb=kb)
    grouped = {}
    for block, vector in zip(blocks, vectors):
        grouped.setdefault(content_embedding_key(embedder, block), {})[block["block_id"]] = vector
    for cache_key, vectors_by_id in grouped.items():
        kb.put_embeddings(cache_key, vectors_by_id)
    return len(blocks)


def hybrid_search(kb: KnowledgeStore, query: str,
                  embedder: EmbeddingProvider,
                  filters: Optional[SearchFilters] = None,
                  limit: int = 20, embed_top: int = 200,
                  ledger: Optional[BudgetLedger] = None
                  ) -> Dict[str, Any]:
    """Keyword + vector recall fused with RRF (P4-02).

    R09: the candidate pool is ALWAYS the filter-approved set - keyword hits
    narrow it further, and the semantic fallback draws from the SAME
    approved set, never from the raw index. Filters (sources/symbols/dates/
    as_of/collections) apply BEFORE any embedding call, so disallowed text
    cannot leave the box via this path."""
    from .indexing import allowed_block_ids

    kw = keyword_search(kb, query, filters, limit=embed_top)
    if not kw.get("ok"):
        return kw
    allowed = allowed_block_ids(kb, filters)
    if not allowed:
        return {"ok": True, "generation_id": kw["generation_id"],
                "hits": [], "terms": kw.get("terms", [])}
    allowed_set = set(allowed)
    keyword_rank = [hit.block["block_id"] for hit in kw["hits"]
                    if hit.block["block_id"] in allowed_set]
    # S10/T06: the VECTOR leg recalls independently over the ENTIRE allowed
    # set (embed_top only caps how many top-ranked candidates flow into
    # fusion, never which blocks are scoreable), so a semantically strong
    # block at any position - including beyond the first N rows - is
    # reachable.
    ensure_block_embeddings(kb, embedder, allowed, ledger=ledger)
    vectors, _q_usage = budgeted_embed(embedder, [query], ledger=ledger, kb=kb)
    query_vec = vectors[0]
    from .content import consumer_blocks
    projected = {b["block_id"]: b for b in consumer_blocks(kb, kb.blocks_by_ids(allowed))}
    dims = getattr(embedder, "dimensions", 0) or None
    scored = []
    for block_id in allowed:
        if block_id not in projected:
            continue
        cache_key = content_embedding_key(embedder, projected[block_id])
        vector = kb.get_embedding(cache_key, block_id, dimensions=dims)
        if vector:
            scored.append((block_id, _cosine(query_vec, vector)))
    vector_rank = [bid for bid, _ in
                   sorted(scored, key=lambda t: -t[1])][:embed_top]

    fused: Dict[str, float] = {}
    for rank, bid in enumerate(keyword_rank):
        fused[bid] = fused.get(bid, 0.0) + 1.0 / (RRF_K + rank + 1)
    for rank, bid in enumerate(vector_rank):
        fused[bid] = fused.get(bid, 0.0) + 1.0 / (RRF_K + rank + 1)
    ordered = sorted(fused, key=lambda bid: -fused[bid])[:limit]
    blocks = {b["block_id"]: b for b in consumer_blocks(kb, kb.blocks_by_ids(ordered))}
    hits = []
    for bid in ordered:
        block = blocks.get(bid)
        if block:
            hits.append({
                "block": block,
                "score": round(fused[bid], 6),
                "score_kind": "rrf_hybrid",
                "matched_terms": [],
                "vector_score": next((s for b_, s in scored if b_ == bid), None),
            })
    return {"ok": True, "generation_id": kw["generation_id"], "hits": hits,
            "terms": kw.get("terms", [])}


def build_analysis_prompt(query: str, blocks: Sequence[Dict[str, Any]]) -> str:
    lines = [
        "You are a research assistant. Answer strictly using the numbered",
        "evidence blocks below. Cite every factual statement as [n] referring",
        "to the block number. If the evidence does not support a number, say",
        "unknown instead of guessing.",
        "",
        "Question: %s" % query,
        "",
    ]
    for i, block in enumerate(blocks, start=1):
        lines.append("[%d] (%s/%s page-ish %s) %s" % (
            i, block["source"], block["doc_id"],
            (block.get("locator") or {}).get("page", "?"), block["text"]))
    return "\n".join(lines)


@dataclass
class AnalysisResult:
    draft: str
    citations: List[Dict[str, Any]]
    verification: Dict[str, Any]


def verify_citations(draft: str, cited_indexes: Sequence[int],
                     blocks: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """A17: every citation must resolve to a retrieved, accessible block."""
    valid = []
    invalid = []
    from .content import evidence_url
    for idx in cited_indexes:
        if 1 <= idx <= len(blocks):
            block = blocks[idx - 1]
            valid.append({"n": idx, "block_id": block["block_id"],
                          "projection_id": block.get("projection_id"),
                          "source": block["source"], "doc_id": block["doc_id"],
                          "evidence_url": evidence_url(block)})
        else:
            invalid.append({"n": idx, "reason": "index_out_of_range"})
    return {"valid": valid, "invalid": invalid,
            "all_valid": not invalid,
            "unsupported_numeric_claims": []}


def execute_analysis_run(kb: KnowledgeStore, run_id: str, query: str,
                         chat: ChatProvider,
                         retriever=None, top_k: int = 8,
                         budget: Optional[Budget] = None,
                         prompt_version: str = "pv1",
                         ledger: Optional[BudgetLedger] = None) -> Dict[str, Any]:
    """Run one analysis: retrieve -> prompt -> model -> verify -> persist.

    Failure modes (A18): provider errors mark the run failed without
    publishing a draft; retryable errors keep the run re-runnable; budget
    breaches reserve-or-refuse BEFORE any provider bytes leave (R01).
    """
    budget = budget or Budget()
    ledger = ledger or BudgetLedger(kb, budget)
    run = kb.get_analysis_run(run_id)
    if run is None:
        raise ValueError("run %r not found" % run_id)
    from .content import consumer_blocks, is_stale
    if is_stale(kb._conn, "analysis", run_id):
        return {"run_id": run_id, "status": "stale", "error": "content_changed_create_new_run"}
    if run["status"] == "done":
        return {"run_id": run_id, "status": "done", "idempotent": True}

    kb.update_analysis_run(run_id, status="running")
    try:
        if retriever is None:
            def retriever(q, k):
                result = keyword_search(kb, q, None, limit=k)
                return result.get("hits", [])
        hits = retriever(query, top_k)
        blocks = [hit["block"] if isinstance(hit, dict) and "block" in hit
                  else hit.block for hit in hits]
        blocks = consumer_blocks(kb, blocks)
        if not blocks:
            raise ValueError("no_usable_evidence")
        prompt = build_analysis_prompt(query, blocks)
        estimated_input = estimate_tokens(prompt)
        if estimated_input > budget.max_input_tokens_per_run:
            kb.update_analysis_run(
                run_id, status="failed",
                error="budget_exceeded_per_run_input_tokens")
            return {"run_id": run_id, "status": "failed",
                    "error": "budget_exceeded_per_run_input_tokens",
                    "retryable": False}
        # U02: when the chat provider carries the per-attempt gate, physical
        # attempts are the request unit - the business reservation covers
        # tokens only (mirrors the embedding path)
        # V01: business reservation counts the logical request (persists on
        # settle); the attempt gate bounds physical retries separately
        gated_chat = hasattr(chat, "attempt_ledger")
        try:
            reservation = ledger.reserve("chat", estimated_input,
                                         run_id=run_id,
                                         count_request=not gated_chat)
        except BudgetExceeded as exc:
            code = str(exc).split(":")[0]
            kb.update_analysis_run(run_id, status="failed", error=code)
            return {"run_id": run_id, "status": "failed", "error": code,
                    "retryable": False}
        if hasattr(chat, "attempt_ledger"):
            chat.attempt_ledger = ledger
            chat._attempt_count_requests = False
        try:
            draft, usage = chat.complete(prompt)
        except EgressNotAllowed:
            ledger.release(reservation)  # gate refused before bytes left
            raise
        except Exception:
            ledger.fail_unknown(reservation, run_id=run_id)
            raise
        ledger.settle(reservation, usage, run_id=run_id)
        from .content import context_current
        if not context_current(kb, blocks):
            kb.update_analysis_run(run_id, status="stale", draft=draft,
                                   error="content_changed_during_run")
            return {"run_id": run_id, "status": "stale", "error": "content_changed_during_run"}
        cited = sorted({int(m) for m in CITATION_RE.findall(draft)})
        verification = verify_citations(draft, cited, blocks)
        kb.update_analysis_run(
            run_id, status="done", draft=draft,
            citations=[c for c in verification["valid"]],
            verification=verification, finished_at=None, error=None)
        kb.emit_event("analysis.completed", None, None, None,
                      {"run_id": run_id, "all_citations_valid":
                       verification["all_valid"]},
                      event_id="evt-run-" + run_id[-24:])
        return {"run_id": run_id, "status": "done", "draft": draft,
                "citations": verification["valid"],
                "verification": verification}
    except BudgetExceeded as exc:
        kb.update_analysis_run(run_id, status="failed", error=str(exc))
        return {"run_id": run_id, "status": "failed", "error": str(exc),
                "retryable": False}
    except ProviderCallError as exc:
        kb.update_analysis_run(run_id, status="failed",
                               error="%s" % exc)
        return {"run_id": run_id, "status": "failed", "error": str(exc),
                "retryable": exc.retryable}
    except ProviderNotConfigured as exc:
        kb.update_analysis_run(run_id, status="failed", error=str(exc))
        return {"run_id": run_id, "status": "failed", "error": str(exc),
                "retryable": False}
