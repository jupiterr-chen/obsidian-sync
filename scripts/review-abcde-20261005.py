"""Offline independent acceptance probes. No production access or real HTTP.

Run: python scripts/review-abcde-20261005.py
Exit 1 means an acceptance condition is unmet; synthetic databases are retained.
Do not treat these probes as real-document quality or production acceptance.
"""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app"), str(ROOT / "app/tests")]
from test_abcde_delivery import _kb, _seed_version, _record_extraction
from fixtures import temp_dir
from knowledge.background import build_background_package
from knowledge.analysis_tasks import register_ready_analysis_tasks
from knowledge.summaries import enqueue_summary_update, consume_updates, summary_history
from knowledge.reading import ReadingPublisher, reading_filename
from knowledge.budget import Budget, BudgetLedger
from knowledge.providers import OpenAICompatibleEmbedding
from knowledge.analysis import budgeted_embed


def main():
    results = []

    def result(name, passed, **observed):
        results.append(dict(probe=name, passed=passed, observed=observed))

    kb = _kb()
    try:
        _seed_version(kb, "TIME")  # first observed 2026-10-04
        _record_extraction(kb, "TIME", "v1", "time-extract")
        packages = [build_background_package(kb, "company", "EX",
                    as_of="2000-01-01T00:00:00Z", as_of_mode=mode)
                    for mode in ("system", "public")]
        counts = [len(p["sources"]) for p in packages]
        result("Q01_historical_cutoff", counts == [0, 0], source_counts=counts)
    finally:
        kb.close()

    kb = _kb()
    try:
        _seed_version(kb, "LATEST")
        _record_extraction(kb, "LATEST", "v1", "old-ready")
        with kb._tx() as conn:
            conn.execute("UPDATE extractions SET config_digest='old-recipe'"
                         " WHERE extraction_id='old-ready'")
        _record_extraction(kb, "LATEST", "v1", "latest-review", status="review")
        r = register_ready_analysis_tasks(kb)
        result("Q02_latest_extraction_only", r["registered"] == 0, **r)
        _seed_version(kb, "PROMPT", sha="b")
        _record_extraction(kb, "PROMPT", "v1", "prompt-ready", sha="b")
        register_ready_analysis_tasks(kb, prompt_version="pv1")
        r = register_ready_analysis_tasks(kb, prompt_version="pv2")
        result("Q02_changed_prompt_identity", r["registered"] == 1, **r)
    finally:
        kb.close()

    kb = _kb()
    try:
        # Mirrors worker revisiting the same open review proposal each cycle.
        for _ in range(3):
            enqueue_summary_update(kb, "company", "EX", "evidence_changed",
                                   {"proposal_id": "same-proposal"})
            consume_updates(kb)
        history = summary_history(kb, "company", "EX")
        result("Q03_summary_event_idempotency", len(history) == 1,
               revisions=len(history))
    finally:
        kb.close()

    kb = _kb()
    try:
        vault = Path(temp_dir()) / "vault"
        vault.mkdir()
        publisher = ReadingPublisher(kb, str(vault), "http://offline.invalid")
        for i in range(2):
            doc, ext = "READ%d" % i, "read-extract-%d" % i
            _seed_version(kb, doc, sha=str(i))
            _record_extraction(kb, doc, "v1", ext, sha=str(i))
            publisher.enqueue("reports", doc, "v1", ext)
        publisher.consume(limit=1)
        index = (Path(publisher.output) / "开始阅读.md").read_text(encoding="utf-8")
        absent = reading_filename("reports", "READ1", "read-extract-1")
        dangling = absent in index and not (Path(publisher.output) / absent).exists()
        result("Q04_publish_batch_has_no_dangling_link", not dangling,
               dangling_link=dangling, pending=len(publisher.pending()))
    finally:
        kb.close()

    kb = _kb()
    try:
        class RetryOnce(OpenAICompatibleEmbedding):
            attempts = 0

            def _transport(self, url, body):
                self.attempts += 1
                if self.attempts == 1:
                    raise TimeoutError("synthetic first-attempt timeout")
                return {"data": [{"index": 0, "embedding": [0.5, 0.5]}],
                        "usage": {"prompt_tokens": 5}}

        provider = RetryOnce(name="offline", model="stub", api_key="fake",
            base_url="https://offline.invalid", egress_allowed=True,
            dimensions=2, max_retries=1)
        ledger = BudgetLedger(kb, Budget(max_requests_total=2))
        error = None
        try:
            budgeted_embed(provider, ["synthetic"], ledger=ledger, kb=kb)
        except Exception as exc:
            error = type(exc).__name__
        result("Q05_two_request_budget_allows_one_retry",
               provider.attempts == 2 and error is None,
               attempts=provider.attempts, error=error)
    finally:
        kb.close()
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
