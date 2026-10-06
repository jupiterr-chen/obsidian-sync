"""Follow-up checks for existing docs/34 requirements; synthetic/offline only.

Retains fixtures, never accesses production, real providers or remote data.
Exit 1 means an already assigned acceptance condition remains unmet.
"""
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app"), str(ROOT / "app/tests")]
from fixtures import temp_dir
from test_ma_activation import _make_store_and_config, _seed_doc, _run_worker
from test_tq3_reprocess import _kb, _seed
from test_n2_analysis_pipeline import _FakeChat
from knowledge.analysis_tasks import register_ready_analysis_tasks, execute_analysis_tasks
from knowledge.budget import Budget, BudgetLedger
from knowledge.config import KnowledgeConfig
from knowledge.effective import effective_extraction
from knowledge.governance import plan_file_governance
from knowledge.indexing import _selected_blocks
from knowledge.jobs import JobRunner
from knowledge.reading import ReadingPublisher, reading_filename
from knowledge.repair import register_reprocess_batch
from knowledge.store import KnowledgeStore


def main():
    results = []

    def record(name, passed, **observed):
        results.append(dict(probe=name, passed=bool(passed), observed=observed))

    # S1 explicitly required same-topic out-of-allowlist evidence exclusion.
    tmp = temp_dir()
    cfg, path = _make_store_and_config(
        tmp, scope={"doc_ids": ["ALLOWED"]},
        topics=[{"id": "liquidity", "keywords": ["liquidity"]}])
    kb = KnowledgeStore(cfg["knowledge_db"])
    _seed_doc(kb, "ALLOWED", "sha-a", "ext-a", None, "AUTHORIZED",
              blocks=1, title="liquidity allowed report")
    _seed_doc(kb, "DENIED", "sha-b", "ext-b", None, "DENIED_SENTINEL",
              blocks=1, title="liquidity outside report")
    kb.close()
    cycle = _run_worker(path)
    kb = KnowledgeStore(cfg["knowledge_db"])
    rows = kb._conn.execute(
        "SELECT evidence_claim_revisions_json FROM summaries"
        " WHERE status='done' AND entity_type='topic'").fetchall()
    leaked = sum("DENIED_SENTINEL" in r[0] for r in rows)
    record("SF01_S1_same_topic_evidence_stays_in_document_scope", leaked == 0,
           B_registered=cycle["analysis_tasks"]["registered"],
           topic_summaries_done=len(rows),
           C_done_with_denied_evidence=leaked)
    kb.close()

    # S2 explicitly required incomplete new results not to replace better old.
    kb = _kb()
    def block(text, page, bad=False):
        return {"block_type": "paragraph", "text": text,
                "locator": {"kind": "pdf", "page": page},
                "quality": {"status": "review" if bad else "ready",
                            "issues": ["damaged_text_layer"] if bad else []}}
    _seed(kb, "PAGES", "p", "good-old", blocks=[
        block("Healthy page one revenue 123", 1),
        block("Healthy page two margin 25%", 2)])
    pub = ReadingPublisher(kb, temp_dir(), base_url="http://invalid.local")
    pub.enqueue("reports", "PAGES", "v1", "good-old")
    pub.consume()
    _seed(kb, "PAGES", "p", "mixed-new", status="review", blocks=[
        block("\x01\x02\x03\x04" * 40, 1, True),
        block("Healthy page two margin 25%", 2)])
    pub.enqueue("reports", "PAGES", "v1", "mixed-new")
    pub.consume()
    selected = _selected_blocks(kb)
    chosen = effective_extraction(kb._conn, "reports", "PAGES", "v1")
    record("SF02_S2_partial_damage_cannot_displace_complete_old",
           chosen["extraction_id"] == "good-old" and len(selected) == 2,
           effective=chosen["extraction_id"], indexed_blocks=len(selected),
           old_healthy_blocks=2)

    # Existing S2 requirement: human-note references protect generated files.
    old_file = Path(pub.output) / "text-legacy.md"
    old_file.write_text("machine legacy content", encoding="utf-8")
    manifest_file = Path(pub.output) / ".knowledge-writeback.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    manifest["files"][old_file.name] = {
        "owner": "existing-text-export",
        "last_hash": hashlib.sha256(old_file.read_bytes()).hexdigest()}
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
    (Path(pub.output).parent / "My research.md").write_text(
        "Human reference [[解析正文/text-legacy#^evidence]]", encoding="utf-8")
    plan = plan_file_governance(kb, pub.output)
    disposition = next(x["disposition"] for x in plan["files"]
                       if x["file"] == old_file.name)
    record("SF03_S2_human_wikilink_keeps_legacy_file",
           disposition != "archive-candidate", disposition=disposition)
    kb.close()

    # S3 required the normal executor to obey the frozen recipe, not just
    # reject registration under a different recipe.
    kb = _kb()
    root = Path(temp_dir())
    raw = b"Synthetic original revenue 123 and margin 25 percent.\n" * 4
    sha = hashlib.sha256(raw).hexdigest()
    blob = root / "blob.txt"
    blob.write_bytes(raw)
    _seed(kb, "RECIPE", sha, "old-recipe")
    with kb._tx() as conn:
        conn.execute("UPDATE kb_versions SET media_type='text/plain',"
                     " ext='txt', bytes=? WHERE doc_id='RECIPE'", (len(raw),))
    kb.record_snapshot("reports", "RECIPE", "v1", sha, len(raw),
                       "blob.txt", "2026-10-06T00:00:00Z")
    approved_cfg = KnowledgeConfig(knowledge_db=kb.path, snapshot_root=str(root),
        extra={"ocr": {"engine": "off", "max_pages_per_doc": 1}})
    approved_digest = JobRunner(kb, approved_cfg, None).extract_digest
    register_reprocess_batch(kb, approved_digest, [{
        "source": "reports", "doc_id": "RECIPE", "version_id": "v1"}],
        "approved-batch")
    cfg = KnowledgeConfig(knowledge_db=kb.path, snapshot_root=str(root),
        extra={"ocr": {"engine": "off", "max_pages_per_doc": 2}})
    runner = JobRunner(kb, cfg, None)
    assert runner.extract_digest != approved_digest
    outcome = runner.run_extract_jobs(limit=1)
    row = kb._conn.execute(
        "SELECT config_digest FROM extractions WHERE doc_id='RECIPE'"
        " AND extraction_id!='old-recipe' ORDER BY rowid DESC LIMIT 1").fetchone()
    unexpected = row is not None and row[0] != approved_digest
    record("SF04_S3_executor_honors_frozen_recipe", not unexpected,
           job_done=outcome["done"], different_recipe_extraction=unexpected)
    kb.close()

    # S3 also required crash recovery: the initial member freeze cannot
    # persist just the first member if registration interrupts mid-batch.
    kb = _kb()
    _seed(kb, "A", "a", "ext-a")
    _seed(kb, "B", "b", "ext-b")
    items = [{"source": "reports", "doc_id": d, "version_id": "v1"}
             for d in ("A", "B")]
    with patch.object(kb, "register_job", side_effect=RuntimeError("crash")):
        try:
            register_reprocess_batch(kb, "recipe", items, "crash-batch")
        except RuntimeError:
            pass
    resumed = register_reprocess_batch(kb, "recipe", items, "crash-batch")
    members = [r[0] for r in kb._conn.execute(
        "SELECT doc_id FROM reprocess_batches WHERE batch_id='crash-batch'"
        " ORDER BY doc_id")]
    jobs = [r[0] for r in kb._conn.execute(
        "SELECT doc_id FROM jobs WHERE stage='extract' ORDER BY doc_id")]
    record("SF06_S3_initial_registration_crash_resumes_original_batch",
           not resumed.get("refused") and members == ["A", "B"] and jobs == ["A", "B"],
           refused=resumed.get("refused", False), reason=resumed.get("reason"),
           frozen_members=members, registered_jobs=jobs)
    kb.close()

    # F3 assigned budget waiting separately from provider failure attempts.
    kb = _kb()
    _seed(kb, "WAIT", "w", "ext-wait")
    chat = _FakeChat()
    register_ready_analysis_tasks(kb, model_identity="offline-fake/fake-model",
                                  blocked_reason=None)
    for _ in range(3):
        execute_analysis_tasks(kb, chat, max_attempts=3,
                               ledger=BudgetLedger(kb, Budget(max_requests_total=0)))
    before = chat.calls
    execute_analysis_tasks(kb, chat, max_attempts=3,
                           ledger=BudgetLedger(kb, Budget()))
    row = kb._conn.execute("SELECT status, attempts, error FROM analysis_tasks").fetchone()
    record("SF05_F3_budget_recovery_does_not_exhaust_failure_retries",
           row["status"] == "done", calls_while_budget_zero=before,
           calls_after_recovery=chat.calls-before, task_status=row["status"],
           attempts=row["attempts"], error=row["error"])
    kb.close()
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
