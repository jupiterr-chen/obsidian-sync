"""P0 regressions: term normalization (NFKC + t2s), the documents directory
listing, and advisory metadata flags.

Background: recorded production comparisons (kb-search-comparisons.json)
showed the simplified query 资产负债 returning zero hits while the
traditional 資產負債 found the same corpus blocks, and company baselines
had to be reconstructed from keyword recall because no directory view
existed. These tests lock the fixes in.
"""

from __future__ import annotations

import json
import os
import threading
import unittest
import urllib.request

from fixtures import temp_dir

from knowledge.indexing import (
    SearchFilters,
    TOKENIZER_VERSION,
    build_generation,
    search,
    tokenize,
)
from knowledge.kbapi import (
    KbApi,
    KbApiError,
    build_kb_server,
    document_metadata_flags,
    encode_cursor,
)
from knowledge.store import KnowledgeStore


def _doc(source, doc_id, symbol, *, doc_type="earnings",
         report_period="2026-03-31", published_at="2026-05-15T00:00:00Z",
         first_seen="2026-05-15T00:00:00Z"):
    return {
        "source": source, "doc_id": doc_id, "title": doc_id,
        "display_title": "Report %s" % doc_id, "symbol": symbol,
        "doc_type": doc_type, "available": True, "first_seen_at": first_seen,
        "last_seen_at": first_seen, "report_date": report_period,
        "report_period": report_period, "published_at": published_at,
        "filing_date": None,
    }


def _version(source, doc_id, version_id, sha):
    return {
        "source": source, "doc_id": doc_id, "version_id": version_id,
        "sha256": sha, "bytes": 100, "media_type": "application/pdf",
        "ext": "pdf", "rel_path": "x.pdf", "is_current": True,
        "state": "ready", "content_changed_at": None,
    }


def _block(block_type, text, locator):
    return {"block_type": block_type, "text": text, "locator": locator,
            "quality": {"status": "ready", "issues": []}}


def _record(kb, source, doc_id, version_id, sha, extraction_suffix, blocks):
    kb.record_extraction({
        "extraction_id": "extr-%s-%s" % (doc_id.lower(), extraction_suffix),
        "source": source, "doc_id": doc_id, "version_id": version_id,
        "snapshot_sha256": sha, "parser_id": "test", "parser_version": "1",
        "config_digest": "cfg", "status": "ready", "issues": [],
        "stats": {},
    }, blocks)


