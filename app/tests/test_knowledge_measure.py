"""Sampling and measurement tests (P1-03/P1-04): contracts on synthetic data."""

from __future__ import annotations

import json
import os
import unittest

from fixtures import make_config, temp_dir

from knowledge.config import KnowledgeConfig
from knowledge.jobs import JobRunner
from knowledge.measure import (
    count_tokens,
    extract_html_text,
    heuristic_counter,
    measure_sample,
    pdf_page_count,
    register_token_counter,
)
from knowledge.sampling import format_of, manifest_digest, select_sample
from knowledge.snapshot import SnapshotStore
from knowledge.store import KnowledgeStore
from knowledge.sync import SyncService


class SamplingMeasureTest(unittest.TestCase):
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
        )
        self.kb = KnowledgeStore(self.kb_config.knowledge_db)
        SyncService(self.kb, self.kb_config).run()
        self.blobs = SnapshotStore(self.kb_config.snapshot_root)
        runner = JobRunner(self.kb, self.kb_config, self.library_config, blobs=self.blobs)
        result = runner.run_snapshot_jobs()
        self.assertTrue(result["ok"], result)

    def tearDown(self):
        self.kb.close()

    def test_sample_is_stratified_deterministic_and_covers_formats(self):
        plan = select_sample(self.kb, total=6, tune=4, blind=2, seed=1)
        manifest = plan.to_manifest()
        self.assertEqual(manifest["actual"]["total"], 6)
        self.assertEqual(manifest["actual"]["tune"] + manifest["actual"]["blind"], 6)
        # both sources present (stratified, not clustered)
        sources = {s["source"] for s in manifest["samples"]}
        self.assertEqual(sources, {"reports", "discord"})
        # deterministic: same seed -> same digest, different seed -> likely other
        again = select_sample(self.kb, total=6, tune=4, blind=2, seed=1).to_manifest()
        self.assertEqual(manifest_digest(manifest), manifest_digest(again))
        # every sample pins the full identity tuple
        for sample in manifest["samples"]:
            self.assertIn("sha256", sample)
            self.assertTrue(sample["sha256"])

    def test_manifest_is_valid_json_contract(self):
        manifest = select_sample(self.kb).to_manifest()
        encoded = json.dumps(manifest, ensure_ascii=False)
        decoded = json.loads(encoded)
        self.assertEqual(decoded["schema"], "researchkb.sample-manifest/1")
        self.assertLessEqual(decoded["actual"]["total"], 30)

    def test_measure_sample_reports_honest_approximation(self):
        manifest = select_sample(self.kb, total=6, tune=4, blind=2).to_manifest()
        report = measure_sample(self.kb, self.blobs, manifest)
        self.assertEqual(report["schema"], "researchkb.measurement-report/1")
        self.assertEqual(report["summary"]["total"], 6)
        # synthetic corpus is pdf-only -> honest "not extracted", no fake numbers
        for row in report["rows"]:
            if row["format"] == "pdf":
                self.assertEqual(row["status"], "not_extracted")
                self.assertIsNone(row["text_chars"])
        self.assertGreaterEqual(len(report["unextracted"]), 1)
        self.assertFalse(report["all_token_counts_exact"])
        self.assertIn("BLOCKED", report["summary"]["token_note"])

    def test_measure_text_and_html_paths(self):
        # hand-build a tiny knowledge store with txt/html versions
        kb = KnowledgeStore(os.path.join(self.tmp, "measure2.sqlite3"))
        try:
            kb.upsert_documents([{
                "source": "reports", "doc_id": "t1", "title": "t",
                "available": True, "first_seen_at": "2026-10-01T00:00:00Z",
                "last_seen_at": "2026-10-01T00:00:00Z",
            }], "2026-10-01T00:00:00Z")
            import hashlib

            txt = "毛利率提升 3.2 个百分点 margin expanded".encode("utf-8")
            html = b"<html><script>bad()</script><body><p>Revenue grew 12%</p></body></html>"
            kb.upsert_versions([
                {"source": "reports", "doc_id": "t1", "version_id": "v-txt",
                 "sha256": hashlib.sha256(txt).hexdigest(), "bytes": len(txt),
                 "media_type": "text/plain", "ext": "txt", "rel_path": "a.txt",
                 "is_current": False, "state": "ready", "content_changed_at": None},
                {"source": "reports", "doc_id": "t1", "version_id": "v-html",
                 "sha256": hashlib.sha256(html).hexdigest(), "bytes": len(html),
                 "media_type": "text/html", "ext": "html", "rel_path": "a.html",
                 "is_current": True, "state": "ready", "content_changed_at": None},
            ], "2026-10-01T00:00:00Z")
            blobs = SnapshotStore(os.path.join(self.tmp, "snap2"))
            from knowledge.snapshot import snapshot_version

            for payload, vid in ((txt, "v-txt"), (html, "v-html")):
                import tempfile

                fd, path = tempfile.mkstemp(dir=self.tmp)
                with os.fdopen(fd, "wb") as handle:
                    handle.write(payload)
                with open(path, "rb") as handle:
                    snapshot_version(kb, blobs, handle, "reports", "t1", vid,
                                     None, len(payload))
            manifest = {
                "schema": "researchkb.sample-manifest/1",
                "samples": [
                    {"source": "reports", "doc_id": "t1", "version_id": "v-txt",
                     "sha256": None, "bytes": len(txt), "media_type": "text/plain",
                     "stratum": "reports|txt|unknown", "split": "tune"},
                    {"source": "reports", "doc_id": "t1", "version_id": "v-html",
                     "sha256": None, "bytes": len(html), "media_type": "text/html",
                     "stratum": "reports|html|unknown", "split": "tune"},
                ],
            }
            report = measure_sample(kb, blobs, manifest)
            rows = {r["version_id"]: r for r in report["rows"]}
            txt_row, html_row = rows["v-txt"], rows["v-html"]
            self.assertEqual(txt_row["status"], "measured")
            self.assertEqual(txt_row["encoding"], "utf-8")
            self.assertGreater(txt_row["text_chars"], 0)
            self.assertGreater(txt_row["token_count"], 0)
            self.assertEqual(txt_row["token_method"], "approximate")
            self.assertEqual(html_row["status"], "measured")
            # baseline html extraction: script stripped, text kept (unit-level)
            text, _ = extract_html_text(html)
            self.assertIn("Revenue grew 12%", text)
            self.assertNotIn("bad()", text)
        finally:
            kb.close()

    def test_heuristic_counter_is_labelled_approximate(self):
        result = heuristic_counter("毛利")
        self.assertEqual(result.method, "approximate")
        self.assertEqual(result.count, 2)  # cjk ~ 1 token per char
        result = heuristic_counter("abcdefgh")
        self.assertEqual(result.count, 2)  # latin ~ 4 chars per token
        # registered exact counter is distinguished from heuristic
        register_token_counter("fake-exact", lambda text: type(
            "R", (), {"count": len(text.split()) // 2 + 1, "tokenizer": "fake",
                      "method": "exact", "note": ""})())
        exact = count_tokens("a b c", "fake-exact")
        self.assertEqual(exact.method, "exact")

    def test_format_of_covers_all_baseline_formats(self):
        self.assertEqual(format_of("application/pdf", None), "pdf")
        self.assertEqual(format_of(None, "html"), "html")
        self.assertEqual(format_of("image/png", None), "img")
        self.assertEqual(format_of("text/plain", None), "txt")
        self.assertEqual(format_of("application/vnd.x", None), "other")

    def test_pdf_page_count_never_guesses(self):
        simple = b"%PDF-1.4 /Type /Page /Type /Page /Type /Pages trailer"
        pages, method = pdf_page_count(simple)
        self.assertEqual(pages, 2)
        self.assertEqual(method, "page-object-scan")
        pages, method = pdf_page_count(b"%PDF /Type /ObjStm ...")
        self.assertIsNone(pages)
        self.assertEqual(method, "object-streams-unsupported")
        pages, method = pdf_page_count(b"%PDF nothing here")
        self.assertIsNone(pages)
        self.assertEqual(method, "no-page-objects-found")


if __name__ == "__main__":
    unittest.main()
