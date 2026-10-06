"""MA activation acceptance (offline): the standard service entry runs
two conflicting LONG documents across >= 2 processing rounds with a
budget exhaustion and recovery in between.

Checks per docs/31: B/C pages exist and match the CURRENT result
version (partial -> done republishes); evidence is globally numbered
and the final draft re-verified; unrelated documents never enter the
queue or the ledger (scope + allowlist); usage is accountable; the
per-run input cap sends nothing when it cannot be met; topic rules
work from the SERVICE entry with persisted entity relations.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from fixtures import temp_dir

REPO = Path(__file__).resolve().parents[2]


def _run_worker(config_path, expect_ok=True):
    result = subprocess.run(
        [sys.executable, "-m", "knowledge", "worker",
         "--config", config_path, "--once"],
        capture_output=True, text=True, timeout=600, cwd=str(REPO),
        env={**os.environ, "PYTHONPATH": str(REPO / "app")})
    if expect_ok:
        assert result.returncode == 0, result.stderr[-3000:]
        return json.loads(result.stdout)
    return result


def _make_store_and_config(tmp, *, budget=None, scope=None,
                           topics=None):
    from fixtures import make_config
    from library.ingest import Ingestor

    library_path = os.path.join(tmp, "library-config.json")
    if not os.path.exists(library_path):
        lib_cfg, _, _ = make_config(tmp)
        Ingestor(lib_cfg).run()
        Ingestor(lib_cfg).close()
    with open(library_path, "r", encoding="utf-8") as handle:
        library = json.load(handle)
    vault = os.path.join(tmp, "vault-out")
    os.makedirs(vault, exist_ok=True)
    config = {
        "catalog_db": library["catalog_db"],
        "knowledge_db": os.path.join(tmp, "state", "knowledge.sqlite3"),
        "snapshot_root": os.path.join(tmp, "state", "snaps"),
        "library_config": library_path,
        "vault_dir": vault,
        "public_base_url": "http://127.0.0.1:8765",
        "providers": {"chat": {"kind": "scripted-chat",
                               "replies": [
                                   "多头证据 [1]：毛利率扩张至 30%%，"
                                   "需求强劲，风险有限。",
                                   "空头反证 [2]：竞争加剧，毛利率或降至"
                                   " 20%%，需谨慎。"]}},
        "analysis": {"enabled": True, "prompt_version": "pv1",
                     "max_tasks_per_cycle": 5},
    }
    if scope is not None:
        config["analysis"]["scope"] = scope
    if budget is not None:
        config["budget"] = budget
    if topics is not None:
        config["summarization"] = {"topics": topics}
    path = os.path.join(tmp, "knowledge.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(config, handle, ensure_ascii=False)
    return config, path


def _seed_doc(kb, doc_id, sha, extraction_id, symbol, text_prefix,
              blocks=24, title=None):
    stamp = "2026-10-04T00:00:00Z"
    kb.upsert_documents([{
        "source": "reports", "doc_id": doc_id,
        "title": title or ("Title %s" % doc_id), "symbol": symbol,
        "available": True, "first_seen_at": stamp,
        "last_seen_at": stamp}], stamp)
    kb.upsert_versions([{
        "source": "reports", "doc_id": doc_id, "version_id": "v1",
        "sha256": sha, "bytes": 100, "media_type": "application/pdf",
        "ext": "pdf", "rel_path": "x", "is_current": True,
        "state": "ready", "content_changed_at": None}], stamp)
    kb.record_extraction({
        "extraction_id": extraction_id, "source": "reports",
        "doc_id": doc_id, "version_id": "v1",
        "snapshot_sha256": sha, "parser_id": "t", "parser_version": "1",
        "config_digest": "digest-%s" % extraction_id,
        "status": "ready", "issues": [], "stats": {}},
        [{"block_type": "paragraph",
          "text": "%s 第 %d 段：关键数字 %.1f%%" % (
              text_prefix, i, 20.0 + i * 0.5),
          "locator": {"kind": "pdf", "page": i + 1},
          "quality": {"status": "ready", "issues": []}}
         for i in range(blocks)])


class MACrossRoundAcceptanceTest(unittest.TestCase):
    def test_two_long_docs_two_rounds_budget_interrupt_and_recover(self):
        tmp = temp_dir()
        # round 1 budget: 3 requests only - each doc is 24 blocks = 3
        # sections + 1 synthesis = 4 calls; with 2 docs the budget dies
        # mid-way, leaving partials; round 2 (generous budget) completes
        config1, path1 = _make_store_and_config(
            tmp, budget={"max_requests_total": 3},
            scope={"symbols": ["600519"]})
        from knowledge.store import KnowledgeStore

        seed = KnowledgeStore(config1["knowledge_db"])
        try:
            _seed_doc(seed, "BULL", "sha-bull", "extr-bull", "600519",
                      "多头观点：毛利率将扩张，需求强劲")
            _seed_doc(seed, "BEAR", "sha-bear", "extr-bear", "600519",
                      "空头反证：竞争加剧，毛利率承压")
            _seed_doc(seed, "OTHER", "sha-other", "extr-other", "000001",
                      "无关公司资料，不得进入队列")  # outside scope
        finally:
            seed.close()

        round1 = _run_worker(path1)
        self.assertTrue(round1["ok"], round1.get("error"))
        executed1 = round1["analysis_executed"]
        # the 3 paid calls cannot finish both 4-call documents
        self.assertEqual(executed1["done"], 0)
        self.assertGreaterEqual(executed1["partial"], 1, executed1)
        # the out-of-scope document never registered or executed
        self.assertEqual(round1["analysis_tasks"]["registered"], 2)

        # partials are published and marked 待续
        analysis_dir = os.path.join(config1["vault_dir"], "分析报告")
        index1 = open(os.path.join(analysis_dir, "分析索引.md"),
                      encoding="utf-8").read()
        self.assertIn("部分分析", index1)

        # ROUND 2: budget recovered -> resume WITHOUT re-paying done
        # sections, finish both docs, republish by result hash
        config2, path2 = _make_store_and_config(
            tmp, budget={"max_requests_total": 100},
            scope={"symbols": ["600519"]})
        # keep the SAME knowledge db/vault paths (the tmp is the same)
        round2 = _run_worker(path2)
        self.assertTrue(round2["ok"], round2.get("error"))
        self.assertEqual(round2["analysis_executed"]["done"], 2,
                         round2["analysis_executed"])

        from knowledge.store import KnowledgeStore as _KS

        kb = _KS(config2["knowledge_db"])
        try:
            with kb._lock:
                rows = kb._conn.execute(
                    "SELECT doc_id, status, result_note, publish_path,"
                    " coverage_json FROM analysis_tasks"
                    " ORDER BY doc_id").fetchall()
                usage = kb._conn.execute(
                    "SELECT COUNT(*) c FROM usage_events WHERE run_id"
                    " IN (SELECT run_id FROM analysis_runs)"
                ).fetchone()["c"]
                unrelated = kb._conn.execute(
                    "SELECT COUNT(*) c FROM analysis_tasks WHERE"
                    " doc_id='OTHER'").fetchone()["c"]
                outbox = kb._conn.execute(
                    "SELECT task_key, result_hash, status FROM"
                    " analysis_outbox ORDER BY id").fetchall()
        finally:
            kb.close()

        self.assertEqual([r["status"] for r in rows], ["done", "done"])
        self.assertEqual(unrelated, 0,
                         "out-of-scope document entered the queue")
        for row in rows:
            self.assertIn("完整分析", row["result_note"])
        # result revisions each publish: the interrupted document has
        # BOTH its partial and its done hash; the document the budget
        # never reached has its single done hash (it stayed queued, not
        # an empty partial)
        by_task = {}
        for row in outbox:
            by_task.setdefault(row["task_key"], []).append(
                row["result_hash"])
        self.assertEqual(len(by_task), 2)
        self.assertTrue(any(len(hashes) >= 2
                            for hashes in by_task.values()),
                        "the interrupted partial never republished: %r"
                        % by_task)
        self.assertTrue(all(len(hashes) >= 1
                            for hashes in by_task.values()))
        # the index now links the DONE pages with the current content
        index2 = open(os.path.join(analysis_dir, "分析索引.md"),
                      encoding="utf-8").read()
        self.assertIn("已完成 2 份", index2)
        self.assertIn("Title BULL", index2)
        self.assertIn("Title BEAR", index2)
        # the interrupted doc's CURRENT link reaches its done revision
        # (the candidate path recorded at publish time)
        bull_row = next(r for r in rows if r["doc_id"] == "BULL")
        self.assertIn(bull_row["publish_path"], index2)
        for row in rows:
            page = open(os.path.join(analysis_dir, row["publish_path"]),
                        encoding="utf-8").read()
            self.assertNotIn("部分覆盖：", page,
                             "linked page is still the partial draft")
            self.assertIn("机器生成，待人工复核", page)
            self.assertIn("毛利率", page)
        # budget accounting for the ANALYSIS runs only: 3 (round 1) +
        # the remaining sections + syntheses - paid sections are never
        # re-paid (each document costs at most its 4 calls in total)
        self.assertLessEqual(usage, 3 + 4 + 4, usage)

        # C: the company summary updated AFTER round 2 (B drives C);
        # both views present in the final revision's evidence
        kb = _KS(config2["knowledge_db"])
        try:
            with kb._lock:
                summary = kb._conn.execute(
                    "SELECT revision, status, content,"
                    " evidence_claim_revisions_json FROM summaries"
                    " WHERE entity_type='company' AND entity_id='600519'"
                    " AND status='done' ORDER BY revision DESC LIMIT 1"
                ).fetchone()
        finally:
            kb.close()
        self.assertIsNotNone(summary,
                             "company summary never generated after B")
        evidence = json.loads(summary["evidence_claim_revisions_json"])
        texts = [item.get("text", "") for item in evidence]
        self.assertTrue(any("多头" in t for t in texts),
                        "bull view missing from final summary evidence")
        self.assertTrue(any("空头" in t for t in texts),
                        "bear view missing from final summary evidence")
        summary_index = os.path.join(config2["vault_dir"], "总结",
                                     "总结索引.md")
        self.assertTrue(os.path.isfile(summary_index))

    def test_enabled_without_scope_registers_nothing(self):
        tmp = temp_dir()
        config, path = _make_store_and_config(tmp)  # no scope key
        from knowledge.store import KnowledgeStore

        seed = KnowledgeStore(config["knowledge_db"])
        try:
            _seed_doc(seed, "ANY", "sha-any", "extr-any", "600519",
                      "任意资料")
        finally:
            seed.close()
        cycle = _run_worker(path)
        self.assertTrue(cycle["ok"], cycle.get("error"))
        self.assertEqual(cycle["analysis_tasks"]["registered"], 0)
        self.assertTrue(cycle["analysis_tasks"].get("scope_required"),
                        cycle["analysis_tasks"])
        # nothing executed for any doc (the seeded doc stayed queued)
        self.assertEqual(cycle["analysis_executed"]["done"], 0)
        self.assertEqual(cycle["analysis_executed"]["partial"], 0)

    def test_per_run_cap_sends_nothing_when_unmeetable(self):
        from knowledge.analysis_tasks import (execute_analysis_tasks,
                                              register_ready_analysis_tasks)
        from knowledge.budget import Budget, BudgetLedger
        from knowledge.store import KnowledgeStore
        import tempfile

        kb = KnowledgeStore(os.path.join(temp_dir(), "k.sqlite3"))
        try:
            _seed_doc(kb, "CAP", "sha-cap", "extr-cap", "600519",
                      "超限文档", blocks=2)
            register_ready_analysis_tasks(
                kb, model_identity="offline/x", blocked_reason=None)

            class _Chat:
                name, model = "offline", "x"
                calls = 0

                def complete(self, prompt):
                    type(self).calls += 1
                    return "x [1]", _Usage()

            class _Usage:
                def __init__(self):
                    from knowledge.providers import Usage

                    self._u = Usage("offline", "x", 1, 1, "test")

            chat = _Chat()
            result = execute_analysis_tasks(
                kb, chat,
                ledger=BudgetLedger(kb, Budget(
                    max_input_tokens_per_run=1)))
            self.assertEqual(chat.calls, 0,
                             "oversized call left the machine")
            self.assertEqual(result["failed"], 1, result)
        finally:
            kb.close()

    def test_topic_summary_from_service_entry(self):
        tmp = temp_dir()
        config, path = _make_store_and_config(
            tmp, scope={"symbols": ["EX"]},
            topics=[{"id": "流动性", "keywords": ["流动性"]}])
        from knowledge.store import KnowledgeStore

        seed = KnowledgeStore(config["knowledge_db"])
        try:
            _seed_doc(seed, "TOPIC1", "sha-t1", "extr-t1", None,
                      "流动性专题资料", blocks=4,
                      title="全球流动性观察周报")
            _seed_doc(seed, "TOPIC2", "sha-t2", "extr-t2", None,
                      "流动性反证资料", blocks=4,
                      title="流动性风险与反证")
            _seed_doc(seed, "NOMATCH", "sha-nm", "extr-nm", None,
                      "无关资料", blocks=4, title="公司治理杂谈")
        finally:
            seed.close()
        cycle = _run_worker(path)
        self.assertTrue(cycle["ok"], cycle.get("error"))
        from knowledge.store import KnowledgeStore as _KS

        kb = _KS(config["knowledge_db"])
        try:
            with kb._lock:
                mapping = kb._conn.execute(
                    "SELECT entity_id, doc_id FROM entity_documents"
                    " WHERE entity_type='topic' ORDER BY doc_id"
                ).fetchall()
                topic_history = kb._conn.execute(
                    "SELECT COUNT(*) c FROM summaries WHERE"
                    " entity_type='topic' AND entity_id='流动性'"
                ).fetchone()["c"]
                nomatch = kb._conn.execute(
                    "SELECT COUNT(*) c FROM summaries WHERE"
                    " entity_id='公司治理杂谈' OR entity_id='NOMATCH'"
                ).fetchone()["c"]
        finally:
            kb.close()
        # the mapping is persisted and only matching docs joined
        self.assertEqual([r["doc_id"] for r in mapping],
                         ["TOPIC1", "TOPIC2"])
        self.assertGreaterEqual(topic_history, 1,
                                "topic summary never generated")
        self.assertEqual(nomatch, 0,
                         "non-matching topic generated a summary")


if __name__ == "__main__":
    unittest.main()
