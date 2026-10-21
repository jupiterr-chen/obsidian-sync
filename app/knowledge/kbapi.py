"""/api/kb/v1 HTTP service (P3-02, docs/04 contract).

Runs on its own port, separate from the first-layer library service whose
/api/v1 behavior is untouched. Every endpoint requires a bearer token with
the right permission scope (research.read for data, admin.jobs for ops).
Tokens come from the knowledge config file / environment - never from the
repo. The server is read-only against the knowledge store except for job
ops which are guarded by admin.jobs.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import traceback
import uuid
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

from .extract import to_evidence_block
from .indexing import MAX_QUERY_CHARS, SearchFilters, search, snippet_for
from .schema import validate_evidence_block
from .store import KnowledgeStore

PERM_READ = "research.read"
RESULT_WINDOW_MAX = 1000  # R12: hard pagination window
PERM_ADMIN_JOBS = "admin.jobs"

# ---------------------------------------------------------------------------
# Document metadata quality flags (advisory, read-time, deterministic).
#
# A flag records an observable inconsistency - a malformed period literal or
# an implausible period/published distance - it never rewrites or rejects
# the stored catalog value. Consumers should treat a flagged field as
# UNVERIFIED rather than trusting or discarding it blindly.
# ---------------------------------------------------------------------------
# doc_type substrings (case-insensitive) that mark a document as a financial
# filing expected to carry a report period and an issuer symbol.
FINANCIAL_DOC_TYPE_TOKENS: Tuple[str, ...] = (
    "report", "earnings", "results", "interim", "annual", "quarter",
    "公告", "報告", "报告", "財報", "财报", "季報", "季报", "年報", "年报",
    "中期", "业绩", "業績",
)
_PERIOD_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DAY_PREFIX_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
# A filing is normally published days-to-months after its period end; a gap
# beyond this many days in EITHER direction means period or published_at is
# suspect (e.g. an FY2023 annual stored with the previous fiscal year end).
PERIOD_SUSPECT_GAP_DAYS = 400
# 財政年度/財務年度 titles imply the fiscal calendar, so the report period
# must be one of a small set of period-end conventions. Real defect this
# catches: 「2023財政年度中期報告」 stored with report_period=2021-12-31
# (correct: 2022-09-30). Bounded deterministic rule; titles without the
# fiscal-year phrase (10-K, 業績公告, broker notes) are never checked.
_FISCAL_TITLE_RE = re.compile(
    r"(20\d{2})\s*(?:財政年度|财政年度|財務年度|财务年度)(中期)?")


def _expected_period_ends(fiscal_year: int, interim: bool) -> frozenset:
    """Period-end conventions implied by a 財政年度 (fiscal-year) title.

    Annual: year ending fiscal_year-03-31 (Apr–Mar fiscal, e.g. 9988) or
    fiscal_year-12-31 (calendar year). Interim: six months to (fiscal_year
    -1)-09-30 (Apr–Mar) or mid-year/quarter ends within fiscal_year.
    """
    if interim:
        return frozenset({
            "%d-09-30" % (fiscal_year - 1),
            "%d-06-30" % fiscal_year,
            "%d-09-30" % fiscal_year,
            "%d-12-31" % fiscal_year,
        })
    return frozenset({"%d-03-31" % fiscal_year, "%d-12-31" % fiscal_year})


def _iso_day(value: Any) -> Optional[date]:
    """Leading YYYY-MM-DD of a stored date/timestamp, or None if absent/malformed."""
    if not value:
        return None
    match = _DAY_PREFIX_RE.match(str(value).strip())
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def document_metadata_flags(doc: Dict[str, Any]) -> List[str]:
    """Bounded metadata flags for one kb_documents row (see block comment)."""
    flags: List[str] = []
    period = str(doc.get("report_period") or "").strip()
    symbol = str(doc.get("symbol") or "").strip()
    doc_type = str(doc.get("doc_type") or "").strip().lower()
    if period and not _PERIOD_DAY_RE.match(period):
        flags.append("period_invalid")
    period_day = _iso_day(period)
    published_day = _iso_day(doc.get("published_at"))
    if (period_day is not None and published_day is not None
            and abs((published_day - period_day).days) > PERIOD_SUSPECT_GAP_DAYS):
        flags.append("period_suspect")
    if period_day is not None:
        title = "%s\n%s" % (doc.get("title") or "", doc.get("display_title") or "")
        fiscal_mentions = _FISCAL_TITLE_RE.findall(title)
        if fiscal_mentions:
            consistent = any(
                period_day.isoformat() in _expected_period_ends(int(year), bool(interim))
                for year, interim in fiscal_mentions
            )
            if not consistent:
                flags.append("period_title_mismatch")
    if any(token in doc_type for token in FINANCIAL_DOC_TYPE_TOKENS):
        if not period:
            flags.append("period_missing")
        if not symbol:
            flags.append("symbol_missing")
    return flags


class KbApiError(Exception):
    def __init__(self, status: int, code: str, message: str,
                 retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.retryable = retryable


def encode_cursor(payload: Dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> Dict[str, Any]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        return json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except Exception:
        raise KbApiError(400, "invalid_cursor", "cursor is not decodable")


class KbApi:
    """Request handling logic, transport-agnostic for testability."""

    def __init__(self, kb: KnowledgeStore, tokens: Dict[str, List[str]],
                 embedder: Any = None, chat: Any = None,
                 budget: Any = None, vision: Any = None,
                 snapshot_root: str = "state/snapshots"):
        from .budget import Budget, BudgetLedger

        self.kb = kb
        self.tokens = tokens
        self.embedder = embedder
        self.chat = chat
        self.vision = vision
        self.budget = budget if budget is not None else Budget()
        self.ledger = BudgetLedger(kb, self.budget)
        self.snapshot_root = snapshot_root

    def attach_providers(self, chat: Any = None, embedder: Any = None,
                         vision: Any = None) -> None:
        """Explicit role binding (R03): a vision model never impersonates
        the chat role, and analysis stays disabled without a real chat."""
        self.chat = chat
        self.embedder = embedder
        self.vision = vision

    def authenticate(self, bearer: Optional[str], permission: str) -> str:
        if not bearer:
            raise KbApiError(401, "unauthenticated", "missing bearer token")
        for token, perms in self.tokens.items():
            if token == bearer and permission in perms:
                return permission
        raise KbApiError(403, "forbidden", "token lacks %s" % permission)

    # ------------------------------------------------------------- handlers
    def health(self) -> Dict[str, Any]:
        return {"status": "ok"}

    def ready(self) -> Dict[str, Any]:
        generation = self.kb.active_generation()
        return {"ready": generation is not None,
                "generation_id": generation["generation_id"] if generation else None}

    def do_search(self, body: Dict[str, Any], limit_default: int = 20) -> Dict[str, Any]:
        request_id = "req-" + uuid.uuid4().hex[:16]
        query = body.get("query")
        if not isinstance(query, str) or not query.strip():
            raise KbApiError(400, "invalid_query", "query must be a non-empty string")
        if len(query) > MAX_QUERY_CHARS:
            raise KbApiError(400, "invalid_query",
                             "query longer than %d characters" % MAX_QUERY_CHARS)
        mode = body.get("mode", "keyword")
        if mode not in ("keyword", "hybrid"):
            raise KbApiError(400, "invalid_mode", "mode must be keyword|hybrid")
        raw_filters = body.get("filters") or {}
        if not isinstance(raw_filters, dict):
            raise KbApiError(400, "invalid_filters", "filters must be an object")
        # R12: cursor identity is validated FIRST - a cursor from another
        # query/mode/generation must 409 even when the mode itself is
        # unavailable in this deployment
        pre_cursor = body.get("cursor")
        if pre_cursor:
            decoded = decode_cursor(pre_cursor)
            if decoded.get("digest") != self._query_digest(query, raw_filters,
                                                           mode):
                raise KbApiError(409, "cursor_expired",
                                 "cursor belongs to a different query or mode")
            if decoded.get("epoch") and                     decoded.get("epoch") != self.metadata_epoch():
                raise KbApiError(409, "cursor_expired",
                                 "document metadata changed since the cursor"
                                 " was issued; restart pagination")
        if mode == "hybrid" and self.embedder is None:
            raise KbApiError(422, "mode_unavailable",
                             "mode %r is not enabled in this deployment" % mode)
        if raw_filters.get("collections") not in (None, ["source_documents"]):
            raise KbApiError(403, "forbidden",
                             "no accessible collections match the filter")
        filters = SearchFilters(
            sources=raw_filters.get("sources"),
            symbols=raw_filters.get("symbols"),
            doc_types=raw_filters.get("doc_types"),
            date_from=raw_filters.get("date_from"),
            date_to=raw_filters.get("date_to"),
            as_of=raw_filters.get("as_of"),
            as_of_mode=raw_filters.get("as_of_mode", "system"),
        )
        if filters.as_of_mode not in ("system", "public"):
            raise KbApiError(400, "invalid_filters", "as_of_mode must be system|public")
        limit = body.get("limit", limit_default)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise KbApiError(400, "invalid_limit", "limit must be 1..100")
        cursor = body.get("cursor")
        offset = 0
        if cursor:
            decoded = decode_cursor(cursor)
            digest = self._query_digest(query, raw_filters, mode)
            if decoded.get("digest") != digest:
                raise KbApiError(409, "cursor_expired",
                                 "cursor belongs to a different query or mode")
            active = self.kb.active_generation()
            if active and decoded.get("generation") != active["generation_id"]:
                raise KbApiError(409, "cursor_expired",
                                 "index generation changed since the cursor was issued")
            if decoded.get("epoch") and                     decoded.get("epoch") != self.metadata_epoch():
                raise KbApiError(409, "cursor_expired",
                                 "document metadata changed; restart pagination")
            try:
                offset = int(decoded.get("offset", 0))
            except (TypeError, ValueError):
                raise KbApiError(400, "invalid_cursor", "cursor offset invalid")

        # R12: fetch the FULL window up to this page's end so offset slicing
        # sees every qualifying row (the old limit+1 recall truncated
        # traversal after page two).
        window = offset + limit + 1
        if window > RESULT_WINDOW_MAX:
            raise KbApiError(422, "result_window_exceeded",
                             "pagination window exceeds %d hits; refine the"
                             " query" % RESULT_WINDOW_MAX, retryable=False)
        if mode == "hybrid":
            from .analysis import hybrid_search

            result = hybrid_search(self.kb, query, self.embedder, filters,
                                   limit=window, ledger=self.ledger)
            if not result.get("ok"):
                if str(result.get("error", "")).startswith("budget"):
                    raise KbApiError(429, "budget_exceeded",
                                     result.get("error", "budget exceeded"),
                                     retryable=True)
                raise KbApiError(503, "not_ready", result.get("error", "not ready"))
            hits = [SimpleNamespace(block=h["block"], score=h["score"],
                                    score_kind=h["score_kind"],
                                    matched_terms=h.get("matched_terms", []))
                    for h in result["hits"]]
        else:
            result = search(self.kb, query, filters, limit=window)
            if not result.get("ok"):
                raise KbApiError(503, "not_ready", result.get("error", "not ready"))
            hits = result["hits"]
        page = hits[offset:offset + limit]
        next_cursor = None
        if offset + limit < len(hits):
            next_cursor = encode_cursor({
                "digest": self._query_digest(query, raw_filters, mode),
                "epoch": self.metadata_epoch(),
                "generation": result["generation_id"],
                "offset": offset + limit,
            })
        normalized = {k: v for k, v in raw_filters.items() if v}
        return {
            "request_id": request_id,
            "generation_id": result["generation_id"],
            "normalized_filters": normalized,
            "hits": [self._hit_to_json(hit) for hit in page],
            "next_cursor": next_cursor,
        }

    def _query_digest(self, query: str, filters: Dict[str, Any],
                      mode: str = "keyword") -> str:
        # R12: mode is part of the cursor identity - a keyword cursor must
        # not be replayed against a hybrid result set
        canonical = json.dumps({"q": query, "f": filters, "m": mode},
                               ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    def metadata_epoch(self) -> str:
        """S08/T04: digest over the VALUES of every revision-prone field
        that search filters read (available/symbol/doc_type/dates/source),
        plus version-level public-time bases. Length/count sums miss
        same-length edits and offsetting changes; hashing the normalized
        row stream catches both."""
        with self.kb._lock:
            rows = self.kb._conn.execute(
                "SELECT source, doc_id, UPPER(COALESCE(symbol,'')),"
                " COALESCE(doc_type,''), COALESCE(report_date,''),"
                " COALESCE(published_at,''), COALESCE(filing_date,''),"
                " CASE WHEN available=1 THEN 1 ELSE 0 END AS avail"
                " FROM kb_documents ORDER BY source, doc_id").fetchall()
            version_rows = self.kb._conn.execute(
                "SELECT source, doc_id, version_id, public_available_at"
                " FROM kb_versions WHERE is_current=1"
                " ORDER BY source, doc_id").fetchall()
        parts = ["|".join(str(r[i]) for i in range(8)) for r in rows]
        parts += ["v:" + "|".join(str(r[i]) for i in range(4))
                  for r in version_rows]
        from .content import revision
        parts.append("content:" + revision(self.kb._conn))
        epoch_source = "\n".join(parts)
        return hashlib.sha256(epoch_source.encode("utf-8")).hexdigest()[:12]

    def _hit_to_json(self, hit) -> Dict[str, Any]:
        from .content import evidence_url
        block = hit.block
        evidence = to_evidence_block(block)
        text, _spans = snippet_for(block["text"], hit.matched_terms)
        return {
            "schema_version": "1",
            "source": block["source"],
            "doc_id": block["doc_id"],
            "source_version": block["version_id"],
            "source_sha256": block["snapshot_sha256"],
            "extraction_id": block["extraction_id"],
            "block_id": block["block_id"],
            "projection_id": block.get("projection_id"),
            "chart_assets": block.get("chart_assets", []),
            "block_type": block["block_type"],
            "text": block["text"],
            "snippet": text,
            "locator": block["locator"],
            "quality": block["quality"],
            "evidence_url": evidence_url(block),
            "source_version_url": "/api/kb/v1/documents/%s/%s/versions/%s" % (
                block["source"], block["doc_id"], block["version_id"]),
            "score_kind": hit.score_kind,
            "score": hit.score,
        }

    def list_documents(self, params: Dict[str, List[str]]) -> Dict[str, Any]:
        """Directory listing over kb_documents (identity-driven enumeration).

        Lets a consumer enumerate a subject's document set deterministically
        (e.g. every filing for one symbol) instead of reconstructing it from
        keyword recall, where "no hits" was indistinguishable from "not in
        the library". Stable order (source, doc_id); the cursor is bound to
        the filter set and the metadata epoch, mirroring search pagination.
        """
        def _single(name: str) -> Optional[str]:
            # accepts parse_qs shape (list) and bare strings from direct callers
            value = params.get(name)
            if isinstance(value, (list, tuple)):
                return value[0] if value else None
            return value if isinstance(value, str) else None

        def _values(name: str) -> List[str]:
            value = params.get(name)
            if isinstance(value, (list, tuple)):
                return [item for item in value if isinstance(item, str)]
            return [value] if isinstance(value, str) else []

        where: List[str] = []
        args: List[Any] = []
        symbols = [s for s in _values("symbol") if s.strip()]
        if symbols:
            where.append("UPPER(COALESCE(d.symbol,'')) IN (%s)"
                         % ",".join("?" for _ in symbols))
            args.extend(s.upper() for s in symbols)
        doc_type = _single("doc_type")
        if doc_type:
            where.append("UPPER(COALESCE(d.doc_type,'')) = UPPER(?)")
            args.append(doc_type)
        source = _single("source")
        if source:
            where.append("d.source = ?")
            args.append(source)
        date_expr = ("COALESCE(d.report_date, substr(d.published_at,1,10),"
                     " d.filing_date, substr(d.first_seen_at,1,10))")
        date_from = _single("date_from")
        if date_from:
            where.append(date_expr + " >= ?")
            args.append(date_from)
        date_to = _single("date_to")
        if date_to:
            where.append(date_expr + " <= ?")
            args.append(date_to)
        available = _single("available")
        if available is not None:
            normalized = available.strip().lower()
            if normalized not in ("true", "false", "1", "0"):
                raise KbApiError(400, "invalid_filters",
                                 "available must be true|false")
            where.append("d.available = ?")
            args.append(1 if normalized in ("true", "1") else 0)
        limit = 50
        raw_limit = _single("limit")
        if raw_limit is not None:
            try:
                limit = int(raw_limit)
            except ValueError:
                raise KbApiError(400, "invalid_limit", "limit must be an integer")
        if not 1 <= limit <= 100:
            raise KbApiError(400, "invalid_limit", "limit must be 1..100")
        # digest over the RESOLVED filter values so callers may pass parse_qs
        # lists or bare strings interchangeably without breaking cursors
        filter_digest = hashlib.sha256(json.dumps(
            {"symbol": symbols, "doc_type": doc_type, "source": source,
             "date_from": date_from, "date_to": date_to,
             "available": (available.strip().lower()
                           if available is not None else None)},
            sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
        cursor = _single("cursor")
        offset = 0
        if cursor:
            decoded = decode_cursor(cursor)
            if decoded.get("digest") != filter_digest:
                raise KbApiError(409, "cursor_expired",
                                 "cursor belongs to a different filter set")
            if decoded.get("epoch") and                     decoded.get("epoch") != self.metadata_epoch():
                raise KbApiError(409, "cursor_expired",
                                 "document metadata changed; restart pagination")
            try:
                offset = int(decoded.get("offset", 0))
            except (TypeError, ValueError):
                raise KbApiError(400, "invalid_cursor", "cursor offset invalid")
        if offset + limit > RESULT_WINDOW_MAX:
            raise KbApiError(422, "result_window_exceeded",
                             "pagination window exceeds %d documents"
                             % RESULT_WINDOW_MAX, retryable=False)
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        listing_sql = (
            "SELECT d.*,"
            " (SELECT COUNT(*) FROM kb_versions v"
            "   WHERE v.source=d.source AND v.doc_id=d.doc_id) AS version_count,"
            " (SELECT v2.version_id FROM kb_versions v2"
            "   WHERE v2.source=d.source AND v2.doc_id=d.doc_id"
            "   AND v2.is_current=1 LIMIT 1) AS current_version_id"
            " FROM kb_documents d" + clause +
            " ORDER BY d.source, d.doc_id LIMIT ? OFFSET ?")
        with self.kb._lock:
            rows = self.kb._conn.execute(
                listing_sql, [*args, limit, offset]).fetchall()
            total_row = self.kb._conn.execute(
                "SELECT COUNT(*) FROM kb_documents d" + clause, args).fetchone()
        total = int(total_row[0]) if total_row else 0
        documents = []
        for row in rows:
            doc = dict(row)
            doc["available"] = bool(doc.pop("available"))
            doc["metadata_flags"] = document_metadata_flags(doc)
            doc["document_url"] = "/api/kb/v1/documents/%s/%s" % (
                doc["source"], doc["doc_id"])
            documents.append(doc)
        next_cursor = None
        if offset + limit < total:
            next_cursor = encode_cursor({
                "digest": filter_digest, "epoch": self.metadata_epoch(),
                "offset": offset + limit})
        return {"documents": documents, "total": total, "limit": limit,
                "offset": offset, "next_cursor": next_cursor}

    def document(self, source: str, doc_id: str) -> Dict[str, Any]:
        with self.kb._lock:
            doc = self.kb._conn.execute(
                "SELECT * FROM kb_documents WHERE source=? AND doc_id=?",
                (source, doc_id)).fetchone()
            versions = self.kb._conn.execute(
                "SELECT version_id, sha256, bytes, media_type, ext, is_current,"
                " state FROM kb_versions WHERE source=? AND doc_id=?"
                " ORDER BY is_current DESC, version_id",
                (source, doc_id)).fetchall()
        if doc is None:
            raise KbApiError(404, "not_found", "document not found")
        result = dict(doc)
        result["available"] = bool(result.pop("available"))
        result["metadata_flags"] = document_metadata_flags(result)
        version_list = []
        for v in versions:
            v = dict(v)
            v["is_current"] = bool(v["is_current"])
            extraction = self.kb.latest_extraction(source, doc_id, v["version_id"])
            v["extraction_status"] = extraction["status"] if extraction else None
            v["extraction_id"] = extraction["extraction_id"] if extraction else None
            version_list.append(v)
        result["versions"] = version_list
        return result

    def document_version(self, source: str, doc_id: str, version_id: str) -> Dict[str, Any]:
        doc = self.document(source, doc_id)
        for version in doc["versions"]:
            if version["version_id"] == version_id:
                version = dict(version)
                # R11: link the immutable byte snapshot for this fixed version
                version["snapshot_url"] = "/api/kb/v1/snapshots/%s/%s/%s" % (
                    source, doc_id, version_id)
                snap = self.kb.get_snapshot(source, doc_id, version_id)
                if snap is not None:
                    version["snapshot_sha256"] = snap["sha256"]
                    version["snapshot_state"] = snap.get("state", "verified")
                else:
                    version["snapshot_state"] = "not_taken"
                return {"source": source, "doc_id": doc_id, "version": version,
                        "document": {k: doc[k] for k in
                                     ("title", "display_title", "market", "symbol",
                                      "doc_type", "report_period", "filing_date",
                                      "published_at", "report_date", "first_seen_at")}}
        raise KbApiError(404, "not_found", "version not found")

    def snapshot_bytes(self, source: str, doc_id: str,
                       version_id: str) -> Dict[str, Any]:
        """R11: serve the immutable byte snapshot of a fixed version.

        The stored blob is re-verified (sha256+size) against the recorded
        identity on every read - sealing time is not a permanent disk
        integrity proof (R04 lineage).
        """
        snap = self.kb.get_snapshot(source, doc_id, version_id)
        if snap is None:
            raise KbApiError(404, "not_found", "snapshot not taken")
        from .snapshot import SnapshotStore, IntegrityError

        blobs = SnapshotStore(self.snapshot_root)
        # S04: verify and read the SAME bytes - hash the content actually
        # being returned instead of verify-then-reopen (the re-review's
        # verify/read swap window); a mismatch mid-read refuses or retries
        # against a consistent copy, never serving new bytes under the old
        # identity.
        path = os.path.join(blobs.root, *snap["store_path"].split("/"))
        import hashlib

        data = None
        for attempt in range(3):
            try:
                with open(path, "rb") as handle:
                    data = handle.read()
            except OSError as exc:
                raise KbApiError(404, "not_found",
                                 "snapshot blob unreadable: %s" % exc)
            actual_sha = hashlib.sha256(data).hexdigest()
            if actual_sha == snap["sha256"] and len(data) == snap["bytes"]:
                break
            data = None  # concurrent rewrite: retry the read
        if data is None:
            self.kb.mark_snapshot_state(source, doc_id, version_id, "corrupted")
            raise KbApiError(409, "snapshot_corrupted",
                             "stored bytes fail identity verification")
        version_row = self.kb.get_version(source, doc_id, version_id) or {}
        media_type = version_row.get("media_type") or "application/octet-stream"
        filename = "%s_%s" % (doc_id, version_id)
        ext = version_row.get("ext")
        if ext:
            filename += "." + ext
        return {"data": data, "media_type": media_type, "filename": filename,
                "etag": '"%s"' % snap["sha256"]}

    def evidence(self, block_id: str, projection_id=None) -> Dict[str, Any]:
        row = self.kb.get_block_with_identity(block_id)
        if row is None:
            raise KbApiError(404, "not_found", "evidence block not found")
        evidence = to_evidence_block(row)
        errors = validate_evidence_block(evidence)
        if errors:  # never serve an invalid evidence block
            raise KbApiError(500, "invalid_evidence",
                             "stored block fails its contract")
        siblings = self.kb.get_blocks(row["extraction_id"])
        index = next(i for i, b in enumerate(siblings) if b["block_id"] == block_id)
        context_before = [b["text"] for b in siblings[max(0, index - 1):index]]
        context_after = [b["text"] for b in siblings[index + 1:index + 2]]
        from .content import project_block
        try:
            projection = project_block(self.kb._conn, row, projection_id=projection_id)
        except ValueError as exc:
            raise KbApiError(409, "projection_unavailable", str(exc))
        if projection_id:
            evidence = to_evidence_block(dict(row, text=projection["text"]))
            evidence["projection_id"] = projection_id
            from .content import consumer_blocks
            context_before = [b["text"] for b in consumer_blocks(self.kb, siblings[max(0,index-1):index])]
            context_after = [b["text"] for b in consumer_blocks(self.kb, siblings[index+1:index+2])]
        response = {
            "evidence": evidence,
            "default_projection": {k: projection.get(k) for k in
                                   ("projection_id", "text", "chart_assets", "content_policy")},
            "raw_evidence_retained": True,
            "raw_evidence_url": "/api/kb/v1/evidence/" + block_id,
            "projection_selection": "explicit" if projection_id else "current",
            "context": {"before": context_before, "after": context_after},
            "source_version_url": "/api/kb/v1/documents/%s/%s/versions/%s" % (
                row["source"], row["doc_id"], row["version_id"]),
        }
        raw_table = row.get("table") if isinstance(row, dict) else None
        if isinstance(raw_table, dict) and isinstance(raw_table.get("rows"), list):
            # Sibling section (NOT part of the evidence-block v1 contract):
            # the structured table with read-time numeric interpretation, so
            # consumers bind a value to (row, col) instead of guessing the
            # column of a flattened text line.
            from .tables import TableBlock

            table = TableBlock(rows=raw_table["rows"],
                               header_rows=int(raw_table.get("header_rows") or 0))
            response["table"] = {
                "rows": table.rows,
                "header_rows": table.header_rows,
                "normalized_cells": table.normalized_cells(),
            }
        return response

    def extraction_blocks(self, extraction_id: str, cursor: Optional[str],
                          limit: int = 50) -> Dict[str, Any]:
        extraction = self.kb.get_extraction(extraction_id)
        if extraction is None:
            raise KbApiError(404, "not_found", "extraction not found")
        offset = 0
        if cursor:
            decoded = decode_cursor(cursor)
            if decoded.get("extraction_id") != extraction_id:
                raise KbApiError(409, "cursor_expired", "cursor belongs elsewhere")
            offset = int(decoded.get("offset", 0))
        limit = max(1, min(int(limit), 200))
        blocks = self.kb.get_blocks(extraction_id)
        page = blocks[offset:offset + limit]
        next_cursor = None
        if offset + limit < len(blocks):
            next_cursor = encode_cursor({"extraction_id": extraction_id,
                                         "offset": offset + limit})
        return {"extraction_id": extraction_id,
                "status": extraction["status"],
                "blocks": [to_evidence_block(dict(b, **{
                    "source": extraction["source"], "doc_id": extraction["doc_id"],
                    "version_id": extraction["version_id"],
                    "snapshot_sha256": extraction["snapshot_sha256"],
                })) for b in page],
                "next_cursor": next_cursor}

    def chart_asset(self, block_id, name, projection_id=None):
        """Serve only an asset actually referenced by this evidence version."""
        from pathlib import Path
        payload = self.evidence(block_id, projection_id)
        assets = payload["default_projection"].get("chart_assets") or []
        asset = next((a for a in assets if a["name"] == name), None)
        if asset is None:
            raise KbApiError(404, "not_found", "chart asset not referenced by evidence")
        root = Path(self.kb.path).resolve().parent / "chart-assets"
        path = root / name
        if path.resolve().parent != root:
            raise KbApiError(409, "asset_corrupted", "chart asset path mismatch")
        try:
            data = path.read_bytes()
        except OSError:
            raise KbApiError(404, "not_found", "chart asset unavailable")
        if hashlib.sha256(data).hexdigest() != asset["sha256"]:
            raise KbApiError(409, "asset_corrupted", "chart asset hash mismatch")
        return {"data":data, "media_type":"image/png", "filename":name,
                "etag":'"'+asset["sha256"]+'"'}

    def changes(self, cursor: Optional[str], limit: int = 100) -> Dict[str, Any]:
        sequence = 0
        if cursor:
            try:
                sequence = int(decode_cursor(cursor).get("sequence", 0))
            except (TypeError, ValueError):
                raise KbApiError(400, "invalid_cursor", "cursor has no sequence")
        events = self.kb.events_after(sequence, limit=limit)
        next_cursor = None
        if len(events) == limit and events:
            next_cursor = encode_cursor({"sequence": events[-1]["sequence"]})
        return {"events": events, "next_cursor": next_cursor}

    def create_analysis_run(self, body: Dict[str, Any]) -> Dict[str, Any]:
        if self.chat is None:
            raise KbApiError(422, "task_disabled",
                             "analysis runs are not enabled in this deployment",
                             retryable=False)
        query = body.get("query")
        if not isinstance(query, str) or not query.strip():
            raise KbApiError(400, "invalid_query", "query must be a non-empty string")
        mode = body.get("mode", "keyword")
        if mode == "hybrid" and self.embedder is None:
            raise KbApiError(422, "mode_unavailable",
                             "hybrid mode is not enabled in this deployment")
        from .analysis import execute_analysis_run

        created = self.kb.create_analysis_run(query, mode=mode)
        if body.get("execute", True):
            def retriever(q, k):
                if mode == "hybrid":
                    from .analysis import hybrid_search

                    result = hybrid_search(self.kb, q, self.embedder, None,
                                           limit=k, ledger=self.ledger)
                    return result.get("hits", [])
                result = search(self.kb, q, None, limit=k)
                return result.get("hits", [])

            outcome = execute_analysis_run(
                self.kb, created["run_id"], query, self.chat,
                retriever=retriever, budget=self.budget, ledger=self.ledger)
            if outcome.get("status") == "failed":
                raise KbApiError(422, "analysis_failed",
                                 outcome.get("error", "analysis failed"),
                                 retryable=outcome.get("retryable", False))
        return self.get_analysis_run(created["run_id"])

    def get_analysis_run(self, run_id: str) -> Dict[str, Any]:
        run = self.kb.get_analysis_run(run_id)
        if run is None:
            raise KbApiError(404, "not_found", "analysis run not found")
        usage = self.kb.usage_for_run(run_id)
        return {
            "run_id": run["run_id"], "status": run["status"],
            "query": run["query"], "mode": run["mode"],
            "draft": run.get("draft"),
            "citations": run.get("citations"),
            "verification": run.get("verification"),
            "usage": usage, "error": run.get("error"),
        }

    def build_background_package(self, entity_type: str, entity_id: str,
                                 as_of: Optional[str] = None,
                                 as_of_mode: str = "system",
                                 limit: int = 50) -> Dict[str, Any]:
        from .background import build_background_package

        return build_background_package(
            self.kb, entity_type, entity_id, as_of=as_of,
            as_of_mode=as_of_mode,
            limit=max(1, min(int(limit), 200)))

    # ---------------------------------------------------------------- memory
    def list_claims(self, status: Optional[str] = None) -> Dict[str, Any]:
        return {"claims": self.kb.list_claims(status=status)}

    def get_claim(self, claim_id: str) -> Dict[str, Any]:
        claim = self.kb.get_claim(claim_id)
        if claim is None:
            raise KbApiError(404, "not_found", "claim not found")
        claim["history"] = self.kb.claim_history(claim_id)
        return claim

    def review_claim_route(self, claim_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        from .memory import review_claim

        action = body.get("action")
        reviewer = body.get("reviewer")
        if not action or not reviewer:
            raise KbApiError(400, "invalid_body", "action and reviewer are required")
        try:
            return review_claim(
                self.kb, claim_id, str(action), str(reviewer),
                note=body.get("note"),
                new_statement=body.get("statement"),
                new_evidence=body.get("evidence"),
                new_counterevidence=body.get("counterevidence"))
        except ValueError as exc:
            raise KbApiError(404 if "not found" in str(exc) else 400,
                             "not_found" if "not found" in str(exc) else "invalid_action",
                             str(exc))

    def review_proposal_route(self, proposal_id: str,
                              body: Dict[str, Any]) -> Dict[str, Any]:
        from .memory import resolve_proposal

        action = body.get("action")
        reviewer = body.get("reviewer")
        if not action or not reviewer:
            raise KbApiError(400, "invalid_body", "action and reviewer are required")
        try:
            return resolve_proposal(self.kb, proposal_id, str(action),
                                    str(reviewer))
        except ValueError as exc:
            raise KbApiError(404, "not_found", str(exc))


def load_tokens(config_dict: Dict[str, Any]) -> Dict[str, List[str]]:
    """Tokens from config; production injects via environment instead."""
    tokens: Dict[str, List[str]] = {}
    for token, perms in (config_dict.get("api_tokens") or {}).items():
        tokens[str(token)] = [str(p) for p in perms]
    env_token = os.environ.get("RESEARCHKB_KB_TOKEN")
    if env_token:
        tokens.setdefault(env_token, [PERM_READ])
    return tokens


class Handler(BaseHTTPRequestHandler):
    api: KbApi = None  # type: ignore[assignment]
    server_version = "ResearchKB-Knowledge/0.1"

    def _send(self, status: int, payload: Dict[str, Any], head_only: bool = False) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def _error(self, exc: KbApiError, head_only: bool = False) -> None:
        self._send(exc.status, {
            "error": {"code": exc.code, "message": exc.message,
                      "request_id": "req-" + uuid.uuid4().hex[:16],
                      "retryable": exc.retryable},
        }, head_only)

    def _parts(self) -> List[str]:
        return [unquote(p) for p in urlparse(self.path).path.split("/") if p]

    def _query(self) -> Dict[str, List[str]]:
        return parse_qs(urlparse(self.path).query)

    def _bearer(self) -> Optional[str]:
        header = self.headers.get("Authorization") or ""
        if header.lower().startswith("bearer "):
            return header[7:].strip() or None
        return None

    def _dispatch(self, head_only: bool) -> None:
        try:
            parts = self._parts()
            if not parts or parts[0] != "api":
                raise KbApiError(404, "not_found", "not found")
            if parts[1:2] != ["kb"] or parts[2:3] != ["v1"]:
                raise KbApiError(404, "not_found", "unknown api prefix")
            route = parts[3:]
            if not route:
                raise KbApiError(404, "not_found", "not found")

            if route == ["health"]:
                return self._send(200, self.api.health(), head_only)
            if route == ["ready"]:
                return self._send(200, self.api.ready(), head_only)

            if route[:1] == ["search"] and self.command == "POST":
                self.api.authenticate(self._bearer(), PERM_READ)
                body = self._read_json_body()
                return self._send(200, self.api.do_search(body), head_only)

            if route[:1] == ["analysis-runs"]:
                if self.command == "POST" and len(route) == 1:
                    self.api.authenticate(self._bearer(), "analysis.run")
                    body = self._read_json_body()
                    try:
                        payload = self.api.create_analysis_run(body)
                        return self._send(200, payload, head_only)
                    except KbApiError as exc:
                        return self._error(exc, head_only)
                if self.command == "GET" and len(route) == 2:
                    self.api.authenticate(self._bearer(), "analysis.run")
                    return self._send(200, self.api.get_analysis_run(route[1]),
                                      head_only)
                raise KbApiError(404, "not_found", "not found")

            if route[:1] == ["documents"]:
                self.api.authenticate(self._bearer(), PERM_READ)
                if len(route) == 1 and self.command == "GET":
                    # directory listing: identity-driven enumeration over
                    # kb_documents (symbol/doc_type/source/date filters)
                    return self._send(200, self.api.list_documents(
                        self._query()), head_only)
                if len(route) == 3:
                    return self._send(200, self.api.document(route[1], route[2]),
                                      head_only)
                if len(route) == 5 and route[3] == "versions":
                    # documents/{s}/{d}/versions/{v} - R11: the old length
                    # check made every fixed-version URL 404
                    return self._send(200, self.api.document_version(
                        route[1], route[2], route[4]), head_only)
                raise KbApiError(404, "not_found", "not found")

            if route[:1] == ["snapshots"] and len(route) == 4                     and self.command == "GET":
                self.api.authenticate(self._bearer(), PERM_READ)
                payload = self.api.snapshot_bytes(route[1], route[2], route[3])
                return self._send_blob(payload, head_only)

            if route[:1] == ["evidence"] and len(route) == 2:
                self.api.authenticate(self._bearer(), PERM_READ)
                projection = (self._query().get("projection") or [None])[0]
                return self._send(200, self.api.evidence(route[1], projection), head_only)

            if route[:1] == ["evidence"] and len(route) == 4 and route[2] == "charts" and self.command == "GET":
                self.api.authenticate(self._bearer(), PERM_READ)
                projection = (self._query().get("projection") or [None])[0]
                return self._send_blob(self.api.chart_asset(route[1], route[3], projection), head_only)

            if route[:1] == ["extractions"]:
                self.api.authenticate(self._bearer(), PERM_READ)
                if len(route) == 3 and route[2] == "blocks":
                    cursor = (self._query().get("cursor") or [None])[0]
                    limit = int((self._query().get("limit") or ["50"])[0])
                    return self._send(200, self.api.extraction_blocks(
                        route[1], cursor, limit), head_only)
                raise KbApiError(404, "not_found", "not found")

            if route[:1] == ["changes"] and len(route) == 1:
                self.api.authenticate(self._bearer(), PERM_READ)
                cursor = (self._query().get("cursor") or [None])[0]
                limit = int((self._query().get("limit") or ["100"])[0])
                return self._send(200, self.api.changes(cursor, limit), head_only)

            if route[:1] == ["claims"]:
                self.api.authenticate(self._bearer(), PERM_READ)
                if len(route) == 1:
                    status = (self._query().get("status") or [None])[0]
                    return self._send(200, self.api.list_claims(status), head_only)
                if len(route) == 2:
                    return self._send(200, self.api.get_claim(route[1]), head_only)
                if len(route) == 3 and route[2] == "review" and self.command == "POST":
                    self.api.authenticate(self._bearer(), "memory.review")
                    return self._send(200, self.api.review_claim_route(
                        route[1], self._read_json_body()), head_only)
                raise KbApiError(404, "not_found", "not found")

            if route[:1] == ["background-package"] and self.command == "POST":
                self.api.authenticate(self._bearer(), PERM_READ)
                body = self._read_json_body()
                entity_type = body.get("entity_type")
                entity_id = body.get("entity_id")
                if entity_type not in ("company", "topic") or not entity_id:
                    raise KbApiError(400, "invalid_entity",
                                     "entity_type (company|topic) and"
                                     " entity_id are required")
                # N1: a malformed as_of/as_of_mode answers 400 - never a
                # silently unfiltered "current" package labelled historical
                from .background import _parse_cutoff

                try:
                    _parse_cutoff((body.get("filters") or {}).get("as_of"))
                except ValueError as exc:
                    raise KbApiError(400, "invalid_as_of", str(exc))
                if (body.get("filters") or {}).get(
                        "as_of_mode", "system") not in ("system", "public"):
                    raise KbApiError(400, "invalid_as_of_mode",
                                     "as_of_mode must be system|public")
                package = self.api.build_background_package(
                    entity_type, entity_id,
                    as_of=(body.get("filters") or {}).get("as_of"),
                    as_of_mode=(body.get("filters") or {}).get(
                        "as_of_mode", "system"),
                    limit=body.get("limit") or 50)
                return self._send(200, package, head_only)

            if route[:1] == ["memory-proposals"] and len(route) == 3 \
                    and route[2] == "review" and self.command == "POST":
                self.api.authenticate(self._bearer(), "memory.review")
                return self._send(200, self.api.review_proposal_route(
                    route[1], self._read_json_body()), head_only)

            raise KbApiError(404, "not_found", "not found")
        except KbApiError as exc:
            self._error(exc, head_only)
        except BrokenPipeError:
            pass
        except Exception:
            self._log_exception()
            self._error(KbApiError(500, "internal_error", "internal error"), head_only)

    def _send_blob(self, payload: Dict[str, Any], head_only: bool) -> None:
        body = payload["data"]
        self.send_response(200)
        self.send_header("Content-Type", payload["media_type"])
        self.send_header("Content-Length", str(len(body)))
        self.send_header("ETag", payload["etag"])
        self.send_header("Accept-Ranges", "none")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Disposition",
                         'inline; filename="%s"' % payload["filename"])
        if str(payload["media_type"]).startswith("text/html"):
            self.send_header(
                "Content-Security-Policy",
                "sandbox; default-src 'none'; img-src data:;"
                " style-src 'unsafe-inline'; base-uri 'none';"
                " form-action 'none'")
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def _read_json_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            raise KbApiError(400, "invalid_body", "request body is not JSON")
        if not isinstance(body, dict):
            raise KbApiError(400, "invalid_body", "request body must be an object")
        return body

    def _log_exception(self) -> None:
        try:
            print(traceback.format_exc())
        except Exception:
            pass

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch(head_only=False)

    def do_HEAD(self) -> None:  # noqa: N802
        self._dispatch(head_only=True)

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch(head_only=False)

    def log_message(self, fmt, *args) -> None:
        return


def build_kb_server(kb: KnowledgeStore, tokens: Dict[str, List[str]],
                    host: str = "127.0.0.1", port: int = 8766,
                    embedder: Any = None, chat: Any = None,
                    budget: Any = None, vision: Any = None,
                    snapshot_root: str = "state/snapshots") -> ThreadingHTTPServer:
    api = KbApi(kb, tokens, embedder=embedder, chat=chat, budget=budget,
                vision=vision, snapshot_root=snapshot_root)
    handler = type("BoundKbHandler", (Handler,), {"api": api})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server
