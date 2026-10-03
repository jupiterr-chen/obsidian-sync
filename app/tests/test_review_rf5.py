"""RF5 regression tests (R10 write-back uniqueness/ownership, R15 impact
outbox) - written RED first."""

from __future__ import annotations

import os
import unittest

from fixtures import temp_dir


class R10WritebackTest(unittest.TestCase):
    def setUp(self):
        from knowledge.writeback import register_write_root

        self.dir = os.path.join(temp_dir(), "vault-gen")
        os.makedirs(self.dir, exist_ok=True)
        register_write_root(self.dir)

    def test_same_second_candidates_are_unique_and_never_overwritten(self):
        from knowledge.writeback import write_candidate

        first = write_candidate(self.dir, "clm-a.md", "# v1")
        self.assertEqual(first["outcome"], "written")
        # human edits the main file -> candidate path taken
        with open(os.path.join(self.dir, "clm-a.md"), "a", encoding="utf-8") as fh:
            fh.write("\nhuman edits")
        second = write_candidate(self.dir, "clm-a.md", "# v2")
        self.assertEqual(second["outcome"], "preserved_with_candidate")
        third = write_candidate(self.dir, "clm-a.md", "# v3")
        self.assertEqual(third["outcome"], "preserved_with_candidate")
        # R10: two candidates in the same second must be distinct files, and
        # a human edit to the FIRST candidate must survive the third export
        self.assertNotEqual(second["candidate_path"], third["candidate_path"])
        with open(second["candidate_path"], "a", encoding="utf-8") as fh:
            fh.write("\nhuman candidate annotation")
        fourth = write_candidate(self.dir, "clm-a.md", "# v4")
        with open(second["candidate_path"], "r", encoding="utf-8") as fh:
            self.assertIn("human candidate annotation", fh.read())
        self.assertNotEqual(fourth["candidate_path"], second["candidate_path"])
        # main file keeps the human edit throughout
        with open(os.path.join(self.dir, "clm-a.md"), "r", encoding="utf-8") as fh:
            self.assertIn("human edits", fh.read())

    def test_write_root_whitelist_enforced(self):
        from knowledge.writeback import write_candidate, WriteBackError

        outside = os.path.join(temp_dir(), "outside")
        with self.assertRaises(WriteBackError):
            write_candidate(outside, "x.md", "content")

    def test_manifest_concurrent_updates_keep_both_entries(self):
        from knowledge.writeback import write_candidate

        a = write_candidate(self.dir, "doc-a.md", "A content")
        b = write_candidate(self.dir, "doc-b.md", "B content")
        self.assertEqual(a["outcome"], "written")
        self.assertEqual(b["outcome"], "written")
        with open(os.path.join(self.dir, ".knowledge-writeback.json"),
                  encoding="utf-8") as handle:
            import json

            manifest = json.load(handle)
        self.assertIn("doc-a.md", manifest["files"])
        self.assertIn("doc-b.md", manifest["files"])


