"""Original S1/S2 boundaries: missing-page activation and claim egress.

Only isolated stores and offline providers; no production/model requests.
"""
import unittest
from unittest.mock import patch

from test_tq3_reprocess import _kb, _seed
from knowledge.effective import effective_extraction
from knowledge.extract import extract_pdf
from knowledge.indexing import _selected_blocks
from knowledge.ocr import OcrConfig
from knowledge.providers import Usage
from knowledge.summaries import consume_updates, enqueue_summary_update


def _block(page):
    return {"block_type": "paragraph",
            "text": "Healthy original page %d: revenue 123, margin 25%%. " % page,
            "locator": {"kind": "pdf", "page": page},
            "quality": {"status": "ready", "issues": []}}


class CaptureChat:
    name, model = "offline-review", "synthetic"

    def __init__(self):
        self.prompts = []

    def complete(self, prompt):
        self.prompts.append(prompt)
        return "Synthetic summary", Usage(self.name, self.model, 10, 2, "offline")


class ReviewCompletenessAndScopeTest(unittest.TestCase):
    def test_real_extractor_missing_page_keeps_complete_old(self):
        kb = _kb()
        try:
            _seed(kb, "PAGES", "p", "old-complete", blocks=[_block(1), _block(2)])
            with patch("knowledge.extract.extractor_info", return_value=("pypdfium2", "test")), \
                    patch("knowledge.extract._pdfium_page_texts",
                          return_value=[_block(1)["text"], None]):
                result = extract_pdf(b"synthetic", ocr_config=OcrConfig(engine="off"))
            self.assertEqual(result.stats["missing_content_pages"], 1)
            kb.record_extraction({
                "extraction_id": "new-incomplete", "source": "reports",
                "doc_id": "PAGES", "version_id": "v1", "snapshot_sha256": "p",
                "parser_id": result.parser_id, "parser_version": result.parser_version,
                "config_digest": "new", "status": result.status,
                "issues": result.issues, "stats": result.stats}, [
                    {"block_type": b.block_type, "text": b.text, "locator": b.locator,
                     "quality": {"status": b.quality.status, "issues": b.quality.issues}}
                    for b in result.blocks])
            self.assertEqual(effective_extraction(kb._conn, "reports", "PAGES", "v1")
                             ["extraction_id"], "old-complete")
            self.assertEqual(len(_selected_blocks(kb)), 2)
        finally:
            kb.close()

    def test_clean_bytes_do_not_override_failure_or_page_quality(self):
        cases = [
            ("failed", {}, None),
            ("review", {"low_confidence_pages": 1}, None),
            ("ready", {"pages": 2}, None),  # page 2 absent even if status is stale
            ("ready", {}, "review"),  # block quality must agree with the extraction
        ]
        for status, stats, block_status in cases:
            with self.subTest(status=status, stats=stats, block_status=block_status):
                kb = _kb()
                try:
                    _seed(kb, "PAGES", "p", "old-complete", blocks=[_block(1), _block(2)])
                    block = _block(1)
                    if block_status:
                        block["quality"] = {"status": block_status,
                                            "issues": ["ocr_low_confidence"]}
                    _seed(kb, "PAGES", "p", "new", blocks=[block], status=status)
                    import json
                    with kb._tx() as conn:
                        conn.execute("UPDATE extractions SET stats_json=? WHERE extraction_id='new'",
                                     (json.dumps(stats),))
                    self.assertEqual(effective_extraction(kb._conn, "reports", "PAGES", "v1")
                                     ["extraction_id"], "old-complete")
                finally:
                    kb.close()

    def test_complete_successor_switches_and_failed_only_is_not_fallback(self):
        kb = _kb()
        try:
            _seed(kb, "PAGES", "p", "old", blocks=[_block(1), _block(2)])
            _seed(kb, "PAGES", "p", "new", blocks=[_block(1), _block(2)])
            self.assertEqual(effective_extraction(kb._conn, "reports", "PAGES", "v1")
                             ["extraction_id"], "new")
            _seed(kb, "FAILED", "f", "failed", blocks=[_block(1)], status="failed")
            self.assertIsNone(effective_extraction(kb._conn, "reports", "FAILED", "v1"))
            _seed(kb, "REVIEW", "r", "review", blocks=[_block(1)], status="review")
            self.assertEqual(effective_extraction(kb._conn, "reports", "REVIEW", "v1")
                             ["status"], "review")
        finally:
            kb.close()

    def _claims(self, kb):
        refs = {name: {"source": "reports", "doc_id": name, "version_id": "v1"}
                for name in ("ALLOWED", "DENIED")}
        for name, evidence, counter in [
            ("AUTHORIZED_CLAIM", [refs["ALLOWED"]], []),
            ("DENIED_CLAIM", [refs["DENIED"]], []),
            ("MIXED_CLAIM", [refs["ALLOWED"]], [refs["DENIED"]]),
            ("UNSCOPED_CLAIM", [], []),
        ]:
            kb.upsert_claim({"claim_id": name, "current_revision": 1,
                             "subject": "EX", "statement": name, "status": "confirmed",
                             "evidence": evidence, "counterevidence": counter})
        enqueue_summary_update(kb, "company", "EX", "review-fixture", {},
                               event_key="review-claims")

    def test_summary_send_scopes_claims_and_counterevidence(self):
        kb = _kb()
        try:
            self._claims(kb)
            chat = CaptureChat()
            outcome = consume_updates(kb, chat=chat, allowed_entities={("company", "EX")},
                                      allowed_documents={("reports", "ALLOWED")})
            self.assertEqual(outcome["generated"], 1)
            self.assertEqual(len(chat.prompts), 1)
            self.assertIn("AUTHORIZED_CLAIM", chat.prompts[0])
            for name in ("DENIED_CLAIM", "MIXED_CLAIM", "UNSCOPED_CLAIM"):
                self.assertNotIn(name, chat.prompts[0])
        finally:
            kb.close()

    def test_empty_document_scope_never_sends_claim_only_summary(self):
        kb = _kb()
        try:
            self._claims(kb)
            chat = CaptureChat()
            consume_updates(kb, chat=chat, allowed_entities={("company", "EX")},
                            allowed_documents=set())
            self.assertEqual(chat.prompts, [])
        finally:
            kb.close()
