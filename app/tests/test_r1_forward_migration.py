"""R1 (AC01): forward migration for stores created by the previous release.

The AC1 review built an isolated store from the real old SCHEMA (git
2a85fc5) and the new ensure_schema crashed: SCHEMA creates a UNIQUE
INDEX over summary_outbox(event_key) before any ALTER adds that column
to pre-existing tables. Production upgrade path, not a fresh-store
issue. The fix must detect/patch columns BEFORE creating indexes, be
idempotent, survive interrupted migrations, preserve queued events and
revision history, and let a full worker cycle succeed with models off.
"""
from __future__ import annotations

import ast
import os
import subprocess
import unittest
from pathlib import Path

from fixtures import temp_dir

REPO = Path(__file__).resolve().parents[2]


def _kb():
    from knowledge.store import KnowledgeStore

    return KnowledgeStore(os.path.join(temp_dir(), "k.sqlite3"))


def _old_schema() -> str:
    """The REAL previous-release SCHEMA, read from git (not retyped)."""
    source = subprocess.check_output(
        ["git", "show", "2a85fc5:app/knowledge/summaries.py"],
        cwd=REPO).decode("utf-8")
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "SCHEMA"
                for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("SCHEMA not found in the old release source")


def _build_old_store() -> "object":
    """An isolated store with the OLD schema plus realistic content: a
    queued (pending) summary event and one recorded revision."""
    kb = _kb()
    kb._conn.executescript(_old_schema())
    with kb._tx() as conn:
        conn.execute(
            "INSERT INTO summary_outbox (entity_type, entity_id, reason,"
            " detail_json, status, created_at) VALUES"
            " ('company','EX','evidence_changed','{\"p\":1}','pending',"
            " '2026-10-04T00:00:00Z')")
        conn.execute(
            "INSERT INTO summaries (entity_type, entity_id, revision,"
            " status, content, evidence_claim_revisions_json,"
            " blocked_reason, model_identity, created_at) VALUES"
            " ('company','EX',1,'done','old revision content','[]',NULL,"
            " 'old-identity','2026-10-04T00:00:00Z')")
    return kb


class R1ForwardMigrationTest(unittest.TestCase):
    def test_upgrade_old_store_idempotent_and_preserving(self):
        from knowledge.summaries import ensure_schema, pending_updates, \
            summary_history

        kb = _build_old_store()
        try:
            ensure_schema(kb)  # must not raise (AC01 crash)
            # data preserved: the queued event and old revision survive
            self.assertEqual(len(pending_updates(kb)), 1)
            history = summary_history(kb, "company", "EX")
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["content"], "old revision content")
            # new columns exist and the unique index is live
            cols = [r[1] for r in kb._conn.execute(
                "PRAGMA table_info(summary_outbox)").fetchall()]
            self.assertIn("event_key", cols)
            index = kb._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND"
                " name='idx_summary_outbox_event'").fetchone()
            self.assertIsNotNone(index)
            # upgrade twice more: no change, no error (idempotent)
            ensure_schema(kb)
            ensure_schema(kb)
            self.assertEqual(len(pending_updates(kb)), 1)
            # the new event_key uniqueness is enforced after upgrade
            from knowledge.summaries import enqueue_summary_update

            self.assertTrue(enqueue_summary_update(
                kb, "company", "EX", "reason-x", None, event_key="k1"))
            self.assertFalse(enqueue_summary_update(
                kb, "company", "EX", "reason-x", None, event_key="k1"))
        finally:
            kb.close()

    def test_interrupted_migration_retries_cleanly(self):
        """Simulate a crash after the first ALTER committed: the retry
        completes the migration without error or data loss."""
        from knowledge.summaries import ensure_schema

        kb = _build_old_store()
        try:
            with kb._tx() as conn:
                conn.execute(
                    "ALTER TABLE summary_outbox ADD COLUMN event_key TEXT")
            # interrupt here (summaries.event_key still missing, index
            # not yet created); the retry must complete everything
            ensure_schema(kb)
            ensure_schema(kb)
            for table in ("summary_outbox", "summaries"):
                cols = [r[1] for r in kb._conn.execute(
                    "PRAGMA table_info(%s)" % table).fetchall()]
                self.assertIn("event_key", cols, table)
            index = kb._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND"
                " name='idx_summary_outbox_event'").fetchone()
            self.assertIsNotNone(index)
            rows = kb._conn.execute(
                "SELECT COUNT(*) c FROM summaries").fetchone()["c"]
            self.assertEqual(rows, 1)
        finally:
            kb.close()

    def test_old_store_full_worker_cycle_with_models_off(self):
        """The production upgrade path: a store created by the previous
        release runs a FULL worker cycle with no provider - no crash in
        the second half of the cycle (the review's failure mode)."""
        from knowledge.config import KnowledgeConfig
        from knowledge.summaries import consume_updates, ensure_schema
        from knowledge.worker import run_cycle
        from library.config import Config
        from library.ingest import Ingestor

        tmp = temp_dir()
        from fixtures import make_config

        lib_cfg, _, _ = make_config(tmp)
        Ingestor(lib_cfg).run()
        Ingestor(lib_cfg).close()
        cfg = KnowledgeConfig(
            catalog_db=lib_cfg.catalog_db,
            knowledge_db=os.path.join(tmp, "state", "knowledge.sqlite3"),
            snapshot_root=os.path.join(tmp, "state", "snaps"),
            library_config="unused")
        # run one cycle with the CURRENT code (fresh store), then
        # regress the summary tables to the OLD release shape with real
        # content, then run the next cycle over the upgraded store
        first = run_cycle(cfg, lib_cfg)
        self.assertTrue(first["ok"], first.get("error"))
        kb_path = cfg.knowledge_db

        from knowledge.store import KnowledgeStore

        kb = KnowledgeStore(kb_path)
        try:
            with kb._tx() as conn:
                conn.execute("DROP TABLE summaries")
                conn.execute("DROP TABLE summary_outbox")
            kb._conn.executescript(_old_schema())
            with kb._tx() as conn:
                conn.execute(
                    "INSERT INTO summary_outbox (entity_type, entity_id,"
                    " reason, detail_json, status, created_at) VALUES"
                    " ('company','EX','evidence_changed','{}','pending',"
                    " '2026-10-04T00:00:00Z')")
        finally:
            kb.close()

        second = run_cycle(cfg, lib_cfg)  # models off the whole time
        self.assertTrue(second["ok"], second.get("error"))
        self.assertGreaterEqual(second["summaries"]["blocked"], 1,
                                "old queued event was not consumed")
        # and the cycle after that stays clean (converged)
        third = run_cycle(cfg, lib_cfg)
        self.assertTrue(third["ok"], third.get("error"))


if __name__ == "__main__":
    unittest.main()
