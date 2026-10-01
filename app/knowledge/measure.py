"""Measurement harness for pages, text and token counts (P1-04).

Measures sampled versions from their immutable snapshots. Token counting is
pluggable: the shipped heuristic counter is explicitly approximate and must
never be reported as a real tokenizer count; real counters register through
``register_token_counter`` and name their tokenizer identity.

P1 scope: txt/html/pdf basic statistics with stdlib only. PDF body-text
extraction is P2 work; here PDFs get page counts when derivable from the
file structure and are otherwise listed as not-yet-extractable (honest
"未提取名单" rather than fake numbers).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .snapshot import SnapshotStore
from .store import KnowledgeStore

CHUNK = 1 << 20
REPORT_SCHEMA = "researchkb.measurement-report/1"


class TokenizerUnavailable(Exception):
    pass


@dataclass
class TokenCount:
    count: Optional[int]
    tokenizer: str
    method: str  # "exact" | "approximate"
    note: str = ""


TokenCounter = Callable[[str], TokenCount]


def heuristic_counter(text: str) -> TokenCount:
    """Script-aware character heuristic; clearly labelled approximate.

    CJK-heavy text uses ~1 token per character, latin text ~4 chars/token.
    This produces an ORDER OF MAGNITUDE estimate only; the docs (09) forbid
    presenting it as a tokenizer measurement.
    """
    if not text:
        return TokenCount(0, "heuristic-script-ratio", "approximate",
                          "empty text")
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    total = len(text)
    cjk_ratio = cjk / total
    latin = total - cjk
    estimate = cjk + latin / 4.0
    return TokenCount(
        int(round(estimate)), "heuristic-script-ratio", "approximate",
        "order-of-magnitude estimate; cjk_ratio=%.2f; not a tokenizer count" % cjk_ratio,
    )


_TOKEN_COUNTERS: Dict[str, TokenCounter] = {"heuristic": heuristic_counter}


def register_token_counter(name: str, counter: TokenCounter) -> None:
    _TOKEN_COUNTERS[name] = counter


def count_tokens(text: str, counter_name: str = "heuristic") -> TokenCount:
    counter = _TOKEN_COUNTERS.get(counter_name)
    if counter is None:
        raise TokenizerUnavailable(
            "token counter %r not registered (available: %s)"
            % (counter_name, sorted(_TOKEN_COUNTERS)))
    return counter(text)


# ----------------------------------------------------------------- text stats
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def extract_html_text(raw: bytes) -> tuple:
    """Baseline stdlib HTML text extraction (P2 replaces with DOM parsing)."""
    try:
        text = raw.decode("utf-8", errors="strict")
        encoding = "utf-8"
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
        encoding = "utf-8-replaced"
    # strip script/style blocks first (baseline only; P2 does real DOM work)
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
    text = _TAG_RE.sub(" ", text)
    import html as html_mod

    text = html_mod.unescape(text)
    text = _WS_RE.sub(" ", text).strip()
    return text, encoding


def decode_text(raw: bytes) -> tuple:
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace"), "utf-8-replaced"


_PAGE_OBJ_RE = re.compile(rb"/Type\s*/Page[^s]")


def pdf_page_count(raw: bytes) -> tuple:
    """Count page objects in the raw bytes; None when not derivable.

    This handles uncompressed object streams only; PDFs with compressed
    object streams (most modern files) return (None, "compressed") until the
    P2 parser is selected. Never guesses.
    """
    if b"/Type /ObjStm" in raw or b"/Type/ObjStm" in raw:
        return None, "object-streams-unsupported"
    matches = _PAGE_OBJ_RE.findall(raw)
    if not matches:
        return None, "no-page-objects-found"
    return len(matches), "page-object-scan"


@dataclass
class MeasurementRow:
    source: str
    doc_id: str
    version_id: str
    sha256: str
    fmt: str
    bytes: int
    pages: Optional[int] = None
    page_method: Optional[str] = None
    text_chars: Optional[int] = None
    text_sha256: Optional[str] = None
    encoding: Optional[str] = None
    token_count: Optional[int] = None
    token_method: Optional[str] = None
    token_tokenizer: Optional[str] = None
    token_note: Optional[str] = None
    status: str = "measured"  # measured | not_extracted | error
    status_detail: Optional[str] = None
    extras: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source, "doc_id": self.doc_id,
            "version_id": self.version_id, "sha256": self.sha256,
            "format": self.fmt, "bytes": self.bytes,
            "pages": self.pages, "page_method": self.page_method,
            "text_chars": self.text_chars, "text_sha256": self.text_sha256,
            "encoding": self.encoding,
            "token_count": self.token_count, "token_method": self.token_method,
            "token_tokenizer": self.token_tokenizer, "token_note": self.token_note,
            "status": self.status, "status_detail": self.status_detail,
        }


def measure_snapshot(row: Dict[str, Any], blob_path: str,
                     counter_name: str = "heuristic") -> MeasurementRow:
    """Measure one sampled version from its snapshot file."""
    from .sampling import format_of

    fmt = format_of(row.get("media_type"), row.get("ext"))
    out = MeasurementRow(
        source=row["source"], doc_id=row["doc_id"], version_id=row["version_id"],
        sha256=row["sha256"], fmt=fmt, bytes=row.get("bytes") or 0,
    )
    with open(blob_path, "rb") as handle:
        raw = handle.read()

    if fmt == "txt":
        text, encoding = decode_text(raw)
        out.encoding = encoding
    elif fmt == "html":
        text, encoding = extract_html_text(raw)
        out.encoding = encoding
    elif fmt == "img":
        out.status = "not_extracted"
        out.status_detail = "image OCR is P2 scope"
        return out
    elif fmt == "pdf":
        pages, method = pdf_page_count(raw)
        out.pages, out.page_method = pages, method
        out.status = "not_extracted"
        out.status_detail = "pdf body extraction is P2 scope (parser not selected)"
        return out
    else:
        out.status = "not_extracted"
        out.status_detail = "unknown format"
        return out

    out.text_chars = len(text)
    out.text_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    tokens = count_tokens(text, counter_name)
    out.token_count = tokens.count
    out.token_method = tokens.method
    out.token_tokenizer = tokens.tokenizer
    out.token_note = tokens.note
    return out


def measure_sample(kb: KnowledgeStore, blobs: SnapshotStore,
                   manifest: Dict[str, Any],
                   counter_name: str = "heuristic") -> Dict[str, Any]:
    """Measure every sample in a manifest; snapshot must already exist."""
    rows: List[Dict[str, Any]] = []
    unextracted: List[Dict[str, Any]] = []
    for sample in manifest.get("samples", []):
        snap = kb.get_snapshot(sample["source"], sample["doc_id"], sample["version_id"])
        if snap is None:
            row = MeasurementRow(
                source=sample["source"], doc_id=sample["doc_id"],
                version_id=sample["version_id"], sha256=sample.get("sha256") or "",
                fmt="unknown", bytes=sample.get("bytes") or 0,
                status="error", status_detail="snapshot missing",
            )
            rows.append(row.to_dict())
            unextracted.append({"doc_id": sample["doc_id"], "reason": "snapshot missing"})
            continue
        blob_path = os_path_join(blobs.root, snap["store_path"])
        row = measure_snapshot(sample, blob_path, counter_name)
        rows.append(row.to_dict())
        if row.status != "measured":
            unextracted.append({
                "source": row.source, "doc_id": row.doc_id,
                "version_id": row.version_id,
                "reason": row.status_detail or row.status,
            })

    measured = [r for r in rows if r["status"] == "measured"]
    token_counts = [r["token_count"] for r in measured if r["token_count"] is not None]
    exact = [r for r in measured if r.get("token_method") == "exact"]
    return {
        "schema": REPORT_SCHEMA,
        "manifest_seed": manifest.get("seed"),
        "token_counter": counter_name,
        "all_token_counts_exact": len(exact) == len(measured) and bool(measured),
        "rows": rows,
        "summary": {
            "total": len(rows),
            "measured": len(measured),
            "not_extracted_or_error": len(rows) - len(measured),
            "token_total_approximate": sum(token_counts) if token_counts else None,
            "token_note": "heuristic estimates only; real tokenizer counts are "
                          "BLOCKED until sources and a tokenizer are available",
        },
        "unextracted": unextracted,
    }


def os_path_join(root: str, rel: str) -> str:
    import os

    return os.path.join(root, *rel.split("/"))
