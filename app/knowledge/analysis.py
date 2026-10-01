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

from .indexing import SearchFilters, search as keyword_search
from .providers import (
    ChatProvider,
    EmbeddingProvider,
    ProviderCallError,
    ProviderNotConfigured,
    Usage,
)
from .store import KnowledgeStore

RRF_K = 60
CITATION_RE = re.compile(r"\[(\d+)\]")


@dataclass
class Budget:
    max_input_tokens_per_run: int = 200_000
    max_total_input_tokens: Optional[int] = None  # None = unlimited (offline)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Budget":
        return cls(
            max_input_tokens_per_run=int(data.get("max_input_tokens_per_run",
                                                   200_000)),
            max_total_input_tokens=(
                int(data["max_total_input_tokens"])
                if data.get("max_total_input_tokens") is not None else None),
        )


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    da = sum(x * x for x in a) ** 0.5 or 1.0
    db = sum(y * y for y in b) ** 0.5 or 1.0
    return num / (da * db)


def ensure_block_embeddings(kb: KnowledgeStore, embedder: EmbeddingProvider,
                            block_ids: Sequence[str]) -> int:
    """Embed missing blocks (cache keyed by model). Returns newly embedded."""
    missing = [bid for bid in block_ids if kb.get_embedding(embedder.model, bid) is None]
    if not missing:
        return 0
    blocks = kb.blocks_by_ids(missing)
    vectors, usage = embedder.embed([b["text"] for b in blocks])
    kb.put_embeddings(embedder.model,
                      {b["block_id"]: v for b, v in zip(blocks, vectors)})
    kb.record_usage(usage.provider, usage.model, "embedding",
                    usage.input_tokens, usage.output_tokens, usage.cost_basis)
    return len(blocks)


def hybrid_search(kb: KnowledgeStore, query: str,
                  embedder: EmbeddingProvider,
                  filters: Optional[SearchFilters] = None,
                  limit: int = 20, embed_top: int = 200
                  ) -> Dict[str, Any]:
    """Keyword + vector recall fused with RRF (P4-02)."""
    kw = keyword_search(kb, query, filters, limit=embed_top)
    if not kw.get("ok"):
        return kw
    # candidate pool: everything the keyword side can see
    pool_ids = [hit.block["block_id"] for hit in kw["hits"]]
    # when the keyword side finds nothing, fall back to the whole active index
    if not pool_ids:
        with kb._lock:
            rows = kb._conn.execute(
                "SELECT block_id FROM index_doc_terms WHERE generation_id=?",
                (kw["generation_id"],)).fetchall()
        pool_ids = [r["block_id"] for r in rows][:embed_top]
    ensure_block_embeddings(kb, embedder, pool_ids)
    vectors, q_usage = embedder.embed([query])
    query_vec = vectors[0]
    kb.record_usage(q_usage.provider, q_usage.model, "embedding",
                    q_usage.input_tokens, q_usage.output_tokens,
                    q_usage.cost_basis)
    scored = []
    for block_id in pool_ids:
        vector = kb.get_embedding(embedder.model, block_id)
        if vector:
            scored.append((block_id, _cosine(query_vec, vector)))
    vector_rank = [bid for bid, _ in sorted(scored, key=lambda t: -t[1])]
    keyword_rank = [h.block["block_id"] for h in kw["hits"]]

    fused: Dict[str, float] = {}
    for rank, bid in enumerate(keyword_rank):
        fused[bid] = fused.get(bid, 0.0) + 1.0 / (RRF_K + rank + 1)
    for rank, bid in enumerate(vector_rank):
        fused[bid] = fused.get(bid, 0.0) + 1.0 / (RRF_K + rank + 1)
    ordered = sorted(fused, key=lambda bid: -fused[bid])[:limit]
    blocks = {b["block_id"]: b for b in kb.blocks_by_ids(ordered)}
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
    for idx in cited_indexes:
        if 1 <= idx <= len(blocks):
            block = blocks[idx - 1]
            valid.append({"n": idx, "block_id": block["block_id"],
                          "source": block["source"], "doc_id": block["doc_id"],
                          "evidence_url": "/api/kb/v1/evidence/%s"
                                          % block["block_id"]})
        else:
            invalid.append({"n": idx, "reason": "index_out_of_range"})
    return {"valid": valid, "invalid": invalid,
            "all_valid": not invalid,
            "unsupported_numeric_claims": []}


def execute_analysis_run(kb: KnowledgeStore, run_id: str, query: str,
                         chat: ChatProvider,
                         retriever=None, top_k: int = 8,
                         budget: Optional[Budget] = None,
                         prompt_version: str = "pv1") -> Dict[str, Any]:
    """Run one analysis: retrieve -> prompt -> model -> verify -> persist.

    Failure modes (A18): provider errors mark the run failed without
    publishing a draft; retryable errors keep the run re-runnable; budget
    breaches reject before any provider call.
    """
    budget = budget or Budget()
    run = kb.get_analysis_run(run_id)
    if run is None:
        raise ValueError("run %r not found" % run_id)
    if run["status"] == "done":
        return {"run_id": run_id, "status": "done", "idempotent": True}

    if budget.max_total_input_tokens is not None:
        totals = kb.usage_totals()
        if totals["input_tokens"] >= budget.max_total_input_tokens:
            kb.update_analysis_run(run_id, status="failed",
                                   error="budget_exceeded_total_input_tokens")
            return {"run_id": run_id, "status": "failed",
                    "error": "budget_exceeded_total_input_tokens",
                    "retryable": False}

    kb.update_analysis_run(run_id, status="running")
    try:
        if retriever is None:
            def retriever(q, k):
                result = keyword_search(kb, q, None, limit=k)
                return result.get("hits", [])
        hits = retriever(query, top_k)
        blocks = [hit["block"] if isinstance(hit, dict) and "block" in hit
                  else hit.block for hit in hits]
        prompt = build_analysis_prompt(query, blocks)
        estimated_input = len(prompt) // 4 + 1
        if estimated_input > budget.max_input_tokens_per_run:
            kb.update_analysis_run(
                run_id, status="failed",
                error="budget_exceeded_per_run_input_tokens")
            return {"run_id": run_id, "status": "failed",
                    "error": "budget_exceeded_per_run_input_tokens",
                    "retryable": False}
        draft, usage = chat.complete(prompt)
        kb.record_usage(usage.provider, usage.model, "chat",
                        usage.input_tokens or estimated_input,
                        usage.output_tokens, usage.cost_basis, run_id=run_id)
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
    except ProviderCallError as exc:
        kb.update_analysis_run(run_id, status="failed",
                               error="%s" % exc)
        return {"run_id": run_id, "status": "failed", "error": str(exc),
                "retryable": exc.retryable}
    except ProviderNotConfigured as exc:
        kb.update_analysis_run(run_id, status="failed", error=str(exc))
        return {"run_id": run_id, "status": "failed", "error": str(exc),
                "retryable": False}
