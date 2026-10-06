"""N3 (Q03) + worker integration: entity summaries and the full chain.

Proves with an offline fake provider: the same event queued three times
produces ONE revision; a document's FIRST appearance queues its company
entity; two reports with different views drive one entity's summary
with both sides preserved and unrelated entities untouched; blocked
revisions recover when a provider arrives; the full worker cycle runs
ingest -> analysis -> Obsidian pages -> entity summaries and is
idempotent across three runs and a restart; human edits are never
overwritten.
"""
from __future__ import annotations

import os
import unittest

from fixtures import temp_dir


def _kb():
    from knowledge.store import KnowledgeStore

    return KnowledgeStore(os.path.join(temp_dir(), "k.sqlite3"))


def _seed(kb, doc_id, sha, extraction_id, symbol="EX", status="ready",
          blocks=2):
    stamp = "2026-10-04T00:00:00Z"
    kb.upsert_documents([{
        "source": "reports", "doc_id": doc_id,
        "title": "Title %s" % doc_id, "symbol": symbol, "available": True,
        "first_seen_at": stamp, "last_seen_at": stamp,
        "report_date": "2026-06-30",
    }], stamp)
    kb.upsert_versions([{
        "source": "reports", "doc_id": doc_id, "version_id": "v1",
        "sha256": sha, "bytes": 10, "media_type": "application/pdf",
        "ext": "pdf", "rel_path": "x", "is_current": True,
        "state": "ready", "content_changed_at": None,
    }], stamp)
    kb.record_extraction({
        "extraction_id": extraction_id, "source": "reports",
        "doc_id": doc_id, "version_id": "v1",
        "snapshot_sha256": sha, "parser_id": "t", "parser_version": "1",
        "config_digest": "digest-%s" % extraction_id,
        "status": status, "issues": [], "stats": {}},
        [{"block_type": "paragraph",
          "text": "block %d of %s" % (i, doc_id),
          "locator": {"kind": "pdf", "page": i + 1},
          "quality": {"status": "ready", "issues": []}}
         for i in range(blocks)])


