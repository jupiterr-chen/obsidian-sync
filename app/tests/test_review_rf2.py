"""RF2 regression tests (R04 snapshot integrity, R02 config identity,
R05 PDF page order/quality, R06 HTML offsets) - written RED first."""

from __future__ import annotations

import json
import os
import unittest

from fixtures import temp_dir


def _pipeline(register_stages=("snapshot", "extract")):
    """Full synthetic pipeline fixture (library -> snapshots -> extracts)."""
    from fixtures import make_config
    from knowledge.config import KnowledgeConfig
    from knowledge.jobs import JobRunner
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
        library_config="unused", register_stages=register_stages)
    kb = KnowledgeStore(config.knowledge_db)
    SyncService(kb, config).run()
    runner = JobRunner(kb, config, library_config,
                       blobs=SnapshotStore(config.snapshot_root))
    if "snapshot" in register_stages:
        result = runner.run_snapshot_jobs()
        assert result["ok"], result.get("errors")
    return kb, config, library_config, runner, reports


class R04SnapshotIntegrityTest(unittest.TestCase):
    """R04: consumers must verify blob bytes; corruption fails closed."""

    def _first_snapshot(self, kb):
        with kb._lock:
            row = kb._conn.execute(
                "SELECT * FROM snapshots LIMIT 1").fetchone()
        return dict(row)

    def test_corrupted_blob_same_size_blocks_extraction(self):
        kb, config, library_config, runner, reports = _pipeline(
            register_stages=("snapshot",))
        try:
            self.assertTrue(runner.run_snapshot_jobs()["ok"])
            snap = self._first_snapshot(kb)
            path = os.path.join(runner.blobs.root,
                                *snap["store_path"].split("/"))
            with open(path, "r+b") as handle:  # same-size corruption
                handle.seek(0)
                handle.write(b"XXXXXXXXXX")
            config.register_stages = ("snapshot", "extract")
            result = runner.run_extract_jobs()
            self.assertEqual(result["failed"], 1)
            self.assertIn("corrupt", json.dumps(result["errors"]))
            # no evidence published under the stale sha
            extraction = kb.latest_extraction(snap["source"], snap["doc_id"],
                                               snap["version_id"])
            self.assertIsNone(extraction)
            # snapshot marked corrupted for operators
            marked = kb.get_snapshot(snap["source"], snap["doc_id"],
                                     snap["version_id"])
            self.assertEqual(marked.get("state"), "corrupted")
        finally:
            kb.close()

    def test_corrupted_blob_different_size_fails_closed(self):
        kb, config, library_config, runner, reports = _pipeline(
            register_stages=("snapshot",))
        try:
            self.assertTrue(runner.run_snapshot_jobs()["ok"])
            snap = self._first_snapshot(kb)
            path = os.path.join(runner.blobs.root,
                                *snap["store_path"].split("/"))
            with open(path, "ab") as handle:
                handle.write(b"extra bytes")
            config.register_stages = ("snapshot", "extract")
            result = runner.run_extract_jobs()
            self.assertEqual(result["failed"], 1)
        finally:
            kb.close()

    def test_revisit_of_bound_snapshot_verifies_bytes(self):
        kb, config, library_config, runner, reports = _pipeline(
            register_stages=("snapshot",))
        try:
            self.assertTrue(runner.run_snapshot_jobs()["ok"])
            snap = self._first_snapshot(kb)
            path = os.path.join(runner.blobs.root,
                                *snap["store_path"].split("/"))
            with open(path, "r+b") as handle:
                handle.write(b"ZZZZ")
            with self.assertRaises(Exception):
                runner._execute_snapshot({
                    "id": 1, "source": snap["source"],
                    "doc_id": snap["doc_id"],
                    "version_id": snap["version_id"]})
        finally:
            kb.close()


