"""Deterministic offline counterexamples for GLM chart batching."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from knowledge.chart_batch import (
    BatchError, GLMChartRunner, _make_pilot, compare_rounds, freeze_candidates,
    parse_provider_response, read_json, save_json_once, sha256_bytes,
    render_frozen_page, validate_regions,
)
from knowledge.store import KnowledgeStore
from test_knowledge_analysis import _block, _doc, _version


def _response(regions=None, model="GLM-5.3-Flash", stop="end_turn"):
    return {"model": model, "stop_reason": stop, "usage": {"input_tokens": 5},
            "content": [{"type": "text", "text": json.dumps(
                {"regions": regions or []}, separators=(",", ":"))}]}


class ChartBatchTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="glm-chart-batch-"))
        self.op = self.root / "operation"
        self.snapshot_root = self.root / "snapshots"
        self.snapshot_root.mkdir()

    def tearDown(self):
        # Runtime fixtures are intentionally retained; this test never recursively deletes paths.
        pass

    def test_strict_regions_model_and_truncation(self):
        good = [{"kind": "chart", "bbox": [0, 0, 1, 1],
                 "caption_hint": None, "uncertainty": "unclear"}]
        self.assertEqual(len(validate_regions({"regions": good})), 1)
        for invalid in (
            {"regions": [{**good[0], "bbox": [0, 0, 2, 1]}]},
            {"regions": [{**good[0], "extra": "exfiltrate"}]},
            {"regions": [{**good[0], "kind": "confirmed"}]},
        ):
            with self.assertRaises(BatchError):
                validate_regions(invalid)
        self.assertEqual(parse_provider_response(_response(model="other"))[0], "wrong_model")
        self.assertEqual(parse_provider_response(_response(stop="max_tokens"))[0], "truncated")
        raw = {"model": "GLM-5.3-Flash", "stop_reason": "end_turn",
               "content": [{"type": "text", "text": "not-json"}]}
        status, _, output_hash, _ = parse_provider_response(raw)
        self.assertEqual(status, "invalid_json_or_schema")
        self.assertEqual(output_hash, sha256_bytes(b"not-json"))

    def test_stratified_pilot_keeps_single_image_with_render_page_one(self):
        items = []
        for category in ("native", "ocr", "unknown"):
            for index in range(12):
                image = category == "unknown" and index == 0
                items.append({"item_id": "%s-%d" % (category, index),
                    "source": "s", "doc_id": "%s-%d" % (category, index),
                    "source_category": category, "media_type": "image/png" if image else "application/pdf",
                    "ext": "png" if image else "pdf", "page": 1,
                    "source_page": None if image else 1})
        pilot = _make_pilot(items, 17, 10)
        self.assertEqual(pilot["actual_by_source"], {"native": 10, "ocr": 10, "unknown": 10})
        selected = {item["item_id"]: item for item in pilot["items"]}
        self.assertIn("unknown-0", selected)
        self.assertEqual(len(selected), 30)
        image = b"single image source bytes"
        image_path = self.snapshot_root / "image.bin"
        image_path.write_bytes(image)
        rendered, media = render_frozen_page({"store_path": "image.bin",
            "snapshot_sha256": sha256_bytes(image), "media_type": "image/png",
            "ext": "png", "page": 1}, self.snapshot_root)
        self.assertEqual((rendered, media), (image, "image/png"))

    def test_freeze_preserves_raw_unicode_and_tracks_skips_without_db_writes(self):
        db = self.root / "knowledge.sqlite3"
        kb = KnowledgeStore(str(db))
        raw = "原文\r\n第二行\u2028第三行"
        snapshot = b"immutable snapshot bytes"
        snapshot_hash = sha256_bytes(snapshot)
        store_path = "blob.bin"
        (self.snapshot_root / store_path).write_bytes(snapshot)
        stamp = "2026-10-10T00:00:00Z"
        kb.upsert_documents([_doc("src", "doc")], stamp)
        kb.upsert_versions([_version("src", "doc", "v1", snapshot_hash)], stamp)
        kb.record_extraction({"extraction_id": "e1", "source": "src", "doc_id": "doc",
            "version_id": "v1", "snapshot_sha256": snapshot_hash, "parser_id": "test",
            "parser_version": "1", "config_digest": "cfg", "status": "ready",
            "issues": [], "stats": {"page_ocr_status": ["text_layer"]}},
            [_block("paragraph", raw, {"page": 1})])
        with kb._tx() as conn:
            conn.execute("UPDATE kb_versions SET bytes=? WHERE source='src' AND doc_id='doc' AND version_id='v1'",
                         (len(snapshot),))
            conn.execute("INSERT INTO snapshots VALUES(?,?,?,?,?,?,?,?)",
                         ("src", "doc", "v1", snapshot_hash, store_path, len(snapshot), stamp, "verified"))
            conn.execute("INSERT INTO snapshot_blobs VALUES(?,?,?,?)",
                         (snapshot_hash, len(snapshot), store_path, stamp))
            # Schema 3 is required by freeze and must never be upgraded there.
            conn.execute("PRAGMA user_version=3")
        block = kb.get_blocks("e1")[0]
        audit = self.root / "audit.json"
        audit.write_text(json.dumps({"schema": "chart-release-audit/1", "dry_run": True,
            "db": {"active_generation": None, "candidate_groups": [],
                   "unconfirmed_candidates": [
                       {"block_id": block["block_id"], "extraction_id": "e1",
                        "source": "src", "doc_id": "doc", "version_id": "v1",
                        "page": 1, "text_hash": sha256_bytes(raw.encode()), "signals": {}},
                       {"block_id": "missing", "extraction_id": "e1", "source": "src",
                        "doc_id": "doc", "version_id": "v1", "page": 1,
                        "text_hash": "0" * 64, "signals": {}}]}}), encoding="utf-8")
        kb._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        before = hashlib.sha256(db.read_bytes()).hexdigest()
        readonly = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
        readonly.row_factory = sqlite3.Row
        readonly.execute("PRAGMA query_only=ON")
        self.assertEqual(readonly.execute("PRAGMA query_only").fetchone()[0], 1)
        summary = freeze_candidates(readonly, audit, self.snapshot_root,
                                    self.op, seed=3, per_source=1)
        readonly.close()
        manifest = read_json(Path(summary["manifest"]))
        self.assertEqual(manifest["items"][0]["text"], raw)
        self.assertEqual(manifest["skipped"][0]["reason"], "block_missing")
        self.assertEqual(before, hashlib.sha256(db.read_bytes()).hexdigest())
        with self.assertRaises(BatchError):
            save_json_once(Path(summary["manifest"]), {"different": True})
        kb.close()

    def test_two_rounds_are_isolated_and_cached_duplicate_dispatch(self):
        calls = []
        lock = threading.Lock()
        def transport(payload):
            with lock:
                calls.append(payload)
                ordinal = len(calls)
            return _response([{"kind": "chart", "bbox": [0, 0, 1, 1],
                               "caption_hint": "ROUND_ONE_SECRET_MARKER" if ordinal == 1 else None,
                               "uncertainty": None}])
        runner = GLMChartRunner(self.op, transport=transport, workers=4, source_digest="a")
        item = {"item_id": "stable", "text_hash": "t", "text": "source words",
                "source": "s", "doc_id": "d", "version_id": "v", "extraction_id": "e",
                "block_id": "b", "snapshot_sha256": "h", "page": 1,
                "source_category": "native"}
        first = runner._request(item, b"same page", "image/png", 1)
        second = runner._request(item, b"same page", "image/png", 2)
        self.assertEqual(first["status"], "valid")
        self.assertEqual(second["status"], "valid")
        self.assertEqual(len(calls), 2)
        self.assertNotIn("ROUND_ONE_SECRET_MARKER", calls[1]["messages"][0]["content"][1]["text"])
        restarted = GLMChartRunner(self.op, transport=lambda _p: self.fail("cache miss"),
                                   source_digest="a")
        self.assertEqual(restarted._request(item, b"same page", "image/png", 1), first)
        self.assertEqual(compare_rounds(first, second), "agreement")
        changed_recipe = GLMChartRunner(self.op, transport=lambda _p: _response(), source_digest="b")
        self.assertNotEqual(changed_recipe.recipe, runner.recipe)

    def test_unknown_dispatch_never_retries_and_auth_limit_stops_new_dispatch(self):
        item = {"item_id": "one", "text_hash": "t", "text": "safe",
                "source": "s", "doc_id": "d", "version_id": "v", "extraction_id": "e",
                "block_id": "b", "snapshot_sha256": "h", "page": 1,
                "source_category": "unknown"}
        calls = []
        def fail(_payload):
            calls.append(1)
            raise TimeoutError()
        runner = GLMChartRunner(self.op, transport=fail, source_digest="x")
        result = runner._request(item, b"page", "image/png", 1)
        self.assertEqual(result["status"], "unknown_dispatch")
        again = GLMChartRunner(self.op, transport=lambda _p: self.fail("must not retry"), source_digest="x")
        self.assertEqual(again._request(item, b"page", "image/png", 1)["status"], "unknown_dispatch")
        self.assertEqual(len(calls), 1)

        class AuthError(Exception):
            code = 403
        import urllib.error
        http_error = urllib.error.HTTPError("https://fixed.invalid", 403, "forbidden", {}, None)
        auth_op = self.root / "auth-op"
        attempted = []
        def forbidden(_payload):
            attempted.append(1)
            raise http_error
        auth_runner = GLMChartRunner(auth_op, transport=forbidden, source_digest="auth")
        self.assertEqual(auth_runner._request(item, b"page", "image/png", 1)["status"], "provider_http_error")
        other = {**item, "item_id": "different"}
        self.assertEqual(auth_runner._request(other, b"page", "image/png", 1)["status"], "circuit_open")
        self.assertEqual(len(attempted), 1)


if __name__ == "__main__":
    unittest.main()
