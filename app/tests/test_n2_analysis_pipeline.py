"""N2 (Q02): a real single-document analysis pipeline with a fake provider.

Covers the two acceptance counter-examples (an older ready extraction
under a newer review one must not register; a changed prompt version
must register a NEW identity) plus the executor loop: claim/lease,
document-own-blocks analysis, citation verification, durable run +
task results, analysis-page publish, three-cycle idempotency, crash
lease recovery, budget queuing and human-edit protection.
"""
from __future__ import annotations

import os
import unittest

from fixtures import temp_dir


def _kb():
    from knowledge.store import KnowledgeStore

    return KnowledgeStore(os.path.join(temp_dir(), "k.sqlite3"))


def _seed(kb, doc_id, sha, extraction_id, status="ready", blocks=2,
          title=None):
    stamp = "2026-10-04T00:00:00Z"
    kb.upsert_documents([{
        "source": "reports", "doc_id": doc_id,
        "title": title or "Title %s" % doc_id, "symbol": "EX",
        "available": True, "first_seen_at": stamp, "last_seen_at": stamp,
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
          "text": "block %d of %s says margin rose to 25%%" % (i, doc_id),
          "locator": {"kind": "pdf", "page": i + 1},
          "quality": {"status": "ready", "issues": []}}
         for i in range(blocks)])