class _FakeChat:
    name = "offline-fake"
    model = "fake-model"

    def __init__(self):
        self.calls = 0

    def complete(self, prompt):
        self.calls += 1
        from knowledge.providers import Usage

        return ("综合观点 [1]：证据一致指向正面；反证见 [2]。" if self.calls
                else ""), Usage(self.name, self.model,
                                len(prompt) // 4, 8, "test:offline")


class N3SummaryEventTest(unittest.TestCase):
    def test_same_event_three_cycles_one_revision(self):
        from knowledge.summaries import (consume_updates,
                                         enqueue_summary_update,
                                         summary_history)

        kb = _kb()
        try:
            for _ in range(3):
                enqueue_summary_update(kb, "company", "EX",
                                       "evidence_changed",
                                       {"proposal_id": "same-proposal"})
                consume_updates(kb)
            history = summary_history(kb, "company", "EX")
            self.assertEqual(len(history), 1,
                             "one logical event must produce exactly one"
                             " revision, got %d" % len(history))
            self.assertEqual(history[0]["status"], "blocked")
            # the blocked revision preserves the evidence identity
            self.assertIsNotNone(history[0]["event_key"])
        finally:
            kb.close()

    def test_first_document_maps_to_entity(self):
        from knowledge.summaries import (consume_updates,
                                         entities_for_document,
                                         enqueue_summary_update,
                                         summary_history)

        kb = _kb()
        try:
            _seed(kb, "FIRST", "a", "extr-first", symbol="600519")
            entities = entities_for_document(kb, "reports", "FIRST")
            self.assertEqual(entities,
                             [{"entity_type": "company",
                               "entity_id": "600519"}])
            for entity in entities:
                enqueue_summary_update(
                    kb, entity["entity_type"], entity["entity_id"],
                    "document_added",
                    {"source": "reports", "doc_id": "FIRST",
                     "version_id": "v1"},
                    event_key="doc:reports:FIRST:v1")
            consume_updates(kb)
            history = summary_history(kb, "company", "600519")
            self.assertEqual(len(history), 1)
            # no symbol -> no entity (unrelated docs stay out)
            _seed(kb, "NOSYM", "b", "extr-nosym", symbol=None)
            self.assertEqual(entities_for_document(kb, "reports", "NOSYM"),
                             [])
        finally:
            kb.close()

    def test_two_views_drive_one_entity_not_unrelated(self):
        from knowledge.memory import create_claim, review_claim
        from knowledge.summaries import (consume_updates,
                                         enqueue_summary_update,
                                         summary_history)

        kb = _kb()
        try:
            _seed(kb, "BULL", "a", "extr-bull", symbol="600519")
            _seed(kb, "BEAR", "b", "extr-bear", symbol="600519")
            _seed(kb, "OTHER", "c", "extr-other", symbol="000001")
            bull = create_claim(
                kb, "bull: margins expanding",
                [{"source": "reports", "doc_id": "BULL", "version_id": "v1",
                  "block_id": "extr-bull-b0000",
                  "extraction_id": "extr-bull"}], subject="600519")
            bear = create_claim(
                kb, "bear: competition rising",
                [{"source": "reports", "doc_id": "BEAR", "version_id": "v1",
                  "block_id": "extr-bear-b0000",
                  "extraction_id": "extr-bear"}], subject="600519")
            other = create_claim(
                kb, "unrelated entity claim",
                [{"source": "reports", "doc_id": "OTHER", "version_id": "v1",
                  "block_id": "extr-other-b0000",
                  "extraction_id": "extr-other"}], subject="000001")
            review_claim(kb, bull["claim_id"], "accept", reviewer="a")
            review_claim(kb, bear["claim_id"], "challenge", reviewer="a",
                         note="counter-view")
            review_claim(kb, other["claim_id"], "accept", reviewer="a")

            chat = _FakeChat()
            enqueue_summary_update(kb, "company", "600519",
                                   "evidence_changed",
                                   {"cause": "two views"},
                                   event_key="ev:600519:two-views")
            result = consume_updates(kb, chat=chat)
            self.assertEqual(result["generated"], 1)
            history = summary_history(kb, "company", "600519")
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["status"], "done")
            # both sides + their claims preserved as evidence
            import json as _json

            evidence = _json.loads(kb._conn.execute(
                "SELECT evidence_claim_revisions_json FROM summaries"
                " WHERE entity_type='company' AND entity_id='600519'"
            ).fetchone()[0])
            statements = {e["statement"] for e in evidence
                          if e.get("kind", "claim") == "claim"}
            self.assertIn("bull: margins expanding", statements)
            self.assertIn("bear: competition rising", statements)
            # the unrelated entity was never touched
            self.assertEqual(summary_history(kb, "company", "000001"), [])
            self.assertEqual(chat.calls, 1)
        finally:
            kb.close()

    def test_blocked_revision_recovers_when_provider_arrives(self):
        from knowledge.summaries import (consume_updates,
                                         enqueue_blocked_entity_refreshes,
                                         enqueue_summary_update,
                                         summary_history)

        kb = _kb()
        try:
            # R2: a provider cannot generate without evidence - give the
            # entity one real document so recovery actually generates
            _seed(kb, "RECOVER", "r", "extr-recover", symbol="EX")
            enqueue_summary_update(kb, "company", "EX", "document_added",
                                   {"source": "reports", "doc_id": "X"},
                                   event_key="doc:reports:X:v1")
            blocked = consume_updates(kb)  # no provider: blocked revision
            self.assertEqual(blocked["blocked"], 1)
            # provider arrives: refresh is queued and generated
            queued = enqueue_blocked_entity_refreshes(kb)
            self.assertEqual(queued, 1)
            chat = _FakeChat()
            result = consume_updates(kb, chat=chat)
            self.assertEqual(result["generated"], 1)
            history = summary_history(kb, "company", "EX")
            self.assertEqual(len(history), 2)
            self.assertEqual(history[0]["status"], "blocked")
            self.assertEqual(history[1]["status"], "done")
            # refresh is itself idempotent
            self.assertEqual(enqueue_blocked_entity_refreshes(kb), 0)
        finally:
            kb.close()

    def test_publish_versioned_pages_and_human_edits_win(self):
        from knowledge.summaries import (SUMMARY_DIR_NAME, SUMMARY_INDEX_NAME,
                                         publish_pending_summaries,
                                         record_summary)

        kb = _kb()
        try:
            record_summary(kb, "company", "600519", "first version",
                           [{"claim_id": "c1", "revision": 1,
                             "statement": "s1", "status": "accepted"}])
            record_summary(kb, "company", "600519", "second version",
                           [{"claim_id": "c1", "revision": 2,
                             "statement": "s2", "status": "accepted"}])
            vault = os.path.join(temp_dir(), "vault")
            os.makedirs(vault, exist_ok=True)
            first = publish_pending_summaries(kb, vault, base_url="http://x:1")
            self.assertEqual(first["published"], 2)
            # each revision has its own immutable page
            files = [f for f in os.listdir(
                os.path.join(vault, SUMMARY_DIR_NAME))
                if f.startswith("summary-")]
            self.assertEqual(len(files), 2)
            index = open(os.path.join(vault, SUMMARY_DIR_NAME,
                                      SUMMARY_INDEX_NAME),
                         encoding="utf-8").read()
            self.assertIn("rev 2", index)
            # republish: nothing new (log dedup), history intact
            second = publish_pending_summaries(kb, vault,
                                               base_url="http://x:1")
            self.assertEqual(second["published"], 0)
            # human edit on a revision page: preserved (append-only)
            target = files[0]
            path = os.path.join(vault, SUMMARY_DIR_NAME, target)
            with open(path, "a", encoding="utf-8") as handle:
                handle.write("\n人工批注\n")
            publish_pending_summaries(kb, vault, base_url="http://x:1")
            with open(path, encoding="utf-8") as handle:
                self.assertIn("人工批注", handle.read())
        finally:
            kb.close()


