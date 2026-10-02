"""OCR switch tests: config routing, honest degradation, PDF page OCR merge.

Uses a fake engine so the suite stays dependency-free; real RapidOCR/pypdfium2
are exercised on the server (see HANDOFF notes).
"""

from __future__ import annotations

import os
import unittest

from fixtures import temp_dir

from knowledge.extract import extract_image, extract_pdf
from knowledge.ocr import (
    LocalRapidOcr,
    OcrConfig,
    OcrEngineError,
    build_fallback_engine,
    build_ocr_engine,
    render_page_to_png,
)
from knowledge.providers import ProviderNotConfigured


class FakeOcr:
    """Deterministic fake replacing render+OCR for pipeline tests."""

    name = "fake-ocr"

    def __init__(self, text="OCR 识别出的中文正文内容足够长因此可以通过质量阈值检查 margin analysis section", confidence=0.9):
        self.text = text
        self.confidence = confidence

    def run(self, image_bytes):
        return self.text, self.confidence


class OcrSwitchTest(unittest.TestCase):
    def test_config_parsing_defaults_and_overrides(self):
        default = OcrConfig.from_dict({})
        self.assertEqual(default.engine, "local")
        self.assertEqual(default.languages, ["ch", "en"])
        custom = OcrConfig.from_dict({"engine": "off", "render_dpi": 300,
                                      "max_pages_per_doc": 10})
        self.assertEqual(custom.engine, "off")
        self.assertEqual(custom.render_dpi, 300)
        self.assertEqual(custom.max_pages_per_doc, 10)

    def test_build_engine_off_returns_none(self):
        self.assertIsNone(build_ocr_engine(OcrConfig(engine="off")))

    def test_local_engine_unavailable_degrades_to_none(self):
        # rapidocr not installed in the test env -> honest None, no raise
        engine = build_ocr_engine(OcrConfig(engine="local"))
        if LocalRapidOcr().available():
            self.skipTest("rapidocr installed; degradation path not testable")
        self.assertIsNone(engine)

    def test_vision_api_requires_filled_provider(self):
        with self.assertRaises(ProviderNotConfigured):
            build_ocr_engine(OcrConfig(engine="vision-api"),
                             provider_specs={"vision_ocr": {
                                 "base_url": "https://FILL-ME/x",
                                 "api_key": "FILL-ME", "model": "FILL-ME"}})
        with self.assertRaises(ProviderNotConfigured):
            build_ocr_engine(OcrConfig(engine="vision-api"), provider_specs={})

    def test_image_extraction_uses_injected_engine(self):
        result = extract_image(b"\x89PNG fake", ocr=FakeOcr())
        self.assertEqual(result.status, "ready")
        self.assertIn("margin analysis section", result.blocks[0].text)
        self.assertEqual(result.stats["ocr_engine"], "fake-ocr")
        self.assertEqual(result.stats["ocr_confidence"], 0.9)
        # low confidence flags review
        low = extract_image(b"\x89PNG fake", ocr=FakeOcr(confidence=0.3))
        self.assertEqual(low.status, "review")
        self.assertIn("low_ocr_confidence", low.issues)

    def test_pdf_ocr_applied_to_sparse_pages(self):
        content = (b"BT /F1 12 Tf 72 720 Td (Hi) Tj ET")
        raw = build_pdf_bytes(content)
        base = extract_pdf(raw)
        self.assertTrue(any("needs_ocr" in i for i in base.issues))
        self.assertEqual(base.stats.get("ocr_applied_pages", 0), 0)

        # with a fake engine + fake renderer the sparse page gets OCR text
        def fake_renderer(raw_pdf, page_number, dpi=200):
            return b"PNGBYTES"

        result = extract_pdf(raw, ocr=FakeOcr(), ocr_config=OcrConfig(),
                             renderer=fake_renderer)
        self.assertEqual(result.stats.get("ocr_applied_pages"), 1)
        self.assertTrue(any("ocr_applied" in i for i in result.issues))
        self.assertIn("OCR 识别出的中文正文", result.blocks[0].text)
        self.assertIn("Hi", result.blocks[0].text)

    def test_pdf_max_pages_limit(self):
        raw = build_pdf_bytes(b"BT ET")  # one page, zero text
        config = OcrConfig(max_pages_per_doc=0)
        result = extract_pdf(raw, ocr=FakeOcr(), ocr_config=config,
                             renderer=lambda r, p, dpi=200: b"PNG")
        self.assertEqual(result.stats.get("ocr_applied_pages"), 0)
        self.assertTrue(any("needs_ocr" in i for i in result.issues))

    def test_render_page_without_pypdfium2_raises_honestly(self):
        try:
            import pypdfium2  # noqa: F401

            self.skipTest("pypdfium2 installed; absence path not testable")
        except ImportError:
            pass
        with self.assertRaises(OcrEngineError):
            render_page_to_png(b"%PDF-1.4 not a real doc", 1)


