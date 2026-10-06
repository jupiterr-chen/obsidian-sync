"""Lexical index and search over evidence blocks (P3-01).

Tokenizer: ASCII terms (letters/digits with ._%+- kept, so ticker codes and
filings like ``600519`` / ``10-Q`` index whole) plus CJK character unigrams
and bigrams (short-word recall: ``毛利`` matches both the bigram and the two
unigrams). Ranking is BM25 computed over the inverted index at query time —
 adequate at research-corpus scale (hundreds of documents).

Index content is immutable per generation; publishing swaps a single active
pointer (ADR0003/0004 lineage).
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .store import KnowledgeStore

ASCII_TERM_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._%+-]*")
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")

DEFAULT_BM25_K1 = 1.5
DEFAULT_BM25_B = 0.75
MAX_QUERY_CHARS = 2000


def tokenize(text: str) -> List[str]:
    """Mixed Chinese/English tokenization with short-word fallback."""
    terms: List[str] = []
    for match in ASCII_TERM_RE.finditer(text):
        terms.append(match.group(0).lower())
    for match in CJK_RE.finditer(text):
        chunk = match.group(0)
        terms.extend(chunk)  # unigrams: one-char and two-char words stay findable
        terms.extend(chunk[i:i + 2] for i in range(len(chunk) - 1))  # bigrams
    return terms


def query_terms(query: str) -> List[str]:
    return list(dict.fromkeys(tokenize(query[:MAX_QUERY_CHARS])))


@dataclass
class SearchHit:
    block: Dict[str, Any]
    score: float
    score_kind: str = "bm25"
    matched_terms: List[str] = field(default_factory=list)


@dataclass
class SearchFilters:
    sources: Optional[List[str]] = None
    symbols: Optional[List[str]] = None
    doc_types: Optional[List[str]] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    as_of: Optional[str] = None
    as_of_mode: str = "system"  # system | public
    collections: Optional[List[str]] = None  # only "source_documents" exists today


# TQ2 v2: binary-polluted blocks (byte-decoded glyph indexes) are
# excluded from the DEFAULT search index - they remain reachable
# through the evidence/blocks APIs and the reading vault.
SELECTION_POLICY = "current-version-latest-extraction-v2"


SELECTION_SQL = (
    "SELECT extraction_id FROM ("
    "  SELECT e2.extraction_id,"
    "         ROW_NUMBER() OVER ("
    "           PARTITION BY e2.source, e2.doc_id"
    "           ORDER BY e2.created_at DESC, e2.extraction_id DESC) AS rn"
    "  FROM extractions e2"
    "  JOIN kb_versions v ON v.source = e2.source"
    "     AND v.doc_id = e2.doc_id AND v.version_id = e2.version_id"
    "  WHERE v.is_current = 1 AND e2.status != 'failed'"
    " ) WHERE rn = 1")


def _selected_blocks(kb: KnowledgeStore) -> List[Any]:
    """R08/ADR0007: index only the CURRENT source version per document,
    using that version's EFFECTIVE extraction (S2: the newest
    extraction with at least one usable block - a newer polluted or
    empty extraction never evicts older good text from the default
    index). Historical extractions stay queryable through the
    evidence/blocks APIs, never through the default search index."""
    from .effective import effective_extraction_ids

    with kb._lock:
        extraction_ids = effective_extraction_ids(kb._conn)
        if not extraction_ids:
            return []
        placeholders = ",".join("?" for _ in extraction_ids)
        rows = kb._conn.execute(
            "SELECT b.block_id, b.text, b.extraction_id FROM blocks b"
            " WHERE b.extraction_id IN (%s)"
            " ORDER BY b.extraction_id, b.ordinal" % placeholders,
            extraction_ids).fetchall()
    from .quality import block_evidence_usable

    return [row for row in rows
            if block_evidence_usable(row["text"] or "")[0]]


def allowed_block_ids(kb: KnowledgeStore,
                      filters: Optional["SearchFilters"]) -> List[str]:
    """R09: the complete filter-approved candidate set, computed BEFORE any
    embedding or recall - semantic fallback pools may never bypass
    source/symbol/date/as_of filtering."""
    filters = filters or SearchFilters()
    where, params = _document_filter_sql(filters)
    clause = " AND ".join(where)
    version_join = " JOIN kb_versions v ON v.source = b_v.source" \
                   " AND v.doc_id = b_v.doc_id AND v.version_id = b_v.version_id"
    version_where = ""
    if filters.as_of and filters.as_of_mode == "system":
        version_where = (" AND v.first_observed_at IS NOT NULL"
                         " AND v.first_observed_at <= ?")
        params = list(params) + [filters.as_of]
    if filters.as_of and filters.as_of_mode == "public":
        version_where = (" AND v.public_available_at IS NOT NULL"
                         " AND v.public_available_at <= ?")
        params = list(params) + [filters.as_of]
    sql = ("SELECT b.block_id FROM blocks b"
           " JOIN extractions b_v ON b_v.extraction_id = b.extraction_id"
           + version_join +
           " JOIN kb_documents d ON d.source = b_v.source AND d.doc_id = b_v.doc_id"
           " WHERE b.extraction_id IN (" + SELECTION_SQL + ")"
           " AND " + clause + version_where)
    with kb._lock:
        rows = kb._conn.execute(sql, params).fetchall()
    return [row["block_id"] for row in rows]


def build_generation(kb: KnowledgeStore, force: bool = False) -> Dict[str, Any]:
    """Build and publish an index generation (R07 lifecycle).

    building -> postings written -> verified (count check in the same tx)
    -> active (atomic pointer swap). Crash residue (a building or unverified
    row) is DELETED and rebuilt, never blindly activated; a healthy active
    generation keeps serving throughout and is only replaced by a verified
    successor. No-op when the active manifest already matches.
    """
    rows = _selected_blocks(kb)
    manifest_source = "\n".join("%s:%s" % (r["block_id"], r["extraction_id"])
                                for r in rows)
    manifest_hash = hashlib.sha256(
        (SELECTION_POLICY + "\x00" + manifest_source).encode("utf-8")).hexdigest()
    active = kb.active_generation()
    if active and active["manifest_hash"] == manifest_hash and not force:
        return {"ok": True, "changed": False, "generation_id": active["generation_id"],
                "manifest_hash": manifest_hash, "blocks": len(rows)}

    generation_id = "gen-" + manifest_hash[:24]
    existing = kb.get_generation(generation_id)
    if existing is not None and existing["status"] in ("building", "retired"):
        # crash residue from an interrupted build: discard and rebuild
        kb.delete_postings(generation_id)
        with kb._tx() as conn:
            conn.execute("DELETE FROM index_generations WHERE generation_id=?",
                         (generation_id,))
        existing = None
    if existing is not None and existing["status"] == "active":
        kb.retire_orphan_generations()
        return {"ok": True, "changed": False, "generation_id": generation_id,
                "manifest_hash": manifest_hash,
                "stats": existing.get("stats") or {}}
    if existing is not None and existing["status"] == "verified":
        stats = kb.doc_term_stats(generation_id)
        stats["postings"] = kb._conn.execute(
            "SELECT COUNT(*) FROM index_postings WHERE generation_id=?",
            (generation_id,)).fetchone()[0]
        kb.activate_generation(generation_id, stats)
        kb.retire_orphan_generations()
        return {"ok": True, "changed": True, "generation_id": generation_id,
                "manifest_hash": manifest_hash, "stats": stats}

    kb.create_generation(generation_id, manifest_hash)
    postings: List[Tuple[str, str, int]] = []
    doc_terms: List[Tuple[str, int, int]] = []
    for row in rows:
        counts: Dict[str, int] = {}
        for term in tokenize(row["text"]):
            counts[term] = counts.get(term, 0) + 1
        for term, tf in counts.items():
            postings.append((term, row["block_id"], tf))
        doc_terms.append((row["block_id"], len(counts), len(row["text"])))
    kb.write_postings(generation_id, postings, doc_terms)
    try:
        stats = kb.finalize_generation(generation_id, expected_blocks=len(rows))
    except ValueError as exc:
        # failed build: keep the previous healthy active, retire the residue
        kb.delete_postings(generation_id)
        with kb._tx() as conn:
            conn.execute("DELETE FROM index_generations WHERE generation_id=?",
                         (generation_id,))
        kb.retire_orphan_generations()
        return {"ok": False, "changed": False, "error": "verification_failed",
                "detail": str(exc)}
    kb.activate_generation(generation_id, stats)
    kb.retire_orphan_generations()
    kb.emit_event("index.published", None, None, None,
                  {"generation_id": generation_id, "manifest_hash": manifest_hash,
                   "selection_policy": SELECTION_POLICY, **stats},
                  event_id="evt-index-" + manifest_hash[:32])
    return {"ok": True, "changed": True, "generation_id": generation_id,
            "manifest_hash": manifest_hash, "stats": stats}


def _document_filter_sql(filters: SearchFilters) -> Tuple[List[str], List[Any]]:
    where: List[str] = []
    params: List[Any] = []
    # R08: unavailable (source missing/withdrawn) documents never match
    where.append("d.available = 1")
    if filters.sources:
        where.append("d.source IN (%s)" % ",".join("?" for _ in filters.sources))
        params.extend(filters.sources)
    if filters.symbols:
        where.append("UPPER(d.symbol) IN (%s)"
                     % ",".join("?" for _ in filters.symbols))
        params.extend(s.upper() for s in filters.symbols)
    if filters.doc_types:
        where.append("d.doc_type IN (%s)" % ",".join("?" for _ in filters.doc_types))
        params.extend(filters.doc_types)
    date_expr = ("COALESCE(d.report_date, substr(d.published_at,1,10), d.filing_date,"
                 " substr(d.first_seen_at,1,10))")
    if filters.date_from:
        where.append(date_expr + " >= ?")
        params.append(filters.date_from)
    if filters.date_to:
        where.append(date_expr + " <= ?")
        params.append(filters.date_to)
    if filters.as_of:
        if filters.as_of_mode == "public":
            # S03: public visibility is claimed on PUBLICATION EVIDENCE
            # (published_at / filing_date) - never on the report period,
            # which would leak future information. The version-level basis
            # is enforced per-candidate in search(); the document-level
            # prefilter only removes docs with NO basis at all.
            public_basis = ("COALESCE(d.published_at, d.filing_date)")
            where.append(public_basis + " IS NOT NULL")
        # system mode is enforced per-version in search() (R08): the
        # document check alone cannot prove the CURRENT version was
        # observable at as_of.
    return where, params


def search(kb: KnowledgeStore, query: str, filters: Optional[SearchFilters] = None,
           limit: int = 20, k1: float = DEFAULT_BM25_K1, b: float = DEFAULT_BM25_B
           ) -> Dict[str, Any]:
    """Keyword search over the active generation. Returns hits + generation."""
    filters = filters or SearchFilters()
    generation = kb.active_generation()
    if generation is None:
        return {"ok": False, "error": "no_active_generation"}
    terms = query_terms(query)
    if not terms:
        return {"ok": True, "generation_id": generation["generation_id"],
                "hits": [], "terms": []}
    postings = kb.postings_for_terms(generation["generation_id"], terms)
    if not postings:
        return {"ok": True, "generation_id": generation["generation_id"],
                "hits": [], "terms": terms}

    stats = kb.doc_term_stats(generation["generation_id"])
    n_docs = max(1, stats["blocks"])
    avg_len = (stats["total_length"] / n_docs) or 1.0
    all_block_ids = {entry["block_id"]
                     for entries in postings.values() for entry in entries}
    lengths = kb.block_lengths(generation["generation_id"], list(all_block_ids))
    scores: Dict[str, float] = {}
    matched: Dict[str, List[str]] = {}
    for term, entries in postings.items():
        df = len(entries)
        if df == 0:
            continue
        idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
        for entry in entries:
            block_id = entry["block_id"]
            tf = entry["tf"]
            doc_len = lengths.get(block_id, avg_len) or avg_len
            norm = tf * (k1 + 1) / (tf + k1 * (1 - b + b * doc_len / avg_len))
            scores[block_id] = scores.get(block_id, 0.0) + idf * norm
            matched.setdefault(block_id, []).append(term)

    # R12: deterministic total order (score desc, block_id asc as tiebreak)
    candidates = sorted(scores, key=lambda bid: (-scores[bid], bid))
    # fetch blocks + document metadata for filter application
    hits: List[SearchHit] = []
    limit = max(1, min(int(limit), 1000))
    where, params = _document_filter_sql(filters)
    for block_id in candidates:
        if len(hits) >= limit:
            break
        blocks = kb.blocks_by_ids([block_id])
        if not blocks:
            continue
        block = blocks[0]
        with kb._lock:
            doc = kb._conn.execute(
                "SELECT source, doc_id, symbol, doc_type, report_date, published_at,"
                " filing_date, first_seen_at FROM kb_documents"
                " WHERE source=? AND doc_id=?",
                (block["source"], block["doc_id"]),
            ).fetchone()
        if doc is None:
            continue
        doc = dict(doc)
        if where:
            clause = " AND ".join(where)
            check = kb._conn.execute(
                "SELECT 1 FROM kb_documents d WHERE d.source=? AND d.doc_id=? AND "
                + clause,
                (doc["source"], doc["doc_id"], *params),
            ).fetchone()
            if not check:
                continue
        if filters.as_of and filters.as_of_mode == "system":
            # R08: version-level observability. Unknown first_observed_at is
            # NOT visible at any past as_of (no fabricated history).
            version = kb.get_version(block["source"], block["doc_id"],
                                     block["version_id"])
            first_observed = (version or {}).get("first_observed_at")
            if not first_observed or first_observed > filters.as_of:
                continue
        if filters.as_of and filters.as_of_mode == "public":
            # S03: version-level publication evidence; unknown basis is
            # never visible at a past public cutoff (no report-period leak)
            version = kb.get_version(block["source"], block["doc_id"],
                                     block["version_id"])
            public_at = (version or {}).get("public_available_at")
            if not public_at or public_at > filters.as_of:
                continue
        hits.append(SearchHit(block=block, score=round(scores[block_id], 4),
                              matched_terms=sorted(set(matched.get(block_id, [])))))
    return {"ok": True, "generation_id": generation["generation_id"],
            "hits": hits, "terms": terms}


def snippet_for(text: str, terms: Iterable[str], width: int = 80) -> Tuple[str, List[Tuple[int, int]]]:
    """Snippet around the first match + char offsets of all matched terms."""
    lowered = text.lower()
    spans: List[Tuple[int, int]] = []
    for term in terms:
        start = lowered.find(term.lower())
        if start >= 0:
            spans.append((start, start + len(term)))
    if not spans:
        return text[:width], []
    spans.sort()
    first = spans[0][0]
    lo = max(0, first - width // 4)
    hi = min(len(text), lo + width)
    lo = max(0, hi - width)
    return text[lo:hi], spans
