"""P4 tests: providers, hybrid recall, analysis runs, citation verification,
usage ledger and budget gates - all with mocks (protocol only)."""

from __future__ import annotations

import os
import unittest

from fixtures import temp_dir

from knowledge.analysis import (
    Budget,
    build_analysis_prompt,
    execute_analysis_run,
    hybrid_search,
    verify_citations,
)
from knowledge.indexing import build_generation, search
from knowledge.kbapi import KbApi, KbApiError
from knowledge.providers import (
    MockEmbedder,
    ProviderCallError,
    ProviderNotConfigured,
    ScriptedChat,
    load_providers,
)
from knowledge.store import KnowledgeStore


def _doc(source, doc_id, symbol="EXAMPLE", first_seen="2026-09-01T00:00:00Z"):
    return {
        "source": source, "doc_id": doc_id, "title": doc_id,
        "display_title": "Report %s" % doc_id, "symbol": symbol,
        "doc_type": "H1", "available": True, "first_seen_at": first_seen,
        "last_seen_at": first_seen, "report_date": "2026-06-30",
    }


def _version(source, doc_id, version_id, sha, media="application/pdf", ext="pdf"):
    return {
        "source": source, "doc_id": doc_id, "version_id": version_id,
        "sha256": sha, "bytes": 100, "media_type": media, "ext": ext,
        "rel_path": "x", "is_current": True, "state": "ready",
        "content_changed_at": None,
    }


def _block(block_type, text, locator):
    return {"block_type": block_type, "text": text, "locator": locator,
            "quality": {"status": "ready", "issues": []}}


class HybridSearchTest(unittest.TestCase):
    def setUp(self):
        self.kb = KnowledgeStore(os.path.join(temp_dir(), "knowledge.sqlite3"))
        stamp = "2026-10-01T00:00:00Z"
        self.kb.upsert_documents([_doc("reports", "R1")], stamp)
        self.kb.upsert_versions([_version("reports", "R1", "v1", "a" * 64)], stamp)
        texts = [
            "gross margin expanded 3.2 pp driven by premium mix",
            "revenue grew 12 percent year over year",
            "gross margin gross margin gross margin repeated keyword",
            "R&D expense ratio stable around 11 percent",
        ]
        self.block_ids = []
        self.kb.record_extraction({
            "extraction_id": "extr-r1", "source": "reports", "doc_id": "R1",
            "version_id": "v1", "snapshot_sha256": "a" * 64,
            "parser_id": "test", "parser_version": "1", "config_digest": "cfg",
            "status": "ready", "issues": [], "stats": {},
        }, [_block("paragraph", text, {"kind": "pdf", "page": i + 1})
            for i, text in enumerate(texts)])
        build_generation(self.kb)
        self.embedder = MockEmbedder()

    def tearDown(self):
        self.kb.close()

    def test_hybrid_fuses_keyword_and_vector(self):
        result = hybrid_search(self.kb, "margin mix", self.embedder)
        self.assertTrue(result["ok"])
        self.assertGreater(len(result["hits"]), 0)
        top = result["hits"][0]
        self.assertEqual(top["score_kind"], "rrf_hybrid")
        # block 1 (margin+mix terms) and block 3 (dense margin) rank high
        self.assertIn("gross margin", top["block"]["text"].lower())
        # embeddings cached: second call embeds only the query
        before = self.kb.usage_totals()["calls"]
        hybrid_search(self.kb, "margin mix", self.embedder)
        after = self.kb.usage_totals()["calls"]
        self.assertEqual(after - before, 1)  # query embedding only

    def test_hybrid_falls_back_to_full_pool(self):
        # a query with no keyword hits still returns vector-ranked results
        result = hybrid_search(self.kb, "zzz unmatched query", self.embedder)
        self.assertTrue(result["ok"])
        # deterministic mock embedder: any query yields ranks over the pool
        self.assertEqual(len(result["hits"]), 4)

    def test_usage_ledger_records_embeddings(self):
        hybrid_search(self.kb, "margin", self.embedder)
        totals = self.kb.usage_totals()
        self.assertGreater(totals["input_tokens"], 0)
        self.assertGreaterEqual(totals["calls"], 2)  # blocks + query