class NormalizationSearchTest(unittest.TestCase):
    """Simplified/traditional and full/half-width term equivalence."""

    def setUp(self):
        self.kb = KnowledgeStore(os.path.join(temp_dir(), "knowledge.sqlite3"))
        stamp = "2026-10-01T00:00:00Z"
        # 小米繁体季报块（生产语料形态）+ 阿里简体块 + 全角代码块
        self.kb.upsert_documents([
            _doc("reports", "XIAOMI-Q1", "01810"),
            _doc("reports", "ALI-FY23", "09988"),
        ], stamp)
        self.kb.upsert_versions([
            _version("reports", "XIAOMI-Q1", "v1", "a" * 64),
            _version("reports", "ALI-FY23", "v1", "b" * 64),
        ], stamp)
        _record(self.kb, "reports", "XIAOMI-Q1", "v1", "a" * 64, "01", [
            _block("paragraph",
                   "本季度未經審核的簡明綜合資產負債表：總資產人民幣3,000億元。",
                   {"kind": "pdf", "page": 3}),
        ])
        _record(self.kb, "reports", "ALI-FY23", "v1", "b" * 64, "01", [
            _block("paragraph",
                   "根据美国公认会计准则编制的营业收入为人民币2,048亿元。",
                   {"kind": "pdf", "page": 5}),
            _block("paragraph",
                   "半導體設備廠商 ASML 出貨量創新高，光刻機需求強勁。",
                   {"kind": "pdf", "page": 7}),
        ])
        build_generation(self.kb)

    def tearDown(self):
        self.kb.close()

    def test_tokenizer_folds_script_and_width(self):
        self.assertEqual(set(tokenize("资产负债")), set(tokenize("資產負債")))
        self.assertEqual(set(tokenize("ASML")), set(tokenize("ＡＳＭＬ")))
        self.assertEqual(set(tokenize("营业收入")), set(tokenize("營業收入")))

    def test_simplified_query_finds_traditional_blocks(self):
        # 生产事故回归：简体查询曾 0 命中同一索引下的繁体财报
        result = search(self.kb, "资产负债")
        self.assertTrue(result["ok"])
        self.assertGreater(len(result["hits"]), 0)
        self.assertEqual(result["hits"][0].block["doc_id"], "XIAOMI-Q1")

    def test_traditional_query_finds_simplified_blocks(self):
        result = search(self.kb, "營業收入")
        self.assertTrue(result["ok"])
        self.assertGreater(len(result["hits"]), 0)
        self.assertEqual(result["hits"][0].block["doc_id"], "ALI-FY23")

    def test_full_width_query_matches_ascii_terms(self):
        result = search(self.kb, "ＡＳＭＬ")
        self.assertTrue(result["ok"])
        self.assertGreater(len(result["hits"]), 0)

    def test_symbol_filter_never_leaks_other_subjects(self):
        # 主体污染回归：带 symbol 过滤的检索不得命中其他主体或无主体文档
        result = search(self.kb, "资产", SearchFilters(symbols=["01810"]))
        self.assertTrue(result["ok"])
        self.assertTrue(result["hits"])
        self.assertTrue(all(h.block["doc_id"] == "XIAOMI-Q1"
                            for h in result["hits"]))
        result = search(self.kb, "美国公认会计准则",
                        SearchFilters(symbols=["01810"]))
        self.assertEqual(result["hits"], [])

    def test_tokenizer_version_is_part_of_generation_identity(self):
        first = build_generation(self.kb)
        self.assertFalse(first["changed"])  # unchanged corpus -> no-op
        import knowledge.indexing as indexing

        original = indexing.TOKENIZER_VERSION
        try:
            indexing.TOKENIZER_VERSION = original + "-probe"
            second = build_generation(self.kb)
            # tokenizer identity change must force a rebuild, never silently
            # reuse postings built with the old term rules
            self.assertTrue(second["changed"])
            self.assertNotEqual(first["generation_id"], second["generation_id"])
        finally:
            indexing.TOKENIZER_VERSION = original
        self.assertTrue(TOKENIZER_VERSION)


