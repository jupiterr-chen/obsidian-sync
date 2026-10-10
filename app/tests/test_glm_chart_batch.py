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
        fenced = {"model": "GLM-5.3-Flash", "stop_reason": "end_turn",
                  "usage": {"input_tokens": 77}, "content": [{"type": "text",
                  "text": '```json\n{"regions":[]}\n```'}]}
        status, classification, _, usage = parse_provider_response(fenced)
        self.assertEqual((status, classification, usage["input_tokens"]),
                         ("valid", {"regions": []}, 77))
        fenced_empty_language = {**fenced, "content": [{"type": "text",
            "text": '```\n{"regions":[]}\n```'}]}
        self.assertEqual(parse_provider_response(fenced_empty_language)[0], "valid")
        fenced_with_prose = {**fenced, "content": [{"type": "text",
            "text": 'Here is JSON:\n```json\n{"regions":[]}\n```'}]}
        self.assertEqual(parse_provider_response(fenced_with_prose)[0], "invalid_json_or_schema")

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

    def _write_legacy_dispatch(self, operation, runner, item, image, round_number,
                               result=None, raw=None, recipe="f" * 64):
        old_hash = runner._input_identity(item, image, round_number, recipe)
        cache = operation / "cache"
        cache.mkdir(parents=True, exist_ok=True)
        dispatch = {"input_hash": old_hash, "item_id": item["item_id"],
                    "round": round_number, "image_sha256": sha256_bytes(image),
                    "model": "GLM-5.3-Flash",
                    "endpoint": "https://open.bigmodel.cn/api/anthropic/v1/messages",
                    "recipe_hash": recipe, "at_unix": 1}
        save_json_once(cache / ("r%d-%s.dispatch.json" % (round_number, old_hash)), dispatch)
        result_path = cache / ("r%d-%s.json" % (round_number, old_hash))
        if result is not None:
            save_json_once(result_path, {"input_hash": old_hash, "recipe_hash": recipe,
                "round": round_number, **result})
        if raw is not None:
            save_json_once(operation / "raw-response.json", raw)
        return old_hash, result_path

    def test_resume_reuses_legacy_valid_and_fenced_raw_without_network(self):
        item = {"item_id": "resume-item", "text_hash": "text-hash", "text": "safe source",
                "source": "s", "doc_id": "d", "version_id": "v", "extraction_id": "e",
                "block_id": "b", "snapshot_sha256": "h", "page": 1,
                "source_category": "native"}
        image = b"same-rendered-page"
        old_op = self.root / "old-op"
        old = GLMChartRunner(self.root / "probe", transport=lambda _: _response(), source_digest="new")
        regions = [{"kind": "chart", "bbox": [0, 0, 0.5, 0.5],
                    "caption_hint": None, "uncertainty": None}]
        old_raw = {"model": "GLM-5.3-Flash", "stop_reason": "end_turn",
            "usage": {"input_tokens": 101, "output_tokens": 13},
            "content": [{"type": "text", "text": "```json\n" + json.dumps(
                {"regions": regions}, separators=(",", ":")) + "\n```"}]}
        output_hash = sha256_bytes(old_raw["content"][0]["text"].strip().encode())
        self._write_legacy_dispatch(old_op, old, item, image, 1,
            result={"status": "invalid_json_or_schema", "response_sha256": output_hash,
                    "usage": old_raw["usage"], "model": "GLM-5.3-Flash",
                    "stop_reason": "end_turn", "seconds": 1.25}, raw=old_raw)
        new_op = self.root / "new-op"
        calls = []
        runner = GLMChartRunner(new_op, transport=lambda payload: calls.append(payload) or self.fail("network"),
                                source_digest="new", resume_from=[old_op])
        runner.manifest_hash = "manifest-hash"
        result = runner._request(item, image, "image/png", 1)
        self.assertEqual(result["status"], "valid")
        self.assertEqual(result["usage"], old_raw["usage"])
        self.assertEqual(result["usage_provenance"], "reused_response")
        self.assertEqual(result["reuse_provenance"]["input_hash"],
                         read_json(old_op / "cache" / next(p.name for p in (old_op / "cache").glob("*.dispatch.json")))["input_hash"])
        self.assertFalse(calls)
        self.assertTrue((new_op / "responses" / (result["input_hash"] + ".json")).is_file())

    def test_resume_valid_cache_and_timeout_then_known_failure_retry_once(self):
        item = {"item_id": "resume-valid", "text_hash": "hash", "text": "safe",
                "source": "s", "doc_id": "d", "version_id": "v", "extraction_id": "e",
                "block_id": "b", "snapshot_sha256": "h", "page": 1,
                "source_category": "native"}
        image = b"page"
        old = GLMChartRunner(self.root / "hasher", transport=lambda _: _response(), source_digest="new")
        valid_op = self.root / "valid-old"
        raw = _response([{"kind": "table", "bbox": [0, 0, 1, 1],
                          "caption_hint": None, "uncertainty": None}])
        status, classification, response_hash, usage = __import__(
            "knowledge.chart_batch", fromlist=["parse_provider_response"]).parse_provider_response(raw)
        self.assertEqual(status, "valid")
        self._write_legacy_dispatch(valid_op, old, item, image, 2,
            result={"status": "valid", "classification": classification,
                "response_sha256": response_hash, "usage": usage, "model": raw["model"],
                "stop_reason": raw["stop_reason"], "seconds": 2.0})
        calls = []
        new = GLMChartRunner(self.root / "valid-new", transport=lambda p: calls.append(p),
                             source_digest="new", resume_from=[valid_op])
        new.manifest_hash = "manifest-hash"
        reused = new._request(item, image, "image/png", 2)
        self.assertEqual(reused["status"], "valid")
        self.assertEqual(reused["usage_provenance"], "reused_response")
        self.assertFalse(calls)

        unknown_op = self.root / "timeout-old"
        timeout_item = {**item, "item_id": "timeout-item"}
        self._write_legacy_dispatch(unknown_op, old, timeout_item, image, 1, result=None)
        attempted = []
        timeout_runner = GLMChartRunner(self.root / "timeout-new",
            transport=lambda p: attempted.append(p) or _response(), source_digest="new",
            resume_from=[unknown_op])
        timeout_runner.manifest_hash = "manifest-hash"
        self.assertEqual(timeout_runner._request(timeout_item, image, "image/png", 1)["status"],
                         "unknown_dispatch")
        self.assertFalse(attempted)

        invalid_op = self.root / "invalid-old"
        invalid_item = {**item, "item_id": "known-invalid"}
        invalid_raw = {"model": "GLM-5.3-Flash", "stop_reason": "max_tokens",
                       "usage": {"input_tokens": 9}, "content": [{"type": "text", "text": "cut"}]}
        invalid_hash = sha256_bytes(b"cut")
        self._write_legacy_dispatch(invalid_op, old, invalid_item, image, 1,
            result={"status": "truncated", "response_sha256": invalid_hash,
                    "usage": invalid_raw["usage"], "model": invalid_raw["model"],
                    "stop_reason": "max_tokens"}, raw=invalid_raw)
        attempts = []
        replacement = GLMChartRunner(self.root / "invalid-new",
            transport=lambda p: attempts.append(p) or _response(), source_digest="new",
            resume_from=[invalid_op])
        replacement.manifest_hash = "manifest-hash"
        self.assertEqual(replacement._request(invalid_item, image, "image/png", 1)["status"], "valid")
        self.assertEqual(replacement._request(invalid_item, image, "image/png", 1)["status"], "valid")
        self.assertEqual(len(attempts), 1)

    def test_resume_tampered_dispatch_or_bound_manifest_fails_before_transport(self):
        item = {"item_id": "tamper-item", "text_hash": "hash", "text": "safe",
                "source": "s", "doc_id": "d", "version_id": "v", "extraction_id": "e",
                "block_id": "b", "snapshot_sha256": "h", "page": 1,
                "source_category": "native"}
        image = b"same-page"
        old = GLMChartRunner(self.root / "hasher-tamper", transport=lambda _: _response(), source_digest="new")
        tampered = self.root / "tampered-old"
        self._write_legacy_dispatch(tampered, old, item, image, 1)
        dispatch_path = next((tampered / "cache").glob("*.dispatch.json"))
        marker = read_json(dispatch_path)
        marker["image_sha256"] = "0" * 64
        dispatch_path.write_text(json.dumps(marker), encoding="utf-8")
        called = []
        runner = GLMChartRunner(self.root / "tampered-new",
            transport=lambda p: called.append(p) or _response(), source_digest="new",
            resume_from=[tampered])
        runner.manifest_hash = "manifest-hash"
        with self.assertRaises(BatchError):
            runner._request(item, image, "image/png", 1)
        self.assertFalse(called)

        tampered_result = self.root / "tampered-result-old"
        old_hash, result_path = self._write_legacy_dispatch(
            tampered_result, old, item, image, 1,
            result={"status": "truncated", "response_sha256": "a" * 64,
                    "model": "GLM-5.3-Flash", "stop_reason": "max_tokens"})
        result_value = read_json(result_path)
        result_value["input_hash"] = "b" * 64
        result_path.write_text(json.dumps(result_value), encoding="utf-8")
        runner_result = GLMChartRunner(self.root / "tampered-result-new",
            transport=lambda p: called.append(p) or _response(), source_digest="new",
            resume_from=[tampered_result])
        runner_result.manifest_hash = "manifest-hash"
        with self.assertRaises(BatchError):
            runner_result._request(item, image, "image/png", 1)
        self.assertFalse(called)

        bound = self.root / "wrong-manifest-op"
        bound.mkdir()
        save_json_once(bound / "manifest-binding.json", {"manifest_sha256": "other-manifest"})
        runner2 = GLMChartRunner(self.root / "bound-new", transport=lambda _: self.fail("network"),
                                 source_digest="new", resume_from=[bound])
        runner2.manifest_hash = "manifest-hash"
        with self.assertRaises(BatchError):
            runner2._resume_item(item, image, 1)

    def test_resume_auth_or_wrong_model_keeps_circuit_open(self):
        item = {"item_id": "old-auth", "text_hash": "hash", "text": "safe",
                "source": "s", "doc_id": "d", "version_id": "v", "extraction_id": "e",
                "block_id": "b", "snapshot_sha256": "h", "page": 1,
                "source_category": "native"}
        image = b"page"
        hasher = GLMChartRunner(self.root / "auth-hasher", transport=lambda _: _response(), source_digest="new")
        old_op = self.root / "old-auth-op"
        self._write_legacy_dispatch(old_op, hasher, item, image, 1,
            result={"status": "provider_http_error", "http_status": 401})
        attempted = []
        runner = GLMChartRunner(self.root / "auth-resume-op",
            transport=lambda payload: attempted.append(payload) or _response(), source_digest="new",
            resume_from=[old_op])
        runner.manifest_hash = "manifest-hash"
        self.assertEqual(runner._request(item, image, "image/png", 1)["status"], "provider_http_error")
        another = {**item, "item_id": "another-item"}
        self.assertEqual(runner._request(another, image, "image/png", 1)["status"], "circuit_open")
        self.assertFalse(attempted)

        wrong_op = self.root / "old-wrong-model-op"
        wrong_item = {**item, "item_id": "old-wrong-model"}
        self._write_legacy_dispatch(wrong_op, hasher, wrong_item, image, 2,
            result={"status": "wrong_model", "model": "unexpected-model",
                    "stop_reason": "end_turn"})
        wrong_attempts = []
        wrong_runner = GLMChartRunner(self.root / "wrong-model-resume-op",
            transport=lambda payload: wrong_attempts.append(payload) or _response(), source_digest="new",
            resume_from=[wrong_op])
        wrong_runner.manifest_hash = "manifest-hash"
        self.assertEqual(wrong_runner._request(wrong_item, image, "image/png", 2)["status"], "wrong_model")
        self.assertTrue((wrong_runner.operation / "circuit-open.json").is_file())
        self.assertFalse(wrong_attempts)


if __name__ == "__main__":
    unittest.main()
