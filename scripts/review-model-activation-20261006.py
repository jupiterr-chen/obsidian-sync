"""Offline model-activation gates; not blockers for analysis-disabled maintenance.

No real model/network/production access. Fixtures are retained. Exit 1
means one of the B/C activation requirements is unmet.
"""
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app"), str(ROOT / "app/tests")]
from test_n2_analysis_pipeline import _kb, _seed, _FakeChat
from knowledge.analysis_tasks import register_ready_analysis_tasks, execute_analysis_tasks
from knowledge.analysis_publish import AnalysisPublisher
from knowledge.budget import Budget, BudgetLedger
from knowledge.providers import Usage


def register(kb):
    register_ready_analysis_tasks(kb, model_identity="offline-fake/fake-model",
                                  blocked_reason=None)


def main():
    observations = []
    kb = _kb()
    try:
        _seed(kb, "PART", "s", "partial-ext", blocks=16)
        register(kb)
        chat = _FakeChat()
        publisher = AnalysisPublisher(kb, tempfile.mkdtemp())
        execute_analysis_tasks(kb, chat, ledger=BudgetLedger(kb, Budget(max_requests_total=1)))
        publisher.consume()
        execute_analysis_tasks(kb, chat, ledger=BudgetLedger(kb, Budget()))
        result = publisher.consume()
        row = kb._conn.execute("SELECT status,publish_path FROM analysis_tasks").fetchone()
        content = (Path(publisher.output) / row["publish_path"]).read_text(encoding="utf-8")
        observations.append({"probe": "MA01_partial_to_done_republishes",
            "passed": row["status"] == "done" and "部分覆盖" not in content,
            "observed": {"db_status": row["status"], "published_after_resume": result["published"],
                         "linked_page_still_partial": "部分覆盖" in content}})
    finally:
        kb.close()

    kb = _kb()
    try:
        _seed(kb, "CITE", "c", "cite-ext", blocks=16)
        register(kb)
        class CiteChat:
            name, model = "offline-fake", "fake-model"

            def __init__(self):
                self.calls = 0

            def complete(self, prompt):
                self.calls += 1
                draft = "invalid merged reference [999]" if self.calls == 3 else "section evidence [1]"
                return draft, Usage(self.name, self.model, 10, 5, "test:offline")

        execute_analysis_tasks(kb, CiteChat())
        row = kb._conn.execute("SELECT draft,verification_json,citations_json FROM analysis_runs").fetchone()
        verification = json.loads(row["verification_json"])
        observations.append({"probe": "MA02_verify_final_synthesis_citations",
            "passed": not verification["all_valid"],
            "observed": {"final_contains_999": "[999]" in row["draft"],
                         "all_valid": verification["all_valid"],
                         "citation_numbers": [c["n"] for c in json.loads(row["citations_json"])]}})
    finally:
        kb.close()

    kb = _kb()
    try:
        _seed(kb, "CAP", "d", "cap-ext", blocks=2)
        register(kb)
        chat = _FakeChat()
        execute_analysis_tasks(kb, chat, ledger=BudgetLedger(kb, Budget(max_input_tokens_per_run=1)))
        observations.append({"probe": "MA03_enforce_per_run_input_budget",
            "passed": chat.calls == 0, "observed": {"cap": 1, "provider_calls": chat.calls}})
    finally:
        kb.close()

    print(json.dumps(observations, ensure_ascii=False, indent=2))
    return 0 if all(x["passed"] for x in observations) else 1


if __name__ == "__main__":
    raise SystemExit(main())
