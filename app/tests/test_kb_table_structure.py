"""P1-E: structured table evidence for HTML extractions.

Production failure: tables were flattened to "header => row" text, so the
research end could not reliably bind a number to its period/currency column
(two-year RMB/USD tables). These tests lock the structured payload: rows +
header count stored beside the flat projection, exposed as a sibling
`table` section on /evidence with read-time numeric interpretation.
"""

from __future__ import annotations

import os
import unittest

from fixtures import temp_dir

from knowledge.extract import EXTRACT_CONFIG, extract_html
from knowledge.kbapi import KbApi
from knowledge.store import KnowledgeStore
from knowledge.tables import TableBlock, bounded_table_payload, normalize_number

# 兩年期人民幣/美元雙列財務表（生產語料形態）
_TABLE_HTML = """
<html><body>
<p>下表列示所示期間的簡明綜合經營業績。</p>
<table>
  <tr><th>項目</th><th>2024年人民幣千元</th><th>2025年人民幣千元</th><th>2025年美元千元</th></tr>
  <tr><td>總收入</td><td>365,906</td><td>421,245</td><td>58,824</td></tr>
  <tr><td>毛利</td><td>(1,234.56)</td><td>23.2%</td><td>$78,9</td></tr>
  <tr><td>總收入</td><td>365,906</td><td>421,245</td><td>58,824</td></tr>
</table>
<p>附註：金額未經審核。</p>
</body></html>
"""


class TableExtractionTest(unittest.TestCase):
    def test_html_table_block_carries_structured_payload(self):
        result = extract_html(_TABLE_HTML.encode("utf-8"))
        tables = [b for b in result.blocks if b.block_type == "table"]
        self.assertEqual(len(tables), 1)
        block = tables[0]
        self.assertIsNotNone(block.table)
        self.assertEqual(block.table["header_rows"], 1)
        rows = block.table["rows"]
        self.assertEqual(len(rows), 4)  # header + 3 data rows
        self.assertEqual(rows[0][0], "項目")
        self.assertEqual(rows[1][0], "總收入")

    def test_projection_joins_full_header_and_handles_duplicate_rows(self):
        result = extract_html(_TABLE_HTML.encode("utf-8"))
        block = next(b for b in result.blocks if b.block_type == "table")
        lines = block.text.split("\n")
        # header line + one line per data row (the trailing duplicate of the
        # first data row must NOT be misread as the header via list.index)
        self.assertEqual(len(lines), 4)
        self.assertNotIn("=>", lines[0])
        self.assertTrue(all("=>" in line for line in lines[1:]))
        self.assertIn("2025年美元千元", lines[1])  # FULL header, not header[:4]
        self.assertEqual(lines[1], lines[3])  # duplicate row keeps its prefix

    def test_non_table_blocks_have_no_table_payload(self):
        result = extract_html(_TABLE_HTML.encode("utf-8"))
        for block in result.blocks:
            if block.block_type != "table":
                self.assertIsNone(block.table)

    def test_extract_config_bumped_for_table_semantics(self):
        # identity guard: the stored extraction_id must never silently reuse
        # products built by the pre-table recipe
        self.assertEqual(EXTRACT_CONFIG["blocks"], "evidence-block-v2")

    def test_bounded_table_payload_trims(self):
        payload = bounded_table_payload(
            [["x" * 999] * 80] * 500, header_rows=1)
        self.assertEqual(len(payload["rows"]), 200)
        self.assertEqual(len(payload["rows"][0]), 40)
        self.assertEqual(len(payload["rows"][0][0]), 200)


class TableStorageAndEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.kb = KnowledgeStore(os.path.join(temp_dir(), "knowledge.sqlite3"))
        stamp = "2026-10-01T00:00:00Z"
        self.kb.upsert_documents([{
            "source": "reports", "doc_id": "T1", "title": "T1",
            "symbol": "01810", "doc_type": "earnings", "available": True,
            "first_seen_at": stamp, "last_seen_at": stamp,
            "report_period": "2025-03-31",
            "published_at": "2025-05-15T00:00:00Z",
        }], stamp)
        self.kb.upsert_versions([{
            "source": "reports", "doc_id": "T1", "version_id": "v1",
            "sha256": "a" * 64, "bytes": 100, "media_type": "text/html",
            "ext": "html", "rel_path": "x.html", "is_current": True,
            "state": "ready", "content_changed_at": None,
        }], stamp)
        result = extract_html(_TABLE_HTML.encode("utf-8"))
        self.extraction_id = "extr-tables-01"
        self.kb.record_extraction({
            "extraction_id": self.extraction_id, "source": "reports",
            "doc_id": "T1", "version_id": "v1", "snapshot_sha256": "a" * 64,
            "parser_id": "stdlib-html", "parser_version": "1",
            "config_digest": "cfg-v2", "status": "ready", "issues": [],
            "stats": {},
        }, [{
            "block_type": block.block_type, "text": block.text,
            "locator": block.locator,
            "quality": {"status": block.quality.status,
                        "issues": block.quality.issues},
            "table": block.table,
        } for block in result.blocks])
        self.api = KbApi(self.kb, {"tok": ["research.read"]})
        self.table_block_id = next(
            b["block_id"] for b in self.kb.get_blocks(self.extraction_id)
            if b["block_type"] == "table")

    def tearDown(self):
        self.kb.close()

    def test_roundtrip_returns_structured_table(self):
        blocks = self.kb.get_blocks(self.extraction_id)
        table_block = next(b for b in blocks if b["block_type"] == "table")
        self.assertIn("table", table_block)
        self.assertEqual(table_block["table"]["header_rows"], 1)
        self.assertEqual(len(table_block["table"]["rows"]), 4)

    def test_evidence_api_exposes_normalized_cells(self):
        payload = self.api.evidence(self.table_block_id)
        self.assertIn("table", payload)
        table = payload["table"]
        self.assertEqual(table["header_rows"], 1)
        cells = {(c["row"], c["col"]): c for c in table["normalized_cells"]}
        # header row cells are not numerically interpreted
        self.assertIsNone(cells[(0, 1)]["number"])
        # plain thousands number
        self.assertEqual(cells[(1, 1)]["number"]["value"], 365906.0)
        # parentheses negative
        self.assertEqual(cells[(2, 1)]["number"]["value"], -1234.56)
        self.assertEqual(cells[(2, 1)]["number"]["negative_style"], "parentheses")
        # percent flag
        self.assertTrue(cells[(2, 2)]["number"]["is_percent"])
        self.assertEqual(cells[(2, 2)]["number"]["value"], 23.2)
        # currency symbol recorded, not converted (value stays unresolved
        # for the ambiguous "78,9" grouping - conservative, never guessed)
        self.assertEqual(cells[(2, 3)]["number"]["currency"], "$")
        self.assertIsNone(cells[(2, 3)]["number"]["value"])
        # the evidence block contract itself stays v1-shaped (no table key)
        self.assertNotIn("table", payload["evidence"])

    def test_number_normalizer_direct_contracts(self):
        self.assertEqual(normalize_number("(1,234.56)").value, -1234.56)
        self.assertEqual(normalize_number("23.2%").is_percent, True)
        self.assertEqual(normalize_number("$78,9").currency_symbol, "$")
        self.assertIsNone(normalize_number("$78,9").value)
        self.assertIsNone(normalize_number("不適用").value)
        self.assertIn("empty", normalize_number("-").issues)
        table = TableBlock(rows=[["a"], ["1"]], header_rows=1)
        self.assertEqual(table.normalized_cells()[1]["number"]["value"], 1.0)


if __name__ == "__main__":
    unittest.main()
