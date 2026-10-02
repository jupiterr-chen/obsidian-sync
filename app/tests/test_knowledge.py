"""Knowledge layer tests: idempotent sync, immutable snapshots, job recovery.

All fixtures are synthetic (reports/discord fake archives from fixtures.py);
no real documents are needed. Covers acceptance scenarios A02 (idempotency)
and A03 (version/recovery) at the offline level.
"""

from __future__ import annotations

import io
import json
import os
import sqlite3
import unittest

from fixtures import build_reports_fixture, make_config, temp_dir

from knowledge.config import KnowledgeConfig
from knowledge.jobs import JobRunner
from knowledge.snapshot import (
    SnapshotStore,
    SnapshotError,
    SourceConflict,
    snapshot_version,
)
from knowledge.store import (
    IntegrityError,
    JOB_DONE,
    JOB_FAILED,
    JOB_PENDING,
    JOB_RUNNING,
    KnowledgeStore,
    config_digest,
    idempotency_key,
)
from knowledge.sync import SyncService, open_catalog_readonly


class KnowledgeLayerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = temp_dir()
        self.library_config, self.reports, self.discord = make_config(self.tmp)
        from library.ingest import Ingestor

        ingestor = Ingestor(self.library_config)
        summary = ingestor.run()
        ingestor.close()
        self.assertTrue(summary["ok"], summary)
        self.kb_config = KnowledgeConfig(
            catalog_db=self.library_config.catalog_db,
            knowledge_db=os.path.join(self.tmp, "state", "knowledge.sqlite3"),
            snapshot_root=os.path.join(self.tmp, "state", "snapshots"),
            library_config=os.path.join(self.tmp, "config.json"),
        )
        self.kb = KnowledgeStore(self.kb_config.knowledge_db)
        self.sync = SyncService(self.kb, self.kb_config)
        self.blobs = SnapshotStore(self.kb_config.snapshot_root)

    def tearDown(self):
        self.kb.close()

    def _runner(self):
        return JobRunner(self.kb, self.kb_config, self.library_config, blobs=self.blobs)

    # ---------------------------------------------------------------- A02
    def test_sync_three_runs_produce_no_duplicates(self):
        first = self.sync.run()
        baseline = self.kb.counts()
        self.assertTrue(first["ok"])
        self.assertGreater(baseline["documents"], 0)
        self.assertGreater(baseline["versions"], 0)

        for _ in range(2):
            stats = self.sync.run()
            self.assertEqual(stats["new_documents"], 0)
            self.assertEqual(stats["new_versions"], 0)
            self.assertEqual(stats["jobs_registered"], 0)

        self.assertEqual(self.kb.counts(), baseline)
        jobs = self.kb.job_counts("snapshot")
        self.assertEqual(jobs[JOB_PENDING], baseline["versions"])
        self.assertEqual(jobs[JOB_DONE] + jobs[JOB_FAILED] + jobs[JOB_RUNNING], 0)

    def test_job_registration_is_idempotent(self):
        self.kb.upsert_versions([{
            "source": "reports", "doc_id": "a", "version_id": "v1",
            "sha256": None, "bytes": None, "media_type": None, "ext": None,
            "rel_path": None, "is_current": True, "state": "ready",
            "content_changed_at": None,
        }], "2026-10-01T00:00:00Z")
        digest = config_digest({"store": "content-addressed", "format": 1})
        self.assertTrue(self.kb.register_job("reports", "a", "v1", "snapshot", digest))
        self.assertFalse(self.kb.register_job("reports", "a", "v1", "snapshot", digest))
        self.assertFalse(self.kb.register_job("reports", "a", "v1", "snapshot", digest))
        other = config_digest({"store": "content-addressed", "format": 2})
        self.assertTrue(self.kb.register_job("reports", "a", "v1", "snapshot", other))
        counts = self.kb.job_counts("snapshot")
        self.assertEqual(counts[JOB_PENDING], 2)
        # distinct tuple -> distinct idempotency key
        self.assertNotEqual(
            idempotency_key("reports", "a", "v1", "snapshot", digest),
            idempotency_key("discord", "a", "v1", "snapshot", digest),
        )

    def test_runner_snapshots_all_versions_and_reruns_are_noops(self):
        self.sync.run()
        result = self._runner().run_snapshot_jobs()
        self.assertTrue(result["ok"], result)
        counts = self.kb.counts()
        self.assertEqual(counts["snapshots"], counts["versions"])
        self.assertEqual(counts["blobs"], counts["versions"])
        self.assertEqual(self.kb.job_counts("snapshot")[JOB_DONE], counts["versions"])

        # every blob on disk matches its sha256 identity and size
        from knowledge.store import utc_now  # noqa: F401  (import check)

        for row in self.kb._conn.execute("SELECT * FROM snapshots").fetchall():
            path = os.path.join(self.blobs.root, row["store_path"])
            self.assertTrue(os.path.isfile(path), path)
            self.assertEqual(os.path.getsize(path), row["bytes"])

        # second full cycle: nothing new (A02 - files and rows stable)
        self.sync.run()
        second = self._runner().run_snapshot_jobs()
        self.assertEqual(second["processed"], 0)
        self.assertEqual(self.kb.counts(), counts)

    # ---------------------------------------------------------------- A03
    def test_new_version_creates_new_rows_and_old_stays_readable(self):
        self.sync.run()
        self._runner().run_snapshot_jobs()
        before_counts = self.kb.counts()
        old_snap = self.kb.get_snapshot("reports", "a1111111111111111111",
                                        "b2222222222222222222")
        self.assertIsNotNone(old_snap)

        # add a third artifact as the new current version of the same report
        root = self.reports["root"]
        rel_three = ("CN/600519/2026-06-30__H1__test__a1111111111111111111"
                     "__b3333333333333333333.pdf")
        data = b"%PDF-1.4 third version content"
        os.makedirs(os.path.dirname(os.path.join(root, rel_three)), exist_ok=True)
        with open(os.path.join(root, rel_three), "wb") as handle:
            handle.write(data)
        import hashlib

        sha_three = hashlib.sha256(data).hexdigest()
        conn = sqlite3.connect(self.reports["db"])
        conn.execute(
            "INSERT INTO artifacts VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("b3333333333333333333", "a1111111111111111111", sha_three, len(data),
             "application/pdf", "/app/reports/" + rel_three,
             "2026-07-03T00:00:00Z", "ready", "http://example/f3", None),
        )
        conn.execute(
            "UPDATE manifest SET current_artifact_id='b3333333333333333333'"
            " WHERE report_id='a1111111111111111111'")
        conn.commit()
        conn.close()

        from library.ingest import Ingestor

        ingestor = Ingestor(self.library_config)
        self.assertTrue(ingestor.run()["ok"])
        ingestor.close()

        stats = self.sync.run()
        self.assertEqual(stats["new_versions"], 1)
        self.assertEqual(stats["jobs_registered"], 1)
        result = self._runner().run_snapshot_jobs()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["processed"], 1)

        after = self.kb.counts()
        self.assertEqual(after["versions"], before_counts["versions"] + 1)
        self.assertEqual(after["snapshots"], before_counts["snapshots"] + 1)

        # the old version's snapshot binding and blob are untouched
        self.assertEqual(
            self.kb.get_snapshot("reports", "a1111111111111111111",
                                 "b2222222222222222222"),
            old_snap)
        old_path = os.path.join(self.blobs.root, old_snap["store_path"])
        self.assertTrue(os.path.isfile(old_path))
        with open(old_path, "rb") as handle:
            self.assertEqual(hashlib.sha256(handle.read()).hexdigest(), old_snap["sha256"])

    def test_upstream_overwrite_fails_closed_and_keeps_old_snapshot(self):
        self.sync.run()
        self._runner().run_snapshot_jobs()
        target_rel = self.reports["rel_two"]
        target = os.path.join(self.reports["root"], target_rel)
        with open(target, "wb") as handle:  # overwrite upstream bytes in place
            handle.write(b"%PDF-1.4 tampered upstream bytes")

        from library.ingest import Ingestor

        ingestor = Ingestor(self.library_config)
        self.assertTrue(ingestor.run()["ok"])
        ingestor.close()

        stats = self.sync.run()
        # conflicted version must not be enqueued for snapshotting
        self.assertEqual(stats["jobs_registered"], 0)
        version = self.kb.get_version("reports", "a1111111111111111111",
                                      "b2222222222222222222")
        self.assertEqual(version["state"], "conflict")

        # previously verified snapshot remains bound and readable
        snap = self.kb.get_snapshot("reports", "a1111111111111111111",
                                    "b2222222222222222222")
        self.assertIsNotNone(snap)
        path = os.path.join(self.blobs.root, snap["store_path"])
        self.assertTrue(os.path.isfile(path))
        # no jobs left to run; runner is a no-op
        self.assertEqual(self._runner().run_snapshot_jobs()["processed"], 0)

    def test_source_hash_mismatch_fails_closed(self):
        self.sync.run()
        # tamper the file behind the current version without telling the
        # catalog; same length, different bytes -> size check passes, hash fails
        target = os.path.join(self.reports["root"], self.reports["rel_two"])
        with open(target, "r+b") as handle:
            handle.write(b"XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX")
        result = self._runner().run_snapshot_jobs()
        self.assertFalse(result["ok"])
        self.assertEqual(result["failed"], 1)
        self.assertIn("source hash mismatch", json.dumps(result["errors"]))
        # the failed job is permanent (identity conflict), not retried forever
        self.assertEqual(self.kb.job_counts("snapshot")[JOB_FAILED], 1)
        self.assertEqual(self.kb.job_counts("snapshot")[JOB_PENDING], 0)

    def test_interrupted_job_recovers_via_lease_expiry(self):
        self.sync.run()
        job = self.kb.claim_next_job("snapshot", lease_seconds=900)
        self.assertIsNotNone(job)
        self.assertEqual(job["status"], JOB_RUNNING)
        # simulate a crash: lease expired while the job was still "running"
        with self.kb._tx() as conn:
            conn.execute("UPDATE jobs SET lease_until='2000-01-01T00:00:00Z' WHERE id=?",
                         (job["id"],))
        recovered = self.kb.recover_stale_jobs("snapshot")
        self.assertEqual(recovered, 1)
        result = self._runner().run_snapshot_jobs()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["recovered"], 0)
        self.assertEqual(self.kb.job_counts("snapshot")[JOB_DONE],
                         self.kb.counts()["versions"])

    # ------------------------------------------------------ snapshot store
    def _source_file(self, payload: bytes) -> object:
        """A real opened file (the snapshot path requires a file descriptor)."""
        import tempfile

        fd, path = tempfile.mkstemp(prefix="knowledge-src-", dir=self.tmp)
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        return open(path, "rb")

    def test_blobs_are_deduplicated_across_versions(self):
        payload = b"identical content across sources"
        handle_a = self._source_file(payload)
        digest_a = snapshot_version(
            self.kb, self.blobs, handle_a,
            "reports", "doc-a", "v1", None, len(payload))
        handle_a.close()
        handle_b = self._source_file(payload)
        digest_b = snapshot_version(
            self.kb, self.blobs, handle_b,
            "discord", "doc-b", "v9", None, len(payload))
        handle_b.close()
        self.assertEqual(digest_a, digest_b)
        self.assertEqual(self.kb.counts()["blobs"], 1)
        self.assertEqual(self.kb.counts()["snapshots"], 2)

    def test_corrupted_blob_detected_and_never_overwritten(self):
        payload = b"payload that will be corrupted later"
        handle = self._source_file(payload)
        digest = snapshot_version(
            self.kb, self.blobs, handle,
            "reports", "doc-a", "v1", None, len(payload))
        handle.close()
        path = self.blobs.blob_abs_path(digest)
        with open(path, "r+b") as handle:  # corrupt without changing identity row
            handle.write(b"XXXX")
        handle = self._source_file(payload)
        with self.assertRaises(IntegrityError):
            snapshot_version(
                self.kb, self.blobs, handle,
                "reports", "doc-b", "v2", None, len(payload))
        handle.close()
        # the (corrupted) blob file is still there - never deleted/overwritten
        self.assertTrue(os.path.isfile(path))

    def test_snapshot_identity_rewrite_refused(self):
        handle = self._source_file(b"first bytes")
        snapshot_version(self.kb, self.blobs, handle,
                         "reports", "doc-a", "v1", None, 11)
        handle.close()
        handle = self._source_file(b"other bytes")
        with self.assertRaises(IntegrityError):
            snapshot_version(self.kb, self.blobs, handle,
                             "reports", "doc-a", "v1", None, None)
        handle.close()

    def test_unstable_source_fails_closed(self):
        from knowledge.snapshot import SourceUnstable, _verify_stable

        class Stat:
            def __init__(self, size, mtime):
                self.st_size = size
                self.st_mtime_ns = mtime

        # identical stats pass, any drift (size or mtime) fails closed
        _verify_stable(None, Stat(10, 1), Stat(10, 1))
        with self.assertRaises(SourceUnstable):
            _verify_stable(None, Stat(10, 1), Stat(20, 1))
        with self.assertRaises(SourceUnstable):
            _verify_stable(None, Stat(10, 1), Stat(10, 2))

    def test_size_mismatch_against_catalog_fails_closed(self):
        handle = self._source_file(b"short")
        with self.assertRaises(SourceConflict):
            snapshot_version(
                self.kb, self.blobs, handle,
                "reports", "doc-a", "v1", None, expected_bytes=999)
        handle.close()

    # ---------------------------------------------------------- catalog ro
    def test_catalog_opened_read_only(self):
        conn = open_catalog_readonly(self.kb_config.catalog_db)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("DELETE FROM documents")
        finally:
            conn.close()

    # --------------------------------------------------------------- CLI
    def test_cli_sync_and_run_snapshots(self):
        config_path = os.path.join(self.tmp, "knowledge.json")
        library_config_path = os.path.join(self.tmp, "library.json")
        with open(library_config_path, "w", encoding="utf-8") as handle:
            json.dump({
                "catalog_db": self.library_config.catalog_db,
                "vault_dir": self.library_config.vault_dir,
                "state_dir": self.library_config.state_dir,
                "sources": {
                    name: {"type": cfg.type, "root": cfg.root, **cfg.extra}
                    for name, cfg in self.library_config.sources.items()
                },
                "human_dirs": dict(self.library_config.human_dirs),
            }, handle)
        with open(config_path, "w", encoding="utf-8") as handle:
            json.dump({
                "catalog_db": self.kb_config.catalog_db,
                "knowledge_db": self.kb_config.knowledge_db,
                "snapshot_root": self.kb_config.snapshot_root,
                "library_config": library_config_path,
            }, handle)
        from knowledge.__main__ import main

        self.assertEqual(main(["sync", "--config", config_path]), 0)
        self.assertEqual(main(["run-snapshots", "--config", config_path]), 0)
        self.assertEqual(main(["status", "--config", config_path]), 0)
        counts = self.kb.counts()
        self.assertEqual(counts["snapshots"], counts["versions"])
        self.assertEqual(self.kb.job_counts("snapshot")[JOB_DONE], counts["versions"])

    def test_cli_rebuild_index_and_evidence_links(self):
        """Regression: special subcommands must dispatch before the generic
        fallback (rebuild-index used to raise 'unknown command')."""
        from knowledge.__main__ import main

        self.sync.run()
        self._runner().run_snapshot_jobs()
        self.kb_config.register_stages = ("snapshot", "extract")
        extract_result = self._runner().run_extract_jobs()
        self.assertTrue(extract_result["ok"], extract_result.get("errors"))
        config_path = os.path.join(self.tmp, "knowledge-cli.json")
        with open(config_path, "w", encoding="utf-8") as handle:
            json.dump({
                "catalog_db": self.kb_config.catalog_db,
                "knowledge_db": self.kb_config.knowledge_db,
                "snapshot_root": self.kb_config.snapshot_root,
                "library_config": os.path.join(self.tmp, "unused.json"),
            }, handle)
        self.assertEqual(main(["rebuild-index", "--config", config_path]), 0)
        self.assertIsNotNone(self.kb.active_generation())
        # rebuild again: unchanged manifest is a no-op but still exit 0
        self.assertEqual(main(["rebuild-index", "--config", config_path]), 0)
        # evidence-links over a real snapshot version
        with self.kb._lock:
            row = self.kb._conn.execute(
                "SELECT s.source, s.doc_id FROM snapshots s JOIN extractions e"
                " ON e.source = s.source AND e.doc_id = s.doc_id"
                " JOIN blocks b ON b.extraction_id = e.extraction_id"
                " LIMIT 1").fetchone()
        out_path = os.path.join(self.tmp, "links.md")
        self.assertEqual(main(["evidence-links", "--config", config_path,
                               "--source", row["source"],
                               "--doc-id", row["doc_id"], "--out", out_path]), 0)
        self.assertTrue(os.path.isfile(out_path))
        with open(out_path, "r", encoding="utf-8") as handle:
            markdown = handle.read()
        self.assertIn("证据索引", markdown)
        self.assertIn("/api/kb/v1/evidence/", markdown)


if __name__ == "__main__":
    unittest.main()
