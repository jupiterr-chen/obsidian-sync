"""P2 extraction tests: extractors, evidence blocks, idempotent extract jobs."""

from __future__ import annotations

import json
import os
import unittest
import zlib

from fixtures import make_config, temp_dir

from knowledge.config import KnowledgeConfig
from knowledge.extract import (
    Block,
    compute_extraction_id,
    extract_html,
    extract_pdf,
    extract_txt,
    extract_image,
    get_extractor,
    register_ocr_engine,
    to_evidence_block,
)
from knowledge.jobs import JobRunner
from knowledge.quality import analyze_text, route_page_to_ocr
from knowledge.schema import validate_evidence_block
from knowledge.snapshot import SnapshotStore
from knowledge.store import JOB_DONE, KnowledgeStore
from knowledge.sync import SyncService
from knowledge.tables import TableBlock, normalize_number


def build_pdf(contents: bytes, compress: bool = False) -> bytes:
    stream = contents
    header = b"<< /Length %d >>" % len(stream)
    if compress:
        stream = zlib.compress(contents)
        header = b"<< /Length %d /Filter /FlateDecode >>" % len(stream)
    return (
        b"%PDF-1.4\n"
        b"3 0 obj\n" + header + b"\nstream\n" + stream + b"\nendstream\nendobj\n"
        b"4 0 obj\n<< /Type /Page /Parent 1 0 R /Contents 3 0 R >>\nendobj\n"
        b"trailer\n<< /Root 1 0 R >>\n%%EOF"
    )


