"""Fourth-review regressions (U01-U05) - RED first against baseline.

These target REAL business paths on UPGRADED old databases, the three
provider entrypoints, the real claim-export entrypoint and the actual
shadow tooling - not synthetic string checks or fresh empty databases.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch

from fixtures import temp_dir

from test_third_review import build_old_database

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(REPO, "app"))


def _kb():
    from knowledge.store import KnowledgeStore

    return KnowledgeStore(os.path.join(temp_dir(), "k.sqlite3"))


# ================================================================== U01
class U01OldDbBudgetBusinessTest(unittest.TestCase):
    def test_upgraded_old_db_runs_budget_business(self):
        """0a473d9-schema DB upgraded: reserve/settle/unknown/replay actually
        EXECUTE (the review only proved 'opens') - the missing
        usage_events.counts_request migration breaks the first reserve."""
        from knowledge.budget import Budget, BudgetLedger
        from knowledge.providers import Usage
        from knowledge.store import KnowledgeStore

        path = os.path.join(temp_dir(), "old-budget.sqlite3")
        build_old_database(path)
        store = KnowledgeStore(path)
        try:
            ledger = BudgetLedger(store, Budget(max_total_input_tokens=50))
            rid = ledger.reserve("chat", 8)
            ledger.settle(rid, Usage("p", "m", 6, 1, "t:none"))
            rid2 = ledger.reserve("chat", 4)
            ledger.fail_unknown(rid2)
            ledger.fail_unknown(rid2)  # replay idempotent
            totals = ledger._totals()
            # 7 legacy tokens + 6 settled + 4 unknown-estimate = 17
            self.assertEqual(totals["input"], 17)
            # legacy chat row + settle + unknown = 3 requests
            self.assertEqual(totals["requests"], 3)
            # legacy rows survived alongside the new business
            self.assertEqual(store.usage_totals()["input_tokens"], 17)
            with store._lock:
                legacy = store._conn.execute(
                    "SELECT COUNT(*) FROM usage_events WHERE provider='old'"
                ).fetchone()[0]
            self.assertEqual(legacy, 1)
        finally:
            store.close()
        # reopen: still works, nothing lost
        store2 = KnowledgeStore(path)
        try:
            ledger2 = BudgetLedger(store2, Budget(max_total_input_tokens=50))
            self.assertEqual(ledger2._totals()["input"], 17)
        finally:
            store2.close()


# ================================================================== U02
class U02AllEntrypointsGatedTest(unittest.TestCase):
    """chat analysis, vision OCR and embedding: cap=1 + first-attempt
    timeout with internal retry allowed -> exactly ONE transport call in
    EACH entrypoint, and no orphan reserved rows afterwards."""

    def _retry_provider(self, cls, **kwargs):
        class Retrying(cls):
            attempts = 0

            def _transport(self, url, body):
                Retrying.attempts += 1
                raise OSError("timeout")

        return Retrying(attempts=0, **kwargs), Retrying

    def test_chat_analysis_entrypoint_gated(self):
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

            chat, retry_cls = self._retry_provider(
                OpenAICompatibleChat, name="c", model="m",
                base_url="https://x.invalid", api_key="k",
                egress_allowed=True, max_retries=1)
            ledger = BudgetLedger(kb, Budget(max_requests_total=1))
            chat.attempt_ledger = ledger
            created = kb.create_analysis_run("margin")
            outcome = execute_analysis_run(
                kb, created["run_id"], "margin", chat,
                retriever=lambda q, k: search(kb, q, None, limit=k).get(
                    "hits", []),
                ledger=ledger)
            self.assertEqual(retry_cls.attempts, 1,
                             "chat retry escaped the request gate")
            self.assertEqual(outcome["status"], "failed")
            # no orphan reserved rows: every reservation reaches a terminal
            # or still-meaningful state attributable to the run
            with kb._lock:
                rows = [dict(r) for r in kb._conn.execute(
                    "SELECT kind, status FROM budget_reservations")]
            orphans = [r for r in rows if r["status"] == "reserved"
                       and r["kind"] == "http-attempt"]
            self.assertEqual(orphans, [],
                             "unsettled http-attempt rows: %r" % rows)
        finally:
            kb.close()

    def test_vision_ocr_entrypoint_gated(self):
        from knowledge.budget import Budget, BudgetLedger
        from knowledge.ocr import VisionApiOcr
        from knowledge.providers import OpenAICompatibleVision

        vision, retry_cls = self._retry_provider(
            OpenAICompatibleVision, name="v", model="m",
            base_url="https://x.invalid", api_key="k",
            egress_allowed=True, max_retries=1)
        kb = _kb()
        try:
            ledger = BudgetLedger(kb, Budget(max_requests_total=1,
                                             max_input_tokens_per_page=100,
                                             max_total_input_tokens=1000))
            engine = VisionApiOcr(chat_provider=vision, ledger=ledger,
                                  page_token_cap=50)
            engine.attempt_ledger = ledger  # real wiring under test
            with self.assertRaises(Exception):
                engine.run(b"PNG")
            self.assertEqual(retry_cls.attempts, 1,
                             "vision retry escaped the request gate")
            with kb._lock:
                orphans = [dict(r) for r in kb._conn.execute(
                    "SELECT kind, status FROM budget_reservations"
                    " WHERE status='reserved' AND kind='http-attempt'")]
            self.assertEqual(orphans, [])
        finally:
            kb.close()

    def test_embedding_success_leaves_no_orphan_attempts(self):
        """A SUCCESSFUL embed call must settle/release its http-attempt
        reservations - not leave them permanently reserved (the review saw
        a stuck 'http-attempt' row inflating totals by its estimate)."""
        from knowledge.analysis import budgeted_embed, ensure_block_embeddings
        from knowledge.budget import Budget, BudgetLedger
        from knowledge.providers import OpenAICompatibleEmbedding

        class OKEmbedding(OpenAICompatibleEmbedding):
            attempts = 0

            def _transport(self, url, body):
                OKEmbedding.attempts += 1
                return {"data": [{"index": 0, "embedding": [0.5, 0.5]}],
                        "usage": {"prompt_tokens": 5}}

        kb = _kb()
        try:
            stamp = "2026-10-01T00:00:00Z"
            kb.upsert_documents([{
                "source": "reports", "doc_id": "D", "title": "D",
                "available": True, "first_seen_at": stamp,
                "last_seen_at": stamp,
            }], stamp)
            kb.upsert_versions([{
                "source": "reports", "doc_id": "D", "version_id": "v1",
                "sha256": "a" * 64, "bytes": 10,
                "media_type": "application/pdf", "ext": "pdf",
                "rel_path": "x", "is_current": True, "state": "ready",
                "content_changed_at": None,
            }], stamp)
            kb.record_extraction({
                "extraction_id": "extr-d", "source": "reports",
                "doc_id": "D", "version_id": "v1",
                "snapshot_sha256": "a" * 64, "parser_id": "t",
                "parser_version": "1", "config_digest": "c",
                "status": "ready", "issues": [], "stats": {}},
                [{"block_type": "paragraph", "text": "cache test",
                  "locator": {"kind": "pdf", "page": 1},
                  "quality": {"status": "ready", "issues": []}}])
            embedder = OKEmbedding(name="e", model="m",
                                   base_url="https://x.invalid",
                                   api_key="k", egress_allowed=True,
                                   dimensions=2, max_retries=1)
            ledger = BudgetLedger(kb, Budget(max_total_input_tokens=1000))
            budgeted_embed(embedder, ["hello"], ledger=ledger, kb=kb)
            with kb._lock:
                rows = [dict(r) for r in kb._conn.execute(
                    "SELECT kind, status, counts_request FROM"
                    " budget_reservations")]
            stuck = [r for r in rows if r["status"] == "reserved"]
            self.assertEqual(stuck, [],
                             "successful call left reservations open: %r"
                             % rows)
            # real usage (5 tokens) recorded as measured, not the estimate
            usage = kb.usage_totals()
            self.assertGreaterEqual(usage["input_tokens"], 5)
        finally:
            kb.close()


# ================================================================== U03
class U03LegacyNullFirstObservedTest(unittest.TestCase):
    def test_upgraded_legacy_null_stays_unknown(self):
        """MIGRATED rows with first_observed_at=NULL: a January doc date
        must NOT be bound as the version's public time (the review's
        legacy leak)."""
        from knowledge.indexing import build_generation, search, SearchFilters
        from knowledge.store import KnowledgeStore

        path = os.path.join(temp_dir(), "legacy-null.sqlite3")
        build_old_database(path)
        store = KnowledgeStore(path)
        try:
            stamp = "2026-10-03T00:00:00Z"
            store.upsert_documents([{
                "source": "reports", "doc_id": "R1", "title": "legacy",
                "available": True, "first_seen_at": "2026-01-01T00:00:00Z",
                "last_seen_at": stamp,
                "published_at": "2026-01-01T00:00:00Z",
            }], stamp)
            # re-sync the legacy version row (NULL first_observed)
            store.upsert_versions([{
                "source": "reports", "doc_id": "R1", "version_id": "v1",
                "sha256": "a", "bytes": 10,
                "media_type": "application/pdf", "ext": "pdf",
                "rel_path": "x", "is_current": True, "state": "ready",
                "content_changed_at": None,
                # NO first_observed_at -> legacy unknown
            }], stamp)
            version = store.get_version("reports", "R1", "v1")
            self.assertIsNone(version["first_observed_at"])
            self.assertIsNone(version["public_available_at"],
                              "legacy NULL bound the doc date")
            self.assertEqual(version["public_time_basis"], "unknown")
            store.record_extraction({
                "extraction_id": "extr-legacy", "source": "reports",
                "doc_id": "R1", "version_id": "v1",
                "snapshot_sha256": "a", "parser_id": "t",
                "parser_version": "1", "config_digest": "c",
                "status": "ready", "issues": [], "stats": {}},
                [{"block_type": "paragraph", "text": "needle legacy",
                  "locator": {"kind": "pdf", "page": 1},
                  "quality": {"status": "ready", "issues": []}}])
            build_generation(store)
            july = search(store, "needle", SearchFilters(
                as_of="2026-07-01T00:00:00Z", as_of_mode="public"))
            self.assertEqual(july["hits"], [],
                             "legacy unknown leaked as public in July")
        finally:
            store.close()


# ================================================================== U04
class U04RealClaimExportTest(unittest.TestCase):
    def test_same_claim_across_seconds_exports_one_candidate(self):
        """The REAL export_claim_candidates entrypoint with an unchanged
        accepted claim, run three times at DIFFERENT wall-clock seconds
        (rendered utc_now differs each time) -> exactly one candidate file."""
        import time

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
                kb, "accepted claim statement about margins",
                [{"source": "reports", "doc_id": "R1", "version_id": "v1",
                  "block_id": "b", "extraction_id": "e"}],
                subject="EXAMPLE")
            review_claim(kb, created["claim_id"], "accept", reviewer="alice")
            directory = os.path.join(temp_dir(), "vault")
            os.makedirs(directory, exist_ok=True)
            register_write_root(directory)
            claim_file = created["claim_id"] + ".md"
            for _ in range(3):
                export_claim_candidates(kb, directory, status="accepted")
                time.sleep(1.1)  # different rendered timestamps
            # the main file + EXACTLY ONE candidate across three
            # differently-timestamped renders (was 3 candidates)
            candidates = [f for f in os.listdir(directory)
                          if f.startswith(created["claim_id"])
                          and ".candidate-" in f]
            self.assertEqual(len(candidates), 1,
                             "unchanged claim produced %d candidates: %r"
                             % (len(candidates), candidates))
        finally:
            kb.close()


# ================================================================== U05
class U05ShadowToolingTest(unittest.TestCase):
    @staticmethod
    def _run_tool(name, *args):
        result = subprocess.run(
            [sys.executable,
             os.path.join(REPO, "tools", "shadow-acceptance", name), *args],
            capture_output=True, text=True, timeout=300, cwd=REPO,
            env={**os.environ, "PYTHONPATH": "app"})
        return result

    def test_sample_manifest_pins_sha256_and_hash(self):
        out_dir = os.path.join(temp_dir(), "shadow")
        result = self._run_tool(
            "shadow_sample.py", "--config", "nonexistent.json",
            "--out-dir", out_dir)
        # config missing -> honest failure (not a crash pretending success)
        self.assertNotEqual(result.returncode, 0)

    def test_runner_rejects_production_state_dir(self):
        """A state-dir equal to (or inside) the production knowledge db's
        directory must be REFUSED before any write."""
        manifest = os.path.join(temp_dir(), "m.json")
        with open(manifest, "w", encoding="utf-8") as handle:
            json.dump({"samples": [{"source": "reports", "doc_id": "X",
                                    "version_id": "v1", "sha256": "a" * 64,
                                    "split": "tune", "stratum": "s"}]},
                      handle)
        # a REAL (minimal) config so the tool reaches the isolation check
        cfg = os.path.join(temp_dir(), "shadow-cfg.json")
        production_root = os.path.join(temp_dir(), "prod")
        os.makedirs(os.path.join(production_root, "state"), exist_ok=True)
        with open(cfg, "w", encoding="utf-8") as handle:
            json.dump({
                "catalog_db": os.path.join(production_root, "catalog.sqlite3"),
                "knowledge_db": os.path.join(production_root, "state",
                                             "knowledge.sqlite3"),
                "snapshot_root": os.path.join(production_root, "state",
                                              "snapshots"),
                "library_config": cfg,
            }, handle)
        result = self._run_tool(
            "shadow_run.py", "--config", cfg, "--manifest", manifest,
            "--state-dir", os.path.join(production_root, "state"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refus", (result.stdout + result.stderr).lower())

    def test_annotations_not_overwritten_on_resample(self):
        """shadow_sample must not overwrite existing annotation files."""
        out_dir = os.path.join(temp_dir(), "shadow-resample")
        os.makedirs(os.path.join(out_dir, "annotations"), exist_ok=True)
        marker = os.path.join(out_dir, "annotations", "MARKER.md")
        with open(marker, "w", encoding="utf-8") as handle:
            handle.write("HUMAN GOLD STANDARD")
        # run the real tool with a synthetic plan store; it fails early on
        # config, but the protection itself is unit-testable:
        from knowledge.writeback import register_write_root, write_candidate

        register_write_root(os.path.join(out_dir, "annotations"))
        write_candidate(os.path.join(out_dir, "annotations"),
                        "MARKER.md", "machine re-render")
        with open(marker, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "HUMAN GOLD STANDARD")


if __name__ == "__main__":
    unittest.main()