class AnalysisRunTest(unittest.TestCase):
    def setUp(self):
        self.kb = KnowledgeStore(os.path.join(temp_dir(), "knowledge.sqlite3"))
        stamp = "2026-10-01T00:00:00Z"
        self.kb.upsert_documents([_doc("reports", "R1")], stamp)
        self.kb.upsert_versions([_version("reports", "R1", "v1", "a" * 64)], stamp)
        self.blocks = [
            _block("paragraph", "毛利率 30%，同比提升 3.2 个百分点。",
                   {"kind": "pdf", "page": 2}),
            _block("paragraph", "营收增长 12%。", {"kind": "pdf", "page": 3}),
        ]
        self.kb.record_extraction({
            "extraction_id": "extr-r1", "source": "reports", "doc_id": "R1",
            "version_id": "v1", "snapshot_sha256": "a" * 64,
            "parser_id": "test", "parser_version": "1", "config_digest": "cfg",
            "status": "ready", "issues": [], "stats": {},
        }, self.blocks)
        build_generation(self.kb)

    def tearDown(self):
        self.kb.close()

    def _retriever(self, query, k):
        result = search(self.kb, query, None, limit=k)
        return result.get("hits", [])

    def test_prompt_contains_numbered_evidence(self):
        prompt = build_analysis_prompt("毛利率如何变化？", [
            {"source": "reports", "doc_id": "R1", "text": "毛利率 30%",
             "locator": {"page": 2}},
        ])
        self.assertIn("[1]", prompt)
        self.assertIn("Question:", prompt)
        self.assertIn("毛利率", prompt)

    def test_successful_run_with_valid_citations(self):
        chat = ScriptedChat(replies=["毛利率改善。\n依据 [1] 和 [2]。"])
        query = "毛利率 营收 增长"
        created = self.kb.create_analysis_run(query)
        outcome = execute_analysis_run(
            self.kb, created["run_id"], query, chat,
            retriever=self._retriever)
        self.assertEqual(outcome["status"], "done")
        self.assertTrue(outcome["verification"]["all_valid"])
        self.assertEqual(len(outcome["citations"]), 2)
        run = self.kb.get_analysis_run(created["run_id"])
        self.assertEqual(run["status"], "done")
        usage = self.kb.usage_for_run(created["run_id"])
        self.assertEqual(len(usage), 1)
        self.assertEqual(usage[0]["kind"], "chat")
        # idempotent: re-running a done run is a no-op without new usage
        again = execute_analysis_run(self.kb, created["run_id"],
                                     "毛利率如何变化？", chat,
                                     retriever=self._retriever)
        self.assertTrue(again.get("idempotent"))
        self.assertEqual(len(self.kb.usage_for_run(created["run_id"])), 1)

    def test_invalid_citations_flagged_not_hidden(self):
        chat = ScriptedChat(replies=["结论。\n依据 [1] 和 [9]。"])
        created = self.kb.create_analysis_run("毛利率？")
        outcome = execute_analysis_run(self.kb, created["run_id"], "毛利率？",
                                        chat, retriever=self._retriever)
        self.assertEqual(outcome["status"], "done")
        self.assertFalse(outcome["verification"]["all_valid"])
        self.assertEqual(outcome["verification"]["invalid"],
                         [{"n": 9, "reason": "index_out_of_range"}])
        self.assertEqual(len(outcome["verification"]["valid"]), 1)

    def test_provider_failure_fails_run_without_publishing(self):
        chat = ScriptedChat(fail_with=ProviderCallError("429 rate limited",
                                                        retryable=True))
        created = self.kb.create_analysis_run("毛利率？")
        outcome = execute_analysis_run(self.kb, created["run_id"], "毛利率？",
                                        chat, retriever=self._retriever)
        self.assertEqual(outcome["status"], "failed")
        self.assertTrue(outcome["retryable"])
        run = self.kb.get_analysis_run(created["run_id"])
        self.assertIsNone(run["draft"])  # no draft published on failure
        self.assertEqual(self.kb.usage_for_run(created["run_id"]), [])

    def test_budget_gates_reject_before_provider_calls(self):
        chat = ScriptedChat()
        budget = Budget(max_total_input_tokens=5)
        self.kb.record_usage("prior", "prior-model", "chat", 10, 0, "test:none")
        created = self.kb.create_analysis_run("毛利率？")
        outcome = execute_analysis_run(self.kb, created["run_id"], "毛利率？",
                                        chat, retriever=self._retriever,
                                        budget=budget)
        self.assertEqual(outcome["status"], "failed")
        self.assertEqual(outcome["error"], "budget_exceeded_total_input_tokens")
        self.assertEqual(chat.calls, 0)
        # per-run gate
        budget = Budget(max_input_tokens_per_run=1)
        created2 = self.kb.create_analysis_run("营收？")
        outcome2 = execute_analysis_run(self.kb, created2["run_id"], "营收？",
                                        chat, retriever=self._retriever,
                                        budget=budget)
        self.assertEqual(outcome2["error"],
                         "budget_exceeded_per_run_input_tokens")
        self.assertEqual(chat.calls, 0)

    def test_verify_citations_bounds(self):
        blocks = [{"block_id": "b1", "source": "s", "doc_id": "d"}]
        result = verify_citations("text [1] [2]", [1, 2], blocks)
        self.assertTrue(result["all_valid"] is False)
        self.assertEqual(result["valid"][0]["block_id"], "b1")
        self.assertEqual(result["invalid"], [{"n": 2,
                                              "reason": "index_out_of_range"}])