class ExtractorUnitTest(unittest.TestCase):
    def test_txt_paragraphs_with_char_offsets(self):
        raw = ("第一段：毛利率 30%，较去年同期明显提升。@@NL@@"
               "Second paragraph about revenue growth and margins.").encode("utf-8")
        raw = raw.replace(b"@@NL@@", b"\n\n")
        result = extract_txt(raw)
        self.assertEqual(result.parser_id, "stdlib-txt")
        self.assertEqual(len(result.blocks), 2)
        first = result.blocks[0]
        self.assertEqual(first.block_type, "paragraph")
        self.assertEqual(first.locator["kind"], "text")
        self.assertEqual(raw.decode("utf-8")[first.locator["start_char"]:first.locator["end_char"]],
                         first.text)

    def test_html_blocks_dom_paths_and_tables(self):
        raw = (b"<html><head><style>.x{}</style></head><body>"
               b"<h1>Revenue Analysis</h1>"
               b"<p>Gross margin rose to <b>30%</b> in H1.</p>"
               b"<table><caption>Key figures</caption>"
               b"<tr><th>Metric</th><th>Value</th></tr>"
               b"<tr><td>Gross margin</td><td>30%</td></tr></table>"
               b"<script>evil()</script></body></html>")
        result = extract_html(raw)
        types = [b.block_type for b in result.blocks]
        self.assertIn("heading", types)
        self.assertIn("paragraph", types)
        self.assertIn("table", types)
        self.assertIn("caption", types)
        table = next(b for b in result.blocks if b.block_type == "table")
        self.assertIn("Gross margin", table.text)
        self.assertIn("30%", table.text)
        for block in result.blocks:
            self.assertEqual(block.locator["kind"], "html")
            self.assertTrue(block.locator["dom_path"])
            self.assertIn("html[1]", block.locator["dom_path"])
        # script content never leaks into any block
        self.assertNotIn("evil()", " ".join(b.text for b in result.blocks))
        heading = next(b for b in result.blocks if b.block_type == "heading")
        self.assertIn("Revenue Analysis", heading.text)

    def test_pdf_uncompressed_and_flate_text(self):
        content = (b"BT /F1 12 Tf 72 720 Td (Gross margin expanded materially in the first half) Tj ET")
        for compress in (False, True):
            raw = build_pdf(content, compress=compress)
            result = extract_pdf(raw)
            self.assertEqual(result.status, "ready", result.issues)
            self.assertEqual(result.stats["pages"], 1)
            self.assertEqual(len(result.blocks), 1)
            block = result.blocks[0]
            self.assertEqual(block.locator, {"kind": "pdf", "page": 1})
            self.assertIn("Gross margin expanded materially", block.text)

    def test_pdf_tj_array_and_escapes(self):
        content = (b"BT [(Hel) -250 (lo mar) 20 (gin!)] TJ (a second text line here) Tj ET")
        result = extract_pdf(build_pdf(content))
        text = result.blocks[0].text
        self.assertIn("Hello margin!", text)
        self.assertIn("a second text line here", text)

    def test_pdf_suspects_cid_and_flags_review(self):
        # 2-byte glyph codes that no single-byte mapping can honestly decode
        content = b"BT <" + bytes([0xE6, 0xAF, 0x9C, 0xE5, 0x88, 0xA9, 0xE7, 0x8E, 0x87]).hex().encode() + b"> Tj ET"
        result = extract_pdf(build_pdf(content))
        self.assertEqual(result.status, "review")
        self.assertIn("cid_font_unsupported", result.issues)

    def test_pdf_without_pages_fails(self):
        result = extract_pdf(b"%PDF-1.4 nothing")
        self.assertEqual(result.status, "failed")
        self.assertIn("no_page_objects_found", result.issues)

    def test_sparse_pdf_routes_to_ocr(self):
        raw = build_pdf(b"BT ET")  # page object exists, zero text
        result = extract_pdf(raw)
        self.assertTrue(any("needs_ocr" in issue for issue in result.issues))
        self.assertEqual(result.stats["ocr_candidate_pages"], 1)

    def test_image_without_engine_is_review_never_fake(self):
        result = extract_image(b"\x89PNG fake")
        self.assertEqual(result.status, "review")
        self.assertIn("needs_ocr_engine", result.issues)
        self.assertEqual(result.blocks, [])

        class FakeEngine:
            def run(self, raw):
                return ("OCR text about margin", 0.9)

        register_ocr_engine("fake", FakeEngine())
        result = extract_image(b"\x89PNG fake", engine_name="fake")
        self.assertEqual(result.parser_id, "stdlib-image+fake")
        self.assertEqual(result.blocks[0].locator["kind"], "image")

    def test_quality_signals(self):
        good = analyze_text("a normal paragraph with enough characters " * 3)
        self.assertEqual(good.status, "ready")
        repetitive = analyze_text("\n".join(["same line here"] * 12))
        self.assertEqual(repetitive.status, "review")
        self.assertIn("repetitive_lines", repetitive.issues)
        replaced = analyze_text("x\ufffd\ufffd\ufffdy" * 10)
        self.assertEqual(replaced.status, "review")
        empty = analyze_text("   ")
        self.assertEqual(empty.status, "failed")
        sparse = analyze_text("enough text overall ok", per_page_chars=[100, 0, 0, 0])
        self.assertIn("mostly_sparse_pages", sparse.issues)
        wants, reasons = route_page_to_ocr(0, "")
        self.assertTrue(wants)
        self.assertIn("no_text_layer", reasons)

    def test_normalize_number_conservative(self):
        self.assertEqual(normalize_number("1,234.56").value, 1234.56)
        self.assertEqual(normalize_number("(1,234.56)").value, -1234.56)
        self.assertEqual(normalize_number("(1,234.56)").negative_style, "parentheses")
        self.assertEqual(normalize_number("-12.3%").value, -12.3)
        self.assertTrue(normalize_number("-12.3%").is_percent)
        self.assertEqual(normalize_number("$1,234").value, 1234.0)
        self.assertEqual(normalize_number("$1,234").currency_symbol, "$")
        self.assertEqual(normalize_number("1 234").value, 1234.0)
        self.assertEqual(normalize_number("1.234,56").value, 1234.56)
        self.assertIsNone(normalize_number("n/a").value)
        self.assertIn("empty", normalize_number("—").issues)
        self.assertIn("not_a_plain_number", normalize_number("12.3 pp").issues)
        self.assertIn("ambiguous_decimal_comma", normalize_number("1,5").issues)
        self.assertIn("malformed_grouping", normalize_number("1,23,456.7").issues)

    def test_table_block_normalization(self):
        table = TableBlock(rows=[["指标", "数值"], ["毛利率", "30%"], ["净利润", "(1,234.56)"]],
                           header_rows=1)
        cells = table.normalized_cells()
        numbers = [c["number"] for c in cells
                   if c["number"] and c["number"].get("value") is not None]
        self.assertEqual(len(numbers), 2)
        by_raw = {n["raw"]: n for n in numbers}
        self.assertEqual(by_raw["30%"]["value"], 30.0)
        self.assertTrue(by_raw["30%"]["is_percent"])
        self.assertEqual(by_raw["(1,234.56)"]["value"], -1234.56)


