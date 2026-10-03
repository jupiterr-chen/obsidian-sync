"""Regression tests for the 2026-10-02 independent review (R01-R15).

Each test reproduces a review counterexample; they were written RED first
(failing against the reviewed code) and must stay GREEN after remediation.
Batched per remediation task RF0-RF6.
"""

from __future__ import annotations

import os
import unittest

from fixtures import temp_dir

from knowledge.providers import (
    MockEmbedder,
    ScriptedChat,
)


def _kb():
    from knowledge.store import KnowledgeStore

    return KnowledgeStore(os.path.join(temp_dir(), "knowledge.sqlite3"))


def _seed_doc_with_blocks(kb, extraction_id="extr-r1", text="毛利率 30%，代码 600519。"):
    from knowledge.indexing import build_generation

    stamp = "2026-10-01T00:00:00Z"
    kb.upsert_documents([{
        "source": "reports", "doc_id": "R1", "title": "R1", "symbol": "EXAMPLE",
        "available": True, "first_seen_at": stamp, "last_seen_at": stamp,
        "report_date": "2026-06-30",
    }], stamp)
    kb.upsert_versions([{
        "source": "reports", "doc_id": "R1", "version_id": "v1",
        "sha256": "a" * 64, "bytes": 100, "media_type": "application/pdf",
        "ext": "pdf", "rel_path": "x", "is_current": True, "state": "ready",
        "content_changed_at": None,
    }], stamp)
    kb.record_extraction({
        "extraction_id": extraction_id, "source": "reports", "doc_id": "R1",
        "version_id": "v1", "snapshot_sha256": "a" * 64,
        "parser_id": "t", "parser_version": "1", "config_digest": "cfg",
        "status": "ready", "issues": [], "stats": {},
    }, [{
        "block_type": "paragraph", "text": text,
        "locator": {"kind": "pdf", "page": 2},
        "quality": {"status": "ready", "issues": []},
    }])
    build_generation(kb)


# ===================================================================== RF1
class R01BudgetTest(unittest.TestCase):
    """R01: unified budget with reservation, settlement and vision ledger."""

    def test_top_level_budget_is_loaded_for_serve_kb(self):
        from knowledge.budget import load_budget

        budget = load_budget({"budget": {"max_total_input_tokens": 1}})
        self.assertEqual(budget.max_total_input_tokens, 1)
        # providers.budget still honored for legacy configs
        legacy = load_budget({"providers": {"budget": {
            "max_total_input_tokens": 5}}})
        self.assertEqual(legacy.max_total_input_tokens, 5)
        self.assertIsNone(load_budget({}).max_total_input_tokens)

    def test_reservation_blocks_call_when_remaining_insufficient(self):
        from knowledge.analysis import execute_analysis_run
        from knowledge.indexing import search as kw_search
        from knowledge.budget import Budget, BudgetExceeded

        kb = _kb()
        try:
            _seed_doc_with_blocks(kb)
            chat = ScriptedChat(replies=["结论 [1]。"])
            kb.record_usage("prior", "m", "chat", 9, 0, "test:none")
            created = kb.create_analysis_run("毛利率")
            outcome = execute_analysis_run(
                kb, created["run_id"], "毛利率", chat,
                retriever=lambda q, k: kw_search(kb, q, None, limit=k).get("hits", []),
                budget=Budget(max_total_input_tokens=10))
            # remaining = 10 - 9 = 1 < estimated prompt: must refuse BEFORE
            # any provider call, not settle at 72 tokens afterwards
            self.assertEqual(outcome["status"], "failed")
            self.assertIn("budget", outcome["error"])
            self.assertEqual(chat.calls, 0)
            totals = kb.usage_totals()
            self.assertLessEqual(totals["input_tokens"], 9)
        finally:
            kb.close()

    def test_vision_ocr_usage_recorded_and_page_capped(self):
        from knowledge.ocr import VisionApiOcr
        from knowledge.budget import Budget, BudgetLedger
        from knowledge.providers import OpenAICompatibleVision, Usage

        class CountingVision(OpenAICompatibleVision):
            def __init__(self):
                super().__init__("vision_ocr", "GLM-5.3-Flash",
                                 "http://x.example", "k", egress_allowed=True)
                self.calls = 0

            def complete_with_image(self, prompt, image_bytes, mime="image/png",
                                    max_output_tokens=2000):
                self.calls += 1
                return "OCR text", Usage(self.name, self.model, 4000, 500,
                                         "test:vision")

        kb = _kb()
        try:
            chat = CountingVision()
            # per-page estimate above the configured page ceiling -> refuse
            # before any provider call (R01)
            ledger = BudgetLedger(kb, Budget(max_input_tokens_per_page=50,
                                             max_total_input_tokens=1000))
            engine = VisionApiOcr(chat_provider=chat, ledger=ledger,
                                  page_token_cap=100)
            with self.assertRaises(Exception):
                engine.run(b"PNG")
            self.assertEqual(chat.calls, 0)

            # adequate cap -> call happens AND usage lands in the ledger
            ledger2 = BudgetLedger(kb, Budget(max_input_tokens_per_page=200000,
                                              max_total_input_tokens=100000))
            engine2 = VisionApiOcr(chat_provider=chat, ledger=ledger2,
                                   page_token_cap=5000)
            text, conf = engine2.run(b"PNG")
            self.assertEqual(text, "OCR text")
            self.assertEqual(chat.calls, 1)
            usage = kb.usage_totals()
            self.assertGreaterEqual(usage["input_tokens"], 4000)
            kinds = [row[0] for row in kb._conn.execute(
                "SELECT kind FROM usage_events")]
            self.assertIn("vision", kinds)
        finally:
            kb.close()

    def test_unknown_usage_settled_conservatively_not_zero(self):
        from knowledge.budget import Budget, BudgetLedger
        from knowledge.providers import ProviderCallError, Usage

        ledger = BudgetLedger(_kb(), Budget())
        kb = ledger.kb
        try:
            rid = ledger.reserve("chat", est_input=500)
            try:
                raise ProviderCallError("timeout", retryable=True)
            except ProviderCallError:
                ledger.fail_unknown(rid)
            row = kb._conn.execute(
                "SELECT status FROM budget_reservations WHERE id=?", (rid,)
            ).fetchone()
            self.assertEqual(row[0], "unknown")
            totals = kb.usage_totals()
            self.assertGreaterEqual(totals["input_tokens"], 500)  # estimate kept
        finally:
            kb.close()


