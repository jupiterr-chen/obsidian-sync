"""R2/R2b: B results and document text reach C; durable-result resume.

The AC1 review proved C's input was empty: after a successful B
analysis, C's prompt held neither the report text nor the analysis
output - only source/doc ids as an update "reason" - and a done summary
was persisted anyway. And a crash between the durable result and the
outbox ack re-called the provider and appended a second revision.

These regressions require NO pre-seeded claims: the chain is extraction
-> single-doc analysis -> summary, the way a company's first report
actually arrives.
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fixtures import temp_dir


def _kb():
    from knowledge.store import KnowledgeStore

    return KnowledgeStore(os.path.join(temp_dir(), "k.sqlite3"))


def _seed(kb, doc_id, sha, extraction_id, symbol="EX", blocks=2,
          text=None):
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
        "status": "ready", "issues": [], "stats": {}},
        [{"block_type": "paragraph",
          "text": text or "block %d of %s: margin rose to 25%%" % (
              i, doc_id),
          "locator": {"kind": "pdf", "page": i + 1},
          "quality": {"status": "ready", "issues": []}}
         for i in range(blocks)])


class _FakeChat:
    name = "offline-fake"
    model = "fake-model"

    def __init__(self):
        self.prompts = []

    def complete(self, prompt):
        self.prompts.append(prompt)
        from knowledge.providers import Usage

        return ("SUMMARY_RESULT_%d" % len(self.prompts),
                Usage(self.name, self.model, len(prompt) // 4, 8,
                      "test:offline"))


class R2EvidenceWiringTest(unittest.TestCase):
    def test_report_text_and_analysis_reach_summary(self):
        """No claims pre-seeded: after B runs, C's prompt AND persisted
        evidence must contain the report text and the analysis result,
        each bound to source/version/extraction/run identity."""
        from knowledge.analysis_tasks import (execute_analysis_tasks,
                                              register_ready_analysis_tasks)
        from knowledge.budget import Budget, BudgetLedger
        from knowledge.summaries import (consume_updates,
                                         enqueue_summary_update,
                                         summary_history)

        kb = _kb()
        try:
            _seed(kb, "REP1", "a", "extr-rep1")
            register_ready_analysis_tasks(
                kb, model_identity="offline-fake/fake-model",
                model_name="fake-model", blocked_reason=None)
            analysis_chat = _FakeChat()
            executed = execute_analysis_tasks(kb, analysis_chat)
            self.assertEqual(executed["done"], 1)

            enqueue_summary_update(kb, "company", "EX", "document_added",
                                   {"source": "reports", "doc_id": "REP1",
                                    "version_id": "v1"})
            summary_chat = _FakeChat()
            result = consume_updates(kb, chat=summary_chat)
            self.assertEqual(result["generated"], 1, result)

            prompt = summary_chat.prompts[0]
            # the document's OWN text reached the model
            self.assertIn("margin rose to 25%", prompt)
            # the B analysis result reached the model, with identity
            self.assertIn("SUMMARY_RESULT_1", prompt)
            self.assertIn("run ", prompt)
            # persisted evidence carries the same bindings
            import json as _json

            history = summary_history(kb, "company", "EX")
            self.assertEqual(history[0]["status"], "done")
            evidence = _json.loads(kb._conn.execute(
                "SELECT evidence_claim_revisions_json FROM summaries"
            ).fetchone()[0])
            kinds = {item.get("kind") for item in evidence}
            self.assertIn("document_block", kinds)
            self.assertIn("analysis", kinds)
            for item in evidence:
                if item.get("kind") == "document_block":
                    self.assertTrue(item["source"] and item["version_id"]
                                    and item["extraction_id"]
                                    and item["block_id"])
                    self.assertIn("margin rose", item["text"])
                if item.get("kind") == "analysis":
                    self.assertTrue(item["run_id"] and
                                    item["extraction_id"])
                    self.assertIn("SUMMARY_RESULT_1", item["text"])
        finally:
            kb.close()

    def test_no_evidence_blocks_instead_of_empty_generation(self):
        """An entity with no document text, no analysis and no claim
        must NOT be generated (and not paid for) - consumed into a
        blocked(insufficient_evidence) revision preserving identity."""
        from knowledge.summaries import (STATUS_BLOCKED, consume_updates,
                                         enqueue_summary_update,
                                         summary_history)

        kb = _kb()
        try:
            # document exists but with NO text blocks (empty extraction)
            _seed(kb, "EMPTY", "e", "extr-empty", blocks=0)
            enqueue_summary_update(kb, "company", "EX", "document_added",
                                   {"source": "reports", "doc_id": "EMPTY"})
            chat = _FakeChat()
            result = consume_updates(kb, chat=chat)
            self.assertEqual(result["generated"], 0)
            self.assertEqual(result["blocked"], 1)
            self.assertEqual(chat.prompts, [],
                             "provider was called without evidence")
            history = summary_history(kb, "company", "EX")
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["status"], STATUS_BLOCKED)
            self.assertIn("insufficient", history[0]["blocked_reason"])
        finally:
            kb.close()

    def test_unrelated_company_not_updated(self):
        from knowledge.summaries import (consume_updates,
                                         enqueue_summary_update,
                                         summary_history)

        kb = _kb()
        try:
            _seed(kb, "AAA", "a", "extr-aaa", symbol="AAA")
            _seed(kb, "BBB", "b", "extr-bbb", symbol="BBB")
            enqueue_summary_update(kb, "company", "AAA", "document_added",
                                   {"source": "reports", "doc_id": "AAA"},
                                   event_key="doc:reports:AAA:v1")
            chat = _FakeChat()
            result = consume_updates(kb, chat=chat)
            self.assertEqual(result["generated"], 1)
            self.assertEqual(summary_history(kb, "company", "BBB"), [],
                             "unrelated entity was updated")
            self.assertEqual(chat.calls if hasattr(chat, "calls") else
                             len(chat.prompts), 1)
        finally:
            kb.close()

    def test_topic_mapping_configurable_minimal(self):
        from knowledge.summaries import entities_for_document

        kb = _kb()
        try:
            _seed(kb, "TOPIC1", "t", "extr-topic1", symbol=None)
            # no rules -> no topic entities (company-only, as documented)
            self.assertEqual(
                entities_for_document(kb, "reports", "TOPIC1"), [])
            rules = [{"id": "流动性",
                      "keywords": ["流动性", "liquidity"]}]
            mapped = entities_for_document(kb, "reports", "TOPIC1",
                                           topic_rules=rules)
            # title is "Title TOPIC1" - no keyword match
            self.assertEqual(mapped, [])
            # rename the doc title to match: topic entity appears
            with kb._tx() as conn:
                conn.execute(
                    "UPDATE kb_documents SET title='全球流动性观察'"
                    " WHERE doc_id='TOPIC1'")
            mapped = entities_for_document(kb, "reports", "TOPIC1",
                                           topic_rules=rules)
            self.assertIn({"entity_type": "topic", "entity_id": "流动性"},
                          mapped)
        finally:
            kb.close()


class R2bDurableResumeTest(unittest.TestCase):
    def test_crash_after_result_before_ack_resumes_without_recalling(self):
        """Result persisted, outbox row NOT consumed, process dies. The
        retry must reuse the durable result: one provider call, one
        revision."""
        from knowledge.summaries import (consume_updates,
                                         enqueue_summary_update,
                                         record_summary, summary_history)

        kb = _kb()
        try:
            _seed(kb, "CRASH", "c", "extr-crash")
            enqueue_summary_update(kb, "company", "EX", "document_added",
                                   {"source": "reports", "doc_id": "CRASH",
                                    "version_id": "v1"})
            chat = _FakeChat()
            original = record_summary

            def crash_after_record(*args, **kwargs):
                original(*args, **kwargs)
                raise RuntimeError(
                    "injected crash after durable result before ack")

            with patch.object(
                    __import__("knowledge.summaries", fromlist=["x"]),
                    "record_summary", side_effect=crash_after_record):
                with self.assertRaises(RuntimeError):
                    consume_updates(kb, chat=chat)
            result = consume_updates(kb, chat=chat)
            self.assertEqual(result["reused_durable"], 1, result)
            self.assertEqual(result["generated"], 0)
            self.assertEqual(len(chat.prompts), 1,
                             "provider re-called for a durable result")
            history = summary_history(kb, "company", "EX")
            self.assertEqual(len(history), 1,
                             "second revision appended after resume")
            self.assertEqual(history[0]["status"], "done")
        finally:
            kb.close()

    def test_network_failure_before_disk_stays_pending(self):
        """A provider failure before anything is persisted leaves the
        event pending (one retry on the next consume) - the ambiguous
        window is documented, not hidden behind fake exactly-once."""
        from knowledge.providers import ProviderCallError
        from knowledge.summaries import (consume_updates,
                                         enqueue_summary_update,
                                         pending_updates,
                                         summary_history)

        class ExplodingChat(_FakeChat):
            def complete(self, prompt):
                self.prompts.append(prompt)
                raise ProviderCallError("transport exploded",
                                        retryable=True)

        kb = _kb()
        try:
            _seed(kb, "BOOM", "d", "extr-boom")
            enqueue_summary_update(kb, "company", "EX", "document_added",
                                   {"source": "reports", "doc_id": "BOOM"})
            chat = ExplodingChat()
            result = consume_updates(kb, chat=chat)
            self.assertEqual(result["generated"], 0)
            self.assertEqual(len(result["errors"]), 1,
                             "the transport failure must be reported")
            # the event stays pending; nothing was persisted
            self.assertEqual(len(pending_updates(kb)), 1)
            self.assertEqual(summary_history(kb, "company", "EX"), [])
        finally:
            kb.close()


if __name__ == "__main__":
    unittest.main()