class _FakeChat:
    """Offline provider: echoes a draft citing block [1] (valid)."""

    name = "offline-fake"
    model = "fake-model"

    def __init__(self):
        self.calls = 0

    def complete(self, prompt):
        self.calls += 1
        from knowledge.providers import Usage

        return ("毛利率上升 [1]，系统归纳为正面信号。" if self.calls
                else ""), Usage(self.name, self.model,
                                len(prompt) // 4, 8, "test:offline")


class N2AnalysisTaskIdentityTest(unittest.TestCase):
    def test_latest_extraction_only_and_prompt_identity(self):
        from knowledge.analysis_tasks import (STATUS_BLOCKED,
                                              register_ready_analysis_tasks)

        kb = _kb()
        try:
            # older extraction ready, LATEST extraction review -> no task
            _seed(kb, "L1", "a", "old-ready")
            with kb._tx() as conn:
                conn.execute("UPDATE extractions SET config_digest='old'"
                             " WHERE extraction_id='old-ready'")
            _seed(kb, "L1", "a", "latest-review", status="review")
            result = register_ready_analysis_tasks(kb)
            self.assertEqual(result["registered"], 0,
                             "older ready extraction registered under a"
                             " newer review extraction")
            # changed prompt registers a NEW identity
            _seed(kb, "P1", "b", "prompt-ready")
            register_ready_analysis_tasks(kb, prompt_version="pv1")
            result = register_ready_analysis_tasks(kb, prompt_version="pv2")
            self.assertEqual(result["registered"], 1)
            # same identity again registers nothing
            again = register_ready_analysis_tasks(kb, prompt_version="pv2")
            self.assertEqual(again["registered"], 0)
            with kb._lock:
                statuses = kb._conn.execute(
                    "SELECT status, blocked_reason FROM analysis_tasks"
                    " WHERE doc_id='P1'").fetchall()
            self.assertEqual(sorted(r["status"] for r in statuses),
                             [STATUS_BLOCKED, STATUS_BLOCKED])
            self.assertTrue(all(r["blocked_reason"] == "model_disabled"
                                for r in statuses))
        finally:
            kb.close()

    def test_registration_targets_latest_ready(self):
        from knowledge.analysis_tasks import register_ready_analysis_tasks

        kb = _kb()
        try:
            # latest IS ready -> registers that extraction id
            _seed(kb, "OK1", "a", "extr-old")
            _seed(kb, "OK1", "a", "extr-new")
            register_ready_analysis_tasks(kb)
            with kb._lock:
                row = kb._conn.execute(
                    "SELECT extraction_id FROM analysis_tasks"
                    " WHERE doc_id='OK1'").fetchone()
            self.assertEqual(row["extraction_id"], "extr-new")
        finally:
            kb.close()


class N2ExecutorTest(unittest.TestCase):
    def test_execute_publish_and_idempotent_three_cycles(self):
        from knowledge.analysis_publish import (ANALYSIS_INDEX_NAME,
                                                AnalysisPublisher,
                                                analysis_page_filename)
        from knowledge.analysis_tasks import (execute_analysis_tasks,
                                              register_ready_analysis_tasks,
                                              task_counts)
        from knowledge.budget import Budget, BudgetLedger

        kb = _kb()
        try:
            _seed(kb, "E1", "a", "extr-e1")
            _seed(kb, "E2", "b", "extr-e2")
            chat = _FakeChat()
            ledger = BudgetLedger(kb, Budget())
            registered = register_ready_analysis_tasks(
                kb, prompt_version="pv1",
                model_identity="%s/%s" % (chat.name, chat.model),
                model_name=chat.model, blocked_reason=None)
            self.assertEqual(registered["registered"], 2)

            vault = os.path.join(temp_dir(), "vault")
            os.makedirs(vault, exist_ok=True)
            publisher = AnalysisPublisher(kb, vault,
                                          base_url="http://x:1")

            first = execute_analysis_tasks(kb, chat, ledger=ledger,
                                           prompt_version="pv1")
            self.assertEqual(first["done"], 2, first)
            publish1 = publisher.consume()
            self.assertEqual(publish1["published"], 2)

            # page content: provenance + verification + draft + boundary
            name = analysis_page_filename("reports", "E1", "extr-e1")
            page = open(os.path.join(publisher.output, name),
                        encoding="utf-8").read()
            self.assertIn("机器生成，待人工复核", page)
            self.assertIn("offline-fake/fake-model", page)
            self.assertIn("pv1", page)
            self.assertIn("extr-e1", page)
            self.assertIn("25%", page)          # document OWN block text
            self.assertIn("引用校验", page)
            index = open(os.path.join(publisher.output, ANALYSIS_INDEX_NAME),
                         encoding="utf-8").read()
            self.assertIn("Title E1", index)
            self.assertIn("已完成 2 份", index)

            # cycles two and three: nothing re-executes (no re-payment)
            second = execute_analysis_tasks(kb, chat, ledger=ledger)
            third = execute_analysis_tasks(kb, chat, ledger=ledger)
            self.assertEqual((second["done"], third["done"]), (0, 0))
            self.assertEqual(chat.calls, 2)
            counts = task_counts(kb)
            self.assertEqual(counts.get("done"), 2)
            self.assertEqual(counts.get("pending", 0), 0)

            # durable results: run persisted with draft + citations
            with kb._lock:
                row = kb._conn.execute(
                    "SELECT t.run_id, t.result_note, r.draft,"
                    " r.citations_json FROM analysis_tasks t"
                    " JOIN analysis_runs r ON r.run_id=t.run_id"
                    " WHERE t.doc_id='E1'").fetchone()
            self.assertIn("毛利率上升", row["result_note"])
            self.assertIn("毛利率上升", row["draft"])
            import json as _json

            self.assertTrue(_json.loads(row["citations_json"]))
        finally:
            kb.close()

    def test_human_edit_forces_candidate_not_overwrite(self):
        from knowledge.analysis_publish import AnalysisPublisher
        from knowledge.analysis_tasks import (execute_analysis_tasks,
                                              register_ready_analysis_tasks)
        from knowledge.analysis_publish import analysis_page_filename
        from knowledge.budget import Budget, BudgetLedger

        kb = _kb()
        try:
            _seed(kb, "H1", "a", "extr-h1")
            chat = _FakeChat()
            ledger = BudgetLedger(kb, Budget())
            register_ready_analysis_tasks(
                kb, model_identity="fake/1", blocked_reason=None)
            execute_analysis_tasks(kb, chat, ledger=ledger)
            vault = os.path.join(temp_dir(), "vault")
            os.makedirs(vault, exist_ok=True)
            publisher = AnalysisPublisher(kb, vault, base_url="http://x:1")
            publisher.consume()
            name = analysis_page_filename("reports", "H1", "extr-h1")
            path = os.path.join(publisher.output, name)
            with open(path, "a", encoding="utf-8") as handle:
                handle.write("\n人工批注：待与财报核对\n")
            outcome = publisher.rebuild_index()
            self.assertIn(outcome["outcome"], ("written", "unchanged",
                                               "refreshed"))
            with open(path, encoding="utf-8") as handle:
                self.assertIn("人工批注", handle.read())
        finally:
            kb.close()

    def test_expired_lease_returns_to_pending(self):
        from knowledge.analysis_tasks import (STATUS_PENDING, STATUS_RUNNING,
                                              claim_pending_analysis_tasks,
                                              register_ready_analysis_tasks,
                                              release_expired_analysis_tasks)

        kb = _kb()
        try:
            _seed(kb, "R1", "a", "extr-r1")
            register_ready_analysis_tasks(kb, model_identity="fake/1",
                                          blocked_reason=None)
            claimed = claim_pending_analysis_tasks(kb)
            self.assertEqual(len(claimed), 1)
            with kb._tx() as conn:
                conn.execute(
                    "UPDATE analysis_tasks SET lease_until='2020-01-01"
                    "T00:00:00Z' WHERE task_key=?",
                    (claimed[0]["task_key"],))
            released = release_expired_analysis_tasks(kb)
            self.assertEqual(released, 1)
            with kb._lock:
                status = kb._conn.execute(
                    "SELECT status FROM analysis_tasks").fetchone()[0]
            self.assertEqual(status, STATUS_PENDING)
            # attempts kept counting (1 from the claim)
            with kb._lock:
                attempts = kb._conn.execute(
                    "SELECT attempts FROM analysis_tasks").fetchone()[0]
            self.assertGreaterEqual(attempts, 1)
        finally:
            kb.close()

    def test_budget_exhaustion_queues_without_paid_call(self):
        from knowledge.analysis_tasks import (execute_analysis_tasks,
                                              register_ready_analysis_tasks,
                                              task_counts)
        from knowledge.budget import Budget, BudgetLedger

        kb = _kb()
        try:
            _seed(kb, "Q1", "a", "extr-q1")
            _seed(kb, "Q2", "b", "extr-q2")
            chat = _FakeChat()
            # a cap of exactly ONE request: the first task succeeds, the
            # second must be queued (pending), never sent past the cap
            ledger = BudgetLedger(kb, Budget(max_requests_total=1))
            register_ready_analysis_tasks(kb, model_identity="fake/1",
                                          blocked_reason=None)
            result = execute_analysis_tasks(kb, chat, ledger=ledger)
            self.assertEqual(result["done"], 1)
            self.assertEqual(chat.calls, 1)
            counts = task_counts(kb)
            # budget-blocked task stays queued - R3 records it as an
            # honest PARTIAL (resumable), never done/failed/paid
            queued = counts.get("pending", 0) + counts.get("partial", 0)
            self.assertEqual(queued, 1,
                             "budget-blocked task must stay queued: %r"
                             % counts)
            self.assertEqual(counts.get("done"), 1)
            self.assertEqual(counts.get("failed", 0), 0)
        finally:
            kb.close()

    def test_non_retryable_failure_fails_honestly(self):
        from knowledge.analysis_tasks import execute_analysis_tasks
        from knowledge.budget import Budget, BudgetLedger
        from knowledge.providers import (OpenAICompatibleChat,
                                         ProviderCallError)

        class BadJsonChat(OpenAICompatibleChat):
            def _transport(self, url, body):
                raise ProviderCallError("HTTP 401 from /v1: denied",
                                        retryable=False)

            def complete(self, prompt):
                # route through the gated transport like the real class
                raise ProviderCallError("HTTP 401 from /v1: denied",
                                        retryable=False)

        kb = _kb()
        try:
            _seed(kb, "F1", "a", "extr-f1")
            from knowledge.analysis_tasks import register_ready_analysis_tasks

            register_ready_analysis_tasks(kb, model_identity="fake/1",
                                          blocked_reason=None)
            ledger = BudgetLedger(kb, Budget())
            result = execute_analysis_tasks(kb, BadJsonChat(
                "c", "m", "http://x", "k", egress_allowed=True),
                ledger=ledger)
            self.assertEqual(result["failed"], 1, result)
            from knowledge.analysis_tasks import task_counts

            counts = task_counts(kb)
            self.assertEqual(counts.get("failed"), 1)
        finally:
            kb.close()


if __name__ == "__main__":
    unittest.main()
