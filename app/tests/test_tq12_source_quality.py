"""TQ1/TQ2: source routing and OCR-result selection.

The historical corpus has byte-decoded glyph indexes (C0/C1 control
bytes, dense high-Latin runs) inside pages with PLENTY of characters;
the old router only saw sparse/replacement text and clean ASCII from a
degraded engine sailed through. These tests pin the new behaviour:

- damage fingerprints route the page (dense control bytes, CID-style
  runs, C1/DEL) while legal characters (¥ £ Ø Ë é 負號) never do;
- a damaged layer with clean OCR REPLACES the text (never garbage+OCR
  spliced together); healthy-sparse layers still ADD;
- OCR failure / unmet on a damaged page stays review with an explicit
  damaged marker - never false-ready;
- a legacy engine with demonstrably clean text keeps ready (engine
  marks the inventory, native re-extraction is the remedy, not forced
  page OCR).
"""
from __future__ import annotations

import os
import unittest

from fixtures import temp_dir


def _build_pdf(content: bytes) -> bytes:
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..",
                                    "app"))
    from test_knowledge_extract import build_pdf

    return build_pdf(content)


class _Ocr:
    name = "test-ocr"

    def __init__(self, text="OCR 识别出的中文正文内容足够长因此可以通过质量阈值检查",
                 confidence=0.95):
        self.text = text
        self.confidence = confidence
        self.pages = []

    def run(self, image_bytes):
        self.pages.append(image_bytes)
        return self.text, self.confidence

def _two_page_pdf(text1: str, text2: str) -> bytes:
    """Minimal xref-valid 2-page PDF (the stdlib page parser needs real
    page objects; build_pdf only makes a single-page trailer)."""
    nl = bytes([10])  # newline byte without escape sequences

    def stream(text: str) -> bytes:
        safe = text.replace("(", "").replace(")", "")
        return ("BT /F1 12 Tf 72 720 Td (%s) Tj ET" % safe).encode(
            "latin-1")

    s1, s2 = stream(text1), stream(text2)
    objects = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids [3 0 R 6 0 R] /Count 2 >>",
        3: (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
            b" /Contents 4 0 R >>"),
        4: (b"<< /Length " + str(len(s1)).encode() + b" >>" + nl
            + b"stream" + nl + s1 + nl + b"endstream"),
        5: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        6: (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
            b" /Contents 7 0 R >>"),
        7: (b"<< /Length " + str(len(s2)).encode() + b" >>" + nl
            + b"stream" + nl + s2 + nl + b"endstream"),
    }
    out = b"%PDF-1.4" + nl
    offsets = {}
    for number in sorted(objects):
        offsets[number] = len(out)
        out += (b"%d 0 obj" % number) + nl + objects[number] + nl             + b"endobj" + nl
    mx = max(objects)
    out += b"xref" + nl + b"0 " + str(mx + 1).encode() + nl
    out += b"0000000000 65535 f " + nl
    for number in range(1, mx + 1):
        if number in offsets:
            out += (b"%010d 00000 n " % offsets[number]) + nl
        else:
            out += b"0000000000 65535 f " + nl
    out += (b"trailer" + nl + b"<< /Size " + str(mx + 1).encode()
            + b" /Root 1 0 R >>" + nl + b"startxref" + nl
            + str(offsets[1]).encode() + nl + b"%%EOF")
    return out



def _render(raw, page, dpi=200):
    """Renderer stub: the synthetic damaged PDFs fail pdfium LOAD (the
    control bytes break parsing), so pages are rendered by stub - the
    behaviour under test is text selection, not pdfium rendering."""
    return b"PNG-STUB-%d" % page


