"""F0 bug-fix regressions (V01-V04 + CLI snapshot_root) - RED first.

Each class reproduces a fifth-review counterexample against the REAL
entrypoints (provider classes, export functions, CLI main), including
old-database upgrades, restarts and the create-file-before-manifest
interruption window.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import unittest
from unittest.mock import patch

from fixtures import temp_dir

from test_third_review import build_old_database

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")


def _kb():
    from knowledge.store import KnowledgeStore

    return KnowledgeStore(os.path.join(temp_dir(), "k.sqlite3"))


# ================================================================== V01
class V01SuccessRequestsCountedTest(unittest.TestCase):
    """Successful physical requests must persist exactly one request count
    each (the fifth review: three entrypoints with cap=1 allowed two
    successful calls, totals['requests']==0)."""

    def _ok_provider(self, cls, response, **kwargs):
        class OK(cls):
            attempts = 0

            def _transport(self, url, body):
                OK.attempts += 1
                return response

        return OK(**kwargs), OK

    def test_embedding_success_counts_requests(self):
        from knowledge.analysis import budgeted_embed
        from knowledge.budget import Budget, BudgetLedger
        from knowledge.providers import OpenAICompatibleEmbedding

        embedder, cls = self._ok_provider(
            OpenAICompatibleEmbedding,
            {"data": [{"index": 0, "embedding": [0.5, 0.5]}],
             "usage": {"prompt_tokens": 5}},
            name="e", model="m", base_url="https://x.invalid",
            api_key="k", egress_allowed=True, dimensions=2, max_retries=0)
        kb = _kb()
        try:
            ledger = BudgetLedger(kb, Budget(max_requests_total=1))
            budgeted_embed(embedder, ["hello"], ledger=ledger, kb=kb)
            with self.assertRaises(Exception):
                budgeted_embed(embedder, ["again"], ledger=ledger, kb=kb)
            self.assertEqual(cls.attempts, 1)
            totals = ledger._totals()
            self.assertEqual(totals["requests"], 1,
                             "successful request not counted: %r" % totals)
            # restart (new ledger over the same store): cap still binds
            ledger2 = BudgetLedger(kb, Budget(max_requests_total=1))
            self.assertGreaterEqual(ledger2._totals()["requests"], 1)
        finally:
            kb.close()

    def test_chat_success_counts_requests_via_analysis_run(self):
        from knowledge.analysis import execute_analysis_run
        from knowledge.budget import Budget, BudgetLedger
        from knowledge.indexing import build_generation, search
        from knowledge.providers import OpenAICompatibleChat

        kb = _kb()
        try:
            stamp = "2026-10-01T00:00:00Z"
            kb.upsert_documents([{
                "source": "reports", "doc_id": "R1", "title": "R1",
                "available": True, "first_seen_at": stamp,
                "last_seen_at": stamp,
            }], stamp)
            kb.upsert_versions([{
                "source": "reports", "doc_id": "R1", "version_id": "v1",
                "sha256": "a" * 64, "bytes": 10,
                "media_type": "application/pdf", "ext": "pdf",
                "rel_path": "x", "is_current": True, "state": "ready",
                "content_changed_at": None,
            }], stamp)
            kb.record_extraction({
                "extraction_id": "extr-r1", "source": "reports",
                "doc_id": "R1", "version_id": "v1",
                "snapshot_sha256": "a" * 64, "parser_id": "t",
                "parser_version": "1", "config_digest": "c",
                "status": "ready", "issues": [], "stats": {}},
                [{"block_type": "paragraph", "text": "margin text",
                  "locator": {"kind": "pdf", "page": 1},
                  "quality": {"status": "ready", "issues": []}}])
            build_generation(kb)
            chat, cls = self._ok_provider(
                OpenAICompatibleChat,
                {"choices": [{"message": {"content": "结论 [1]"}}],
                 "usage": {"prompt_tokens": 5, "completion_tokens": 2}},
                name="c", model="m", base_url="https://x.invalid",
                api_key="k", egress_allowed=True, max_retries=0)
            ledger = BudgetLedger(kb, Budget(max_requests_total=1))
            created = kb.create_analysis_run("margin")
            outcome = execute_analysis_run(
                kb, created["run_id"], "margin", chat,
                retriever=lambda q, k: search(kb, q, None, limit=k).get(
                    "hits", []),
                ledger=ledger)
            self.assertEqual(outcome["status"], "done")
            import time

            time.sleep(1.1)  # create_analysis_run hashes utc_now (second
            # resolution); same-second reruns deduplicate by design
            second = kb.create_analysis_run("margin")
            outcome2 = execute_analysis_run(
                kb, second["run_id"], "margin", chat,
                retriever=lambda q, k: search(kb, q, None, limit=k).get(
                    "hits", []),
                ledger=ledger)
            self.assertEqual(outcome2["status"], "failed")
            self.assertEqual(cls.attempts, 1,
                             "second successful call escaped cap=1")
            self.assertEqual(ledger._totals()["requests"], 1)
        finally:
            kb.close()

    def test_vision_success_counts_requests(self):
        from knowledge.budget import Budget, BudgetLedger
        from knowledge.ocr import VisionApiOcr
        from knowledge.providers import OpenAICompatibleVision, Usage

        class OKVision(OpenAICompatibleVision):
            attempts = 0

            def _transport(self, url, body):
                OKVision.attempts += 1
                return {"choices": [{"message": {"content": "ocr text"}}],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 1}}

        vision = OKVision(name="v", model="m", base_url="https://x.invalid",
                          api_key="k", egress_allowed=True, max_retries=0)
        kb = _kb()
        try:
            ledger = BudgetLedger(kb, Budget(max_requests_total=1,
                                             max_input_tokens_per_page=100,
                                             max_total_input_tokens=10_000))
            engine = VisionApiOcr(chat_provider=vision, ledger=ledger,
                                  page_token_cap=50)
            engine.run(b"PNG")
            with self.assertRaises(Exception):
                engine.run(b"PNG2")
            self.assertEqual(OKVision.attempts, 1)
            self.assertEqual(ledger._totals()["requests"], 1)
        finally:
            kb.close()

    def test_bad_response_shape_still_counts_the_request(self):
        """Response unparseable (no usage, malformed body): the request
        WENT OUT - it must count, not silently release to zero."""
        from knowledge.analysis import budgeted_embed
        from knowledge.budget import Budget, BudgetLedger
        from knowledge.providers import OpenAICompatibleEmbedding

        class Garbage(OpenAICompatibleEmbedding):
            def _transport(self, url, body):
                raise ValueError("malformed response body")

        embedder = Garbage(name="g", model="m", base_url="https://x.invalid",
                           api_key="k", egress_allowed=True, dimensions=2,
                           max_retries=0)
        kb = _kb()
        try:
            ledger = BudgetLedger(kb, Budget(max_requests_total=1))
            try:
                budgeted_embed(embedder, ["x"], ledger=ledger, kb=kb)
            except ValueError:
                pass
            totals = ledger._totals()
            self.assertGreaterEqual(totals["requests"], 1,
                                    "dispatched-but-garbage request not"
                                    " counted: %r" % totals)
        finally:
            kb.close()

    def test_upgraded_old_db_request_cap_persists(self):
        from knowledge.budget import Budget, BudgetLedger
        from knowledge.providers import Usage
        from knowledge.store import KnowledgeStore

        path = os.path.join(temp_dir(), "old-cap.sqlite3")
        build_old_database(path)
        store = KnowledgeStore(path)
        try:
            ledger = BudgetLedger(store, Budget(max_requests_total=2))
            # legacy row already counts as 1 request
            self.assertEqual(ledger._totals()["requests"], 1)
            rid = ledger.reserve("chat", 5)
            ledger.settle(rid, Usage("p", "m", 5, 0, "t"))
            self.assertEqual(ledger._totals()["requests"], 2)
            with self.assertRaises(Exception):
                ledger.reserve("chat", 1)  # cap reached
        finally:
            store.close()


# ================================================================== V02
class V02ShadowVerificationTest(unittest.TestCase):
    def test_runner_rejects_manifest_without_sha(self):
        manifest = os.path.join(temp_dir(), "no-sha.json")
        with open(manifest, "w", encoding="utf-8") as handle:
            json.dump({"samples": [{"source": "reports", "doc_id": "X",
                                    "version_id": "v1", "sha256": "",
                                    "split": "tune", "stratum": "s"}]},
                      handle)
        cfg = os.path.join(temp_dir(), "cfg.json")
        state = os.path.join(temp_dir(), "state")
        os.makedirs(state, exist_ok=True)
        with open(cfg, "w", encoding="utf-8") as handle:
            json.dump({"knowledge_db": os.path.join(state, "k.sqlite3"),
                       "snapshot_root": os.path.join(state, "snaps")},
                      handle)
        import subprocess

        result = subprocess.run(
            [sys.executable,
             os.path.join(REPO, "tools", "shadow-acceptance",
                          "shadow_run.py"),
             "--config", cfg, "--manifest", manifest,
             "--state-dir", state, "--dry-run"],
            capture_output=True, text=True, timeout=120, cwd=REPO,
            env={**os.environ, "PYTHONPATH": "app"})
        self.assertNotEqual(result.returncode, 0,
                            "empty sha256 accepted: %s" % result.stdout)
        self.assertIn("sha256", (result.stdout + result.stderr).lower())

    def test_reconcile_readonly_and_strict(self):
        """reconcile must (a) never create a database, (b) fail when the
        blob is missing/hash-mismatched/recipe-mismatched, (c) exit
        non-zero on any problem or insufficient data."""
        import subprocess

        state = os.path.join(temp_dir(), "ro-state")
        manifest = os.path.join(temp_dir(), "ro-manifest.json")
        with open(manifest, "w", encoding="utf-8") as handle:
            json.dump({"samples": [
                {"source": "reports", "doc_id": "D1", "version_id": "v1",
                 "sha256": "a" * 64, "split": "tune", "stratum": "s",
                 "expected_extraction_digest": "deadbeef"}]},
                handle)
        result = subprocess.run(
            [sys.executable,
             os.path.join(REPO, "tools", "shadow-acceptance",
                          "shadow_reconcile.py"),
             "--manifest", manifest, "--state-dir", state],
            capture_output=True, text=True, timeout=120, cwd=REPO,
            env={**os.environ, "PYTHONPATH": "app"})
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(os.path.exists(
            os.path.join(state, "knowledge.sqlite3")),
            "reconcile created a database (must be read-only)")


# ================================================================== V03
class V03MisboundTimeRepairTest(unittest.TestCase):
    def _build_misbound(self, path):
        """A store in the POST-MISBINDING state: v2 has public_available_at
        = the v1-era document date (the pre-U03 bug) with first_observed
        still NULL."""
        from knowledge.store import KnowledgeStore

        store = KnowledgeStore(path)
        stamp = "2026-10-04T00:00:00Z"
        store.upsert_documents([{
            "source": "reports", "doc_id": "D", "title": "D",
            "available": True, "first_seen_at": "2026-01-01T00:00:00Z",
            "last_seen_at": stamp,
            "published_at": "2026-01-01T00:00:00Z",
        }], stamp)
        # insert directly to simulate the pre-fix misbinding
        with store._tx() as conn:
            conn.execute(
                "INSERT INTO kb_versions (source, doc_id, version_id,"
                " sha256, bytes, media_type, ext, rel_path, is_current,"
                " state, content_changed_at, synced_at, first_observed_at,"
                " public_available_at, public_time_basis)"
                " VALUES ('reports','D','v2','b',10,'application/pdf',"
                "'pdf','x',1,'ready',NULL,?,NULL,"
                " '2026-01-01T00:00:00Z','published_at')", (stamp,))
        return store

    def test_audit_finds_misbound_rows(self):
        from knowledge.time_audit import audit_public_times

        path = os.path.join(temp_dir(), "misbound.sqlite3")
        store = self._build_misbound(path)
        store.close()
        report = audit_public_times(path)
        self.assertEqual(report["suspect_rows"], 1)
        self.assertEqual(report["rows"][0]["version_id"], "v2")
        self.assertIsNone(report["rows"][0]["first_observed_at"])
        self.assertIsNotNone(report["rows"][0]["public_available_at"])

    def test_repair_is_idempotent_and_restores_unknown(self):
        from knowledge.indexing import build_generation, search, SearchFilters
        from knowledge.time_audit import audit_public_times, repair_public_times

        path = os.path.join(temp_dir(), "misbound2.sqlite3")
        store = self._build_misbound(path)
        stamp = "2026-10-04T00:00:00Z"
        store.record_extraction({
            "extraction_id": "extr-v2", "source": "reports",
            "doc_id": "D", "version_id": "v2", "snapshot_sha256": "b",
            "parser_id": "t", "parser_version": "1", "config_digest": "c",
            "status": "ready", "issues": [], "stats": {}},
            [{"block_type": "paragraph", "text": "august revision needle",
              "locator": {"kind": "pdf", "page": 1},
              "quality": {"status": "ready", "issues": []}}])
        build_generation(store)
        july = search(store, "needle", SearchFilters(
            as_of="2026-07-01T00:00:00Z", as_of_mode="public"))
        self.assertEqual(len(july["hits"]), 1,
                         "pre-repair leak not reproduced")
        store.close()

        result = repair_public_times(path, apply=True)
        self.assertEqual(result["repaired"], 1)
        # repair preserves the prior value + reason + evidence in an audit row
        store2 = __import__("knowledge.store",
                            fromlist=["KnowledgeStore"]).KnowledgeStore(path)
        try:
            version = store2.get_version("reports", "D", "v2")
            self.assertIsNone(version["public_available_at"])
            self.assertEqual(version["public_time_basis"], "unknown")
            with store2._lock:
                audit = [dict(r) for r in store2._conn.execute(
                    "SELECT * FROM public_time_corrections")]
            self.assertEqual(len(audit), 1)
            self.assertEqual(audit[0]["old_available_at"],
                             "2026-01-01T00:00:00Z")
            self.assertIn("misbound", audit[0]["reason"])
            build_generation(store2)
            july2 = search(store2, "needle", SearchFilters(
                as_of="2026-07-01T00:00:00Z", as_of_mode="public"))
            self.assertEqual(july2["hits"], [])
        finally:
            store2.close()
        # idempotent second run repairs nothing new
        result2 = repair_public_times(path, apply=True)
        self.assertEqual(result2["repaired"], 0)

    def test_explicit_version_evidence_survives_repair(self):
        """Rows with genuine version-scoped evidence must NOT be cleared."""
        from knowledge.time_audit import audit_public_times, repair_public_times
        from knowledge.store import KnowledgeStore

        path = os.path.join(temp_dir(), "explicit.sqlite3")
        store = KnowledgeStore(path)
        stamp = "2026-10-04T00:00:00Z"
        store.upsert_documents([{
            "source": "reports", "doc_id": "E", "title": "E",
            "available": True, "first_seen_at": "2026-01-01T00:00:00Z",
            "last_seen_at": stamp,
        }], stamp)
        with store._tx() as conn:
            conn.execute(
                "INSERT INTO kb_versions (source, doc_id, version_id,"
                " sha256, bytes, media_type, ext, rel_path, is_current,"
                " state, content_changed_at, synced_at, first_observed_at,"
                " public_available_at, public_time_basis)"
                " VALUES ('reports','E','v1','c',10,'application/pdf',"
                "'pdf','x',1,'ready',NULL,?,"
                " '2026-01-02T00:00:00Z','2026-01-03T00:00:00Z',"
                " 'explicit_filing')", (stamp,))
        store.close()
        report = audit_public_times(path)
        self.assertEqual(report["suspect_rows"], 0,
                           "explicit evidence flagged: %r" % report["rows"])
        result = repair_public_times(path, apply=True)
        self.assertEqual(result["repaired"], 0)
        store2 = KnowledgeStore(path)
        try:
            version = store2.get_version("reports", "E", "v1")
            self.assertEqual(version["public_available_at"],
                             "2026-01-03T00:00:00Z")
        finally:
            store2.close()


# ================================================================== V04
class V04FirstPublishAndRecoveryTest(unittest.TestCase):
    def test_first_publish_uses_business_identity(self):
        """First export of a claim revision must register under the SAME
        business identity as later exports (review: main file unregistered
        -> duplicate on the second export)."""
        from knowledge.memory import create_claim, review_claim
        from knowledge.store import KnowledgeStore
        from knowledge.writeback import (export_claim_candidates,
                                         register_write_root)

        kb = _kb()
        try:
            stamp = "2026-10-01T00:00:00Z"
            kb.upsert_documents([{
                "source": "reports", "doc_id": "R1", "title": "R1",
                "available": True, "first_seen_at": stamp,
                "last_seen_at": stamp,
            }], stamp)
            created = create_claim(
                kb, "claim statement v1",
                [{"source": "reports", "doc_id": "R1", "version_id": "v1",
                  "block_id": "b", "extraction_id": "e"}], subject="EX")
            review_claim(kb, created["claim_id"], "accept", reviewer="a")
            directory = os.path.join(temp_dir(), "vault")
            os.makedirs(directory, exist_ok=True)
            register_write_root(directory)
            export_claim_candidates(kb, directory, status="accepted")
            # human edits the main file -> next export of the SAME revision
            # must reuse the candidate identity, not publish a fresh one
            main = os.path.join(directory, created["claim_id"] + ".md")
            with open(main, "w", encoding="utf-8") as handle:
                handle.write("HUMAN EDIT")
            export_claim_candidates(kb, directory, status="accepted")
            candidates = [f for f in os.listdir(directory)
                          if ".candidate-" in f]
            self.assertEqual(len(candidates), 1,
                             "same-revision second export duplicated: %r"
                             % candidates)
        finally:
            kb.close()

    def test_interrupted_candidate_registration_recovers(self):
        """Candidate file created but manifest save interrupted -> retry
        must recognize the orphan file and register it, not create a
        second copy (review: revision-2 retry produced 2 files)."""
        from knowledge.writeback import (_content_identity,
                                         _exclusive_create, _load_manifest,
                                         register_write_root,
                                         write_candidate)

        directory = os.path.join(temp_dir(), "vault-int")
        os.makedirs(directory, exist_ok=True)
        register_write_root(directory)
        # publish revision ONE normally (main file registered)
        write_candidate(directory, "doc.md", "revision one",
                        stable_id="rev1.template-v9")
        # human edits the main file, so revision TWO goes to a candidate;
        # simulate the crash AFTER the candidate file was exclusively
        # created but BEFORE its manifest registration
        with open(os.path.join(directory, "doc.md"), "w",
                  encoding="utf-8") as handle:
            handle.write("HUMAN EDIT")
        content = "revision two content"
        stable = "rev2.template-v9"
        identity = _content_identity(directory, "doc.md", content,
                                     stable_id=stable)
        orphan = os.path.join(
            directory, "doc.candidate-orphan-%s.md" % stable)
        _exclusive_create(orphan, content)
        self.assertEqual(
            _content_identity(directory, "doc.md", content,
                              stable_id=stable), identity)
        # retry: the orphan (name carries the stable marker) is ADOPTED,
        # not duplicated; the human main file is untouched
        result = write_candidate(directory, "doc.md", content,
                                 stable_id=stable)
        candidates = [f for f in os.listdir(directory)
                      if ".candidate-" in f]
        self.assertEqual(len(candidates), 1,
                         "retry duplicated the orphan: %r" % candidates)
        self.assertEqual(candidates[0], os.path.basename(orphan))
        self.assertEqual(
            open(os.path.join(directory, "doc.md"), encoding="utf-8").read(),
            "HUMAN EDIT")
        manifest = _load_manifest(directory)
        self.assertEqual(manifest["candidates"].get(identity), orphan)
        # a further retry is a pure no-op
        again = write_candidate(directory, "doc.md", content,
                                stable_id=stable)
        self.assertEqual(again["outcome"], "unchanged")
        self.assertEqual(again.get("candidate_path") or orphan, orphan)
        self.assertEqual(len([f for f in os.listdir(directory)
                              if ".candidate-" in f]), 1)


# ================================================================== F0-5
class CLIStopgapSnapshotRootTest(unittest.TestCase):
    def test_serve_kb_passes_configured_snapshot_root(self):
        """The CLI main must hand config.snapshot_root into the API server
        (migration hit 404s from a cwd-relative default)."""
        src = open(os.path.join(REPO, "app", "knowledge", "__main__.py"),
                   encoding="utf-8").read()
        self.assertIn("snapshot_root=config.snapshot_root", src,
                      "serve-kb does not pass the configured snapshot_root")

    def test_serve_kb_snapshot_from_any_cwd(self):
        """End-to-end: the API resolves snapshots from the CONFIG path
        (what serve-kb now passes), not the process cwd."""
        import hashlib
        import tempfile
        import threading
        import urllib.request

        from knowledge.kbapi import build_kb_server
        from knowledge.snapshot import SnapshotStore, snapshot_version

        kb = _kb()
        store_root = os.path.join(temp_dir(), "snaps")  # unrelated to cwd
        blobs = SnapshotStore(store_root)
        payload = b"SNAPSHOT BYTES FOR CLI"
        fd, tmpf = tempfile.mkstemp()
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        stamp = "2026-10-04T00:00:00Z"
        kb.upsert_documents([{
            "source": "reports", "doc_id": "S1", "title": "S1",
            "available": True, "first_seen_at": stamp, "last_seen_at": stamp,
        }], stamp)
        kb.upsert_versions([{
            "source": "reports", "doc_id": "S1", "version_id": "v1",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload), "media_type": "application/pdf",
            "ext": "pdf", "rel_path": "x", "is_current": True,
            "state": "ready", "content_changed_at": None,
        }], stamp)
        with open(tmpf, "rb") as handle:
            sha = snapshot_version(kb, blobs, handle, "reports", "S1", "v1",
                                   None, len(payload))
        server = build_kb_server(kb, {"t": ["research.read"]}, "127.0.0.1", 0,
                                 snapshot_root=store_root)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            request = urllib.request.Request(
                "http://127.0.0.1:%d/api/kb/v1/snapshots/reports/S1/v1"
                % port)
            request.add_header("Authorization", "Bearer t")
            with urllib.request.urlopen(request, timeout=10) as response:
                body = response.read()
            self.assertEqual(hashlib.sha256(body).hexdigest(), sha)
        finally:
            server.shutdown()
            server.server_close()
            kb.close()


if __name__ == "__main__":
    unittest.main()