class R02ConfigIdentityTest(unittest.TestCase):
    """R02: effective OCR settings must be part of the task identity."""

    def test_engine_and_dpi_change_the_digest(self):
        from knowledge.extract import extract_config_digest
        from knowledge.ocr import OcrConfig

        off = extract_config_digest(OcrConfig(engine="off"))
        local300 = extract_config_digest(
            OcrConfig(engine="local", render_dpi=300))
        local200 = extract_config_digest(OcrConfig(engine="local"))
        self.assertNotEqual(off, local300)
        self.assertNotEqual(local300, local200)

    def test_provider_model_changes_digest_but_secret_does_not(self):
        from knowledge.extract import extract_config_digest
        from knowledge.ocr import OcrConfig

        cfg = OcrConfig(engine="vision-api")
        with_m1 = extract_config_digest(
            cfg, provider_specs={"vision_ocr": {"model": "GLM-5.3-Flash",
                                                "api_key": "k1"}})
        with_m2 = extract_config_digest(
            cfg, provider_specs={"vision_ocr": {"model": "GLM-5.3",
                                                "api_key": "k1"}})
        self.assertNotEqual(with_m1, with_m2)
        same_model_new_key = extract_config_digest(
            cfg, provider_specs={"vision_ocr": {"model": "GLM-5.3-Flash",
                                                "api_key": "DIFFERENT"}})
        self.assertEqual(with_m1, same_model_new_key)  # secrets excluded

    def test_rerun_same_config_skips_extractor_entirely(self):
        kb, config, library_config, runner, reports = _pipeline()
        try:
            first = runner.run_extract_jobs()
            self.assertTrue(first["ok"], first.get("errors"))
            with kb._lock:
                before = kb._conn.execute(
                    "SELECT COUNT(*) FROM extractions").fetchone()[0]
            # re-arm the jobs so the run reaches the extraction_id check
            # (job-level done would otherwise short-circuit the probe)
            with kb._tx() as conn:
                conn.execute(
                    "UPDATE jobs SET status='pending' WHERE stage='extract'")

            import knowledge.jobs as jobs_module

            calls = []
            real_get = jobs_module.get_extractor

            def counting(fmt):
                calls.append(fmt)
                return real_get(fmt)

            jobs_module.get_extractor = counting
            try:
                second = runner.run_extract_jobs()
            finally:
                jobs_module.get_extractor = real_get
            self.assertEqual(calls, [])  # identity check happens pre-extract
            self.assertEqual(second["processed"], first["processed"])
            with kb._lock:
                after = kb._conn.execute(
                    "SELECT COUNT(*) FROM extractions").fetchone()[0]
            self.assertEqual(after, before)
        finally:
            kb.close()

    def test_config_change_creates_new_extraction_identity(self):
        kb, config, library_config, runner, reports = _pipeline()
        try:
            self.assertTrue(runner.run_extract_jobs()["ok"])
            with kb._lock:
                row = kb._conn.execute(
                    "SELECT source, doc_id, version_id FROM snapshots"
                    " LIMIT 1").fetchone()
            snap = dict(row)
            before = kb.latest_extraction(**snap)
            self.assertIsNotNone(before)
            from knowledge.ocr import OcrConfig

            config.extra["ocr"] = {"engine": "local", "render_dpi": 300}
            runner.extract_digest = runner._current_extract_digest()
            kb.register_job(snap["source"], snap["doc_id"],
                            snap["version_id"], "extract",
                            runner.extract_digest)
            outcome = runner.run_extract_jobs()
            self.assertTrue(outcome["ok"], outcome.get("errors"))
            after = kb.latest_extraction(**snap)
            self.assertIsNotNone(after)
            self.assertNotEqual(after["extraction_id"],
                                before["extraction_id"])
        finally:
            kb.close()


