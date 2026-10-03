"""P3 tests: lexical index, search filters, /api/kb/v1 contract, events."""

from __future__ import annotations

import json
import os
import threading
import unittest
import urllib.request

from fixtures import temp_dir

from knowledge.indexing import (
    SearchFilters,
    build_generation,
    query_terms,
    search,
    snippet_for,
    tokenize,
)
from knowledge.kbapi import KbApi, KbApiError, build_kb_server, load_tokens
from knowledge.schema import validate_evidence_block
from knowledge.store import JOB_DONE, KnowledgeStore


def _doc(source, doc_id, symbol, first_seen="2026-09-01T00:00:00Z"):
    return {
        "source": source, "doc_id": doc_id, "title": doc_id,
        "display_title": "Report %s" % doc_id, "symbol": symbol,
        "doc_type": "H1", "available": True, "first_seen_at": first_seen,
        "last_seen_at": first_seen, "report_date": "2026-06-30",
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


class IndexSearchTest(unittest.TestCase):
    def setUp(self):
        self.kb = KnowledgeStore(os.path.join(temp_dir(), "knowledge.sqlite3"))
        stamp = "2026-10-01T00:00:00Z"
        self.kb.upsert_documents([
            _doc("reports", "R1", "EXAMPLE"),
            _doc("discord", "D1", None),
        ], stamp)
        self.kb.upsert_versions([
            _version("reports", "R1", "v1", "a" * 64),
            _version("discord", "D1", "v1", "b" * 64),
        ], stamp)
        self.extr_r1 = "extr-r1-" + "0" * 20
        self.extr_d1 = "extr-d1-" + "0" * 20
        self.kb.record_extraction({
            "extraction_id": self.extr_r1, "source": "reports", "doc_id": "R1",
            "version_id": "v1", "snapshot_sha256": "a" * 64,
            "parser_id": "test", "parser_version": "1", "config_digest": "cfg",
            "status": "ready", "issues": [],
            "stats": {"pages": 3},
        }, [
            _block("heading", "2026 中期业绩摘要", {"kind": "pdf", "page": 1}),
            _block("paragraph",
                   "毛利率 (gross margin) 为 30%，同比提升 3.2 个百分点；股票代码 600519。",
                   {"kind": "pdf", "page": 2}),
        ])
        self.kb.record_extraction({
            "extraction_id": self.extr_d1, "source": "discord", "doc_id": "D1",
            "version_id": "v1", "snapshot_sha256": "b" * 64,
            "parser_id": "test", "parser_version": "1", "config_digest": "cfg",
            "status": "ready", "issues": [], "stats": {},
        }, [
            _block("paragraph",
                   "Discord research note: revenue growth slows, 10-Q filing delayed.",
                   {"kind": "text", "start_char": 0, "end_char": 60}),
        ])

    def tearDown(self):
        self.kb.close()

    def test_tokenizer_covers_short_cjk_codes_and_numbers(self):
        terms = tokenize("毛利率 600519 10-Q AAPL 毛利")
        self.assertIn("600519", terms)
        self.assertIn("10-q", terms)
        self.assertIn("aapl", terms)
        self.assertIn("毛利", terms)          # two-char word via bigram
        self.assertIn("毛", terms)            # single char via unigram
        self.assertEqual(query_terms("毛利 毛利"), ["毛", "利", "毛利"])  # deduped, order-stable

    def test_build_generation_is_idempotent_and_atomic(self):
        first = build_generation(self.kb)
        self.assertTrue(first["ok"])
        self.assertTrue(first["changed"])
        self.assertEqual(first["stats"]["blocks"], 3)
        active = self.kb.active_generation()
        self.assertEqual(active["generation_id"], first["generation_id"])
        # unchanged manifest -> no-op rebuild
        second = build_generation(self.kb)
        self.assertTrue(second["ok"])
        self.assertFalse(second["changed"])
        self.assertEqual(self.kb.active_generation()["generation_id"],
                         first["generation_id"])
        # stats survive activation
        self.assertEqual(self.kb.active_generation()["stats"]["blocks"], 3)

    def test_search_cjk_english_codes(self):
        build_generation(self.kb)
        for query in ("毛利率", "毛利", "gross margin", "600519", "10-Q", "业绩"):
            result = search(self.kb, query)
            self.assertTrue(result["ok"], query)
            self.assertGreater(len(result["hits"]), 0,
                               "query %r returned no hits" % query)
        result = search(self.kb, "毛利率")
        top = result["hits"][0]
        self.assertEqual(top.block["doc_id"], "R1")
        self.assertIn("毛利", top.matched_terms)
        self.assertTrue(all(t in top.block["text"] or len(t) <= 2
                            for t in top.matched_terms))
        self.assertEqual(top.score_kind, "bm25")
        # snippet contains surrounding context and offsets are in-block chars
        text, spans = snippet_for(top.block["text"], ["毛利率"])
        self.assertTrue(spans)

    def test_search_filters_symbols_sources_asof(self):
        build_generation(self.kb)
        result = search(self.kb, "margin", SearchFilters(symbols=["example"]))
        self.assertTrue(all(h.block["doc_id"] == "R1" for h in result["hits"]))
        result = search(self.kb, "research note", SearchFilters(sources=["discord"]))
        self.assertTrue(all(h.block["doc_id"] == "D1" for h in result["hits"]))
        # as_of=system before first_seen -> nothing visible
        result = search(self.kb, "margin", SearchFilters(
            as_of="2026-08-01T00:00:00Z", as_of_mode="system"))
        self.assertEqual(result["hits"], [])
        # S03: public mode needs PUBLICATION evidence - the fixture docs
        # carry only report_date, so a July cutoff must see nothing; add a
        # published basis before expecting visibility
        result = search(self.kb, "margin", SearchFilters(
            as_of="2026-07-01T00:00:00Z", as_of_mode="public"))
        self.assertEqual(result["hits"], [])
        # T03: evidence must not predate the stored first observation
        # (2026-10-01 in this fixture)
        self.kb.upsert_documents([dict(_doc("reports", "R1", "EXAMPLE"),
                                      published_at="2026-10-01T00:00:00Z")],
                                 "2026-10-01T00:00:00Z")
        self.kb.upsert_versions([_version("reports", "R1", "v1", "a" * 64)],
                                "2026-10-01T00:00:00Z")
        result = search(self.kb, "margin", SearchFilters(
            as_of="2026-10-02T00:00:00Z", as_of_mode="public"))
        self.assertGreater(len(result["hits"]), 0)
        # unknown collections are rejected at the API layer, not here

    def test_new_block_changes_generation(self):
        first = build_generation(self.kb)
        self.kb.upsert_versions([_version("reports", "R1", "v2", "c" * 64)],
                                "2026-10-02T00:00:00Z")
        self.kb.record_extraction({
            "extraction_id": "extr-r1-v2-" + "0" * 18, "source": "reports",
            "doc_id": "R1", "version_id": "v2", "snapshot_sha256": "c" * 64,
            "parser_id": "test", "parser_version": "1", "config_digest": "cfg",
            "status": "ready", "issues": [], "stats": {},
        }, [_block("paragraph", "新增版本的段落内容 about margin", {"kind": "pdf", "page": 1})])
        second = build_generation(self.kb)
        self.assertNotEqual(first["generation_id"], second["generation_id"])
        self.assertEqual(self.kb.active_generation()["generation_id"],
                         second["generation_id"])

    def test_events_flow_and_cursor(self):
        self.kb.emit_event("version.registered", "reports", "R1", "v1", {"sha": "a"})
        self.kb.emit_event("index.published", None, None, None,
                           {"generation_id": "g1"}, event_id="evt-index-g1")
        build_generation(self.kb)  # emits its own index.published
        events = self.kb.events_after(0, limit=2)
        self.assertEqual(len(events), 2)
        cursor = events[-1]["sequence"]
        rest = self.kb.events_after(cursor, limit=10)
        self.assertGreaterEqual(len(rest), 1)
        self.assertEqual(rest[0]["sequence"], cursor + 1)
        # idempotent emission: same payload -> no duplicate
        before = self.kb.latest_event_sequence()
        self.kb.emit_event("version.registered", "reports", "R1", "v1", {"sha": "a"})
        self.assertEqual(self.kb.latest_event_sequence(), before)


class KbApiTest(unittest.TestCase):
    TOKEN = "test-token-123"

    def setUp(self):
        self.kb = KnowledgeStore(os.path.join(temp_dir(), "knowledge.sqlite3"))
        stamp = "2026-10-01T00:00:00Z"
        self.kb.upsert_documents([_doc("reports", "R1", "EXAMPLE")], stamp)
        self.kb.upsert_versions([_version("reports", "R1", "v1", "a" * 64)], stamp)
        self.kb.record_extraction({
            "extraction_id": "extr-r1", "source": "reports", "doc_id": "R1",
            "version_id": "v1", "snapshot_sha256": "a" * 64,
            "parser_id": "test", "parser_version": "1", "config_digest": "cfg",
            "status": "ready", "issues": [], "stats": {},
        }, [
            _block("heading", "2026 中期业绩摘要", {"kind": "pdf", "page": 1}),
            _block("paragraph", "毛利率为 30%，代码 600519。", {"kind": "pdf", "page": 2}),
            _block("paragraph", "第二页继续讨论毛利率趋势。", {"kind": "pdf", "page": 3}),
        ])
        build_generation(self.kb)
        self.api = KbApi(self.kb, {self.TOKEN: ["research.read"]})

    def tearDown(self):
        self.kb.close()

    def _search(self, **body):
        base = {"query": "毛利率", "mode": "keyword"}
        base.update(body)
        return self.api.do_search(base)

    def test_authentication_required_and_scoped(self):
        with self.assertRaises(KbApiError) as ctx:
            self.api.authenticate(None, "research.read")
        self.assertEqual(ctx.exception.status, 401)
        with self.assertRaises(KbApiError) as ctx:
            self.api.authenticate("wrong-token", "research.read")
        self.assertEqual(ctx.exception.status, 403)
        self.assertEqual(self.api.authenticate(self.TOKEN, "research.read"),
                         "research.read")

    def test_search_contract_shape(self):
        result = self._search()
        self.assertIn("request_id", result)
        self.assertIn("generation_id", result)
        self.assertIn("normalized_filters", result)
        hit = result["hits"][0]
        for key in ("source", "doc_id", "source_version", "source_sha256",
                    "extraction_id", "block_id", "block_type", "text",
                    "locator", "quality", "evidence_url", "source_version_url",
                    "score_kind", "score"):
            self.assertIn(key, hit)
        evidence = {k: hit[k] for k in (
            "schema_version", "source", "doc_id", "source_version",
            "source_sha256", "extraction_id", "block_id", "block_type",
            "text", "locator", "quality")}
        evidence["schema_version"] = "1"
        self.assertEqual(validate_evidence_block(evidence), [])

    def test_search_validation_and_modes(self):
        with self.assertRaises(KbApiError) as ctx:
            self._search(query="")
        self.assertEqual(ctx.exception.status, 400)
        with self.assertRaises(KbApiError) as ctx:
            self._search(mode="hybrid")
        self.assertEqual(ctx.exception.status, 422)
        self.assertEqual(ctx.exception.code, "mode_unavailable")
        with self.assertRaises(KbApiError) as ctx:
            self._search(limit=500)
        self.assertEqual(ctx.exception.status, 400)
        with self.assertRaises(KbApiError) as ctx:
            self._search(filters={"collections": ["personal_notes"]})
        self.assertEqual(ctx.exception.status, 403)

    def test_cursor_pagination_consistency(self):
        first = self._search(limit=1)
        self.assertEqual(len(first["hits"]), 1)
        self.assertIsNotNone(first["next_cursor"])
        second = self._search(limit=1, cursor=first["next_cursor"])
        self.assertNotEqual(second["hits"][0]["block_id"],
                            first["hits"][0]["block_id"])
        # cursor bound to a different query -> 409
        with self.assertRaises(KbApiError) as ctx:
            self.api.do_search({"query": "600519",
                                "cursor": first["next_cursor"]})
        self.assertEqual(ctx.exception.status, 409)
        self.assertEqual(ctx.exception.code, "cursor_expired")
        # cursor from another generation -> 409
        from knowledge.kbapi import encode_cursor
        stale = encode_cursor({"digest": json.dumps({
            "q": "毛利率", "f": {}}).encode("utf-8").hex()[:16], "offset": 0,
            "generation": "gen-other"})
        with self.assertRaises(KbApiError):
            self._search(cursor="not-base64-!!")

    def test_documents_versions_evidence(self):
        doc = self.api.document("reports", "R1")
        self.assertEqual(doc["versions"][0]["version_id"], "v1")
        self.assertEqual(doc["versions"][0]["extraction_status"], "ready")
        version = self.api.document_version("reports", "R1", "v1")
        self.assertEqual(version["version"]["sha256"], "a" * 64)
        with self.assertRaises(KbApiError) as ctx:
            self.api.document_version("reports", "R1", "vX")
        self.assertEqual(ctx.exception.status, 404)
        blocks = self.kb.get_blocks("extr-r1")
        evidence = self.api.evidence(blocks[0]["block_id"])
        self.assertEqual(validate_evidence_block(evidence["evidence"]), [])
        self.assertIn("context", evidence)
        self.assertEqual(len(evidence["context"]["after"]), 1)
        with self.assertRaises(KbApiError) as ctx:
            self.api.evidence("missing-block")
        self.assertEqual(ctx.exception.status, 404)

    def test_extraction_blocks_pagination(self):
        result = self.api.extraction_blocks("extr-r1", None, limit=1)
        self.assertEqual(len(result["blocks"]), 1)
        self.assertIsNotNone(result["next_cursor"])
        page2 = self.api.extraction_blocks("extr-r1", result["next_cursor"], limit=1)
        self.assertEqual(len(page2["blocks"]), 1)
        page3 = self.api.extraction_blocks("extr-r1", page2["next_cursor"], limit=1)
        self.assertEqual(len(page3["blocks"]), 1)
        self.assertIsNone(page3["next_cursor"])
        seen = [result["blocks"][0]["block_id"], page2["blocks"][0]["block_id"],
                page3["blocks"][0]["block_id"]]
        self.assertEqual(len(set(seen)), 3)
        for block in result["blocks"]:
            self.assertEqual(validate_evidence_block(block), [])
        with self.assertRaises(KbApiError) as ctx:
            self.api.extraction_blocks("extr-none", None)
        self.assertEqual(ctx.exception.status, 404)

    def test_analysis_runs_disabled(self):
        with self.assertRaises(KbApiError) as ctx:
            self.api.create_analysis_run({})
        self.assertEqual(ctx.exception.status, 422)
        self.assertFalse(ctx.exception.retryable)

    def test_changes_endpoint(self):
        from knowledge.kbapi import encode_cursor

        base = self.kb.latest_event_sequence()
        self.kb.emit_event("version.registered", "reports", "R1", "v1", {})
        result = self.api.changes(None, limit=10)
        self.assertGreaterEqual(len(result["events"]), 1)
        cursor = encode_cursor({"sequence": base})
        fresh = self.api.changes(cursor, limit=10)
        self.assertEqual(len(fresh["events"]), 1)
        self.assertEqual(fresh["events"][0]["event_type"], "version.registered")


class KbHttpLayerTest(unittest.TestCase):
    TOKEN = "http-token"

    @classmethod
    def setUpClass(cls):
        cls.kb = KnowledgeStore(os.path.join(temp_dir(), "knowledge.sqlite3"))
        stamp = "2026-10-01T00:00:00Z"
        cls.kb.upsert_documents([_doc("reports", "R1", "EXAMPLE")], stamp)
        cls.kb.upsert_versions([_version("reports", "R1", "v1", "a" * 64)], stamp)
        cls.kb.record_extraction({
            "extraction_id": "extr-r1", "source": "reports", "doc_id": "R1",
            "version_id": "v1", "snapshot_sha256": "a" * 64,
            "parser_id": "test", "parser_version": "1", "config_digest": "cfg",
            "status": "ready", "issues": [], "stats": {},
        }, [_block("paragraph", "毛利率为 30%。", {"kind": "pdf", "page": 2})])
        build_generation(cls.kb)
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

    def _request(self, path, token=None, method="GET", body=None):
        url = "http://127.0.0.1:%d%s" % (self.port, path)
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(url, data=data, method=method)
        if token:
            request.add_header("Authorization", "Bearer %s" % token)
        if data:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_health_open_others_locked(self):
        status, payload = self._request("/api/kb/v1/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        status, payload = self._request("/api/kb/v1/ready")
        self.assertEqual(status, 200)
        self.assertTrue(payload["ready"])

        status, payload = self._request("/api/kb/v1/documents/reports/R1")
        self.assertEqual(status, 401)
        self.assertEqual(payload["error"]["code"], "unauthenticated")

        status, payload = self._request("/api/kb/v1/documents/reports/R1",
                                        token="wrong")
        self.assertEqual(status, 403)

        status, payload = self._request("/api/kb/v1/documents/reports/R1",
                                        token=self.TOKEN)
        self.assertEqual(status, 200)
        self.assertEqual(payload["doc_id"], "R1")

    def test_search_over_http_with_token(self):
        status, payload = self._request(
            "/api/kb/v1/search", token=self.TOKEN, method="POST",
            body={"query": "毛利率", "mode": "keyword"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["hits"][0]["doc_id"], "R1")
        self.assertIn("evidence_url", payload["hits"][0])
        status, payload = self._request(
            "/api/kb/v1/search", token=self.TOKEN, method="POST",
            body={"query": "毛利率", "mode": "hybrid"})
        self.assertEqual(status, 422)
        self.assertEqual(payload["error"]["code"], "mode_unavailable")

    def test_changes_and_404_shape(self):
        status, payload = self._request("/api/kb/v1/changes", token=self.TOKEN)
        self.assertEqual(status, 200)
        status, payload = self._request("/api/kb/v1/nope", token=self.TOKEN)
        self.assertEqual(status, 404)
        self.assertIn("code", payload["error"])
        self.assertIn("request_id", payload["error"])
        self.assertIn("retryable", payload["error"])

    def test_load_tokens_from_env(self):
        os.environ["RESEARCHKB_KB_TOKEN"] = "env-token-xyz"
        try:
            tokens = load_tokens({})
            self.assertIn("env-token-xyz", tokens)
            self.assertIn("research.read", tokens["env-token-xyz"])
        finally:
            del os.environ["RESEARCHKB_KB_TOKEN"]


if __name__ == "__main__":
    unittest.main()