class DirectoryListingTest(unittest.TestCase):
    """GET /documents: identity-driven enumeration + metadata flags."""

    def setUp(self):
        self.kb = KnowledgeStore(os.path.join(temp_dir(), "knowledge.sqlite3"))
        stamp = "2026-10-01T00:00:00Z"
        self.kb.upsert_documents([
            # 正常财报
            _doc("reports", "MI-2026Q1", "01810"),
            # 阿里型缺陷：FY2023 年报期间写成上一财年末（与发布日差 >400 天）
            _doc("reports", "ALI-FY23", "09988",
                 report_period="2022-09-30", published_at="2023-11-17T00:00:00Z"),
            # 期间为空 + 无代码的财报
            _doc("reports", "BROKEN-Q", None, report_period=None),
            # 非财报类（无期间无代码也不应误报）
            _doc("discord", "NOTE-1", None, doc_type="note",
                 report_period=None, published_at=None),
        ], stamp)
        self.kb.upsert_versions([
            _version("reports", "MI-2026Q1", "v1", "a" * 64),
            _version("reports", "ALI-FY23", "v1", "b" * 64),
        ], stamp)
        self.api = KbApi(self.kb, {"tok": ["research.read"]})

    def tearDown(self):
        self.kb.close()

    def test_listing_scoped_to_symbol_returns_only_that_subject(self):
        result = self.api.list_documents({"symbol": ["01810"]})
        self.assertEqual(result["total"], 1)
        doc = result["documents"][0]
        self.assertEqual(doc["doc_id"], "MI-2026Q1")
        self.assertEqual(doc["version_count"], 1)
        self.assertEqual(doc["current_version_id"], "v1")
        self.assertEqual(doc["metadata_flags"], [])
        self.assertEqual(doc["document_url"],
                         "/api/kb/v1/documents/reports/MI-2026Q1")

    def test_listing_flags_suspect_period_and_missing_fields(self):
        result = self.api.list_documents({"symbol": ["09988"]})
        self.assertEqual(result["total"], 1)
        self.assertIn("period_suspect", result["documents"][0]["metadata_flags"])

        result = self.api.list_documents({"doc_type": ["earnings"]})
        by_id = {d["doc_id"]: d for d in result["documents"]}
        self.assertIn("period_missing", by_id["BROKEN-Q"]["metadata_flags"])
        self.assertIn("symbol_missing", by_id["BROKEN-Q"]["metadata_flags"])
        self.assertNotIn("NOTE-1", by_id)  # doc_type filter excludes notes

    def test_invalid_period_format_is_flagged(self):
        self.kb.upsert_documents([
            _doc("reports", "ODD-PERIOD", "01810", report_period="2023-Q3"),
        ], "2026-10-02T00:00:00Z")
        result = self.api.list_documents({"symbol": ["01810"]})
        odd = next(d for d in result["documents"]
                   if d["doc_id"] == "ODD-PERIOD")
        self.assertIn("period_invalid", odd["metadata_flags"])
        self.assertNotIn("period_suspect", odd["metadata_flags"])

    def test_fiscal_title_period_mismatch_catches_real_defect(self):
        # 生产实况：FY2023 中期报告的期间错存为 2021-12-31（正确应为 2022-09-30）
        self.kb.upsert_documents([
            _doc("reports", "ALI-FY23-INT", "09988",
                 report_period="2021-12-31",
                 first_seen="2023-05-20T00:00:00Z",
                 published_at=None),
        ], "2026-10-02T00:00:00Z",
        )
        # _doc 不写 title；直接改写已入库行的标题
        with self.kb._lock:
            self.kb._conn.execute(
                "UPDATE kb_documents SET title=? WHERE doc_id=?",
                ("2023財政年度中期報告", "ALI-FY23-INT"))
            self.kb._conn.commit()
        doc = self.api.document("reports", "ALI-FY23-INT")
        self.assertIn("period_title_mismatch", doc["metadata_flags"])

    def test_fiscal_title_correct_periods_pass(self):
        cases = [
            ("2023財政年度中期報告", "2022-09-30"),   # 4-3月财年中期
            ("2026 財務年度中期報告", "2025-09-30"),
            ("2021財政年度報告", "2021-03-31"),        # 4-3月财年年报
            ("2024財務年度中期報告", "2023-09-30"),
        ]
        for index, (title, period) in enumerate(cases):
            doc_id = "FYCASE-%d" % index
            self.kb.upsert_documents([
                _doc("reports", doc_id, "09988", report_period=period,
                     published_at=None),
            ], "2026-10-02T00:00:00Z")
            with self.kb._lock:
                self.kb._conn.execute(
                    "UPDATE kb_documents SET title=? WHERE doc_id=?",
                    (title, doc_id))
                self.kb._conn.commit()
            doc = self.api.document("reports", doc_id)
            self.assertEqual(doc["metadata_flags"], [], title)

    def test_fiscal_title_rule_is_bounded(self):
        # 无财年短语的标题（10-K / 业绩公告 / 券商标题）不做该检查
        doc = {"doc_type": "10-K", "symbol": "AAPL", "report_period": "2021-12-31",
               "published_at": None, "title": "Form 10-K fiscal year 2021"}
        self.assertNotIn("period_title_mismatch", document_metadata_flags(doc))
        # 多财年提及时，任一解释一致即通过（保守不误报）
        doc2 = {"doc_type": "ANNUAL", "symbol": "09988",
                "report_period": "2022-03-31", "published_at": None,
                "title": "對比 2022財政年度 與 2023財政年度中期報告"}
        self.assertNotIn("period_title_mismatch", document_metadata_flags(doc2))

    def test_single_document_carries_flags(self):
        doc = self.api.document("reports", "ALI-FY23")
        self.assertIn("metadata_flags", doc)
        self.assertIn("period_suspect", doc["metadata_flags"])

    def test_listing_filters_and_stable_order(self):
        result = self.api.list_documents({"source": ["reports"]})
        ids = [d["doc_id"] for d in result["documents"]]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(result["total"], 3)
        available = self.api.list_documents(
            {"available": ["true"], "source": ["reports"]})
        self.assertEqual(available["total"], 3)
        none_unavailable = self.api.list_documents({"available": ["false"]})
        self.assertEqual(none_unavailable["total"], 0)
        # bare-string params (direct callers) resolve identically to lists
        bare = self.api.list_documents({"source": "reports"})
        self.assertEqual(bare["total"], result["total"])

    def test_listing_pagination_and_cursor_binding(self):
        first = self.api.list_documents({"limit": ["2"]})
        self.assertEqual(len(first["documents"]), 2)
        self.assertIsNotNone(first["next_cursor"])
        second = self.api.list_documents(
            {"limit": ["2"], "cursor": first["next_cursor"]})
        self.assertEqual(second["offset"], 2)
        seen = {d["doc_id"] for d in first["documents"]}
        seen.update(d["doc_id"] for d in second["documents"])
        self.assertEqual(len(seen), first["total"])
        # 游标绑定过滤集：换过滤条件必须 409，而不是静默换结果集
        with self.assertRaises(KbApiError) as ctx:
            self.api.list_documents(
                {"limit": ["2"], "cursor": first["next_cursor"],
                 "symbol": ["01810"]})
        self.assertEqual(ctx.exception.status, 409)
        self.assertEqual(ctx.exception.code, "cursor_expired")

    def test_listing_validation(self):
        with self.assertRaises(KbApiError) as ctx:
            self.api.list_documents({"limit": ["0"]})
        self.assertEqual(ctx.exception.status, 400)
        with self.assertRaises(KbApiError) as ctx:
            self.api.list_documents({"available": ["maybe"]})
        self.assertEqual(ctx.exception.status, 400)
        with self.assertRaises(KbApiError) as ctx:
            self.api.list_documents({"cursor": "not-a-cursor!!"})
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.code, "invalid_cursor")


