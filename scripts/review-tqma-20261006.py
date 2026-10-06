"""Independent TQ/MA acceptance probes. Synthetic data, offline providers only.

No production access, real model calls, deletion, or cleanup. Exit 1 means
one or more acceptance conditions remain unmet. Fixtures are retained.
"""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app"), str(ROOT / "app/tests")]
from fixtures import temp_dir
from test_tq3_reprocess import _kb, _seed
from test_ma_activation import _make_store_and_config, _seed_doc, _run_worker
from knowledge.analysis_tasks import register_ready_analysis_tasks
from knowledge.governance import plan_file_governance
from knowledge.indexing import _selected_blocks
from knowledge.reading import ReadingPublisher, reading_filename
from knowledge.repair import select_reprocess_items, register_reprocess_batch
from knowledge.store import KnowledgeStore
from knowledge.text_quality import build_inventory


def main():
    results = []

    def record(name, passed, **observed):
        results.append(dict(probe=name, passed=bool(passed), observed=observed))

    # Actual worker CLI: no allowlist, but C still sends the seeded company.
    tmp = temp_dir()
    cfg, path = _make_store_and_config(tmp)
    kb = KnowledgeStore(cfg["knowledge_db"])
    _seed_doc(kb, "UNAUTHORIZED", "sha-u", "ext-u", "EX",
              "OUTSIDE_SCOPE_SENTINEL", blocks=1)
    kb.close()
    cycle = _run_worker(path)
    kb = KnowledgeStore(cfg["knowledge_db"])
    rows = kb._conn.execute(
        "SELECT evidence_claim_revisions_json FROM summaries"
        " WHERE status='done'").fetchall()
    outside = sum("OUTSIDE_SCOPE_SENTINEL" in r[0] for r in rows)
    record("TA01_empty_scope_must_block_C_too", not outside,
           B_registered=cycle["analysis_tasks"]["registered"],
           C_done_with_outside_evidence=outside)
    kb.close()

    # Existing queue cannot bypass a narrowed/empty scope at execution time.
    tmp = temp_dir()
    cfg, path = _make_store_and_config(tmp)
    kb = KnowledgeStore(cfg["knowledge_db"])
    _seed_doc(kb, "OLD_QUEUE", "sha-q", "ext-q", "EX",
              "OLD_QUEUE_SENTINEL", blocks=1)
    register_ready_analysis_tasks(kb, model_identity="previous-provider/model",
                                  blocked_reason=None,
                                  scope={"doc_ids": ["OLD_QUEUE"]})
    kb.close()
    cycle = _run_worker(path)
    kb = KnowledgeStore(cfg["knowledge_db"])
    done = kb._conn.execute(
        "SELECT COUNT(*) FROM analysis_tasks WHERE doc_id='OLD_QUEUE'"
        " AND status='done'").fetchone()[0]
    record("TA02_old_queue_respects_active_scope_and_model", done == 0,
           scope_required=cycle["analysis_tasks"].get("scope_required"),
           previous_provider_task_done=done)
    kb.close()

    # A later REVIEW extraction with nonempty garbage must not replace good text.
    kb = _kb()
    _seed(kb, "REGRESS", "s", "aaa-old")
    vault = temp_dir()
    pub = ReadingPublisher(kb, vault, base_url="http://invalid.local")
    pub.enqueue("reports", "REGRESS", "v1", "aaa-old")
    pub.consume()
    _seed(kb, "REGRESS", "s", "zzz-bad", status="review", blocks=[{
        "block_type": "paragraph", "text": "\x01\x02\x03\x04" * 100,
        "locator": {"kind": "pdf", "page": 1},
        "quality": {"status": "review", "issues": ["damaged_text_layer"]}}])
    pub.enqueue("reports", "REGRESS", "v1", "zzz-bad")
    pub.consume()
    index = (Path(pub.output) / "开始阅读.md").read_text(encoding="utf-8")
    selected = [r["extraction_id"] for r in _selected_blocks(kb)]
    old_name = reading_filename("reports", "REGRESS", "aaa-old")
    bad_name = reading_filename("reports", "REGRESS", "zzz-bad")
    record("TA03_reject_worse_nonempty_extraction",
           old_name in index and bad_name not in index and "aaa-old" in selected,
           old_reading_link=old_name in index, bad_reading_link=bad_name in index,
           indexed_extractions=selected)
    plan = plan_file_governance(kb, pub.output)
    entry = next(x for x in plan["files"] if x["file"] == bad_name)
    record("TA04_governance_keeps_actual_link_target",
           entry["disposition"] != "archive-candidate",
           linked_from_current_index=bad_name in index,
           disposition=entry["disposition"],
           referenced_by_publish=entry["referenced_by_publish"])
    kb.close()

    # The CLI rebuilds inventory on every invocation: completing A must not
    # authorize B under the SAME batch id and per-invocation max=1.
    kb = _kb()
    _seed(kb, "A", "a", "old-a", parser_id="stdlib-pdf")
    _seed(kb, "B", "b", "old-b", parser_id="stdlib-pdf")
    items = select_reprocess_items(build_inventory(kb), max_items=1)
    register_reprocess_batch(kb, "current", items, "approved-one")
    _seed(kb, "A", "a", "new-a")
    items2 = select_reprocess_items(build_inventory(kb), max_items=1)
    register_reprocess_batch(kb, "current", items2, "approved-one")
    members = [r[0] for r in kb._conn.execute(
        "SELECT doc_id FROM reprocess_batches WHERE batch_id='approved-one'"
        " ORDER BY doc_id")]
    record("TA05_batch_membership_frozen_across_resume", members == ["A"],
           per_invocation_max=1, same_batch_members=members)
    kb.close()

    # Inventory's CLI is advertised as read-only, including when pointed at
    # an existing valid SQLite file with absent/old application schema.
    tmp = Path(temp_dir())
    db = tmp / "existing.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE sentinel(value TEXT)")
    conn.commit()
    conn.close()
    config = tmp / "knowledge.json"
    config.write_text(json.dumps({"knowledge_db": str(db)}), encoding="utf-8")
    before = db.read_bytes()
    proc = subprocess.run([sys.executable, "-m", "knowledge", "quality-inventory",
                           "--config", str(config)], cwd=ROOT,
                          env={**os.environ, "PYTHONPATH": str(ROOT / "app")},
                          capture_output=True, text=True, timeout=60)
    conn = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)
    tables = conn.execute("SELECT COUNT(*) FROM sqlite_master"
                          " WHERE type='table'").fetchone()[0]
    conn.close()
    record("TA06_inventory_cli_never_initializes_or_migrates",
           db.read_bytes() == before, exit_code=proc.returncode,
           tables_before=1, tables_after=tables)

    proc = subprocess.run(["git", "ls-files", "--error-unmatch",
                           "tools/text-quality/sample_measure.py"],
                          cwd=ROOT, capture_output=True, text=True)
    record("TA07_sample_harness_shipped_in_git", proc.returncode == 0,
           tracked=proc.returncode == 0)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
