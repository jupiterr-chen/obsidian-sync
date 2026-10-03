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
import json
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
# v4 (R02): the digest covers the EFFECTIVE processing configuration - OCR
# engine/dpi/languages/thresholds/fallback, vision model NAME (never the key),
# quality policy version and processing-library versions - so any behavioral
# change yields a new task identity and identical configs rerun for free.
EXTRACT_CONFIG = {"normalization": 4, "blocks": "evidence-block-v1",
                  "ocr": "effective-config-v1"}

STAGE_EXTRACT = "extract"


def _dep_version(name: str) -> Optional[str]:
    try:
        import importlib.metadata as metadata

        return metadata.version(name)
    except Exception:
        return None


def effective_extract_config(ocr_config=None,
                             provider_specs: Optional[Dict[str, Any]] = None
                             ) -> Dict[str, Any]:
    """The full behavior-determining configuration, secrets excluded."""
    from .ocr import OcrConfig
    from .quality import QUALITY_CONFIG

    cfg = ocr_config or OcrConfig()
    specs = provider_specs or {}
    vision_used = cfg.engine == "vision-api" or cfg.fallback == "vision-api"
    return {
        "extract": EXTRACT_CONFIG,
        "quality": QUALITY_CONFIG,
        "ocr": {
            "engine": cfg.engine,
            "fallback": cfg.fallback,
            "render_dpi": cfg.render_dpi,
            "languages": sorted(cfg.languages or []),
            "min_confidence": cfg.min_confidence,
            "fallback_min_confidence": cfg.fallback_min_confidence,
            "max_pages_per_doc": cfg.max_pages_per_doc,
            "vision_model": ((specs.get("vision_ocr") or {}).get("model")
                             if vision_used else None),
        },
        "deps": {
            "pypdfium2": _dep_version("pypdfium2"),
            "rapidocr_onnxruntime": _dep_version("rapidocr-onnxruntime"),
        },
    }


def extract_config_digest(ocr_config=None,
                          provider_specs: Optional[Dict[str, Any]] = None
                          ) -> str:
    canonical = json.dumps(
        effective_extract_config(ocr_config, provider_specs),
        ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def extractor_info(fmt: str, ocr_engine=None):
    """(parser_id, parser_version) that WOULD run for a format, without
    executing anything - enables the R02 zero-cost identity pre-check.

    S06: for images the parser identity includes the EFFECTIVE OCR engine
    name, so a cached product of the same engine is found BEFORE the
    (potentially paid) OCR runs; the runner passes the engine it will use.
    """
    try:
        import pypdfium2  # noqa: F401

        if fmt == "pdf":
            return "pypdfium2", (_dep_version("pypdfium2") or "unknown")
    except ImportError:
        pass
    base = {"pdf": ("stdlib-pdf-degraded", "1"),
            "html": ("stdlib-html", "1"),
            "txt": ("stdlib-txt", "1"),
            "img": ("stdlib-image", "1")}
    if fmt not in base:
        raise ExtractorMissing("no extractor registered for format %r" % fmt)
    parser_id, version = base[fmt]
    if fmt == "img" and ocr_engine is not None:
        parser_id = "stdlib-image+%s" % getattr(ocr_engine, "name", "engine")
    return parser_id, version


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
    __slots__ = ("block_type", "text", "dom_path", "start_char", "end_char")

    def __init__(self, block_type: str, text: str, dom_path: str,
                 start_char: int, end_char: int):
        self.block_type = block_type
        self.text = text
        self.dom_path = dom_path
        self.start_char = start_char
        self.end_char = end_char


_BLOCK_SEPARATOR = "\n"


def _norm_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text)