class TQ1RoutingTest(unittest.TestCase):
    def test_control_byte_density_routes_page(self):
        from knowledge.quality import route_page_to_ocr

        dense = "A" * 30 + "".join(chr(i) for i in range(1, 9)) * 8
        wants, reasons = route_page_to_ocr(len(dense), dense)
        self.assertTrue(wants)
        self.assertIn("control_characters", reasons)

    def test_control_byte_run_routes_page(self):
        from knowledge.quality import route_page_to_ocr

        # low overall density but a single dense run = glyph dump
        text = "正常正文一段。" * 20 + "".join(chr(i) for i in range(1, 9))
        wants, reasons = route_page_to_ocr(len(text), text)
        self.assertTrue(wants)
        self.assertIn("control_characters", reasons)

    def test_cid_style_high_latin_runs_route_page(self):
        from knowledge.quality import route_page_to_ocr

        garbage = "段落开头 " + "ØË¥ÆØË¥ÆØË" * 4
        wants, reasons = route_page_to_ocr(len(garbage), garbage)
        self.assertTrue(wants)
        self.assertIn("cid_style_glyph_runs", reasons)

    def test_legal_characters_never_route(self):
        from knowledge.quality import (QUALITY_CONFIG, analyze_text,
                                       block_evidence_usable,
                                       route_page_to_ocr)

        legal = ("毛利率 ¥12.5m，UK £3.4bn；挪威公司 Ørsted；"
                 "Citigroup's naïve café résumé；負號測試：20%－15%＝5%。"
                 "正常中文正文" * 6)
        wants, reasons = route_page_to_ocr(len(legal), legal)
        self.assertFalse(wants, reasons)
        self.assertEqual(analyze_text(legal).status, "ready")
        usable, why = block_evidence_usable(legal)
        self.assertTrue(usable, why)
        # isolated high-Latin characters are not runs
        self.assertLess(QUALITY_CONFIG["high_latin_run_length"], 10)

    def test_degraded_engine_clean_text_stays_ready(self):
        """Legacy stdlib engine with demonstrably clean ASCII text: the
        ENGINE alone must not force page OCR (native re-extraction is
        the TQ3 remedy); the degraded marker stays in the issues."""
        from knowledge.extract import extract_pdf

        content = (b"BT /F1 12 Tf 72 720 Td (Gross margin expanded"
                   b" materially in the first half) Tj ET")
        result = extract_pdf(_build_pdf(content), ocr=_Ocr())
        self.assertIn("degraded_pdf_engine", "|".join(result.issues))
        self.assertTrue(
            any("needs_ocr" not in i and "legacy" not in i
                for i in result.issues))
        # pages were NOT sent to OCR
        self.assertEqual(result.stats["ocr_applied_pages"], 0)

    def test_garbage_with_high_char_count_routes(self):
        """A page can have thousands of characters of byte-decoded
        garbage; volume is not health."""
        from knowledge.extract import extract_pdf

        garbage = bytes(range(0x20, 0x7F)) + bytes(
            [0xE6, 0xAF, 0x9C, 0xE5, 0x88, 0xA9, 0xE7, 0x8E, 0x87]) * 40
        content = b"BT (" + garbage + b") Tj ET"
        result = extract_pdf(_build_pdf(content))
        self.assertTrue(any("needs_ocr" in i or "damaged" in i
                            for i in result.issues), result.issues)
        self.assertIn("cid_font_unsupported", result.issues)