class DirectoryHttpLayerTest(unittest.TestCase):
    TOKEN = "http-token"

    @classmethod
    def setUpClass(cls):
        cls.kb = KnowledgeStore(os.path.join(temp_dir(), "knowledge.sqlite3"))
        stamp = "2026-10-01T00:00:00Z"
        cls.kb.upsert_documents([
            _doc("reports", "MI-2026Q1", "01810"),
            _doc("reports", "ALI-FY23", "09988",
                 report_period="2022-09-30", published_at="2023-11-17T00:00:00Z"),
        ], stamp)
        cls.kb.upsert_versions([
            _version("reports", "MI-2026Q1", "v1", "a" * 64),
        ], stamp)
        cls.server = build_kb_server(cls.kb, {cls.TOKEN: ["research.read"]},
                                     "127.0.0.1", 0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.kb.close()

    def _request(self, path, token=None):
        url = "http://127.0.0.1:%d%s" % (self.port, path)
        request = urllib.request.Request(url, method="GET")
        if token:
            request.add_header("Authorization", "Bearer %s" % token)
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_directory_requires_auth_then_scopes_to_symbol(self):
        status, payload = self._request("/api/kb/v1/documents?symbol=01810")
        self.assertEqual(status, 401)
        status, payload = self._request(
            "/api/kb/v1/documents?symbol=01810", token=self.TOKEN)
        self.assertEqual(status, 200)
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["documents"][0]["doc_id"], "MI-2026Q1")
        self.assertIn("metadata_flags", payload["documents"][0])

    def test_directory_flags_over_http(self):
        status, payload = self._request(
            "/api/kb/v1/documents?symbol=09988", token=self.TOKEN)
        self.assertEqual(status, 200)
        self.assertIn("period_suspect", payload["documents"][0]["metadata_flags"])

    def test_post_on_directory_is_not_found(self):
        url = "http://127.0.0.1:%d/api/kb/v1/documents" % self.port
        request = urllib.request.Request(url, data=b"{}", method="POST")
        request.add_header("Authorization", "Bearer %s" % self.TOKEN)
        try:
            with urllib.request.urlopen(request) as response:
                status = response.status
        except urllib.error.HTTPError as exc:
            status = exc.code
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