class ProviderRegistryTest(unittest.TestCase):
    def test_unconfigured_provider_raises(self):
        from knowledge.providers import EmbeddingProvider, ChatProvider

        with self.assertRaises(ProviderNotConfigured):
            EmbeddingProvider().embed(["x"])
        with self.assertRaises(ProviderNotConfigured):
            ChatProvider().complete("x")

    def test_load_providers_default_empty_and_mock(self):
        self.assertEqual(load_providers({}), {})
        providers = load_providers({
            "providers": {"emb": {"kind": "mock-embedder", "dimensions": 8}}})
        self.assertIn("emb", providers)
        with self.assertRaises(ProviderNotConfigured):
            load_providers({
                "providers": {"real": {"kind": "openai",
                                       "base_url": "https://real.example/v4",
                                       "api_key": "a-real-looking-key",
                                       "model": "some-model"}}})
        # FILL-ME placeholders are treated as absent (no raise)
        self.assertEqual(load_providers({
            "providers": {"chat": {"kind": "openai", "base_url": "https://FILL-ME",
                                   "api_key": "FILL-ME", "model": "FILL-ME"}}}), {})


class AnalysisApiTest(unittest.TestCase):
    TOKEN = "analysis-token"

    def setUp(self):
        self.kb = KnowledgeStore(os.path.join(temp_dir(), "knowledge.sqlite3"))
        stamp = "2026-10-01T00:00:00Z"
        self.kb.upsert_documents([_doc("reports", "R1")], stamp)
        self.kb.upsert_versions([_version("reports", "R1", "v1", "a" * 64)], stamp)
        self.kb.record_extraction({
            "extraction_id": "extr-r1", "source": "reports", "doc_id": "R1",
            "version_id": "v1", "snapshot_sha256": "a" * 64,
            "parser_id": "test", "parser_version": "1", "config_digest": "cfg",
            "status": "ready", "issues": [], "stats": {},
        }, [_block("paragraph", "毛利率 30%。", {"kind": "pdf", "page": 2})])
        build_generation(self.kb)
        self.chat = ScriptedChat(replies=["毛利率 30%。依据 [1]。"])
        self.embedder = MockEmbedder(dimensions=16)
        self.api = KbApi(self.kb, {self.TOKEN: ["research.read", "analysis.run"]},
                         embedder=None, chat=None)

    def tearDown(self):
        self.kb.close()

    def test_analysis_disabled_without_provider(self):
        with self.assertRaises(KbApiError) as ctx:
            self.api.create_analysis_run({"query": "毛利率？"})
        self.assertEqual(ctx.exception.status, 422)
        self.assertEqual(ctx.exception.code, "task_disabled")

    def test_hybrid_mode_gate(self):
        with self.assertRaises(KbApiError) as ctx:
            self.api.do_search({"query": "毛利率", "mode": "hybrid"})
        self.assertEqual(ctx.exception.status, 422)
        # with an embedder the hybrid mode works end to end
        self.api.embedder = self.embedder
        result = self.api.do_search({"query": "毛利率", "mode": "hybrid"})
        self.assertEqual(result["hits"][0]["score_kind"], "rrf_hybrid")

    def test_analysis_run_via_api(self):
        self.api.chat = self.chat
        result = self.api.create_analysis_run({"query": "毛利率？"})
        self.assertEqual(result["status"], "done")
        self.assertEqual(len(result["citations"]), 1)
        self.assertEqual(result["usage"][0]["kind"], "chat")
        fetched = self.api.get_analysis_run(result["run_id"])
        self.assertEqual(fetched["status"], "done")
        self.assertIn("毛利率", fetched["draft"])
        with self.assertRaises(KbApiError) as ctx:
            self.api.get_analysis_run("run-missing")
        self.assertEqual(ctx.exception.status, 404)