class TQ2SelectionTest(unittest.TestCase):
    def test_damaged_layer_replaced_by_clean_ocr(self):
        """The AC1-era behaviour spliced garbage + OCR together; the
        effective text must now be the clean OCR result ONLY, with the
        replacement recorded as a diagnostic issue."""
        from knowledge.extract import extract_pdf

        garbage = "".join(chr(i) for i in range(1, 33)) * 4  # C0 dump
        content = b"BT (" + garbage.encode("latin-1") + b") Tj ET"
        ocr = _Ocr(text="干净的 OCR 结果，包含关键数字 25.3% 与第 3 页脚注")
        result = extract_pdf(_build_pdf(content), ocr=ocr,
                             renderer=_render)
        self.assertEqual(result.stats["ocr_applied_pages"], 1)
        damaged_note = [i for i in result.issues
                        if "damaged_layer_replaced_by_ocr" in i]
        self.assertTrue(damaged_note, result.issues)
        block_text = result.blocks[0].text
        self.assertIn("干净的 OCR 结果", block_text)
        self.assertIn("25.3%", block_text)
        self.assertNotIn(chr(1), block_text,
                         "damaged text layer spliced back into the page")

    def test_healthy_sparse_layer_still_concatenates(self):
        from knowledge.extract import extract_pdf

        content = b"BT (Hi) Tj ET"
        ocr = _Ocr(text="OCR 补充的长文本内容以满足质量检查阈值要求")
        result = extract_pdf(_build_pdf(content), ocr=ocr,
                             renderer=_render)
        self.assertEqual(result.stats["ocr_applied_pages"], 1)
        block_text = result.blocks[0].text
        self.assertIn("Hi", block_text)
        self.assertIn("OCR 补充", block_text)

    def test_ocr_failure_on_damaged_page_is_not_false_ready(self):
        from knowledge.extract import extract_pdf

        garbage = "".join(chr(i) for i in range(1, 33)) * 4
        content = b"BT (" + garbage.encode("latin-1") + b") Tj ET"

        class Failing(_Ocr):
            def run(self, image_bytes):
                raise RuntimeError("engine down")

        result = extract_pdf(_build_pdf(content), ocr=Failing())
        self.assertNotEqual(result.status, "ready")
        self.assertTrue(any("damaged_text_layer" in i or "ocr_failed" in i
                            for i in result.issues), result.issues)
        # the damaged text stays readable for diagnosis but the block is
        # marked damaged so downstream evidence filters can exclude it
        damaged = [b for b in result.blocks
                   if any("damaged" in issue
                          for issue in (b.quality.issues or []))]
        self.assertTrue(damaged)

    def test_low_confidence_ocr_on_damaged_page_not_ready(self):
        from knowledge.extract import extract_pdf

        garbage = "".join(chr(i) for i in range(1, 33)) * 4
        content = b"BT (" + garbage.encode("latin-1") + b") Tj ET"
        result = extract_pdf(_build_pdf(content),
                             ocr=_Ocr(confidence=0.2),
                             renderer=_render)
        self.assertNotEqual(result.status, "ready")
        self.assertTrue(any("ocr_low_confidence" in i for i in result.issues))

    def test_unmet_ocr_cap_keeps_damaged_marker(self):
        """Beyond max_pages_per_doc the damaged page is honestly unmet,
        never silently published as valid text."""
        from knowledge.extract import extract_pdf

        garbage = ("".join(chr(c) for c in range(1, 33)) * 4)
        raw = _two_page_pdf(garbage, garbage)
        from knowledge.ocr import OcrConfig

        ocr_config = OcrConfig(engine="local", max_pages_per_doc=1)
        result = extract_pdf(raw, ocr=_Ocr(), ocr_config=ocr_config,
                             renderer=_render)
        self.assertGreaterEqual(result.stats["unmet_ocr_pages"], 1)
        self.assertEqual(result.stats["pages"], 2)
        self.assertNotEqual(result.status, "ready")