class R05PdfOrderingTest(unittest.TestCase):
    """R05: page order follows the page tree; gaps are not silently ready."""

    @staticmethod
    def _make_pdf(objects: dict) -> bytes:
        """Serialize a structurally valid PDF (catalog, xref, trailer)."""
        out = bytearray(b"%PDF-1.4\n")
        offsets = {}
        for num in sorted(objects):
            offsets[num] = len(out)
            out += b"%d 0 obj\n" % num + objects[num] + b"\nendobj\n"
        xref_pos = len(out)
        max_num = max(objects)
        out += b"xref\n0 %d\n" % (max_num + 1)
        out += b"0000000000 65535 f \n"
        for num in range(1, max_num + 1):
            if num in offsets:
                out += b"%010d 00000 n \n" % offsets[num]
            else:
                out += b"0000000000 65535 f \n"
        out += (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF"
                % (max_num + 1, xref_pos))
        return bytes(out)

    @staticmethod
    def _stream_body(content: bytes) -> bytes:
        return (b"<< /Length %d >>\nstream\n" % len(content) + content
                + b"\nendstream")

    @staticmethod
    def _page(parent: int, contents: int) -> bytes:
        return (b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 612 792]"
                b" /Contents %d 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
                % (parent, contents))

    def _build(self, kids_order):
        # FIRST lives in the HIGHER object number so object-number ordering
        # (the review's counterexample) would put SECOND on page 1
        kids = b" ".join(b"%d 0 R" % k for k in kids_order)
        objects = {
            1: b"<< /Type /Catalog /Pages 2 0 R >>",
            2: b"<< /Type /Pages /Kids [%s] /Count 2 >>" % kids,
            3: self._page(2, 4),
            4: self._stream_body(b"BT /F1 12 Tf 72 720 Td (SECOND page text body) Tj ET"),
            5: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            8: self._stream_body(b"BT /F1 12 Tf 72 720 Td (FIRST page text body) Tj ET"),
            9: self._page(2, 8),
        }
        return self._make_pdf(objects)

    def test_page_order_follows_kids_not_object_numbers(self):
        from knowledge.extract import extract_pdf

        raw = self._build(kids_order=[9, 3])
        result = extract_pdf(raw)
        self.assertEqual(result.parser_id, "pypdfium2")
        pages_of = {}
        for block in result.blocks:
            if block.locator.get("kind") == "pdf":
                pages_of[block.locator["page"]] = block.text
        self.assertIn("FIRST", pages_of.get(1, ""))
        self.assertIn("SECOND", pages_of.get(2, ""))

    def test_stdlib_fallback_also_follows_kids(self):
        from knowledge.extract import _stdlib_pdf_pages

        raw = self._build(kids_order=[9, 3])
        pages = _stdlib_pdf_pages(raw)
        self.assertEqual(len(pages), 2)
        self.assertIn(b"FIRST", pages[0][1])

    def test_sparse_and_missing_pages_are_not_ready(self):
        from knowledge.extract import extract_pdf

        objects = {
            1: b"<< /Type /Catalog /Pages 2 0 R >>",
            2: b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
            3: self._page(2, 6),
            4: self._page(2, 0),  # no /Contents at all
            5: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            6: self._stream_body(b"BT /F1 12 Tf 72 720 Td (dense body text on page one) Tj ET"),
        }
        result = extract_pdf(self._make_pdf(objects))
        self.assertNotEqual(result.status, "ready")
        self.assertTrue(any("missing" in i or "needs_ocr" in i
                            for i in result.issues))
        self.assertEqual(result.stats.get("pages"), 2)
        self.assertEqual(len(result.stats.get("chars_per_page") or []), 2)


class R06HtmlOffsetsTest(unittest.TestCase):
    """R06: duplicate paragraphs locate to their own occurrences."""

    def test_duplicate_paragraphs_get_distinct_spans(self):
        from knowledge.extract import extract_html

        raw = (b"<html><body><div><p>identical paragraph text here</p></div>"
               b"<section><p>identical paragraph text here</p></section>"
               b"</body></html>")
        result = extract_html(raw)
        paragraphs = [b for b in result.blocks if b.block_type == "paragraph"]
        self.assertEqual(len(paragraphs), 2)
        first, second = paragraphs
        self.assertEqual(first.locator["start_char"], 0)
        self.assertGreater(second.locator["start_char"],
                           first.locator["end_char"])

    def test_offsets_are_reconstructable_from_block_texts(self):
        from knowledge.extract import extract_html

        raw = (b"<html><body><h1>Title Here</h1>"
               b"<p>first   paragraph with   folded whitespace</p>"
               b"<p>second paragraph</p>"
               b"<table><tr><th>k</th><th>v</th></tr></table>"
               b"</body></html>")
        result = extract_html(raw)
        stream_length = result.stats.get("normalized_chars")
        self.assertIsNotNone(stream_length)
        for block in result.blocks:
            self.assertLessEqual(block.locator["end_char"], stream_length)
            self.assertLess(block.locator["start_char"],
                            block.locator["end_char"])


if __name__ == "__main__":
    unittest.main()