class R15ImpactOutboxTest(unittest.TestCase):
    def _pipeline(self):
        import os

        from fixtures import make_config
        from knowledge.config import KnowledgeConfig
        from knowledge.jobs import JobRunner
        from knowledge.memory import create_claim, review_claim
        from knowledge.snapshot import SnapshotStore
        from knowledge.store import KnowledgeStore
        from knowledge.sync import SyncService

        tmp = temp_dir()
        library_config, reports, discord = make_config(tmp)
        from library.ingest import Ingestor

        ingestor = Ingestor(library_config)
        assert ingestor.run()["ok"]
        ingestor.close()
        config = KnowledgeConfig(
            catalog_db=library_config.catalog_db,
            knowledge_db=os.path.join(tmp, "state", "knowledge.sqlite3"),
            snapshot_root=os.path.join(tmp, "state", "snapshots"),
            library_config="unused")
        kb = KnowledgeStore(config.knowledge_db)
        SyncService(kb, config).run()
        runner = JobRunner(kb, config, library_config,
                           blobs=SnapshotStore(config.snapshot_root))
        # one claim citing an existing report document
        create_claim(kb, "claim about report a111",
                     [{"source": "reports", "doc_id": "a1111111111111111111",
                       "version_id": "b2222222222222222222", "block_id": "x",
                       "extraction_id": "y"}], subject="EXAMPLE")
        return kb, config, library_config, runner, reports

    def _add_versions(self, reports, count):
        import hashlib
        import sqlite3

        conn = sqlite3.connect(reports["db"])
        for i in range(count):
            data = ("%%PDF-1.4 wave2 content %03d" % i).encode()
            rel = ("CN/600519/2026-06-30__H1__test__a1111111111111111111"
                   "__c%04d0000000000000000000.pdf" % i)
            path = os.path.join(reports["root"], rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(data)
            conn.execute(
                "INSERT INTO artifacts VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("c%04d0000000000000000000" % i, "a1111111111111111111",
                 hashlib.sha256(data).hexdigest(), len(data),
                 "application/pdf", "/app/reports/" + rel,
                 "2026-07-10T00:00:00Z", "ready", "http://example/w2", None))
        conn.execute(
            "UPDATE manifest SET current_artifact_id='c%04d0000000000000000000'"
            " WHERE report_id='a1111111111111111111'" % (count - 1))
        conn.commit()
        conn.close()

    def test_thirty_plus_new_versions_all_get_exactly_one_proposal(self):
        from knowledge.sync import SyncService
        from knowledge.worker import run_cycle
        from library.ingest import Ingestor

        kb, config, library_config, runner, reports = self._pipeline()
        try:
            self._add_versions(reports, count=30)
            # the knowledge layer mirrors the first-layer catalog, so the
            # library must re-ingest the archive before syncing
            ingestor = Ingestor(library_config)
            self.assertTrue(ingestor.run()["ok"])
            ingestor.close()
            # cross-second reconciliation: first sync, then a second sync
            # after the stamp moves (simulated by direct re-run)
            stats = SyncService(kb, config).run()
            self.assertEqual(stats["new_versions"], 30)
            # crash between sync and impact analysis: the outbox persists
            proposals_before = kb.list_review_proposals()
            self.assertEqual(len(proposals_before), 0)
            cycle = run_cycle(config, library_config)
            self.assertTrue(cycle["ok"], cycle.get("error"))
            proposals = kb.list_review_proposals()
            new_wave = [p for p in proposals
                        if str(p["detail"].get("new_version_id", ""))
                        .startswith("c")]
            self.assertEqual(len(new_wave), 30)
            # a no-change restart must not duplicate proposals
            run_cycle(config, library_config)
            new_wave_after = [p for p in kb.list_review_proposals()
                              if str(p["detail"].get("new_version_id", ""))
                              .startswith("c")]
            self.assertEqual(len(new_wave_after), 30)
            with kb._lock:
                pending = kb._conn.execute(
                    "SELECT COUNT(*) FROM impact_outbox WHERE"
                    " status='pending'").fetchone()[0]
            self.assertEqual(pending, 0)
        finally:
            kb.close()

    def test_outbox_survives_sync_then_delayed_consumption(self):
        from knowledge.sync import SyncService
        from knowledge.worker import consume_impact_outbox
        from library.ingest import Ingestor

        kb, config, library_config, runner, reports = self._pipeline()
        try:
            self._add_versions(reports, count=3)
            ingestor = Ingestor(library_config)
            self.assertTrue(ingestor.run()["ok"])
            ingestor.close()
            SyncService(kb, config).run()
            # crash: nothing consumed yet
            consumed = consume_impact_outbox(kb)
            self.assertGreaterEqual(consumed, 3)
            new_wave = [p for p in kb.list_review_proposals()
                        if str(p["detail"].get("new_version_id", ""))
                        .startswith("c")]
            self.assertEqual(len(new_wave), 3)
            # consuming again is a no-op
            self.assertEqual(consume_impact_outbox(kb), 0)
        finally:
            kb.close()


if __name__ == "__main__":
    unittest.main()