class TQ2DownstreamFilterTest(unittest.TestCase):
    def test_block_evidence_usable(self):
        from knowledge.quality import block_evidence_usable

        usable, _ = block_evidence_usable("正常段落：营收 ¥1.2bn（+8%）")
        self.assertTrue(usable)
        usable, why = block_evidence_usable(
            "".join(chr(i) for i in range(1, 33)) * 3)
        self.assertFalse(usable)
        self.assertIn("control_characters", why)
        usable, why = block_evidence_usable("首段 ØË¥ÆØË¥ÆØË" * 5)
        self.assertFalse(usable)
        self.assertIn("cid_style_glyph_runs", why)

    def test_summaries_evidence_excludes_polluted_blocks(self):
        import json
        import os

        from knowledge.store import KnowledgeStore

        kb = KnowledgeStore(os.path.join(temp_dir(), "k.sqlite3"))
        try:
            stamp = "2026-10-04T00:00:00Z"
            kb.upsert_documents([{
                "source": "reports", "doc_id": "DIRTY",
                "title": "T", "symbol": "EX", "available": True,
                "first_seen_at": stamp, "last_seen_at": stamp}], stamp)
            kb.upsert_versions([{
                "source": "reports", "doc_id": "DIRTY", "version_id": "v1",
                "sha256": "d", "bytes": 1, "media_type": "application/pdf",
                "ext": "pdf", "rel_path": "x", "is_current": True,
                "state": "ready", "content_changed_at": None}], stamp)
            garbage = "".join(chr(i) for i in range(1, 33)) * 6
            kb.record_extraction({
                "extraction_id": "extr-dirty", "source": "reports",
                "doc_id": "DIRTY", "version_id": "v1",
                "snapshot_sha256": "d", "parser_id": "t",
                "parser_version": "1", "config_digest": "c",
                "status": "review", "issues": ["control_characters"],
                "stats": {}},
                [{"block_type": "paragraph", "text": garbage,
                  "locator": {"kind": "pdf", "page": 1},
                  "quality": {"status": "review",
                              "issues": ["control_characters"]}},
                 {"block_type": "paragraph",
                  "text": "干净段落：毛利率 25.3%，营收 ¥1.2bn",
                  "locator": {"kind": "pdf", "page": 2},
                  "quality": {"status": "ready", "issues": []}}])
            from knowledge.summaries import _entity_document_evidence

            evidence = _entity_document_evidence(kb, "company", "EX")
            texts = [item.get("text", "") for item in evidence
                     if item.get("kind") == "document_block"]
            self.assertTrue(texts, "clean block should feed evidence")
            self.assertTrue(all(chr(1) not in t for t in texts),
                            "polluted block entered summary evidence")
            self.assertTrue(any("25.3%" in t for t in texts))
        finally:
            kb.close()

    def test_analysis_retriever_excludes_polluted_blocks(self):
        from knowledge.analysis_tasks import _own_blocks_retriever
        from knowledge.store import KnowledgeStore

        kb = KnowledgeStore(os.path.join(temp_dir(), "k.sqlite3"))
        try:
            stamp = "2026-10-04T00:00:00Z"
            kb.upsert_documents([{
                "source": "reports", "doc_id": "M", "title": "M",
                "symbol": "EX", "available": True,
                "first_seen_at": stamp, "last_seen_at": stamp}], stamp)
            kb.upsert_versions([{
                "source": "reports", "doc_id": "M", "version_id": "v1",
                "sha256": "m", "bytes": 1, "media_type": "application/pdf",
                "ext": "pdf", "rel_path": "x", "is_current": True,
                "state": "ready", "content_changed_at": None}], stamp)
            garbage = "".join(chr(i) for i in range(1, 33)) * 6
            kb.record_extraction({
                "extraction_id": "extr-mixed", "source": "reports",
                "doc_id": "M", "version_id": "v1", "snapshot_sha256": "m",
                "parser_id": "t", "parser_version": "1",
                "config_digest": "c", "status": "review",
                "issues": [], "stats": {}},
                [{"block_type": "paragraph", "text": garbage,
                  "locator": {"kind": "pdf", "page": 1},
                  "quality": {"status": "review",
                              "issues": ["control_characters"]}},
                 {"block_type": "paragraph", "text": "clean analysis text "
                  "with margin 25.3%",
                  "locator": {"kind": "pdf", "page": 2},
                  "quality": {"status": "ready", "issues": []}}])
            retriever = _own_blocks_retriever(kb, "reports", "M",
                                              "extr-mixed")
            hits = retriever("query", None)
            texts = [hit["block"]["text"] for hit in hits]
            self.assertTrue(texts)
            self.assertTrue(all(chr(1) not in t for t in texts),
                            "polluted block entered the analysis prompt")
            self.assertTrue(any("25.3%" in t for t in texts))
        finally:
            kb.close()


if __name__ == "__main__":
    unittest.main()
