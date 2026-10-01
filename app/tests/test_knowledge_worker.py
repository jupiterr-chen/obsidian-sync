"""P6 tests: worker cycle, heartbeat state, backup + restore drill."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

from fixtures import make_config, temp_dir

from knowledge.config import KnowledgeConfig
from knowledge.indexing import build_generation
from knowledge.memory import create_claim, review_claim
from knowledge.store import JOB_DONE, KnowledgeStore
from knowledge.sync import SyncService
from knowledge.worker import (
    KnowledgeWorker,
    read_state,
    run_cycle,
    worker_is_stale,
    worker_state_path,
    write_state,
)

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                       "scripts")


class WorkerCycleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = temp_dir()
        self.library_config, self.reports, self.discord = make_config(self.tmp)
        from library.ingest import Ingestor

        ingestor = Ingestor(self.library_config)
        self.assertTrue(ingestor.run()["ok"])
        ingestor.close()
        self.kb_config = KnowledgeConfig(
            catalog_db=self.library_config.catalog_db,
            knowledge_db=os.path.join(self.tmp, "state", "knowledge.sqlite3"),
            snapshot_root=os.path.join(self.tmp, "state", "snapshots"),
            library_config="unused",
            register_stages=("snapshot", "extract"),
        )

    def test_cycle_is_idempotent_and_publishes_index(self):
        first = run_cycle(self.kb_config, self.library_config)
        self.assertTrue(first["ok"], first.get("error"))
        self.assertGreater(first["counts"]["snapshots"], 0)
        self.assertIsNotNone(first["generation_id"])
        kb = KnowledgeStore(self.kb_config.knowledge_db)
        try:
            baseline = kb.counts()
            self.assertIsNotNone(kb.active_generation())
        finally:
            kb.close()
        second = run_cycle(self.kb_config, self.library_config)
        self.assertTrue(second["ok"])
        kb = KnowledgeStore(self.kb_config.knowledge_db)
        try:
            self.assertEqual(kb.counts(), baseline)  # nothing duplicated (A02)
        finally:
            kb.close()

    def test_cycle_runs_impact_analysis_for_new_versions(self):
        kb = KnowledgeStore(self.kb_config.knowledge_db)
        try:
            run_cycle(self.kb_config, self.library_config)
            evidence = [{
                "source": "reports", "doc_id": "a1111111111111111111",
                "version_id": "b2222222222222222222", "block_id": "x",
                "extraction_id": "y",
            }]
            created = create_claim(kb, "claim about report", evidence,
                                   subject="EXAMPLE")
            review_claim(kb, created["claim_id"], "accept", reviewer="a")
        finally:
            kb.close()
        # a second sync (no new versions) should not create proposals
        second = run_cycle(self.kb_config, self.library_config)
        self.assertTrue(second["ok"])
        self.assertEqual(second["impact_proposals"], 0)

    def test_worker_state_heartbeat_and_staleness(self):
        path = worker_state_path(self.kb_config.knowledge_db)
        write_state(path, {"kind": "knowledge-worker", "state": "idle"})
        state = read_state(path)
        self.assertEqual(state["state"], "idle")
        self.assertIn("updated_at", state)
        self.assertIs(worker_is_stale(path, max_age_seconds=3600), False)
        # write a stale state file directly: write_state would refresh the
        # heartbeat timestamp by design
        stale_state = dict(state)
        stale_state["updated_at"] = "2020-01-01T00:00:00Z"
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(stale_state, handle, ensure_ascii=False)
        self.assertIs(worker_is_stale(path, max_age_seconds=60), True)
        self.assertIsNone(worker_is_stale(path + ".missing"))

    def test_worker_lifecycle_runs_a_cycle(self):
        worker = KnowledgeWorker(self.kb_config, self.library_config,
                                 interval_seconds=60)
        worker.start()
        try:
            import time

            deadline = time.time() + 30
            state = None
            while time.time() < deadline:
                state = read_state(worker_state_path(self.kb_config.knowledge_db))
                if state and state.get("last_cycle"):
                    break
                time.sleep(0.2)
            self.assertIsNotNone(state)
            self.assertTrue(state["last_cycle"].get("ok"),
                            state.get("last_error"))
        finally:
            worker.stop()


class BackupDrillTest(unittest.TestCase):
    def setUp(self):
        self.tmp = temp_dir()
        self.library_config, self.reports, self.discord = make_config(self.tmp)
        from library.ingest import Ingestor

        ingestor = Ingestor(self.library_config)
        self.assertTrue(ingestor.run()["ok"])
        ingestor.close()
        self.kb_config = KnowledgeConfig(
            catalog_db=self.library_config.catalog_db,
            knowledge_db=os.path.join(self.tmp, "state", "knowledge.sqlite3"),
            snapshot_root=os.path.join(self.tmp, "state", "snapshots"),
            library_config="unused",
            register_stages=("snapshot", "extract"),
        )
        cycle = run_cycle(self.kb_config, self.library_config)
        self.assertTrue(cycle["ok"], cycle.get("error"))

    def _run_script(self, *args):
        result = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "backup-knowledge.py"), *args],
            capture_output=True, text=True, cwd=self.tmp, timeout=120)
        return result.returncode, result.stdout, result.stderr

    def test_backup_then_restore_drill_verifies(self):
        out_dir = os.path.join(self.tmp, "backups")
        code, out, err = self._run_script(
            "backup", "--db", self.kb_config.knowledge_db,
            "--out", out_dir, "--snapshots", self.kb_config.snapshot_root)
        self.assertEqual(code, 0, err or out)
        report = json.loads(out)
        self.assertGreater(report["table_counts"]["snapshots"], 0)
        self.assertGreater(report["blobs_copied"], 0)
        backup_db = report["database"]

        code, out, err = self._run_script(
            "drill", "--backup", backup_db,
            "--snapshots", self.kb_config.snapshot_root)
        self.assertEqual(code, 0, err or out)
        drill = json.loads(out)
        self.assertTrue(drill["ok"], drill["problems"])
        self.assertGreater(drill["blobs_verified"], 0)
        self.assertEqual(drill["problems"], [])
        # the drill never touches the production database
        self.assertNotEqual(drill["restored_to"], self.kb_config.knowledge_db)

    def test_drill_detects_corrupted_backup(self):
        out_dir = os.path.join(self.tmp, "backups2")
        code, out, _ = self._run_script(
            "backup", "--db", self.kb_config.knowledge_db, "--out", out_dir)
        self.assertEqual(code, 0)
        backup_db = json.loads(out)["database"]
        with open(backup_db, "r+b") as handle:  # corrupt the backup copy
            handle.write(b"GARBAGEGARBAGE")
        code, out, _ = self._run_script("drill", "--backup", backup_db)
        self.assertNotEqual(code, 0)
        drill = json.loads(out)
        self.assertFalse(drill["ok"])


if __name__ == "__main__":
    unittest.main()