class _HtmlTreeParser(HTMLParser):
    """Block text with DOM paths, tracked against a normalized stream.

    R06: every emitted block records the exact span it occupies in the
    normalized stream (whitespace collapsed at flush time, blocks joined by
    single newlines), so duplicate paragraphs locate to their OWN
    occurrences instead of the first find() hit.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.path: List[Tuple[str, int]] = []          # (tag, nth-of-type)
        self.counters: List[Dict[str, int]] = []
        self.skip_depth = 0
        self.normalized: List[str] = []                # stream segments
        self.length = 0
        self.blocks: List[_DomBlock] = []
        self._current: Optional[_DomBlock] = None
        self._current_raw: List[str] = []
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

    # stream helpers ----------------------------------------------------
    def _emit(self, text: str) -> None:
        if text:
            self.normalized.append(text)
            self.length += len(text)

    def _emit_separator(self) -> None:
        self.normalized.append(_BLOCK_SEPARATOR)
        self.length += len(_BLOCK_SEPARATOR)

    # text handling ----------------------------------------------------
    def _flush_block(self) -> None:
        if self._current is not None:
            text = _norm_ws("".join(self._current_raw)).strip()
            if text:
                start = self.length
                self._emit(text)
                self._current.text = text
                self._current.end_char = self.length
                self.blocks.append(self._current)
                self._emit_separator()
        self._current = None
        self._current_raw = []

    def _start_block(self, block_type: str) -> None:
        self._flush_block()
        self._current = _DomBlock(block_type, "", self._dom_path(),
                                  self.length, self.length)

    def _append_text(self, data: str) -> None:
        if not data:
            return
        if self._current is None:
            self._start_block("paragraph")
        self._current_raw.append(data)

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
                self.table_stack[-1]["row"].append(
                    _norm_ws("".join(self._current_raw)).strip())
            self._flush_block()
        elif tag == "tr" and self.table_stack:
            table = self.table_stack[-1]
            if table["row"]:
                table["rows"].append(table["row"])
            table["row"] = None
        elif tag == "table" and self.table_stack:
            table = self.table_stack.pop()
            if table["rows"]:
                projection = _norm_ws(_table_projection(table["rows"])).strip()
                if projection:
                    dom_block = _DomBlock("table", projection, table["path"],
                                          self.length, self.length)
                    self._emit_separator()
                    dom_block.start_char = self.length
                    self._emit(projection)
                    dom_block.end_char = self.length
                    self.blocks.append(dom_block)
                    self._emit_separator()
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
        if not dom_block.text:
            continue
        # spans were tracked at parse time (R06): the block text IS the
        # stream slice [start_char, end_char)
        result.blocks.append(Block(
            block_type=dom_block.block_type, text=dom_block.text,
            locator={"kind": "html", "dom_path": dom_block.dom_path,
                     "start_char": dom_block.start_char,
                     "end_char": dom_block.end_char},
        ))
    result.status = merge_statuses(result.status, quality.status)
    result.issues = sorted(set(result.issues) | set(quality.issues))
    result.stats.update({
        "encoding": encoding, "chars": len(full_text),
        "normalized_chars": len(full_text),
        "blocks": len(result.blocks), "tables": sum(
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


_PAGES_DICT_RE = re.compile(rb"/Type\s*/Pages(?![a-zA-Z])")
_KIDS_RE = re.compile(rb"/Kids\s*\[(.*?)\]", re.S)
_CONTENTS_ARRAY_RE = re.compile(rb"/Contents\s*\[(.*?)\]", re.S)


def _pdfium_page_texts(raw: bytes) -> Optional[List[str]]:
    """Per-page text via pypdfium2 (real page tree, font/CMap handling)."""
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return None
    document = pdfium.PdfDocument(raw)
    try:
        texts = []
        for index in range(len(document)):
            page = document[index]
            textpage = page.get_textpage()
            texts.append(textpage.get_text_range() or "")
        return texts
    finally:
        document.close()


def _stdlib_pdf_pages(raw: bytes) -> List[Tuple[int, Optional[bytes]]]:
    """(page_object, content_bytes|None) in PAGE-TREE order (R05).

    Order follows /Pages /Kids recursively; object-number order is only a
    flagged fallback when no tree is parseable. A page without decodable
    content yields None so the caller records a missing-content issue."""
    objects = _parse_objects(raw)
    page_objs = [n for n in sorted(objects)
                 if _PAGE_DICT_RE.search(objects[n])]
    if not page_objs:
        return []
    kids_map: Dict[int, List[int]] = {}
    for num, body in objects.items():
        if _PAGES_DICT_RE.search(body):
            match = _KIDS_RE.search(body)
            if match:
                kids_map[num] = [int(x) for x in
                                 re.findall(rb"(\d+)\s+0\s+R", match.group(1))]
    ordered: List[int] = []
    if kids_map:
        all_kids = {k for values in kids_map.values() for k in values}
        roots = [n for n in kids_map if n not in all_kids] or \
            [min(kids_map)]

        def walk(node: int) -> None:
            for kid in kids_map.get(node, []):
                body = objects.get(kid)
                if body is None:
                    continue
                if _PAGES_DICT_RE.search(body):
                    walk(kid)
                elif _PAGE_DICT_RE.search(body):
                    ordered.append(kid)

        for root in roots:
            walk(root)
    if not ordered:
        ordered = sorted(page_objs)  # fallback; caller flags degraded order
    pages: List[Tuple[int, Optional[bytes]]] = []
    for num in ordered:
        body = objects[num]
        stream_nums: List[int] = []
        single = _CONTENTS_RE.search(body)
        array = _CONTENTS_ARRAY_RE.search(body)
        if array:
            stream_nums = [int(x) for x in
                           re.findall(rb"(\d+)\s+0\s+R", array.group(1))]
        elif single:
            stream_nums = [int(single.group(1))]
        data = b""
        for stream_num in stream_nums:
            decoded = _decode_stream(objects.get(stream_num, b""))
            if decoded is None:
                data = b""
                break
            data += decoded
        pages.append((num, data if stream_nums else None))
    return pages


def extract_pdf(raw: bytes, ocr=None, ocr_config=None, renderer=None,
                fallback_ocr=None) -> ExtractionResult:
    issues: List[str] = []
    parser_id, parser_version = extractor_info("pdf")
    page_texts: List[Optional[str]] = []
    if parser_id == "pypdfium2":
        try:
            page_texts = list(_pdfium_page_texts(raw) or [])
        except Exception as exc:  # pdfium parse failure -> degraded stdlib
            issues.append("degraded_pdf_engine:pdfium-load-failed:%s"
                          % type(exc).__name__)
            parser_id, parser_version = "stdlib-pdf-degraded", "1"
            page_texts = []
    if parser_id == "pypdfium2":
        if not page_texts:
            return ExtractionResult(
                parser_id=parser_id, parser_version=parser_version,
                status=STATUS_FAILED, issues=["no_page_objects_found"],
                stats={"pages": None})
        cid_suspect_any = False
        engine_kind = "page-tree"
    else:
        issues.append("degraded_pdf_engine:pypdfium2-missing")
        ordered = _stdlib_pdf_pages(raw)
        if not ordered:
            return ExtractionResult(
                parser_id=parser_id, parser_version=parser_version,
                status=STATUS_FAILED, issues=issues + ["no_page_objects_found"],
                stats={"pages": None})
        cid_suspect_any = False
        page_texts = []
        for _num, data in ordered:
            if data is None:
                page_texts.append(None)
                continue
            pieces, cid_suspect = _pdf_content_text(data)
            cid_suspect_any = cid_suspect_any or cid_suspect
            page_texts.append("\n".join(p for p in pieces if p.strip()))
        engine_kind = "stdlib-simplified"

    blocks: List[Block] = []
    per_page_chars: List[int] = []
    page_confidences: List[Optional[float]] = []
    page_ocr_status: List[str] = []
    ocr_candidates = 0
    ocr_applied = 0
    unmet_ocr_pages = 0
    missing_content_pages = 0
    low_confidence_pages = 0
    min_confidence = getattr(ocr_config, "min_confidence", 0.6)
    max_ocr_pages = getattr(ocr_config, "max_pages_per_doc", 200)
    render_dpi = getattr(ocr_config, "render_dpi", 200)
    for page_index, page_text in enumerate(page_texts, start=1):
        page_confidence = None
        page_status = "text_layer"
        if page_text is None:
            issues.append("page_%d_missing_content" % page_index)
            missing_content_pages += 1
            page_status = "missing_content"
            page_text = ""
        wants_ocr, ocr_reasons = route_page_to_ocr(len(page_text), page_text)
        if wants_ocr:
            ocr_candidates += 1
            issues.append("page_%d_needs_ocr:%s"
                          % (page_index, "+".join(ocr_reasons)))
            if ocr is not None and ocr_applied < max_ocr_pages:
                from .ocr import OcrEngineError, render_page_to_png

                render = renderer or render_page_to_png
                try:
                    png = render(raw, page_index, dpi=render_dpi)
                    ocr_text, confidence = ocr.run(png)
                    engine_label = getattr(ocr, "name", "ocr")
                    threshold = getattr(ocr_config, "fallback_min_confidence",
                                        0.0)
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
                        page_confidence = confidence
                        issues.append("page_%d_ocr_applied:%s:conf=%.2f"
                                      % (page_index, engine_label, confidence))
                        page_status = "ocr_applied"
                except OcrEngineError as exc:
                    issues.append("page_%d_ocr_failed:%s" % (page_index, exc))
                    page_status = "ocr_failed"
                except Exception as exc:  # renderer/engine errors never abort
                    issues.append("page_%d_ocr_failed:%s" % (
                        page_index, type(exc).__name__))
                    page_status = "ocr_failed"
            elif ocr is None or ocr_applied >= max_ocr_pages:
                unmet_ocr_pages += 1
                page_status = "needs_ocr_unmet"
        # S05: OCR confidence gates THIS page and its block - plenty of
        # text on other pages is not evidence this page's numbers are right
        if page_confidence is not None and page_confidence < min_confidence:
            low_confidence_pages += 1
            page_status = "ocr_low_confidence"
            issues.append("page_%d_ocr_low_confidence:%.2f<%.2f"
                          % (page_index, page_confidence, min_confidence))
        page_confidences.append(page_confidence)
        page_ocr_status.append(page_status)
        page_quality = Quality(STATUS_READY)
        if page_status in ("ocr_low_confidence", "ocr_failed",
                           "needs_ocr_unmet", "missing_content"):
            page_quality = Quality(STATUS_REVIEW, [page_status])
        if page_text.strip():
            blocks.append(Block(
                block_type="paragraph", text=page_text,
                locator={"kind": "pdf", "page": page_index},
                quality=page_quality,
            ))
        per_page_chars.append(len(page_text))

    full_text = "\n".join(block.text for block in blocks)
    quality = analyze_text(full_text, per_page_chars)
    merged_issues = sorted(set(issues) | set(quality.issues))
    if cid_suspect_any:
        merged_issues.append("cid_font_unsupported")
    # R05: unhandled OCR candidates / missing content / OCR failures must
    # degrade the document below ready - remaining text volume is not proof.
    page_problems = (unmet_ocr_pages > 0 or missing_content_pages > 0
                     or low_confidence_pages > 0
                     or any("ocr_failed" in i for i in merged_issues))
    status = merge_statuses(quality.status,
                            STATUS_REVIEW if page_problems else STATUS_READY,
                            STATUS_REVIEW if cid_suspect_any else STATUS_READY)
    if not full_text.strip() and not any("needs_ocr" in i for i in merged_issues):
        status = STATUS_FAILED
        merged_issues.append("no_text_layer")
    return ExtractionResult(
        parser_id=parser_id, parser_version=parser_version,
        status=status, issues=merged_issues, blocks=blocks,
        stats={
            "pages": len(page_texts),
            "chars": len(full_text),
            "chars_per_page": per_page_chars,
            "ocr_candidate_pages": ocr_candidates,
            "ocr_applied_pages": ocr_applied,
            "unmet_ocr_pages": unmet_ocr_pages,
            "missing_content_pages": missing_content_pages,
            "low_confidence_pages": low_confidence_pages,
            "page_confidences": page_confidences,
            "page_ocr_status": page_ocr_status,
            "ocr_engine": getattr(ocr, "name", None) if ocr else None,
            "pdf_engine": engine_kind,
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