def build_pdf_bytes(content: bytes) -> bytes:
    return (
        b"%PDF-1.4\n" +
        b"3 0 obj\n<< /Length %d >>\nstream\n" % len(content) + content +
        b"\nendstream\nendobj\n" +
        b"4 0 obj\n<< /Type /Page /Parent 1 0 R /Contents 3 0 R >>\nendobj\n"
    )


if __name__ == "__main__":
    unittest.main()


class FallbackRouteTest(unittest.TestCase):
    def test_low_confidence_page_escalates_to_fallback(self):
        config = OcrConfig(engine="local", fallback="vision-api",
                           fallback_min_confidence=0.6)
        weak = FakeOcr(text="garbled short", confidence=0.3)
        strong = FakeOcr(text="fallback 引擎识别出的完整正文内容足够长因此通过质量阈值",
                         confidence=0.95)
        raw = build_pdf_bytes(b"BT ET")
        result = extract_pdf(raw, ocr=weak, ocr_config=config,
                             renderer=lambda r, p, dpi=200: b"PNG",
                             fallback_ocr=strong)
        self.assertTrue(any("ocr_fallback:fake-ocr->fake-ocr" in i
                            for i in result.issues))
        self.assertIn("fallback 引擎识别出的完整正文", result.blocks[0].text)

    def test_high_confidence_skips_fallback(self):
        config = OcrConfig(engine="local", fallback="vision-api",
                           fallback_min_confidence=0.6)
        good = FakeOcr(text="本地引擎高质量识别的正文内容足够长因此不需要回退处理",
                       confidence=0.97)
        unused = FakeOcr(text="should not appear")
        raw = build_pdf_bytes(b"BT ET")
        result = extract_pdf(raw, ocr=good, ocr_config=config,
                             renderer=lambda r, p, dpi=200: b"PNG",
                             fallback_ocr=unused)
        self.assertFalse(any("ocr_fallback:" in i for i in result.issues))
        self.assertNotIn("should not appear", result.blocks[0].text)

    def test_build_fallback_engine_gates(self):
        from knowledge.ocr import VisionApiOcr
        from knowledge.providers import OpenAICompatibleVision

        vision = OpenAICompatibleVision("vision_ocr", "GLM-5.3-Flash",
                                        "https://x.example", "real-key",
                                        egress_allowed=True)
        engine = build_fallback_engine(
            OcrConfig(fallback="vision-api"),
            providers={"vision_ocr": vision},
            provider_specs={"vision_ocr": {"api_key": "real-key",
                                           "egress_allowed": True}})
        self.assertIsInstance(engine, VisionApiOcr)
        # egress off -> no fallback
        self.assertIsNone(build_fallback_engine(
            OcrConfig(fallback="vision-api"),
            providers={"vision_ocr": OpenAICompatibleVision(
                "vision_ocr", "m", "https://x.example", "k",
                egress_allowed=False)},
            provider_specs={"vision_ocr": {"api_key": "k",
                                           "egress_allowed": False}}))
        # not configured -> none
        self.assertIsNone(build_fallback_engine(OcrConfig()))