if __name__ == "__main__":
    unittest.main()


class AnalysisExportTest(unittest.TestCase):
    def test_export_analysis_runs_markdown(self):
        import os

        from knowledge.writeback import export_analysis_runs, render_analysis_candidate

        kb = KnowledgeStore(os.path.join(temp_dir(), "knowledge.sqlite3"))
        try:
            stamp = "2026-10-01T00:00:00Z"
            kb.upsert_documents([_doc("reports", "R1")], stamp)
            kb.upsert_versions([_version("reports", "R1", "v1", "a" * 64)], stamp)
            kb.record_extraction({
                "extraction_id": "extr-r1", "source": "reports", "doc_id": "R1",
                "version_id": "v1", "snapshot_sha256": "a" * 64,
                "parser_id": "t", "parser_version": "1", "config_digest": "c",
                "status": "ready", "issues": [], "stats": {},
            }, [_block("paragraph", "毛利率 30%", {"kind": "pdf", "page": 1})])
            build_generation(kb)
            chat = ScriptedChat(replies=["毛利率结论。依据 [1]。"])
            created = kb.create_analysis_run("毛利率如何？")
            execute_analysis_run(kb, created["run_id"], "毛利率如何？", chat,
                                 retriever=lambda q, k: search(kb, q, None, limit=k).get("hits", []))
            out_dir = os.path.join(temp_dir(), "vault-gen")
            result = export_analysis_runs(kb, out_dir)
            self.assertEqual(result["count"], 1)
            path = os.path.join(out_dir, "%s.md" % created["run_id"])
            with open(path, "r", encoding="utf-8") as handle:
                markdown = handle.read()
            self.assertIn("待人工审核", markdown)
            self.assertIn("毛利率", markdown)
            self.assertIn("/api/kb/v1/evidence/", markdown)
            self.assertIn("全部有效：True", markdown)
            # re-export is a no-op (unchanged); missing run errors cleanly
            second = export_analysis_runs(kb, out_dir)
            self.assertEqual(second["outcomes"], ["unchanged"])
            missing = export_analysis_runs(kb, out_dir, run_id="run-none")
            self.assertEqual(missing.get("error"), "run not found")
        finally:
            kb.close()
