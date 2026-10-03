"""Unified budget ledger for every paid provider call (R01 remediation).

One reservation per planned provider interaction: reserve -> settle (with
real usage) or fail_unknown (timeout/transport - the attempt may have cost
money, so the estimate is charged conservatively, never zero). Totals count
settled usage plus outstanding/unknown reservations, so concurrent workers
cannot jointly overspend a cap. Token estimates are conservative upper
bounds for mixed CJK/latin text (docs/09 forbids presenting them as real
tokenizer counts; settlement uses provider-side usage when available).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .providers import Usage
from .store import KnowledgeStore


@dataclass
class Budget:
    max_input_tokens_per_run: int = 200_000
    max_total_input_tokens: Optional[int] = None
    max_requests_total: Optional[int] = None
    max_pages_total: Optional[int] = None
    max_input_tokens_per_page: int = 20_000

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Budget":
        data = data or {}

        def opt(key):
            value = data.get(key)
            return int(value) if value is not None else None

        return cls(
            max_input_tokens_per_run=int(data.get("max_input_tokens_per_run",
                                                  200_000)),
            max_total_input_tokens=opt("max_total_input_tokens"),
            max_requests_total=opt("max_requests_total"),
            max_pages_total=opt("max_pages_total"),
            max_input_tokens_per_page=int(data.get("max_input_tokens_per_page",
                                                   20_000)),
        )


def load_budget(config_extra: Dict[str, Any]) -> Budget:
    """Top-level 'budget' wins; legacy providers.budget still honored (R01)."""
    data = config_extra.get("budget")
    if data is None:
        data = (config_extra.get("providers") or {}).get("budget")
    return Budget.from_dict(data or {})


def estimate_tokens(text: str) -> int:
    """Conservative upper bound: CJK ~1 token/char, latin ~4 chars/token."""
    if not text:
        return 8
    cjk = sum(1 for ch in text if "\u3400" <= ch <= "\u9fff"
              or "\uf900" <= ch <= "\ufaff")
    other = len(text) - cjk
    return cjk + (other + 3) // 4 + 8


class BudgetExceeded(Exception):
    """Raised BEFORE any provider bytes leave when a cap would be broken."""

    def __init__(self, message: str):
        super().__init__(message)
        self.retryable = False


class BudgetLedger:
    def __init__(self, kb: KnowledgeStore, budget: Optional[Budget] = None):
        self.kb = kb
        self.budget = budget or Budget()

    # ------------------------------------------------------------- totals
    def _totals(self) -> Dict[str, int]:
        with self.kb._lock:
            usage = self.kb._conn.execute(
                "SELECT COALESCE(SUM(input_tokens),0) i,"
                " COUNT(*) calls FROM usage_events").fetchone()
            reserved = self.kb._conn.execute(
                "SELECT COALESCE(SUM(est_input),0) e, COUNT(*) r"
                " FROM budget_reservations WHERE status IN ('reserved')"
            ).fetchone()
            pages = self.kb._conn.execute(
                "SELECT COUNT(*) p FROM usage_events WHERE kind='vision'"
            ).fetchone()
        return {"input": usage["i"] + reserved["e"],
                "requests": usage["calls"] + reserved["r"],
                "pages": pages["p"]}

    def remaining(self) -> Optional[int]:
        if self.budget.max_total_input_tokens is None:
            return None
        return self.budget.max_total_input_tokens - self._totals()["input"]

    # -------------------------------------------------------- reservation
    def reserve(self, kind: str, est_input: int, run_id: Optional[str] = None,
                counts_as_page: bool = False) -> int:
        est_input = max(1, int(est_input))
        totals = self._totals()
        budget = self.budget
        if (budget.max_total_input_tokens is not None
                and totals["input"] + est_input > budget.max_total_input_tokens):
            raise BudgetExceeded(
                "budget_exceeded_total_input_tokens: used+reserved=%d, "
                "request=%d, cap=%d" % (totals["input"], est_input,
                                        budget.max_total_input_tokens))
        if (budget.max_requests_total is not None
                and totals["requests"] + 1 > budget.max_requests_total):
            raise BudgetExceeded("budget_exceeded_max_requests")
        if counts_as_page and budget.max_pages_total is not None \
                and totals["pages"] + 1 > budget.max_pages_total:
            raise BudgetExceeded("budget_exceeded_max_pages")
        with self.kb._tx() as conn:
            cur = conn.execute(
                "INSERT INTO budget_reservations (kind, est_input, status,"
                " run_id, created_at) VALUES (?,?,?,?,"
                "strftime('%Y-%m-%dT%H:%M:%SZ','now'))",
                (kind, est_input, "reserved", run_id))
            return cur.lastrowid

    def settle(self, reservation_id: int, usage: Usage,
               run_id: Optional[str] = None) -> None:
        with self.kb._tx() as conn:
            conn.execute(
                "UPDATE budget_reservations SET status='settled', settled_at="
                "strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?",
                (reservation_id,))
        self.kb.record_usage(
            usage.provider, usage.model, usage_kind_for_reservation(
                self._kind_of(reservation_id)),
            usage.input_tokens, usage.output_tokens, usage.cost_basis,
            run_id=run_id)

    def fail_unknown(self, reservation_id: int,
                     run_id: Optional[str] = None) -> None:
        """A network attempt failed after dispatch: charge the estimate.

        Timeouts/transport errors may still have been billed provider-side;
        recording zero would under-count (R01)."""
        row = self._reservation(reservation_id)
        if row is None:
            return
        with self.kb._tx() as conn:
            conn.execute(
                "UPDATE budget_reservations SET status='unknown', settled_at="
                "strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?",
                (reservation_id,))
        self.kb.record_usage(
            "unknown-provider", "unknown-model", row["kind"], row["est_input"],
            0, "unknown:estimate-charged", run_id=run_id)

    def release(self, reservation_id: int) -> None:
        """Reservation made but no bytes were dispatched (pre-flight checks)."""
        with self.kb._tx() as conn:
            conn.execute(
                "UPDATE budget_reservations SET status='released', settled_at="
                "strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?",
                (reservation_id,))

    def _reservation(self, reservation_id: int):
        with self.kb._lock:
            return self.kb._conn.execute(
                "SELECT * FROM budget_reservations WHERE id=?",
                (reservation_id,)).fetchone()

    def _kind_of(self, reservation_id: int) -> str:
        row = self._reservation(reservation_id)
        return row["kind"] if row else "chat"


def usage_kind_for_reservation(kind: str) -> str:
    return {"vision-page": "vision"}.get(kind, kind)
