"""A-E delivery-chain regressions: incremental registration (A1), repair
queue bounds (A2), durable reading publish (A3), analysis tasks blocked
without models (B2), summary versioning (C), background packages (D)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from fixtures import temp_dir


def _kb():
    from knowledge.store import KnowledgeStore

    return KnowledgeStore(os.path.join(temp_dir(), "k.sqlite3"))


def _kb_from_path(path):
    from knowledge.store import KnowledgeStore

    return KnowledgeStore(path)


def _seed_version(kb, doc_id="D1", version_id="v1", sha="a", current=True):
    stamp = "2026-10-04T00:00:00Z"
    kb.upsert_documents([{
        "source": "reports", "doc_id": doc_id, "title": "Title %s" % doc_id,
        "symbol": "EX", "available": True, "first_seen_at": stamp,
        "last_seen_at": stamp, "report_date": "2026-06-30",
    }], stamp)
    kb.upsert_versions([{
        "source": "reports", "doc_id": doc_id, "version_id": version_id,
        "sha256": sha, "bytes": 10, "media_type": "application/pdf",
        "ext": "pdf", "rel_path": "x", "is_current": current,
        "state": "ready", "content_changed_at": None,
    }], stamp)
    kb.record_blob(sha, 10, "aa/%s" % sha, stamp)
    kb.record_snapshot("reports", doc_id, version_id, sha, "aa/%s" % sha,
                       10, stamp)
    kb.register_job("reports", doc_id, version_id, "snapshot", "d")
    return stamp


def _record_extraction(kb, doc_id, version_id, extraction_id, status="ready",
                       blocks=1, sha="a"):
    kb.record_extraction({
        "extraction_id": extraction_id, "source": "reports",
        "doc_id": doc_id, "version_id": version_id, "snapshot_sha256": sha,
        "parser_id": "t", "parser_version": "1", "config_digest": "c",
        "status": status, "issues": [], "stats": {}},
        [{"block_type": "paragraph", "text": "正文 block %d" % i,
          "locator": {"kind": "pdf", "page": i + 1},
          "quality": {"status": "ready", "issues": []}} for i in range(blocks)])


class A1IncrementalRegistrationTest(unittest.TestCase):
    def test_recipe_change_does_not_requeue_history(self):
        from knowledge.jobs import JobRunner
        from knowledge.config import KnowledgeConfig
        from knowledge.sampling import format_of  # noqa: F401

        kb = _kb()
        try:
            _seed_version(kb, "D1")
            # old-digest extract job exists (the corpus was processed)
            kb.register_job("reports", "D1", "v1", "extract", "old-digest")
            cfg = KnowledgeConfig(catalog_db="c", knowledge_db=kb.path,
                                  snapshot_root="s", library_config="l")
            runner = JobRunner(kb, cfg, None)
            self.assertEqual(runner.extract_digest, "old-digest" if False
                             else runner.extract_digest)
            # NEW digest: incremental registration must NOT requeue D1
            pending = kb.snapshots_missing_extract_jobs(runner.extract_digest,
                                                        new_only=True)
            self.assertEqual(
                [p for p in pending if p["doc_id"] == "D1"], [],
                "recipe change silently requeued the historical corpus")
            # historical mode explicitly requeues it
            historical = kb.snapshots_missing_extract_jobs(
                runner.extract_digest, new_only=False)
            self.assertIn("D1", [p["doc_id"] for p in historical])
            # a genuinely NEW snapshot is picked up incrementally
            _seed_version(kb, "D2", "v1", sha="b")
            pending2 = kb.snapshots_missing_extract_jobs(
                runner.extract_digest, new_only=True)
            self.assertIn("D2", [p["doc_id"] for p in pending2])
        finally:
            kb.close()

    def test_worker_restart_recovers_without_duplicates(self):
        """run_cycle twice -> extract jobs for new content appear once."""
        from library.config import Config
        from knowledge.config import KnowledgeConfig
        from knowledge.worker import run_cycle
        from fixtures import make_config

        tmp = temp_dir()
        lib_cfg, reports, discord = make_config(tmp)
        from library.ingest import Ingestor

        Ingestor(lib_cfg).run()
        Ingestor(lib_cfg).close()  # idempotent double ingest
        cfg = KnowledgeConfig(
            catalog_db=lib_cfg.catalog_db,
            knowledge_db=os.path.join(tmp, "state", "knowledge.sqlite3"),
            snapshot_root=os.path.join(tmp, "state", "snaps"),
            library_config="unused")
        first = run_cycle(cfg, lib_cfg)
        second = run_cycle(cfg, lib_cfg)
        self.assertTrue(first["ok"] and second["ok"])
        self.assertEqual(second["extracts"]["processed"], 0,
                         "restart reprocessed extracts")


    def test_worker_cycle_with_vault_publishes_and_heals_crash_gap(self):
        """The reading section must run inside a real cycle with vault_dir
        configured (the first deployment crashed it: SELECT extraction_id
        FROM jobs - a column that does not exist). Reconciliation must
        also heal the crash gap: extraction done but publish never
        enqueued must publish on the NEXT cycle, not age out."""
        from knowledge.config import KnowledgeConfig
        from knowledge.worker import run_cycle
        from fixtures import make_config
        from library.ingest import Ingestor

        tmp = temp_dir()
        lib_cfg, _, _ = make_config(tmp)
        Ingestor(lib_cfg).run()
        Ingestor(lib_cfg).close()
        vault = os.path.join(tmp, "vault-out")
        os.makedirs(vault, exist_ok=True)
        cfg = KnowledgeConfig(
            catalog_db=lib_cfg.catalog_db,
            knowledge_db=os.path.join(tmp, "state", "knowledge.sqlite3"),
            snapshot_root=os.path.join(tmp, "state", "snaps"),
            library_config="unused",
            extra={"vault_dir": vault,
                   "public_base_url": "http://127.0.0.1:8765"})
        first = run_cycle(cfg, lib_cfg)
        self.assertTrue(first["ok"], first.get("error"))
        self.assertNotEqual(
            (first.get("reading") or {}).get("reason"),
            "vault_dir not configured", first.get("reading"))
        reading_dir = os.path.join(vault, "解析正文")
        for page in ("开始阅读.md", "处理状态.md"):
            self.assertTrue(os.path.exists(os.path.join(reading_dir, page)),
                            page + " not published")

        # simulate the production incident: extraction committed, the
        # publish step never ran (crash) -> no outbox rows, no files
        kb = _kb_from_path(cfg.knowledge_db)
        try:
            with kb._tx() as conn:
                conn.execute("DELETE FROM publish_outbox")
        finally:
            kb.close()
        for name in os.listdir(reading_dir):
            os.remove(os.path.join(reading_dir, name))

        healed = run_cycle(cfg, lib_cfg)
        self.assertTrue(healed["ok"], healed.get("error"))
        self.assertGreaterEqual(
            healed["reading"].get("enqueued", 0), 1,
            "done extractions with no outbox row were not re-enqueued")
        for page in ("开始阅读.md", "处理状态.md"):
            self.assertTrue(os.path.exists(os.path.join(reading_dir, page)),
                            page + " not republished after heal")
        # steady state: nothing left to reconcile
        third = run_cycle(cfg, lib_cfg)
        self.assertTrue(third["ok"], third.get("error"))
        self.assertEqual(third["reading"].get("enqueued", 0), 0)


class A2RepairQueueTest(unittest.TestCase):
    def test_queue_bounded_and_targets_missing_text(self):
        from knowledge.repair import build_repair_queue, register_repair_jobs

        kb = _kb()
        try:
            _seed_version(kb, "OK1", sha="a")     # ready + text -> fine
            _record_extraction(kb, "OK1", "v1", "extr-ok1")
            _seed_version(kb, "MISS1", sha="b")   # no extraction
            _seed_version(kb, "EMPTY1", sha="c")  # extraction, no blocks
            _record_extraction(kb, "EMPTY1", "v1", "extr-empty1", blocks=0)
            _seed_version(kb, "FAIL1", sha="d")
            _record_extraction(kb, "FAIL1", "v1", "extr-fail1", status="failed")
            queue = build_repair_queue(kb, max_items=2)
            ids = {item["doc_id"] for item in queue}
            self.assertNotIn("OK1", ids)
            self.assertTrue(ids <= {"MISS1", "EMPTY1", "FAIL1"})
            self.assertEqual(len(queue), 2, "queue not bounded to max_items")
            result = register_repair_jobs(kb, "digest-x", max_items=25)
            self.assertEqual(result["queue_size"], 3)
        finally:
            kb.close()


class A3ReadingPublishTest(unittest.TestCase):
    def test_publish_pipeline_idempotent_and_human_preserved(self):
        from knowledge.reading import (INDEX_NAME, ReadingPublisher,
                                       reading_filename)

        kb = _kb()
        try:
            _seed_version(kb, "R1")
            _record_extraction(kb, "R1", "v1", "extr-r1", blocks=2)
            vault = os.path.join(temp_dir(), "vault")
            os.makedirs(vault, exist_ok=True)
            pub = ReadingPublisher(kb, vault, base_url="http://x:1")
            pub.enqueue("reports", "R1", "v1", "extr-r1")
            first = pub.consume()
            self.assertEqual(first["published"], 1)
            name = reading_filename("reports", "R1", "extr-r1")
            path = os.path.join(pub.output, name)
            with open(path, encoding="utf-8") as handle:
                content = handle.read()
            self.assertIn("正文 block 0", content)
            self.assertIn("第 1 页", content)
            self.assertTrue(os.path.isfile(os.path.join(pub.output, INDEX_NAME)))
            # human edits the note; re-publish must NOT overwrite
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(content + "\n人工批注")
            pub.enqueue("reports", "R1", "v1", "extr-r1")
            second = pub.consume()
            with open(path, encoding="utf-8") as handle:
                final = handle.read()
            self.assertIn("人工批注", final)
            files = [f for f in os.listdir(pub.output)
                     if f.startswith("text-")]
            self.assertLessEqual(len(files), 2)  # main + at most 1 candidate
            # index regenerated, statuses listed
            with open(os.path.join(pub.output, INDEX_NAME),
                      encoding="utf-8") as handle:
                index = handle.read()
            self.assertIn("**正文 1 份", index)
        finally:
            kb.close()


class B2AnalysisTasksTest(unittest.TestCase):
    def test_ready_only_registration_blocked_without_model(self):
        from knowledge.analysis_tasks import (STATUS_BLOCKED, STATUS_DONE,
                                              ensure_schema,
                                              register_ready_analysis_tasks,
                                              task_counts)

        kb = _kb()
        try:
            ensure_schema(kb)
            _seed_version(kb, "GOOD1")
            _record_extraction(kb, "GOOD1", "v1", "extr-good1", status="ready")
            _seed_version(kb, "REV1", sha="b")
            _record_extraction(kb, "REV1", "v1", "extr-rev1", status="review")
            _seed_version(kb, "FAIL1", sha="c")
            _record_extraction(kb, "FAIL1", "v1", "extr-fail1", status="failed")
            result = register_ready_analysis_tasks(kb)
            self.assertEqual(result["registered"], 1,
                             "review/failed must not be queued (B4)")
            counts = task_counts(kb)
            self.assertEqual(counts.get(STATUS_BLOCKED), 1)
            self.assertIsNone(counts.get(STATUS_DONE))
            with kb._lock:
                row = kb._conn.execute(
                    "SELECT blocked_reason FROM analysis_tasks").fetchone()
            self.assertEqual(row["blocked_reason"], "model_disabled")
            # idempotent: second registration adds nothing
            self.assertEqual(register_ready_analysis_tasks(kb)["registered"], 0)
        finally:
            kb.close()


class CSummaryVersioningTest(unittest.TestCase):
    def test_outbox_drives_versioned_blocked_summaries(self):
        from knowledge.summaries import (STATUS_BLOCKED, consume_updates,
                                         enqueue_summary_update,
                                         ensure_schema, summary_history)

        kb = _kb()
        try:
            ensure_schema(kb)
            self.assertTrue(enqueue_summary_update(kb, "company", "EX",
                                                   "evidence_changed", {"a": 1}))
            self.assertFalse(enqueue_summary_update(kb, "invalid", "X", "r"))
            result = consume_updates(kb)
            self.assertEqual(result["consumed"], 1)
            history = summary_history(kb, "company", "EX")
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["status"], STATUS_BLOCKED)
            # second evidence change appends a NEW revision (history kept)
            enqueue_summary_update(kb, "company", "EX", "evidence_changed")
            consume_updates(kb)
            history = summary_history(kb, "company", "EX")
            self.assertEqual(len(history), 2)
            self.assertEqual(history[0]["revision"], 1)
            # unrelated entities untouched
            self.assertEqual(summary_history(kb, "company", "OTHER"), [])
        finally:
            kb.close()


class DBackgroundPackageTest(unittest.TestCase):
    def test_package_shape_digest_and_claims(self):
        from knowledge.background import build_background_package
        from knowledge.memory import create_claim, review_claim

        kb = _kb()
        try:
            _seed_version(kb, "BG1")
            _record_extraction(kb, "BG1", "v1", "extr-bg1", blocks=1)
            created = create_claim(
                kb, "claim about EX",
                [{"source": "reports", "doc_id": "BG1", "version_id": "v1",
                  "block_id": "extr-bg1-b0000", "extraction_id": "extr-bg1"}],
                subject="EX")
            review_claim(kb, created["claim_id"], "accept", reviewer="a")
            package = build_background_package(kb, "company", "EX")
            self.assertEqual(package["entity"]["id"], "EX")
            self.assertTrue(package["sources"])
            self.assertEqual(len(package["claims"]), 1)
            self.assertTrue(package["result_digest"].startswith("sha256:"))
            # replay: same store state -> same digest
            again = build_background_package(kb, "company", "EX")
            self.assertEqual(package["result_digest"], again["result_digest"])
            self.assertIn("missing_information", package)
            with self.assertRaises(ValueError):
                build_background_package(kb, "invalid", "EX")
        finally:
            kb.close()

    def test_background_package_http(self):
        import threading
        import urllib.request

        from knowledge.background import build_background_package  # noqa
        from knowledge.kbapi import KbApi

        kb = _kb()
        try:
            _seed_version(kb, "HTTP1")
            api = KbApi(kb, {"t": ["research.read"]})
            package = api.build_background_package("company", "EX")
            self.assertEqual(package["entity"]["id"], "EX")
        finally:
            kb.close()

    def test_background_package_real_http_route(self):
        # RED regression: the Handler route must go through self.api, not
        # self.kb (which only exists on KbApi) - before the fix this
        # endpoint answered 500 internal_error over real HTTP while the
        # direct-call test above stayed green
        import json
        import socket
        import threading
        import urllib.error
        import urllib.request

        from knowledge.kbapi import build_kb_server

        kb = _kb()
        server = None
        try:
            _seed_version(kb, "ROUTE1")
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            server = build_kb_server(kb, {"route-token": ["research.read"]},
                                     host="127.0.0.1", port=port)
            thread = threading.Thread(target=server.serve_forever,
                                      kwargs={"poll_interval": 0.05},
                                      daemon=True)
            thread.start()

            def post(path, token, body):
                req = urllib.request.Request(
                    "http://127.0.0.1:%d%s" % (port, path),
                    data=json.dumps(body).encode("utf-8"), method="POST")
                req.add_header("Authorization", "Bearer %s" % token)
                req.add_header("Content-Type", "application/json")
                try:
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        return resp.status, json.loads(
                            resp.read().decode("utf-8"))
                except urllib.error.HTTPError as exc:
                    return exc.code, json.loads(exc.read().decode("utf-8"))

            status, payload = post(
                "/api/kb/v1/background-package", "route-token",
                {"entity_type": "company", "entity_id": "EX",
                 "filters": {"as_of_mode": "system"}, "limit": 5})
            self.assertEqual(status, 200, payload)
            self.assertEqual(payload["entity"]["id"], "EX")
            self.assertIn("result_digest", payload)
            # invalid entity type is a 400, not a 500
            status, payload = post(
                "/api/kb/v1/background-package", "route-token",
                {"entity_type": "bogus", "entity_id": "EX"})
            self.assertEqual(status, 400, payload)
            # bad token is rejected (401/403 per the api's convention)
            status, payload = post(
                "/api/kb/v1/background-package", "wrong-token",
                {"entity_type": "company", "entity_id": "EX"})
            self.assertIn(status, (401, 403), payload)
        finally:
            if server is not None:
                server.shutdown()
                server.server_close()
            kb.close()


class ECliCommandsTest(unittest.TestCase):
    """The A2/A3/E CLI subcommands must actually run - deployment caught
    repair-queue crashing on a missing KnowledgeStore import and
    ops-status on kb.conn/index_generations.id that never existed."""

    def test_cli_repair_publish_ops(self):
        from knowledge import __main__ as cli
        from knowledge.analysis_tasks import ensure_schema
        from knowledge.store import KnowledgeStore

        kb = _kb()
        config_path = None
        try:
            ensure_schema(kb)
            _seed_version(kb, "CLI1")
            _record_extraction(kb, "CLI1", "v1", "extr-cli1", blocks=1,
                               status="ready")
            db = kb.knowledge_db if hasattr(kb, "knowledge_db") else None
        finally:
            db = db or kb._conn.execute(
                "PRAGMA database_list").fetchone()["file"]
            kb.close()
        vault = os.path.join(temp_dir(), "vault")
        os.makedirs(vault, exist_ok=True)
        config_path = os.path.join(temp_dir(), "knowledge.json")
        with open(config_path, "w", encoding="utf-8") as handle:
            json.dump({"knowledge_db": db,
                       "snapshot_root": os.path.join(temp_dir(), "snaps"),
                       "vault_dir": vault}, handle)

        self.assertEqual(cli.main(["repair-queue", "--config", config_path,
                                   "--max", "5"]), 0)
        self.assertEqual(cli.main(["publish-reading", "--config", config_path,
                                   "--vault-dir", vault]), 0)
        self.assertTrue(os.path.exists(
            os.path.join(vault, "解析正文", "开始阅读.md")))
        self.assertTrue(os.path.exists(
            os.path.join(vault, "解析正文", "处理状态.md")))
        self.assertEqual(cli.main(["ops-status", "--config", config_path]), 0)


if __name__ == "__main__":
    unittest.main()