class R03ProviderWiringTest(unittest.TestCase):
    """R03: vision provider must not masquerade as chat; primary route wired."""

    def test_primary_vision_route_gets_provider(self):
        from knowledge.config import KnowledgeConfig
        from knowledge.ocr import OcrConfig, VisionApiOcr
        from knowledge.providers import OpenAICompatibleVision

        kb = _kb()
        try:
            config = KnowledgeConfig(
                catalog_db="x", knowledge_db=kb.path, snapshot_root="y",
                library_config="z",
                extra={"ocr": {"engine": "vision-api"},
                       "providers": {"vision_ocr": {
                           "kind": "openai-compatible-vision",
                           "base_url": "http://x.example", "api_key": "real-key",
                           "model": "GLM-5.3-Flash", "egress_allowed": True}}})
            from library.config import Config

            library_config = Config.from_dict({
                "sources": {"reports": {"type": "reports_archive",
                                        "root": "/tmp"}}})
            from knowledge.jobs import JobRunner

            runner = JobRunner(kb, config, library_config)
            engine = runner.ocr_engine()
            self.assertIsInstance(engine, VisionApiOcr)
            self.assertIsNotNone(engine.chat_provider)  # was None (R03)
        finally:
            kb.close()

    def test_vision_config_does_not_enable_chat_analysis(self):
        from knowledge.kbapi import KbApi, KbApiError
        from knowledge.providers import OpenAICompatibleVision

        kb = _kb()
        try:
            vision = OpenAICompatibleVision("vision_ocr", "GLM-5.3-Flash",
                                            "http://x.example", "k",
                                            egress_allowed=True)
            api = KbApi(kb, {"t": ["research.read", "analysis.run"]},
                        embedder=None, chat=None)
            api.attach_providers(chat=None, embedder=None, vision=vision)
            with self.assertRaises(KbApiError) as ctx:
                api.create_analysis_run({"query": "x"})
            self.assertEqual(ctx.exception.status, 422)  # not silently vision
        finally:
            kb.close()


if __name__ == "__main__":
    unittest.main()
