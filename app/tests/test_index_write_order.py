"""Index write performance changes must preserve committed data semantics."""
import sqlite3
import unittest

from knowledge.store import KnowledgeStore


class IndexWriteOrderTests(unittest.TestCase):
    def setUp(self):
        self.kb = KnowledgeStore(":memory:")
        self.kb.create_generation("gen-test", "test-manifest")
        self.cache = self.kb._conn.execute("PRAGMA cache_size").fetchone()[0]

    def tearDown(self):
        self.kb.close()

    def test_unsorted_multilingual_postings_and_statistics(self):
        rows = [("收入", "b02", 2), ("0700", "b01", 3),
                ("收入", "b01", 7), ("margin", "b03", 1)]
        original = rows.copy()
        docs = [("b01", 2, 20), ("b02", 1, 12), ("b03", 1, 9)]
        self.kb.write_postings("gen-test", rows, docs)
        actual = [tuple(r) for r in self.kb._conn.execute(
            "SELECT term,block_id,tf FROM index_postings ORDER BY term,block_id")]
        self.assertEqual(actual, sorted(original))
        self.assertEqual(rows, original)  # caller-owned input is unchanged
        stats = self.kb.finalize_generation("gen-test", expected_blocks=3)
        self.assertEqual(stats, {"blocks": 3, "terms": 4,
                                 "total_length": 41, "postings": 4})
        self.assertEqual(self.kb._conn.execute("PRAGMA cache_size").fetchone()[0],
                         self.cache)

    def test_duplicate_key_keeps_original_last_write(self):
        self.kb.write_postings("gen-test", [("x", "b1", 9), ("x", "b1", 2)],
                               [("b1", 1, 10)])
        self.assertEqual(self.kb._conn.execute(
            "SELECT tf FROM index_postings WHERE term='x'").fetchone()[0], 2)

    def test_failure_rolls_back_both_tables_and_restores_cache(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.kb.write_postings("gen-test", [("x", "b1", 1)],
                                   [("b1", 1, None)])
        for table in ("index_postings", "index_doc_terms"):
            self.assertEqual(self.kb._conn.execute(
                "SELECT COUNT(*) FROM " + table).fetchone()[0], 0)
        self.assertEqual(self.kb._conn.execute("PRAGMA cache_size").fetchone()[0],
                         self.cache)

    def test_empty_generation_remains_verifiable(self):
        self.kb.write_postings("gen-test", [], [])
        stats = self.kb.finalize_generation("gen-test", expected_blocks=0)
        self.assertEqual(stats["blocks"], 0)
        self.assertEqual(stats["postings"], 0)


if __name__ == "__main__":
    unittest.main()