class EvidenceSchemaTest(unittest.TestCase):
    def _valid_block(self, **overrides):
        block = {
            "schema_version": "1", "source": "reports", "doc_id": "d1",
            "source_version": "v1",
            "source_sha256": "a" * 64,
            "extraction_id": "e1", "block_id": "e1-b0001",
            "block_type": "paragraph", "text": "毛利率 30%",
            "locator": {"kind": "pdf", "page": 1},
            "quality": {"status": "ready", "issues": []},
        }
        block.update(overrides)
        return block

    def test_contract_example_valid(self):
        path = os.path.join(os.path.dirname(__file__), "..", "..",
                            "contracts", "examples", "evidence-block.json")
        with open(path, "r", encoding="utf-8") as handle:
            example = json.load(handle)
        self.assertEqual(validate_evidence_block(example), [])

    def test_valid_variants(self):
        self.assertEqual(validate_evidence_block(self._valid_block()), [])
        html_block = self._valid_block(
            block_type="heading",
            locator={"kind": "html", "dom_path": "html[1]>body[1]>h1[1]",
                     "start_char": 0, "end_char": 10})
        self.assertEqual(validate_evidence_block(html_block), [])
        text_block = self._valid_block(
            locator={"kind": "text", "start_char": 0, "end_char": 5})
        self.assertEqual(validate_evidence_block(text_block), [])

    def test_rejects_bad_blocks(self):
        self.assertTrue(validate_evidence_block(self._valid_block(
            locator={"kind": "pdf"})))  # pdf without page
        self.assertTrue(validate_evidence_block(self._valid_block(
            locator={"kind": "pdf", "page": 1, "bbox": [1, 2, 3, 4]})))  # bbox w/o cs
        self.assertTrue(validate_evidence_block(self._valid_block(
            locator={"kind": "html", "start_char": 0, "end_char": 1})))  # no dom_path
        self.assertTrue(validate_evidence_block(self._valid_block(
            source_sha256="XYZ")))  # bad hash
        self.assertTrue(validate_evidence_block(self._valid_block(
            quality={"status": "green", "issues": []})))
        self.assertTrue(validate_evidence_block(self._valid_block(
            locator={"kind": "pdf", "page": 1, "surprise": 1})))


