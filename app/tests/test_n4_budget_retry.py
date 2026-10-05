"""N4 (Q05): the physical-request cap must count each attempt exactly once.

The acceptance probe proved a double count: a failed http-attempt writes a
usage row with counts_request=1 (already inside `requests`), and the gate
ADDED dispatched_attempts on top - so cap=2, one timeout plus one legal
retry answered ProviderCallError after a single attempt. The physical
definition here: every usage row with counts_request=1 is one dispatched
request (failed attempt rows included, settled business rows are the
success record of their final attempt), open reservations with
counts_request=1 are in flight. Nothing is summed twice.
"""
from __future__ import annotations

import os
import unittest

from fixtures import temp_dir


def _kb():
    from knowledge.store import KnowledgeStore

    return KnowledgeStore(os.path.join(temp_dir(), "k.sqlite3"))


from knowledge.providers import OpenAICompatibleEmbedding


class _FlakyEmbedding(OpenAICompatibleEmbedding):
    """Fails the first transport call, succeeds on the retry."""

    attempts = 0

    def _transport(self, url, body):
        type(self).attempts += 1
        if type(self).attempts == 1:
            raise TimeoutError("synthetic first-attempt timeout")
        return {"data": [{"index": 0, "embedding": [0.5, 0.5]}],
                "usage": {"prompt_tokens": 5}}


class N4BudgetRetryTest(unittest.TestCase):
    def test_cap_two_allows_one_failure_plus_one_retry(self):
        from knowledge.analysis import budgeted_embed
        from knowledge.budget import Budget, BudgetLedger
        from knowledge.providers import OpenAICompatibleEmbedding

        provider = _FlakyEmbedding(name="offline", model="stub",
                                   api_key="fake",
                                   base_url="https://offline.invalid",
                                   egress_allowed=True, dimensions=2,
                                   max_retries=1)
        kb = _kb()
        try:
            ledger = BudgetLedger(kb, Budget(max_requests_total=2))
            vectors, _usage = budgeted_embed(
                provider, ["synthetic"], ledger=ledger, kb=kb)
            self.assertEqual(len(vectors), 1)
            self.assertEqual(_FlakyEmbedding.attempts, 2,
                             "the legal retry was blocked by the gate")
            totals = ledger._totals()
            # 2 physical attempts happened: the failed one's attempt row
            # plus the settled business row (success request of record)
            self.assertEqual(totals["requests"], 2, totals)
        finally:
            _FlakyEmbedding.attempts = 0
            kb.close()

    def test_third_request_blocked_after_two_spent(self):
        from knowledge.analysis import budgeted_embed
        from knowledge.budget import Budget, BudgetLedger
        from knowledge.providers import (OpenAICompatibleEmbedding,
                                         ProviderCallError)

        class AlwaysTimeout(OpenAICompatibleEmbedding):
            attempts = 0

            def _transport(self, url, body):
                type(self).attempts += 1
                raise TimeoutError("synthetic timeout")

        provider = AlwaysTimeout(name="offline", model="stub", api_key="fake",
                                 base_url="https://offline.invalid",
                                 egress_allowed=True, dimensions=2,
                                 max_retries=1)
        kb = _kb()
        try:
            ledger = BudgetLedger(kb, Budget(max_requests_total=2))
            with self.assertRaises(ProviderCallError):
                budgeted_embed(provider, ["x"], ledger=ledger, kb=kb)
            self.assertEqual(AlwaysTimeout.attempts, 2)
            # both physical slots spent: a NEW logical call must not send
            with self.assertRaises(ProviderCallError) as caught:
                budgeted_embed(provider, ["y"], ledger=ledger, kb=kb)
            self.assertIn("budget", str(caught.exception).lower())
            self.assertEqual(AlwaysTimeout.attempts, 2,
                             "third physical request escaped the cap")
            totals = ledger._totals()
            self.assertEqual(totals["requests"], 2, totals)
        finally:
            kb.close()

    def test_cap_one_blocks_internal_retry(self):
        from knowledge.budget import Budget, BudgetLedger
        from knowledge.providers import (OpenAICompatibleChat,
                                         ProviderCallError)

        class RetryChat(OpenAICompatibleChat):
            attempts = 0

            def _transport(self, url, body):
                type(self).attempts += 1
                raise OSError("timeout")

        chat = RetryChat("c", "m", "http://x", "k", egress_allowed=True,
                         max_retries=1)
        kb = _kb()
        try:
            ledger = BudgetLedger(kb, Budget(max_requests_total=1))
            chat.attempt_ledger = ledger
            with self.assertRaises(ProviderCallError):
                chat.complete("x")
            self.assertEqual(RetryChat.attempts, 1,
                             "cap 1 must allow exactly one attempt")
        finally:
            kb.close()

    def test_cap_binds_across_restart(self):
        from knowledge.analysis import budgeted_embed
        from knowledge.budget import Budget, BudgetLedger
        from knowledge.providers import OpenAICompatibleEmbedding

        provider = _FlakyEmbedding(name="offline", model="stub",
                                   api_key="fake",
                                   base_url="https://offline.invalid",
                                   egress_allowed=True, dimensions=2,
                                   max_retries=1)
        kb = _kb()
        try:
            ledger = BudgetLedger(kb, Budget(max_requests_total=2))
            budgeted_embed(provider, ["synthetic"], ledger=ledger, kb=kb)
            # restart: new ledger over the same store still sees 2 spent
            ledger2 = BudgetLedger(kb, Budget(max_requests_total=2))
            self.assertGreaterEqual(ledger2._totals()["requests"], 2)
        finally:
            _FlakyEmbedding.attempts = 0
            kb.close()

    def test_inflight_attempt_reservations_count_against_cap(self):
        """Two concurrently-open attempt reservations must consume both
        slots of a cap-2 budget - a third gate check fails closed."""
        from knowledge.budget import Budget, BudgetLedger, BudgetExceeded

        kb = _kb()
        try:
            ledger = BudgetLedger(kb, Budget(max_requests_total=2))
            ledger.reserve("http-attempt", 1)
            ledger.reserve("http-attempt", 1)
            with self.assertRaises(BudgetExceeded):
                ledger.reserve("http-attempt", 1)
        finally:
            kb.close()

    def test_chat_and_embedding_share_the_physical_cap(self):
        from knowledge.budget import Budget, BudgetLedger, BudgetExceeded
        from knowledge.providers import Usage

        kb = _kb()
        try:
            ledger = BudgetLedger(kb, Budget(max_requests_total=2))
            rid1 = ledger.reserve("chat", 5)
            ledger.settle(rid1, Usage("p", "m", 5, 0, "t"))
            rid2 = ledger.reserve("embedding", 5)
            ledger.settle(rid2, Usage("p", "m", 5, 0, "t"))
            with self.assertRaises(BudgetExceeded):
                ledger.reserve("chat", 1)
        finally:
            kb.close()


if __name__ == "__main__":
    unittest.main()
