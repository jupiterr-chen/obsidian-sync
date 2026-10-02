"""Pluggable text extraction into evidence blocks (P2, ADR0004).

Extractors are registered per format and must self-report parser identity;
that identity feeds the deterministic extraction_id, so the same input plus
the same parser/config always maps to the same immutable extraction. The
bundled extractors are stdlib-only: the PDF parser handles uncompressed and
FlateDecode content streams with single-byte-encoded text; CID fonts without
a usable mapping are flagged, never guessed.
"""

from __future__ import annotations

import hashlib
import re
import zlib
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Callable, Dict, List, Optional, Tuple

from .quality import (
    Quality,
    STATUS_FAILED,
    STATUS_READY,
    STATUS_REVIEW,
    analyze_text,
    merge_statuses,
    route_page_to_ocr,
)

# Versioned extraction configuration; changes must produce a new digest.
# v2: optional OCR engine integration (PDF per-page + images).
EXTRACT_CONFIG = {"normalization": 3, "blocks": "evidence-block-v1",
                  "ocr": "fallback-engine-v1"}

STAGE_EXTRACT = "extract"


def extract_config_digest() -> str:
    import json

    canonical = json.dumps(EXTRACT_CONFIG, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_extraction_id(source: str, doc_id: str, version_id: str,
                          snapshot_sha256: str, parser_id: str,
                          parser_version: str, config_digest: str) -> str:
    parts = "\x00".join((source, doc_id, version_id, snapshot_sha256,
                         parser_id, parser_version, config_digest))
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()


@dataclass
class Block:
    block_type: str            # paragraph | heading | table | caption | footnote
    text: str
    locator: Dict[str, Any]    # conforms to evidence-block v1 locator
    quality: Quality = field(default_factory=lambda: Quality(STATUS_READY))


@dataclass
class ExtractionResult:
    parser_id: str
    parser_version: str
    status: str                # ready | review | failed
    issues: List[str] = field(default_factory=list)
    blocks: List[Block] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)


class ExtractorMissing(Exception):
    pass


_EXTRACTORS: Dict[str, Callable[[bytes], ExtractionResult]] = {}


def register_extractor(fmt: str, extractor) -> None:
    _EXTRACTORS[fmt] = extractor


def get_extractor(fmt: str) -> Callable[[bytes], ExtractionResult]:
    extractor = _EXTRACTORS.get(fmt)
    if extractor is None:
        raise ExtractorMissing("no extractor registered for format %r" % fmt)
    return extractor


def available_extractors() -> List[str]:
    return sorted(_EXTRACTORS)


# ------------------------------------------------------------------- TXT
def extract_txt(raw: bytes, **_kwargs) -> ExtractionResult:
    try:
        text = raw.decode("utf-8")
        encoding = "utf-8"
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
        encoding = "utf-8-replaced"
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    blocks: List[Block] = []
    cursor = 0
    for para in paragraphs:
        start = text.find(para, cursor)
        if start < 0:  # defensive; stripped content always re-findable
            start = cursor
        blocks.append(Block(
            block_type="paragraph", text=para,
            locator={"kind": "text", "start_char": start,
                     "end_char": start + len(para)},
        ))
        cursor = start + len(para)
    quality = analyze_text(text)
    issues = list(quality.issues)
    if encoding == "utf-8-replaced":
        issues = issues or []
    return ExtractionResult(
        parser_id="stdlib-txt", parser_version="1",
        status=quality.status, issues=issues, blocks=blocks,
        stats={"encoding": encoding, "chars": len(text),
               "paragraphs": len(blocks)},
    )


# ------------------------------------------------------------------- HTML
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_SKIP_TAGS = {"script", "style", "noscript", "template"}
_TABLE_CELLS = {"td", "th"}


class _DomBlock:
    __slots__ = ("block_type", "text", "dom_path", "start_char")

    def __init__(self, block_type: str, text: str, dom_path: str, start_char: int):
        self.block_type = block_type
        self.text = text
        self.dom_path = dom_path
        self.start_char = start_char


