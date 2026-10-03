"""RF4 regression tests (R09 filter-first hybrid, R11 fixed URLs + snapshot
serving, R12 complete pagination) - written RED first."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import unittest
import urllib.request

from fixtures import temp_dir


def _kb():
    from knowledge.store import KnowledgeStore

    return KnowledgeStore(os.path.join(temp_dir(), "knowledge.sqlite3"))


def _seed(kb, doc_id="R1", symbol="EXAMPLE", version="v1", n_blocks=1,
          text_prefix="毛利率 margin 600519"):
    from knowledge.indexing import build_generation

    stamp = "2026-10-01T00:00:00Z"
    kb.upsert_documents([{
        "source": "reports", "doc_id": doc_id, "title": doc_id,
        "symbol": symbol, "available": True, "first_seen_at": stamp,
        "last_seen_at": stamp, "report_date": "2026-06-30",
    }], stamp)
    kb.upsert_versions([{
        "source": "reports", "doc_id": doc_id, "version_id": version,
        "sha256": "a" * 64, "bytes": 100, "media_type": "application/pdf",
        "ext": "pdf", "rel_path": "x", "is_current": True, "state": "ready",
        "content_changed_at": None,
    }], stamp)
    blocks = [{
        "block_type": "paragraph",
        "text": "%s block %03d %s" % (text_prefix, i, "word%d" % i),
        "locator": {"kind": "pdf", "page": i + 1},
        "quality": {"status": "ready", "issues": []},
    } for i in range(n_blocks)]
    kb.record_extraction({
        "extraction_id": "extr-%s" % doc_id, "source": "reports",
        "doc_id": doc_id, "version_id": version, "snapshot_sha256": "a" * 64,
        "parser_id": "t", "parser_version": "1", "config_digest": "c",
        "status": "ready", "issues": [], "stats": {},
    }, blocks)
    build_generation(kb)
    return blocks


class R09HybridFilterFirstTest(unittest.TestCase):
    def test_zero_keyword_hits_with_filters_embeds_nothing(self):
        from knowledge.analysis import hybrid_search
        from knowledge.indexing import SearchFilters
        from knowledge.providers import MockEmbedder

        kb = _kb()
        try:
            _seed(kb)
            embedder = MockEmbedder(dimensions=16)
            result = hybrid_search(kb, "margin", embedder,
                                   SearchFilters(symbols=["NO_SUCH_SYMBOL"]))
            self.assertTrue(result["ok"])
            self.assertEqual(result["hits"], [])
            # R09: nothing may be embedded when the allowed set is empty
            self.assertEqual(embedder.calls if hasattr(embedder, "calls")
                             else 0, 0)
        finally:
            kb.close()

    def test_filters_apply_to_semantic_pool(self):
        from knowledge.analysis import hybrid_search
        from knowledge.indexing import SearchFilters
        from knowledge.providers import MockEmbedder

        kb = _kb()
        try:
            _seed(kb, doc_id="R1", symbol="EXAMPLE")
            _seed(kb, doc_id="R2", symbol="OTHER")
            embedder = MockEmbedder(dimensions=16)
            result = hybrid_search(kb, "zzz-no-keyword-match",
                                   embedder, SearchFilters(symbols=["OTHER"]))
            self.assertTrue(result["ok"])
            for hit in result["hits"]:
                self.assertEqual(hit["block"]["doc_id"], "R2")
            result_all = hybrid_search(kb, "zzz-no-keyword-match", embedder,
                                       SearchFilters(symbols=["EXAMPLE"]))
            for hit in result_all["hits"]:
                self.assertEqual(hit["block"]["doc_id"], "R1")
        finally:
            kb.close()

    def test_embedder_shape_validated(self):
        from knowledge.analysis import budgeted_embed
        from knowledge.providers import MockEmbedder

        class BrokenEmbedder(MockEmbedder):
            def embed(self, texts):
                vectors, usage = super().embed(texts[:1])  # wrong count
                return vectors, usage

        with self.assertRaises(ValueError):
            budgeted_embed(BrokenEmbedder(dimensions=8),
                           ["a", "b"], ledger=None, kb=_kb())


class R11FixedUrlsTest(unittest.TestCase):
    TOKEN = "t1"

    def _server(self, kb, snapshot_root="state/snapshots"):
        from knowledge.kbapi import build_kb_server

        server = build_kb_server(kb, {self.TOKEN: ["research.read"]},
                                 "127.0.0.1", 0, snapshot_root=snapshot_root)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server

    def _request(self, port, path, token=None, method="GET"):
        url = "http://127.0.0.1:%d%s" % (port, path)
        request = urllib.request.Request(url, method=method)
        if token:
            request.add_header("Authorization", "Bearer %s" % token)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def test_every_returned_url_round_trips(self):
        kb = _kb()
        try:
            blocks = _seed(kb, n_blocks=2)
            # bind a real snapshot so the byte endpoint has content
            import tempfile

            from knowledge.snapshot import SnapshotStore, snapshot_version

            store_root = os.path.join(temp_dir(), "blobs")
            blobs = SnapshotStore(store_root)
            payload = b"%PDF-1.4 real bytes for the fixed version"
            fd, path = tempfile.mkstemp(dir=os.path.dirname(store_root))
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
            with open(path, "rb") as handle:
                sha = snapshot_version(kb, blobs, handle, "reports", "R1",
                                       "v1",
                                       hashlib.sha256(payload).hexdigest(),
                                       len(payload))

            server = self._server(kb, snapshot_root=store_root)
            port = server.server_address[1]
            try:
                # 1) search hit URLs
                status, body = self._request(
                    port, "/api/kb/v1/search", self.TOKEN, "POST") \
                    if False else (200, b"{}")
                # POST search via transport
                import urllib.request as ur

                req = ur.Request(
                    "http://127.0.0.1:%d/api/kb/v1/search" % port,
                    data=json.dumps({"query": "毛利率"}).encode(),
                    method="POST",
                    headers={"Authorization": "Bearer %s" % self.TOKEN,
                             "Content-Type": "application/json"})
                with ur.urlopen(req, timeout=10) as response:
                    search_payload = json.loads(response.read())
                hit = search_payload["hits"][0]
                # version URL (R11: this 404'd before the route fix)
                version_path = hit["source_version_url"]
                status, _ = self._request(port, version_path, self.TOKEN)
                self.assertEqual(status, 200, version_path)
                version_detail = self._request(
                    port, version_path, self.TOKEN)[1]
                detail = json.loads(version_detail)
                snapshot_url = detail["version"].get("snapshot_url")
                self.assertIsNotNone(snapshot_url, "version detail must link"
                                     " the fixed snapshot")
                status, blob = self._request(port, snapshot_url, self.TOKEN)
                self.assertEqual(status, 200)
                self.assertEqual(hashlib.sha256(blob).hexdigest(), sha)
                # 2) evidence URL
                status, _ = self._request(port, hit["evidence_url"], self.TOKEN)
                self.assertEqual(status, 200)
                # 3) auth required on the snapshot bytes
                status, _ = self._request(port, snapshot_url, None)
                self.assertEqual(status, 401)
                # 4) unknown snapshot -> 404
                status, _ = self._request(
                    port, "/api/kb/v1/snapshots/reports/R1/vX", self.TOKEN)
                self.assertEqual(status, 404)
            finally:
                server.shutdown()
                server.server_close()
        finally:
            kb.close()

    def test_corrupted_snapshot_refused(self):
        kb = _kb()
        try:
            _seed(kb)
            import tempfile

            from knowledge.snapshot import SnapshotStore, snapshot_version

            store_root = os.path.join(temp_dir(), "blobs2")
            blobs = SnapshotStore(store_root)
            payload = b"%PDF-1.4 original content bytes"
            fd, path = tempfile.mkstemp(dir=os.path.dirname(store_root))
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
            with open(path, "rb") as handle:
                sha = snapshot_version(kb, blobs, handle, "reports", "R1",
                                       "v1",
                                       hashlib.sha256(payload).hexdigest(),
                                       len(payload))
            snap = kb.get_snapshot("reports", "R1", "v1")
            blob_path = os.path.join(store_root,
                                     *snap["store_path"].split("/"))
            with open(blob_path, "r+b") as handle:  # corrupt after sealing
                handle.write(b"XXXX")
            from knowledge.kbapi import KbApi, KbApiError

            api = KbApi(kb, {self.TOKEN: ["research.read"]})
            with self.assertRaises(KbApiError) as ctx:
                api.snapshot_bytes("reports", "R1", "v1")
            self.assertIn(ctx.exception.status, (409, 410, 404))
        finally:
            kb.close()


class R12PaginationTest(unittest.TestCase):
    def _traverse(self, api, limit):
        seen = []
        cursor = None
        while True:
            result = api.do_search({"query": "毛利率", "limit": limit,
                                    "cursor": cursor})
            for hit in result["hits"]:
                seen.append(hit["block_id"])
            cursor = result["next_cursor"]
            if cursor is None:
                return seen

    def test_full_traversal_no_dup_no_miss(self):
        from knowledge.kbapi import KbApi

        kb = _kb()
        try:
            _seed(kb, n_blocks=250)
            api = KbApi(kb, {"t": ["research.read"]})
            for limit in (1, 2, 20, 100):
                seen = self._traverse(api, limit)
                self.assertEqual(len(seen), 250,
                                 "limit=%d lost/duplicated rows" % limit)
                self.assertEqual(len(set(seen)), 250)
        finally:
            kb.close()

    def test_cursor_binds_mode_and_rejects_garbage(self):
        from knowledge.kbapi import KbApi, KbApiError

        kb = _kb()
        try:
            _seed(kb, n_blocks=5)
            api = KbApi(kb, {"t": ["research.read"]})
            first = api.do_search({"query": "毛利率", "limit": 2})
            with self.assertRaises(KbApiError) as ctx:
                api.do_search({"query": "毛利率", "mode": "hybrid",
                               "cursor": first["next_cursor"]})
            self.assertEqual(ctx.exception.status, 409)
            with self.assertRaises(KbApiError) as ctx:
                api.do_search({"query": "毛利率", "cursor": "!!!not-base64"})
            self.assertEqual(ctx.exception.status, 400)
        finally:
            kb.close()


if __name__ == "__main__":
    unittest.main()
