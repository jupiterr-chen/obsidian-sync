"""Independent AC1 probes: isolated SQLite and fake providers only.

Exit 1 = acceptance conditions unmet. No production access, real HTTP,
cleanup, or model calls. Temporary fixture databases are retained.
"""
import ast
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app"), str(ROOT / "app/tests")]
from fixtures import temp_dir
from test_n2_analysis_pipeline import _kb, _seed
from knowledge import summaries as sm
from knowledge.analysis_tasks import register_ready_analysis_tasks, execute_analysis_tasks
from knowledge.analysis_publish import AnalysisPublisher, analysis_page_filename
from knowledge.providers import Usage


class CaptureChat:
    name, model = "offline-capture", "stub"

    def __init__(self):
        self.prompts = []

    def complete(self, prompt):
        self.prompts.append(prompt)
        return ("ANALYSIS_RESULT_%d [1]" % len(self.prompts),
                Usage(self.name, self.model, 10, 10, "test:offline"))


def register(kb, prompt="pv1"):
    return register_ready_analysis_tasks(kb, prompt_version=prompt,
        model_identity="offline-capture/stub", model_name="stub", blocked_reason=None)


def main():
    results = []
    def record(name, passed, **observed):
        results.append(dict(probe=name, passed=passed, observed=observed))

    kb = _kb()
    try:
        old = subprocess.check_output(
            ["git", "show", "2a85fc5:app/knowledge/summaries.py"], cwd=ROOT).decode()
        schema = next(ast.literal_eval(n.value) for n in ast.parse(old).body
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "SCHEMA" for t in n.targets))
        kb._conn.executescript(schema)
        error = None
        try:
            sm.ensure_schema(kb)
        except Exception as exc:
            error = str(exc)
        record("AC01_upgrade_previous_release_schema", error is None, error=error)
    finally:
        kb.close()

    kb = _kb()
    try:
        _seed(kb, "LONG", "a", "long-extract", blocks=100)
        chat = CaptureChat()
        register(kb)
        result = execute_analysis_tasks(kb, chat)
        record("AC03_single_doc_covers_last_section",
            any("block 99 of LONG" in p for p in chat.prompts),
            done=result["done"], calls=len(chat.prompts),
            last_section_seen=any("block 99 of LONG" in p for p in chat.prompts))
        sm.enqueue_summary_update(kb, "company", "EX", "document_added",
            {"source": "reports", "doc_id": "LONG", "version_id": "v1"})
        sm.consume_updates(kb, chat=chat)
        evidence = kb._conn.execute(
            "SELECT evidence_claim_revisions_json FROM summaries").fetchone()[0]
        prompt = chat.prompts[-1]
        record("AC02_analysis_content_reaches_summary",
            "margin rose" in prompt or "ANALYSIS_RESULT_1" in prompt,
            claim_count=kb._conn.execute("SELECT count(*) FROM claims").fetchone()[0],
            summary_evidence=json.loads(evidence),
            source_or_analysis_text_in_prompt=("margin rose" in prompt or "ANALYSIS_RESULT_1" in prompt))

        vault = Path(temp_dir()) / "vault"
        vault.mkdir()
        publisher = AnalysisPublisher(kb, str(vault))
        publisher.consume()
        register(kb, "pv2")
        execute_analysis_tasks(kb, chat, prompt_version="pv2")
        publisher.consume()
        name = analysis_page_filename("reports", "LONG", "long-extract")
        page = (Path(publisher.output) / name).read_text(encoding="utf-8")
        index = (Path(publisher.output) / "分析索引.md").read_text(encoding="utf-8")
        record("AC04_prompt_revision_publishes_distinct_entry",
            index.count("](" + name + ")") < 2,
            main_is_pv1="pv1 / single-doc-v1" in page,
            same_target_links=index.count("](" + name + ")"),
            candidate_count=len(list(Path(publisher.output).glob("*.candidate*"))))
    finally:
        kb.close()

    kb = _kb()
    try:
        _seed(kb, "PENDING", "b", "pending-extract")
        register(kb)
        vault = Path(temp_dir()) / "vault"
        vault.mkdir()
        error = None
        try:
            AnalysisPublisher(kb, str(vault)).consume()
        except Exception as exc:
            error = "%s: %s" % (type(exc).__name__, exc)
        record("AC04_pending_analysis_index_is_usable", error is None, error=error)
    finally:
        kb.close()

    kb = _kb()
    try:
        from knowledge.memory import create_claim, review_claim
        _seed(kb, "CRASH", "c", "crash-extract")
        block = kb.get_blocks("crash-extract")[0]
        claim = create_claim(kb, "Synthetic margin evidence", [{
            "source": "reports", "doc_id": "CRASH", "version_id": "v1",
            "extraction_id": "crash-extract", "block_id": block["block_id"]}], subject="EX")
        review_claim(kb, claim["claim_id"], "accept", reviewer="offline-test")
        sm.enqueue_summary_update(kb, "company", "EX", "document_added",
                                  {"source": "reports", "doc_id": "CRASH", "version_id": "v1"})
        original = sm.record_summary
        def crash_after_record(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("injected crash after durable result before outbox ack")
        chat = CaptureChat()
        with patch.object(sm, "record_summary", side_effect=crash_after_record):
            try:
                sm.consume_updates(kb, chat=chat)
            except RuntimeError:
                pass
        sm.consume_updates(kb, chat=chat)
        revisions = len(sm.summary_history(kb, "company", "EX"))
        record("AC02_summary_resume_reuses_durable_result", revisions == 1 and len(chat.prompts) == 1,
               revisions=revisions, calls=len(chat.prompts))
    finally:
        kb.close()

    kb = _kb()
    try:
        from test_abcde_delivery import _seed_version
        from knowledge.background import build_background_package
        _seed_version(kb, "CURRENT", "a-current", "a", current=True)
        _seed_version(kb, "CURRENT", "z-old", "b", current=False)
        chosen = build_background_package(kb, "company", "EX")["sources"][0]["version_id"]
        record("AC05_no_cutoff_uses_current_version", chosen == "a-current",
               expected="a-current", actual=chosen)
    finally:
        kb.close()

    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