class _HtmlTreeParser(HTMLParser):
    """Collects block-level text with DOM paths and a normalized text stream."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.path: List[Tuple[str, int]] = []          # (tag, nth-of-type)
        self.counters: List[Dict[str, int]] = []
        self.skip_depth = 0
        self.normalized: List[str] = []                # text pieces
        self.length = 0
        self.blocks: List[_DomBlock] = []
        self._current: Optional[_DomBlock] = None
        self.table_stack: List[Dict[str, Any]] = []
        self.in_caption = False

    # path helpers -----------------------------------------------------
    def _dom_path(self) -> str:
        return ">".join("%s[%d]" % (tag, nth) for tag, nth in self.path)

    def _push_path(self, tag: str) -> None:
        if not self.counters:
            self.counters = [{}]
        while len(self.counters) < len(self.path) + 1:
            self.counters.append({})
        sibling = self.counters[len(self.path)]
        sibling[tag] = sibling.get(tag, 0) + 1
        self.path.append((tag, sibling[tag]))
        while len(self.counters) < len(self.path) + 1:
            self.counters.append({})

    def _pop_path(self) -> None:
        if self.path:
            self.path.pop()

    # text handling ----------------------------------------------------
    def _flush_block(self) -> None:
        if self._current is not None and self._current.text.strip():
            self.blocks.append(self._current)
        self._current = None

    def _start_block(self, block_type: str) -> None:
        self._flush_block()
        self._current = _DomBlock(block_type, "", self._dom_path(), self.length)

    def _append_text(self, data: str) -> None:
        if not data:
            return
        if self._current is None:
            self._start_block("paragraph")
        self._current.text += data
        self.normalized.append(data)
        self.length += len(data)

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        self._push_path(tag)
        if tag in _SKIP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag in _HEADING_TAGS:
            self._start_block("heading")
        elif tag == "table":
            self._flush_block()
            self.table_stack.append({"rows": [], "row": None, "path": self._dom_path()})
        elif tag == "tr" and self.table_stack:
            self.table_stack[-1]["row"] = []
        elif tag in _TABLE_CELLS and self.table_stack and self.table_stack[-1]["row"] is not None:
            self._start_block("caption" if self.in_caption else "paragraph")
        elif tag == "caption":
            self.in_caption = True
            self._start_block("caption")
        elif tag in ("p", "li", "blockquote", "pre", "figcaption"):
            self._start_block("paragraph")
        elif tag == "br":
            self._append_text("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1
            self._pop_path()
            return
        if self.skip_depth:
            self._pop_path()
            return
        if tag in _TABLE_CELLS and self.table_stack:
            if self._current is not None:
                self.table_stack[-1]["row"].append(self._current.text.strip())
            self._flush_block()
        elif tag == "tr" and self.table_stack:
            table = self.table_stack[-1]
            if table["row"]:
                table["rows"].append(table["row"])
            table["row"] = None
        elif tag == "table" and self.table_stack:
            table = self.table_stack.pop()
            if table["rows"]:
                projection = _table_projection(table["rows"])
                self.blocks.append(_DomBlock(
                    "table", projection, table["path"], self.length))
                self.normalized.append(projection)
                self.length += len(projection)
        elif tag == "caption":
            self.in_caption = False
            self._flush_block()
        elif tag in _HEADING_TAGS or tag in ("p", "li", "blockquote", "pre", "figcaption"):
            self._flush_block()
        self._pop_path()

    def handle_data(self, data):
        if self.skip_depth:
            return
        if not data.strip() and self._current is None:
            return
        self._append_text(data)


def _table_projection(rows: List[List[str]]) -> str:
    """Searchable projection of a table: header joined onto each row."""
    if not rows:
        return ""
    header = rows[0]
    lines = []
    for row in rows:
        prefix = " | ".join(cell for cell in header[:4]) + " => " if rows.index(row) > 0 and header else ""
        lines.append(prefix + " | ".join(row))
    return "\n".join(lines)


def extract_html(raw: bytes, **_kwargs) -> ExtractionResult:
    try:
        text = raw.decode("utf-8", errors="strict")
        encoding = "utf-8"
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
        encoding = "utf-8-replaced"
    parser = _HtmlTreeParser()
    try:
        parser.feed(text)
        parser.close()
    except Exception as exc:  # malformed html must not crash the pipeline
        result = ExtractionResult(
            parser_id="stdlib-html", parser_version="1", status=STATUS_REVIEW,
            issues=["parse_error:%s" % type(exc).__name__],
            stats={"encoding": encoding},
        )
        _finalize_blocks(result, parser, encoding)
        return result
    result = ExtractionResult(
        parser_id="stdlib-html", parser_version="1", status=STATUS_READY,
        stats={"encoding": encoding},
    )
    _finalize_blocks(result, parser, encoding)
    return result


def _finalize_blocks(result: ExtractionResult, parser: _HtmlTreeParser,
                     encoding: str) -> None:
    full_text = "".join(parser.normalized)
    quality = analyze_text(full_text)
    for dom_block in parser.blocks:
        text = re.sub(r"\s+", " ", dom_block.text).strip()
        if not text:
            continue
        start = full_text.find(dom_block.text[:60]) if dom_block.text else -1
        if start < 0:
            start = min(dom_block.start_char, max(0, len(full_text) - 1))
        end = min(start + len(dom_block.text), len(full_text))
        result.blocks.append(Block(
            block_type=dom_block.block_type, text=text,
            locator={"kind": "html", "dom_path": dom_block.dom_path,
                     "start_char": start, "end_char": end},
        ))
    result.status = merge_statuses(result.status, quality.status)
    result.issues = sorted(set(result.issues) | set(quality.issues))
    result.stats.update({
        "encoding": encoding, "chars": len(full_text),
        "blocks": len(result.blocks), "tables": len(parser.table_stack) + sum(
            1 for b in parser.blocks if b.block_type == "table"),
    })


# ------------------------------------------------------------------- PDF
_OBJ_RE = re.compile(rb"(\d+)\s+(\d+)\s+obj\b", re.S)
_PAGE_DICT_RE = re.compile(rb"/Type\s*/Page(?![a-zA-Z])")
_CONTENTS_RE = re.compile(rb"/Contents\s+(\d+)\s+0\s+R")
_STREAM_RE = re.compile(rb"<<(.*?)>>\s*stream\r?\n?(.*?)\s*endstream", re.S)
_FLATE_RE = re.compile(rb"/FlateDecode")


def _parse_objects(raw: bytes) -> Dict[int, bytes]:
    objects: Dict[int, bytes] = {}
    for match in _OBJ_RE.finditer(raw):
        obj_num = int(match.group(1))
        start = match.end()
        end = raw.find(b"endobj", start)
        objects[obj_num] = raw[start:end if end != -1 else len(raw)]
    return objects


def _decode_stream(body: bytes) -> Optional[bytes]:
    match = _STREAM_RE.search(body)
    if not match:
        return None
    header, data = match.group(1), match.group(2)
    if _FLATE_RE.search(header):
        try:
            return zlib.decompress(data)
        except zlib.error:
            return None
    return data


def _decode_pdf_literal(raw: bytes) -> Tuple[str, bool]:
    """Decode a PDF literal string; returns (text, has_high_bytes)."""
    out = []
    high = 0
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch == 0x5C:  # backslash
            i += 1
            if i >= len(raw):
                break
            esc = raw[i]
            mapping = {0x6E: "\n", 0x72: "\r", 0x74: "\t", 0x62: "\b",
                       0x66: "\f", 0x28: "(", 0x29: ")", 0x5C: "\\"}
            if esc in mapping:
                out.append(mapping[esc])
                i += 1
            elif 0x30 <= esc <= 0x37:  # octal escape, up to 3 digits
                digits = ""
                while i < len(raw) and len(digits) < 3 and 0x30 <= raw[i] <= 0x37:
                    digits += chr(raw[i])
                    i += 1
                try:
                    out.append(chr(int(digits, 8)))
                except ValueError:
                    pass
            else:
                out.append(chr(esc))
                i += 1
        else:
            if ch >= 0x80:
                high += 1
            out.append(chr(ch))  # latin-1 style best effort for simple fonts
            i += 1
    return "".join(out), high > max(2, len(raw) // 4)


def _pdf_content_text(content: bytes) -> Tuple[List[str], bool]:
    """Extract text-showing operator strings from one content stream."""
    pieces: List[str] = []
    cid_suspect = False
    i = 0
    pending: List[str] = []
    n = len(content)
    while i < n:
        ch = content[i]
        if ch == 0x28:  # ( literal string
            depth = 1
            i += 1
            buf = bytearray()
            while i < n and depth:
                c = content[i]
                if c == 0x5C and i + 1 < n:
                    buf.append(c)
                    buf.append(content[i + 1])
                    i += 2
                    continue
                if c == 0x28:
                    depth += 1
                elif c == 0x29:
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                buf.append(c)
                i += 1
            text, high = _decode_pdf_literal(bytes(buf))
            if high:
                cid_suspect = True
            pending.append(text)
        elif ch == 0x3C:  # < hex string
            end = content.find(b">", i)
            if end == -1:
                break
            hex_body = re.sub(rb"\s+", b"", content[i + 1:end])
            try:
                decoded = bytes.fromhex(hex_body.decode("ascii"))
                text, high = _decode_pdf_literal(decoded)
                if high:
                    cid_suspect = True
                pending.append(text)
            except (ValueError, UnicodeDecodeError):
                pass
            i = end + 1
        elif ch in (0x54, 0x27, 0x22):  # 'T' (Tj/TJ/Td/...), quotes
            word_end = i
            while word_end < n and 0x41 <= content[word_end] <= 0x7A:
                word_end += 1
            word = content[i:word_end]
            if word in (b"Tj", b"TJ", b"'", b'"'):
                if pending:
                    pieces.append("".join(pending) if word == b"Tj" else "".join(pending))
                    pending = []
            elif word in (b"Td", b"TD", b"T*", b"TL") and pending:
                pieces.append("".join(pending))
                pending = []
            i = word_end if word_end > i else i + 1
        else:
            if ch in (0x0A, 0x0D) and pending:
                pass  # newline inside stream does not flush operators
            i += 1
    if pending:
        pieces.append("".join(pending))
    return pieces, cid_suspect


def extract_pdf(raw: bytes, ocr=None, ocr_config=None, renderer=None,
                fallback_ocr=None) -> ExtractionResult:
    issues: List[str] = []
    objects = _parse_objects(raw)
    page_nums: List[int] = []
    for obj_num in sorted(objects):
        if _PAGE_DICT_RE.search(objects[obj_num]):
            page_nums.append(obj_num)
    if not page_nums:
        return ExtractionResult(
            parser_id="stdlib-pdf", parser_version="1", status=STATUS_FAILED,
            issues=["no_page_objects_found"], stats={"pages": None},
        )

    blocks: List[Block] = []
    per_page_chars: List[int] = []
    cid_suspect_any = False
    ocr_candidates = 0
    ocr_applied = 0
    max_ocr_pages = getattr(ocr_config, "max_pages_per_doc", 200)
    render_dpi = getattr(ocr_config, "render_dpi", 200)
    for page_index, page_num in enumerate(page_nums, start=1):
        body = objects[page_num]
        contents_match = _CONTENTS_RE.search(body)
        page_text_parts: List[str] = []
        if contents_match:
            stream_num = int(contents_match.group(1))
            stream_body = objects.get(stream_num, b"")
            decoded = _decode_stream(stream_body)
            if decoded is None:
                issues.append("page_%d_content_undecodable" % page_index)
            else:
                pieces, cid_suspect = _pdf_content_text(decoded)
                cid_suspect_any = cid_suspect_any or cid_suspect
                page_text_parts = pieces
        page_text = "\n".join(part for part in page_text_parts if part.strip())
        wants_ocr, ocr_reasons = route_page_to_ocr(len(page_text), page_text)
        if wants_ocr:
            ocr_candidates += 1
            issues.append("page_%d_needs_ocr:%s" % (page_index, "+".join(ocr_reasons)))
            if ocr is not None and ocr_applied < max_ocr_pages:
                from .ocr import OcrEngineError, render_page_to_png

                render = renderer or render_page_to_png
                try:
                    png = render(raw, page_index, dpi=render_dpi)
                    ocr_text, confidence = ocr.run(png)
                    engine_label = getattr(ocr, "name", "ocr")
                    threshold = getattr(ocr_config, "fallback_min_confidence", 0.0)
                    if ((not ocr_text.strip() or confidence < threshold)
                            and fallback_ocr is not None):
                        try:
                            better_text, fb_conf = fallback_ocr.run(png)
                            if better_text.strip():
                                issues.append(
                                    "page_%d_ocr_fallback:%s->%s:conf=%.2f->%.2f"
                                    % (page_index, engine_label,
                                       getattr(fallback_ocr, "name", "fallback"),
                                       confidence, fb_conf))
                                ocr_text = better_text
                                confidence = max(confidence, fb_conf)
                                engine_label = getattr(fallback_ocr, "name",
                                                       "fallback")
                        except Exception:  # fallback failure is non-fatal
                            issues.append("page_%d_ocr_fallback_failed"
                                          % page_index)
                    if ocr_text.strip():
                        page_text = (page_text + "\n" + ocr_text).strip()
                        ocr_applied += 1
                        issues.append("page_%d_ocr_applied:%s:conf=%.2f"
                                      % (page_index, engine_label, confidence))
                except OcrEngineError as exc:
                    issues.append("page_%d_ocr_failed:%s" % (page_index, exc))
                except Exception as exc:  # renderer/engine errors never abort
                    issues.append("page_%d_ocr_failed:%s" % (
                        page_index, type(exc).__name__))
        if page_text.strip():
            blocks.append(Block(
                block_type="paragraph", text=page_text,
                locator={"kind": "pdf", "page": page_index},
            ))

    full_text = "\n".join(block.text for block in blocks)
    quality = analyze_text(full_text, per_page_chars)
    merged_issues = sorted(set(issues) | set(quality.issues))
    if cid_suspect_any:
        merged_issues.append("cid_font_unsupported")
    status = merge_statuses(quality.status,
                            STATUS_REVIEW if cid_suspect_any else STATUS_READY)
    if not full_text.strip() and not any("needs_ocr" in i for i in merged_issues):
        status = STATUS_FAILED
        merged_issues.append("no_text_layer")
    return ExtractionResult(
        parser_id="stdlib-pdf", parser_version="1",
        status=status, issues=merged_issues, blocks=blocks,
        stats={
            "pages": len(page_nums),
            "chars": len(full_text),
            "chars_per_page": per_page_chars,
            "ocr_candidate_pages": ocr_candidates,
            "ocr_applied_pages": ocr_applied,
            "ocr_engine": getattr(ocr, "name", None) if ocr else None,
            "objects_parsed": len(objects),
        },
    )


# ----------------------------------------------------------------- image
_OCR_ENGINES: Dict[str, Any] = {}


def register_ocr_engine(name: str, engine: Any) -> None:
    """Register a local OCR engine: run(image_bytes) -> (text, confidence)."""
    _OCR_ENGINES[name] = engine


def extract_image(raw: bytes, engine_name: Optional[str] = None,
                  ocr=None, **_kwargs) -> ExtractionResult:
    engine = ocr
    if engine is None and engine_name:
        engine = _OCR_ENGINES.get(engine_name)
    if engine is None:
        return ExtractionResult(
            parser_id="stdlib-image", parser_version="1", status=STATUS_REVIEW,
            issues=["needs_ocr_engine"],
            stats={"bytes": len(raw), "ocr_engine": None},
        )
    text, confidence = engine.run(raw)
    quality = analyze_text(text)
    issues = list(quality.issues) + (["low_ocr_confidence"] if confidence < 0.8 else [])
    blocks = [Block(
        block_type="paragraph", text=text, locator={"kind": "image"},
    )] if text.strip() else []
    engine_label = getattr(engine, "name", None) or engine_name or "engine"
    return ExtractionResult(
        parser_id="stdlib-image+%s" % engine_label,
        parser_version="1",
        status=STATUS_REVIEW if issues else STATUS_READY,
        issues=issues, blocks=blocks,
        stats={"bytes": len(raw), "ocr_engine": engine_label,
               "ocr_confidence": confidence},
    )


# ----------------------------------------------------------------- registry
register_extractor("txt", extract_txt)
register_extractor("html", extract_html)
register_extractor("pdf", extract_pdf)
register_extractor("img", extract_image)


# ------------------------------------------------------------- evidence IO
def to_evidence_block(block_row: Dict[str, Any]) -> Dict[str, Any]:
    """Assemble a schema-conformant evidence block from a stored block row."""
    return {
        "schema_version": "1",
        "source": block_row["source"],
        "doc_id": block_row["doc_id"],
        "source_version": block_row["version_id"],
        "source_sha256": block_row["snapshot_sha256"],
        "extraction_id": block_row["extraction_id"],
        "block_id": block_row["block_id"],
        "block_type": block_row["block_type"],
        "text": block_row["text"],
        "locator": block_row["locator"],
        "quality": block_row["quality"],
    }