class WorkerChainIntegrationTest(unittest.TestCase):
    """Full worker cycle with a fake provider: ingest -> analysis ->
    Obsidian -> entity summaries; three cycles + restart idempotent."""

    def test_full_chain_three_cycles_and_restart(self):
        from knowledge.analysis_publish import (ANALYSIS_DIR_NAME,
                                                ANALYSIS_INDEX_NAME,
                                                analysis_page_filename)
        from knowledge.budget import Budget, BudgetLedger
        from knowledge.config import KnowledgeConfig
        from knowledge.reading import INDEX_NAME
        from knowledge.summaries import (SUMMARY_DIR_NAME,
                                         SUMMARY_INDEX_NAME)
        from knowledge.worker import run_cycle
        from library.ingest import Ingestor

        tmp = temp_dir()
        lib_cfg, reports, _discord = _make_reports_fixture(tmp)
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
                   "public_base_url": "http://127.0.0.1:8765",
                   # S1: a provider-carrying cycle declares its sample -
                   # without a declared scope nothing is authorized
                   "analysis": {"scope": {"symbols": ["600519"]}}})
        # the fixture PDFs are synthetic bytes (their extractions land in
        # review/failed by the quality gate - honest), so seed ONE
        # text-ready document to exercise the analysis chain end to end
        from knowledge.store import KnowledgeStore as _KS

        seed_store = _KS(cfg.knowledge_db)
        _seed(seed_store, "CHAIN1", "chain-sha", "extr-chain1",
              symbol="600519")
        seed_store.close()

        chat = _FakeChat()
        first = run_cycle(cfg, lib_cfg, chat=chat,
                          ledger=BudgetLedger(_KS(cfg.knowledge_db),
                                              Budget()))
        self.assertTrue(first["ok"], first.get("error"))
        # B: analysis executed and published into the vault
        self.assertGreaterEqual(first["analysis_executed"]["done"], 1,
                                first.get("analysis_executed"))
        analysis_dir = os.path.join(vault, ANALYSIS_DIR_NAME)
        self.assertTrue(os.path.isdir(analysis_dir))
        self.assertTrue(os.path.isfile(
            os.path.join(analysis_dir, ANALYSIS_INDEX_NAME)))
        pages = [f for f in os.listdir(analysis_dir)
                 if f.startswith("analysis-")]
        self.assertGreaterEqual(len(pages), 1)
        # C: symbol docs queued entity summaries and generated them
        self.assertGreaterEqual(first["summaries"]["generated"], 1,
                                first.get("summaries"))
        summary_index = os.path.join(vault, SUMMARY_DIR_NAME,
                                     SUMMARY_INDEX_NAME)
        self.assertTrue(os.path.isfile(summary_index))
        content = open(summary_index, encoding="utf-8").read()
        self.assertIn("机器生成", content)
        # reading still works (普通阅读保持可用)
        self.assertTrue(os.path.isfile(
            os.path.join(vault, "解析正文", INDEX_NAME)))

        calls_after_first = chat.calls
        done_first = first["analysis_executed"]["done"]

        # cycles 2 and 3: no re-analysis, no re-payment, nothing new
        second = run_cycle(cfg, lib_cfg, chat=chat,
                           ledger=BudgetLedger(_KS(cfg.knowledge_db),
                                               Budget()))
        third = run_cycle(cfg, lib_cfg, chat=chat,
                          ledger=BudgetLedger(_KS(cfg.knowledge_db),
                                              Budget()))
        self.assertTrue(second["ok"] and third["ok"])
        self.assertEqual(second["analysis_executed"]["done"], 0)
        self.assertEqual(third["analysis_executed"]["done"], 0)
        self.assertEqual(chat.calls, calls_after_first)
        self.assertEqual(first["analysis_task_counts"]["done"], done_first)

        # restart-safe: a fresh cycle over the same store changes nothing
        fourth = run_cycle(cfg, lib_cfg, chat=chat,
                           ledger=BudgetLedger(_KS(cfg.knowledge_db),
                                               Budget()))
        self.assertEqual(fourth["analysis_executed"]["done"], 0)
        self.assertEqual(chat.calls, calls_after_first)

    def test_without_provider_everything_stays_blocked_not_paid(self):
        from knowledge.config import KnowledgeConfig
        from knowledge.worker import run_cycle
        from library.ingest import Ingestor

        tmp = temp_dir()
        lib_cfg, _, _ = _make_reports_fixture(tmp)
        Ingestor(lib_cfg).run()
        Ingestor(lib_cfg).close()
        vault = os.path.join(tmp, "vault-out")
        os.makedirs(vault, exist_ok=True)
        cfg = KnowledgeConfig(
            catalog_db=lib_cfg.catalog_db,
            knowledge_db=os.path.join(tmp, "state", "knowledge.sqlite3"),
            snapshot_root=os.path.join(tmp, "state", "snaps"),
            library_config="unused",
            extra={"vault_dir": vault})
        # one ready extraction so a blocked task actually exists
        from knowledge.store import KnowledgeStore as _KS

        seed_store = _KS(cfg.knowledge_db)
        _seed(seed_store, "BLOCKED1", "blocked-sha", "extr-blocked1",
              symbol="600519")
        seed_store.close()
        cycle = run_cycle(cfg, lib_cfg)
        self.assertTrue(cycle["ok"], cycle.get("error"))
        self.assertEqual(cycle["analysis_executed"]["skipped"], True)
        counts = cycle["analysis_task_counts"]
        self.assertGreaterEqual(counts.get("blocked", 0), 1)
        self.assertEqual(counts.get("done", 0), 0)
        self.assertGreaterEqual(cycle["summaries"]["blocked"], 1)
        # no usage rows: nothing left the machine
        from knowledge.store import KnowledgeStore

        kb = KnowledgeStore(cfg.knowledge_db)
        try:
            with kb._lock:
                usage = kb._conn.execute(
                    "SELECT COUNT(*) c FROM usage_events").fetchone()["c"]
        finally:
            kb.close()
        self.assertEqual(usage, 0)


def _make_reports_fixture(tmp):
    from fixtures import make_config

    return make_config(tmp)


if __name__ == "__main__":
    unittest.main()
