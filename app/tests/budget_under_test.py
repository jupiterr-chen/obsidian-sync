"""Test helper: two INDEPENDENT KnowledgeStore connections over one DB
file, so concurrency tests exercise real cross-connection transactions
instead of one in-process object."""

from __future__ import annotations

import os
import tempfile

import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from knowledge.budget import Budget, BudgetLedger  # noqa: E402
from knowledge.store import KnowledgeStore  # noqa: E402


class LedgerPair:
    def __init__(self, cap: int):
        self.path = os.path.join(tempfile.mkdtemp(prefix="sr-budget-"),
                                 "knowledge.sqlite3")
        self.kb1 = KnowledgeStore(self.path)
        self.kb2 = KnowledgeStore(self.path)
        budget = Budget(max_total_input_tokens=cap)
        self.ledgers = [BudgetLedger(self.kb1, budget),
                        BudgetLedger(self.kb2, budget)]

    def close(self):
        self.kb1.close()
        self.kb2.close()