class ExtractPipelineTest(unittest.TestCase):
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
        self.kb = KnowledgeStore(self.kb_config.knowledge_db)
        SyncService(self.kb, self.kb_config).run()
        self.blobs = SnapshotStore(self.kb_config.snapshot_root)
        self.runner = JobRunner(self.kb, self.kb_config, self.library_config,
                                blobs=self.blobs)
        self.assertTrue(self.runner.run_snapshot_jobs()["ok"])

    def tearDown(self):
        self.kb.close()

    def test_extract_chain_idempotent_and_schema_valid(self):
        first = self.runner.run_extract_jobs()
        self.assertTrue(first["ok"], first.get("errors"))
        with self.kb._lock:
            extraction_count = self.kb._conn.execute(
                "SELECT COUNT(*) FROM extractions").fetchone()[0]
            block_count = self.kb._conn.execute(
                "SELECT COUNT(*) FROM blocks").fetchone()[0]
        self.assertEqual(extraction_count, self.kb.counts()["snapshots"])
        self.assertGreater(block_count, 0)

        # re-run everything twice: no new extractions or blocks (A02)
        self.runner.run_extract_jobs()
        self.runner.run_extract_jobs()
        with self.kb._lock:
            self.assertEqual(self.kb._conn.execute(
                "SELECT COUNT(*) FROM extractions").fetchone()[0], extraction_count)
            self.assertEqual(self.kb._conn.execute(
                "SELECT COUNT(*) FROM blocks").fetchone()[0], block_count)
        self.assertEqual(self.kb.job_counts("extract")[JOB_DONE], extraction_count)

        # stored blocks export to schema-valid evidence blocks
        with self.kb._lock:
            sample = self.kb._conn.execute(
                "SELECT block_id FROM blocks LIMIT 1").fetchone()
        row = self.kb.get_block_with_identity(sample["block_id"])
        evidence = to_evidence_block(row)
        errors = validate_evidence_block(evidence)
        self.assertEqual(errors, [])
        self.assertEqual(evidence["source_sha256"], row["snapshot_sha256"])

    def test_fake_fixture_pdfs_fail_honestly(self):
        # fixture corpus PDFs are fake bytes without objects -> failed extraction
        # with an explicit reason, never fabricated text
        result = self.runner.run_extract_jobs()
        self.assertTrue(result["ok"])
        with self.kb._lock:
            statuses = dict(self.kb._conn.execute(
                "SELECT status, COUNT(*) FROM extractions GROUP BY status").fetchall())
        self.assertEqual(statuses.get("failed", 0) + statuses.get("review", 0)
                         + statuses.get("ready", 0),
                         self.kb.counts()["snapshots"])
        with self.kb._lock:
            for row in self.kb._conn.execute(
                    "SELECT x.source, x.doc_id, x.version_id, x.status, x.issues_json"
                    " FROM extractions x WHERE x.status='failed'").fetchall():
                self.assertIn("no_page_objects_found", row["issues_json"])

    def test_real_synthetic_pdf_extracts_through_pipeline(self):
        # hand-craft a real PDF version and push it through the whole chain
        import hashlib

        content = b"BT (Real gross margin text for H1 expanded three point two percent) Tj ET"
        pdf = build_pdf(content)
        sha = hashlib.sha256(pdf).hexdigest()
        rel = "CN/TEST/real.pdf"
        os.makedirs(os.path.dirname(os.path.join(self.reports["root"], rel)), exist_ok=True)
        with open(os.path.join(self.reports["root"], rel), "wb") as handle:
            handle.write(pdf)
        import sqlite3

        conn = sqlite3.connect(self.reports["db"])
        conn.execute(
            "INSERT INTO artifacts VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("b9990000000000000009", "c1111111111111111111", sha, len(pdf),
             "application/pdf", "/app/reports/" + rel,
             "2026-07-04T00:00:00Z", "ready", "http://example/real", None))
        conn.execute("UPDATE manifest SET current_artifact_id='b9990000000000000009'"
                     " WHERE report_id='c1111111111111111111'")
        conn.commit()
        conn.close()
        from library.ingest import Ingestor

        ingestor = Ingestor(self.library_config)
        self.assertTrue(ingestor.run()["ok"])
        ingestor.close()
        SyncService(self.kb, self.kb_config).run()
        self.assertTrue(self.runner.run_snapshot_jobs()["ok"])
        result = self.runner.run_extract_jobs()
        self.assertTrue(result["ok"], result.get("errors"))

        extraction = self.kb.latest_extraction("reports", "c1111111111111111111",
                                               "b9990000000000000009")
        self.assertIsNotNone(extraction)
        self.assertEqual(extraction["status"], "ready")
        blocks = self.kb.get_blocks(extraction["extraction_id"])
        self.assertEqual(len(blocks), 1)
        self.assertIn("Real gross margin text for H1", blocks[0]["text"])
        evidence = to_evidence_block(
            self.kb.get_block_with_identity(blocks[0]["block_id"]))
        self.assertEqual(validate_evidence_block(evidence), [])
        self.assertEqual(evidence["locator"], {"kind": "pdf", "page": 1})

    def test_extraction_id_is_deterministic(self):
        a = compute_extraction_id("s", "d", "v", "sha", "p", "1", "cfg")
        b = compute_extraction_id("s", "d", "v", "sha", "p", "1", "cfg")
        c = compute_extraction_id("s", "d", "v", "sha", "p", "2", "cfg")
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_get_extractor_missing_format(self):
        from knowledge.extract import ExtractorMissing

        with self.assertRaises(ExtractorMissing):
            get_extractor("other")


if __name__ == "__main__":
    unittest.main()
