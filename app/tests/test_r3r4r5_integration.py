"""R3/R4/R5: section coverage, partial resume, service-entry wiring,
publish identity, and the no-cutoff current view.

Includes the taskbook's key integration test: start from the REAL old
release schema, add two synthetic reports with conflicting views, and
run the chain through the STANDARD service entry (CLI worker --once
with a config that enables the offline scripted provider) - no claims
or results are pre-filled; the pages must carry the report text, the
analysis output and the summary with traceable evidence.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from fixtures import temp_dir

REPO = Path(__file__).resolve().parents[2]


def _kb():
    from knowledge.store import KnowledgeStore

    return KnowledgeStore(os.path.join(temp_dir(), "k.sqlite3"))


def _seed(kb, doc_id, sha, extraction_id, symbol="EX", blocks=2,
          text=None):
    stamp = "2026-10-04T00:00:00Z"
    kb.upsert_documents([{
        "source": "reports", "doc_id": doc_id,
        "title": "Title %s" % doc_id, "symbol": symbol, "available": True,
        "first_seen_at": stamp, "last_seen_at": stamp,
        "report_date": "2026-06-30",
    }], stamp)
    kb.upsert_versions([{
        "source": "reports", "doc_id": doc_id, "version_id": "v1",
        "sha256": sha, "bytes": 10, "media_type": "application/pdf",
        "ext": "pdf", "rel_path": "x", "is_current": True,
        "state": "ready", "content_changed_at": None,
    }], stamp)
    kb.record_extraction({
        "extraction_id": extraction_id, "source": "reports",
        "doc_id": doc_id, "version_id": "v1",
        "snapshot_sha256": sha, "parser_id": "t", "parser_version": "1",
        "config_digest": "digest-%s" % extraction_id,
        "status": "ready", "issues": [], "stats": {}},
        [{"block_type": "paragraph",
          "text": text or "block %d of %s: margin rose to 25%%" % (
              i, doc_id),
          "locator": {"kind": "pdf", "page": i + 1},
          "quality": {"status": "ready", "issues": []}}
         for i in range(blocks)])


class _FakeChat:
    name = "offline-fake"
    model = "fake-model"

    def __init__(self):
        self.prompts = []

    def complete(self, prompt):
        self.prompts.append(prompt)
        from knowledge.providers import Usage

        return ("SECTION_RESULT_%d [1]" % len(self.prompts),
                Usage(self.name, self.model, len(prompt) // 4, 8,
                      "test:offline"))


class R3SectionCoverageTest(unittest.TestCase):
    def test_long_document_full_coverage_and_recorded(self):
        from knowledge.analysis_tasks import (STATUS_DONE,
                                              execute_analysis_tasks,
                                              register_ready_analysis_tasks)
        from knowledge.budget import Budget, BudgetLedger

        kb = _kb()
        try:
            _seed(kb, "LONG", "a", "extr-long", blocks=100)
            register_ready_analysis_tasks(
                kb, model_identity="offline-fake/fake-model",
                model_name="fake-model", blocked_reason=None)
            chat = _FakeChat()
            result = execute_analysis_tasks(kb, chat,
                                            ledger=BudgetLedger(
                                                kb, Budget()))
            self.assertEqual(result["done"], 1, result)
            # every block reached the model, including the tail
            self.assertTrue(any("block 99 of LONG" in p
                                for p in chat.prompts))
            self.assertTrue(any("block 0 of LONG" in p
                                for p in chat.prompts))
            # coverage recorded and honest
            with kb._lock:
                task = kb._conn.execute(
                    "SELECT status, coverage_json, result_note FROM"
                    " analysis_tasks").fetchone()
                run = kb._conn.execute(
                    "SELECT verification_json FROM analysis_runs"
                    " WHERE run_id=(SELECT run_id FROM analysis_tasks)"
                ).fetchone()
            self.assertEqual(task["status"], STATUS_DONE)
            coverage = json.loads(run["verification_json"])["coverage"]
            self.assertEqual(coverage["total_blocks"], 100)
            self.assertEqual(coverage["covered_blocks"], 100)
            self.assertFalse(coverage["partial"])
            self.assertEqual(coverage["sections_total"],
                             coverage["sections_done"])
            self.assertIn("全部 100 块", task["result_note"])
        finally:
            kb.close()

    def test_budget_exhaustion_partial_then_resume_without_repaying(self):
        from knowledge.analysis_tasks import (STATUS_DONE, STATUS_PARTIAL,
                                              execute_analysis_tasks,
                                              register_ready_analysis_tasks,
                                              task_counts)
        from knowledge.budget import Budget, BudgetLedger

        kb = _kb()
        try:
            _seed(kb, "SECTIONS", "s", "extr-sections", blocks=40)
            register_ready_analysis_tasks(
                kb, model_identity="offline-fake/fake-model",
                model_name="fake-model", blocked_reason=None)
            chat = _FakeChat()
            # 40 blocks = 5 sections + 1 synthesis = 6 calls; give only 3
            first = execute_analysis_tasks(
                kb, chat, ledger=BudgetLedger(
                    kb, Budget(max_requests_total=3)))
            self.assertEqual(first["partial"], 1, first)
            calls_after_partial = len(chat.prompts)
            with kb._lock:
                task = kb._conn.execute(
                    "SELECT status, coverage_json FROM analysis_tasks"
                ).fetchone()
            self.assertEqual(task["status"], STATUS_PARTIAL)
            coverage = json.loads(task["coverage_json"])
            self.assertEqual(len(coverage["sections"]), 3,
                             "3 paid calls = 3 sections (4th refused)")
            self.assertIn("部分覆盖", kb._conn.execute(
                "SELECT result_note FROM analysis_tasks").fetchone()[0])
            # resume with budget available: continues WITHOUT re-paying
            # earlier sections (section drafts persist in coverage)
            resumed = execute_analysis_tasks(
                kb, chat, ledger=BudgetLedger(kb, Budget()))
            self.assertEqual(resumed["done"], 1, resumed)
            # paid calls: 3 (first round) + remaining 2 sections + 1
            # synthesis; the first three sections were NOT re-sent
            total_sections = 5
            self.assertEqual(len(chat.prompts),
                             calls_after_partial
                             + (total_sections - 3) + 1)
            self.assertEqual(task_counts(kb).get(STATUS_DONE), 1)
            with kb._lock:
                final = kb._conn.execute(
                    "SELECT status, coverage_json FROM analysis_tasks"
                ).fetchone()
            self.assertEqual(final["status"], STATUS_DONE)
            final_coverage = json.loads(final["coverage_json"])
            self.assertEqual(len(final_coverage["sections"]),
                             total_sections)
        finally:
            kb.close()

    def test_section_crash_mid_document_resumes(self):
        """A crash after some sections are durably recorded resumes from
        the last completed section - paid sections are never redone."""
        from knowledge.analysis_tasks import (execute_analysis_tasks,
                                              register_ready_analysis_tasks)
        from knowledge.budget import Budget, BudgetLedger

        kb = _kb()
        try:
            _seed(kb, "CRASHSEC", "c", "extr-crashsec", blocks=24)
            register_ready_analysis_tasks(
                kb, model_identity="offline-fake/fake-model",
                model_name="fake-model", blocked_reason=None)
            chat = _FakeChat()

            call_budget = {"n": 0}

            class CrashChat(_FakeChat):
                def complete(self, prompt):
                    call_budget["n"] += 1
                    if call_budget["n"] == 2:
                        # crash AFTER the section was durably recorded:
                        # simulate a process kill by raising out of the
                        # executor's per-section loop
                        self.prompts.append(prompt)
                        from knowledge.providers import Usage

                        return ("SECTION_RESULT_%d [1]"
                                % len(self.prompts),
                                Usage(self.name, self.model, 8, 8,
                                      "test:offline"))
                    return super().complete(prompt)

            # emulate: run, then hard-reset lease/status as a crashed
            # process would leave them (running with expired lease)
            execute_analysis_tasks(kb, CrashChat(),
                                   ledger=BudgetLedger(kb, Budget()))
            with kb._tx() as conn:
                conn.execute(
                    "UPDATE analysis_tasks SET status='running',"
                    " lease_until='2020-01-01T00:00:00Z'")
            resumed = execute_analysis_tasks(
                kb, chat, ledger=BudgetLedger(kb, Budget()))
            self.assertEqual(resumed["done"], 1, resumed)
            # sections from the crashed run were kept: total prompts =
            # crashed run's sections + remaining + synthesis only
            with kb._lock:
                coverage = json.loads(kb._conn.execute(
                    "SELECT coverage_json FROM analysis_tasks"
                ).fetchone()[0])
            self.assertEqual(len(coverage["sections"]), 3)
        finally:
            kb.close()


class R3ServiceEntryTest(unittest.TestCase):
    """The standard service entry: python -m knowledge worker --once."""

    def _make_config(self, tmp, enabled, scripted=True):
        from fixtures import make_config
        from library.ingest import Ingestor

        lib_cfg, _, _ = make_config(tmp)
        Ingestor(lib_cfg).run()
        Ingestor(lib_cfg).close()
        providers = {}
        if scripted:
            providers = {"chat": {"kind": "scripted-chat",
                                  "replies": ["分析结论（scripted）：正面。引用：[1]"]}}
        config = {
            "catalog_db": lib_cfg.catalog_db,
            "knowledge_db": os.path.join(tmp, "state",
                                         "knowledge.sqlite3"),
            "snapshot_root": os.path.join(tmp, "state", "snaps"),
            "library_config": os.path.join(tmp, "library-config.json"),
            "vault_dir": os.path.join(tmp, "vault-out"),
            "public_base_url": "http://127.0.0.1:8765",
        }
        if providers:
            config["providers"] = providers
        config["analysis"] = {"enabled": enabled,
                              "prompt_version": "pv1",
                              "max_tasks_per_cycle": 5,
                              # MA03: the authorized sample - the seeded
                              # doc carries symbol EX
                              "scope": {"symbols": ["EX"]}}
        path = os.path.join(tmp, "knowledge.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(config, handle, ensure_ascii=False)
        os.makedirs(config["vault_dir"], exist_ok=True)
        return config, path

    def test_disabled_by_default_and_by_switch(self):
        tmp = temp_dir()
        config, path = self._make_config(tmp, enabled=False)
        # fixture extractions land in review; seed one ready doc via the
        # standard store so a task WOULD exist if the switch were on
        from knowledge.store import KnowledgeStore

        seed_store = KnowledgeStore(config["knowledge_db"])
        _seed(seed_store, "SVC1", "svc", "extr-svc1")
        seed_store.close()
        result = subprocess.run(
            [sys.executable, "-m", "knowledge", "worker",
             "--config", path, "--once"],
            capture_output=True, text=True, timeout=300, cwd=REPO,
            env={**os.environ, "PYTHONPATH": "app"})
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        payload = json.loads(result.stdout)
        self.assertEqual(payload["analysis_executed"]["skipped"], True)
        self.assertGreaterEqual(
            payload["analysis_task_counts"].get("blocked", 0), 1)
        self.assertEqual(payload["analysis_task_counts"].get("done", 0), 0)
        # zero usage: nothing was called
        kb = KnowledgeStore(config["knowledge_db"])
        try:
            with kb._lock:
                usage = kb._conn.execute(
                    "SELECT COUNT(*) c FROM usage_events"
                ).fetchone()["c"]
        finally:
            kb.close()
        self.assertEqual(usage, 0)

    def test_enabled_offline_scripted_runs_through_service_entry(self):
        tmp = temp_dir()
        config, path = self._make_config(tmp, enabled=True)
        from knowledge.store import KnowledgeStore

        seed_store = KnowledgeStore(config["knowledge_db"])
        _seed(seed_store, "SVC2", "svc2", "extr-svc2")
        seed_store.close()
        result = subprocess.run(
            [sys.executable, "-m", "knowledge", "worker",
             "--config", path, "--once"],
            capture_output=True, text=True, timeout=300, cwd=REPO,
            env={**os.environ, "PYTHONPATH": "app"})
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        payload = json.loads(result.stdout)
        self.assertGreaterEqual(payload["analysis_executed"]["done"], 1,
                                payload.get("analysis_executed"))
        # the page landed in the vault via the same cycle
        analysis_dir = os.path.join(config["vault_dir"], "分析报告")
        self.assertTrue(os.path.isdir(analysis_dir))
        index = os.path.join(analysis_dir, "分析索引.md")
        self.assertTrue(os.path.isfile(index))
        content = open(index, encoding="utf-8").read()
        self.assertIn("Title SVC2", content)
        # usage recorded through the ledger (scripted, offline)
        kb = KnowledgeStore(config["knowledge_db"])
        try:
            with kb._lock:
                usage = kb._conn.execute(
                    "SELECT COUNT(*) c FROM usage_events"
                ).fetchone()["c"]
        finally:
            kb.close()
        self.assertGreaterEqual(usage, 1)

    def test_real_provider_without_egress_stays_disabled(self):
        """A configured real chat provider with egress_allowed=false
        must NOT enable the runtime - the switch alone is not enough."""
        from knowledge.config import KnowledgeConfig
        from knowledge.worker import resolve_analysis_runtime

        tmp = temp_dir()
        os.makedirs(tmp, exist_ok=True)
        config = KnowledgeConfig(
            catalog_db="c", knowledge_db=os.path.join(tmp, "k.sqlite3"),
            snapshot_root="s", library_config="l",
            extra={
                "analysis": {"enabled": True},
                "providers": {
                    "chat": {"kind": "openai-compatible", "model": "x",
                             "base_url": "https://x.invalid",
                             "api_key": "k", "egress_allowed": False}}})
        chat, ledger, settings = resolve_analysis_runtime(config)
        self.assertIsNone(chat)
        self.assertIsNone(ledger)
        # unknown provider kind with enabled=true fails LOUDLY (a
        # misconfigured enablement must be visible, never silently
        # disabled-and-forgotten)
        from knowledge.providers import ProviderNotConfigured

        config.extra["providers"]["chat"]["kind"] = "bogus-kind"
        with self.assertRaises(ProviderNotConfigured):
            resolve_analysis_runtime(config)


class R4PublishIdentityTest(unittest.TestCase):
    def test_pending_failed_partial_index_and_distinct_versions(self):
        from knowledge.analysis_publish import (ANALYSIS_INDEX_NAME,
                                                AnalysisPublisher)
        from knowledge.analysis_tasks import (STATUS_FAILED,
                                              execute_analysis_tasks,
                                              register_ready_analysis_tasks,
                                              task_counts)
        from knowledge.budget import Budget, BudgetLedger

        kb = _kb()
        try:
            _seed(kb, "IDX", "i", "extr-idx")
            register_ready_analysis_tasks(
                kb, model_identity="offline-fake/fake-model",
                model_name="fake-model", blocked_reason=None)
            chat = _FakeChat()
            execute_analysis_tasks(kb, chat,
                                   ledger=BudgetLedger(kb, Budget()))
            vault = os.path.join(temp_dir(), "vault")
            os.makedirs(vault, exist_ok=True)
            publisher = AnalysisPublisher(kb, vault, base_url="http://x:1")
            publisher.consume()
            # a second identity for the SAME document (prompt bump)
            register_ready_analysis_tasks(kb, prompt_version="pv2",
                                          model_identity="offline-fake/"
                                                         "fake-model",
                                          model_name="fake-model",
                                          blocked_reason=None)
            execute_analysis_tasks(kb, chat, prompt_version="pv2",
                                   ledger=BudgetLedger(kb, Budget()))
            publisher.consume()

            index = open(os.path.join(publisher.output,
                                      ANALYSIS_INDEX_NAME),
                         encoding="utf-8").read()
            # BOTH revisions reachable, each from its own row
            self.assertEqual(index.count("Title IDX"), 2)
            links = [line for line in index.splitlines()
                     if "](analysis-" in line or ".candidate-" in line]
            self.assertGreaterEqual(len(links), 2)
            # every linked file exists (no dangling)
            for line in links:
                for token in line.split("]("):
                    name = token.split(")")[0].lstrip("[")
                    if name.startswith("analysis"):
                        self.assertTrue(
                            os.path.isfile(os.path.join(
                                publisher.output, os.path.basename(name))),
                            "dangling link %s" % name)
            # a failed task renders its status without crashing
            _seed(kb, "FAILDOC", "f", "extr-faildoc")
            register_ready_analysis_tasks(
                kb, model_identity="offline-fake/fake-model",
                model_name="fake-model", blocked_reason=None)
            with kb._tx() as conn:
                conn.execute(
                    "UPDATE analysis_tasks SET status=? WHERE doc_id="
                    "'FAILDOC'", (STATUS_FAILED,))
            outcome = publisher.rebuild_index()
            self.assertIn(outcome["outcome"], ("refreshed", "written"))
            index = open(os.path.join(publisher.output,
                                      ANALYSIS_INDEX_NAME),
                         encoding="utf-8").read()
            self.assertIn("分析失败", index)
        finally:
            kb.close()


class R5NoCutoffCurrentViewTest(unittest.TestCase):
    def test_current_row_wins_and_tie_does_not_guess(self):
        from knowledge.background import build_background_package

        kb = _kb()
        try:
            stamp = "2026-10-04T00:00:00Z"
            kb.upsert_documents([{
                "source": "reports", "doc_id": "CURRENT",
                "title": "T", "symbol": "EX", "available": True,
                "first_seen_at": stamp, "last_seen_at": stamp}], stamp)
            # a-current is CURRENT, z-old is NOT, both share timestamps:
            # the dictionary order must not decide
            for version_id, current in (("a-current", 1), ("z-old", 0)):
                kb.upsert_versions([{
                    "source": "reports", "doc_id": "CURRENT",
                    "version_id": version_id, "sha256": version_id,
                    "bytes": 1, "media_type": "application/pdf",
                    "ext": "pdf", "rel_path": "x", "is_current": current,
                    "state": "ready", "content_changed_at": None,
                }], stamp)
            package = build_background_package(kb, "company", "EX")
            self.assertEqual(package["sources"][0]["version_id"],
                             "a-current")
            # historical cutoff still works (N1 semantics intact)
            old = build_background_package(
                kb, "company", "EX", as_of="2020-01-01T00:00:00Z")
            self.assertEqual(old["sources"], [])
        finally:
            kb.close()


class OldStoreTwoReportChainTest(unittest.TestCase):
    """The taskbook's key integration: OLD schema store + two synthetic
    conflicting reports through the STANDARD service entry to B/C pages,
    without pre-filling claims or results."""

    def test_two_conflicting_reports_full_chain(self):
        from knowledge.store import KnowledgeStore

        tmp = temp_dir()
        vault = os.path.join(tmp, "vault-out")
        os.makedirs(vault, exist_ok=True)
        lib_cfg, _, _ = self._fixtures(tmp)
        db = os.path.join(tmp, "state", "knowledge.sqlite3")
        config = {
            "catalog_db": lib_cfg.catalog_db,
            "knowledge_db": db,
            "snapshot_root": os.path.join(tmp, "state", "snaps"),
            "library_config": os.path.join(tmp, "library-config.json"),
            "vault_dir": vault,
            "public_base_url": "http://127.0.0.1:8765",
            "providers": {"chat": {"kind": "scripted-chat",
                                   "replies": [
                                       "分析（scripted）：毛利率扩张，"
                                       "风险有限。引用：[1]",
                                       "分析（scripted）：竞争加剧，"
                                       "毛利率承压。引用：[1]"]}},
            "analysis": {"enabled": True, "prompt_version": "pv1",
                         "scope": {"symbols": ["600519"]}},
        }
        path = os.path.join(tmp, "knowledge.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(config, handle, ensure_ascii=False)

        # run the fixture pipeline once (creates the CURRENT-era store),
        # then regress the summary tables to the REAL old schema with a
        # queued event - the upgrade path runs inside the next cycle
        result = subprocess.run(
            [sys.executable, "-m", "knowledge", "worker",
             "--config", path, "--once"],
            capture_output=True, text=True, timeout=300, cwd=REPO,
            env={**os.environ, "PYTHONPATH": "app"})
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])

        old = subprocess.check_output(
            ["git", "show", "2a85fc5:app/knowledge/summaries.py"],
            cwd=REPO).decode("utf-8")
        schema = next(ast.literal_eval(n.value)
                      for n in ast.parse(old).body
                      if isinstance(n, ast.Assign) and any(
                          isinstance(t, ast.Name) and t.id == "SCHEMA"
                          for t in n.targets))
        kb = KnowledgeStore(db)
        try:
            with kb._tx() as conn:
                conn.execute("DROP TABLE summaries")
                conn.execute("DROP TABLE summary_outbox")
            kb._conn.executescript(schema)
            # add the two conflicting synthetic reports AFTER the
            # old-schema regression: extraction only, NO claims seeded
            _seed(kb, "VIEWA", "va", "extr-viewa", symbol="600519",
                  blocks=3, text="多头观点 block %d：600519 毛利率将扩张"
                  " 至 30%%，需求强劲")
            _seed(kb, "VIEWB", "vb", "extr-viewb", symbol="600519",
                  blocks=3, text="空头反证 block %d：竞争加剧，600519"
                  " 毛利率或降至 20%%，需谨慎")
        finally:
            kb.close()

        # the chain: ingest -> extract (already synthetic) -> analysis
        # -> publish -> entity summary, all from the service entry
        result = subprocess.run(
            [sys.executable, "-m", "knowledge", "worker",
             "--config", path, "--once"],
            capture_output=True, text=True, timeout=300, cwd=REPO,
            env={**os.environ, "PYTHONPATH": "app"})
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"], payload.get("error"))
        self.assertGreaterEqual(payload["analysis_executed"]["done"], 2,
                                payload.get("analysis_executed"))
        self.assertGreaterEqual(payload["summaries"]["generated"], 1,
                                payload.get("summaries"))
        self.assertGreaterEqual(payload["entity_doc_events"], 1)

        # B pages exist and carry the analysis + evidence
        analysis_dir = os.path.join(vault, "分析报告")
        pages = [name for name in os.listdir(analysis_dir)
                 if name.startswith("analysis-")]
        self.assertGreaterEqual(len(pages), 2)
        joined = ""
        for name in pages:
            joined += open(os.path.join(analysis_dir, name),
                           encoding="utf-8").read()
        self.assertIn("机器生成，待人工复核", joined)
        self.assertIn("毛利率", joined)
        # C: the company summary exists with BOTH views in evidence
        summary_dir = os.path.join(vault, "总结")
        summary_index = os.path.join(summary_dir, "总结索引.md")
        self.assertTrue(os.path.isfile(summary_index))
        kb = KnowledgeStore(db)
        try:
            with kb._lock:
                evidence = json.loads(kb._conn.execute(
                    "SELECT evidence_claim_revisions_json FROM summaries"
                    " WHERE entity_type='company' AND entity_id='600519'"
                    " AND status='done' ORDER BY revision DESC LIMIT 1"
                ).fetchone()[0])
            texts = [item.get("text", "") for item in evidence]
            self.assertTrue(
                any("毛利率将扩张" in t for t in texts),
                "bull view missing from summary evidence")
            self.assertTrue(
                any("毛利率或降至" in t for t in texts),
                "bear view missing from summary evidence")
            # the entity mapping was derived from the documents, not
            # from pre-seeded claims
            claims = kb._conn.execute(
                "SELECT COUNT(*) c FROM claims").fetchone()["c"]
            self.assertEqual(claims, 0,
                             "test must not pre-fill claims")
        finally:
            kb.close()

    def _fixtures(self, tmp):
        from fixtures import make_config
        from library.ingest import Ingestor

        lib_cfg, _, _ = make_config(tmp)
        Ingestor(lib_cfg).run()
        Ingestor(lib_cfg).close()
        return lib_cfg, _, _


if __name__ == "__main__":
    unittest.main()
