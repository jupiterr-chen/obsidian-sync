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
    # S01: totals count settled usage, outstanding reservations AND pages
    # implied by vision usage/reservations (pending pages are spent budget).
    _TOTALS_SQL = """
        SELECT
          (SELECT COALESCE(SUM(input_tokens),0) FROM usage_events) AS used_i,
          (SELECT COUNT(*) FROM usage_events) AS calls,
          (SELECT COALESCE(SUM(est_input),0) FROM budget_reservations
             WHERE status IN ('reserved')) AS res_e,
          (SELECT COUNT(*) FROM budget_reservations
             WHERE status IN ('reserved')) AS res_r,
          (SELECT COUNT(*) FROM usage_events WHERE kind='vision') AS used_p,
          (SELECT COUNT(*) FROM budget_reservations
             WHERE status IN ('reserved','unknown')
               AND kind='vision-page') AS res_p
    """

    def _totals_conn(self, conn) -> Dict[str, int]:
        row = conn.execute(self._TOTALS_SQL).fetchone()
        return {"input": row["used_i"] + row["res_e"],
                "requests": row["calls"] + row["res_r"],
                "pages": row["used_p"] + row["res_p"]}

    def _totals(self) -> Dict[str, int]:
        with self.kb._lock:
            return self._totals_conn(self.kb._conn)

    def remaining(self) -> Optional[int]:
        if self.budget.max_total_input_tokens is None:
            return None
        return self.budget.max_total_input_tokens - self._totals()["input"]

    # -------------------------------------------------------- reservation
    def reserve(self, kind: str, est_input: int, run_id: Optional[str] = None,
                counts_as_page: bool = False) -> int:
        est_input = max(1, int(est_input))
        budget = self.budget
        # S01: check and insert share ONE BEGIN IMMEDIATE write transaction,
        # so two independent connections cannot both pass the cap check and
        # jointly overspend (the re-review's 6+6 vs cap-10 case).
        conn = self.kb._conn
        with self.kb._lock:
            conn.execute("BEGIN IMMEDIATE")
            try:
                totals = self._totals_conn(conn)
                if (budget.max_total_input_tokens is not None
                        and totals["input"] + est_input
                        > budget.max_total_input_tokens):
                    raise BudgetExceeded(
                        "budget_exceeded_total_input_tokens:"
                        " used+reserved=%d, request=%d, cap=%d"
                        % (totals["input"], est_input,
                           budget.max_total_input_tokens))
                if (budget.max_requests_total is not None
                        and totals["requests"] + 1 > budget.max_requests_total):
                    raise BudgetExceeded("budget_exceeded_max_requests")
                if counts_as_page and budget.max_pages_total is not None \
                        and totals["pages"] + 1 > budget.max_pages_total:
                    raise BudgetExceeded("budget_exceeded_max_pages")
                cur = conn.execute(
                    "INSERT INTO budget_reservations (kind, est_input,"
                    " status, run_id, created_at) VALUES (?,?,?,?,"
                    "strftime('%Y-%m-%dT%H:%M:%SZ','now'))",
                    ("vision-page" if counts_as_page else kind, est_input,
                     "reserved", run_id))
                reservation_id = cur.lastrowid
            except Exception:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        return reservation_id

    def settle(self, reservation_id: int, usage: Usage,
               run_id: Optional[str] = None) -> None:
        """Settle reservation + record usage in ONE transaction.

        S01: a missing/zero provider usage is topped up with the
        reservation's estimate (a successful call is never free); settling
        twice is idempotent (unique usage row per reservation)."""
        conn = self.kb._conn
        with self.kb._lock:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT kind, est_input, status FROM"
                    " budget_reservations WHERE id=?",
                    (reservation_id,)).fetchone()
                if row is None:
                    raise ValueError("unknown reservation %r" % reservation_id)
                if row["status"] == "settled":
                    conn.execute("COMMIT")  # idempotent replay
                    return
                input_tokens = usage.input_tokens or row["est_input"]
                conn.execute(
                    "INSERT INTO usage_events (provider, model, kind,"
                    " input_tokens, output_tokens, cost_basis, run_id,"
                    " reservation_id, created_at)"
                    " VALUES (?,?,?,?,?,?,?,?,"
                    "strftime('%Y-%m-%dT%H:%M:%SZ','now'))",
                    (usage.provider, usage.model,
                     usage_kind_for_reservation(row["kind"]),
                     input_tokens, usage.output_tokens, usage.cost_basis,
                     run_id, reservation_id))
                conn.execute(
                    "UPDATE budget_reservations SET status='settled',"
                    " settled_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')"
                    " WHERE id=?", (reservation_id,))
            except Exception:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")

    def settle_crash_before_usage(self, reservation_id: int, usage: Usage,
                                  run_id: Optional[str] = None) -> None:
        """Test hook: crash between the provider answer and any durable
        settlement write (the re-review's interrupted-settle window)."""
        raise RuntimeError("simulated crash before settlement writes")

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
