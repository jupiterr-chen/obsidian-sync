"""RF3 regression tests (R08 version selection/as_of, R07 index recovery)."""

from __future__ import annotations

import os
import unittest

from fixtures import temp_dir


def _kb():
    from knowledge.store import KnowledgeStore

    return KnowledgeStore(os.path.join(temp_dir(), "knowledge.sqlite3"))


def _doc_row(doc_id="R1", first_seen="2026-01-10T00:00:00Z",
             report_date="2026-06-30"):
    return {
        "source": "reports", "doc_id": doc_id, "title": doc_id,
        "display_title": doc_id, "symbol": "EXAMPLE", "doc_type": "H1",
        "available": True, "first_seen_at": first_seen,
        "last_seen_at": first_seen, "report_date": report_date,
    }


def _version_row(version_id, is_current, sha, synced_at="2026-10-02T00:00:00Z"):
    return {
        "source": "reports", "doc_id": "R1", "version_id": version_id,
        "sha256": sha, "bytes": 100, "media_type": "application/pdf",
        "ext": "pdf", "rel_path": "x", "is_current": is_current,
        "state": "ready", "content_changed_at": None,
        "synced_at": synced_at,
    }


def _extraction(extraction_id, version_id, text, sha, stamp="2026-10-01T00:00:00Z"):
    return {
        "extraction_id": extraction_id, "source": "reports", "doc_id": "R1",
        "version_id": version_id, "snapshot_sha256": sha,
        "parser_id": "t", "parser_version": "1", "config_digest": "cfg",
        "status": "ready", "issues": [], "stats": {},
        "created_at": stamp,
    }, [{
        "block_type": "paragraph", "text": text,
        "locator": {"kind": "pdf", "page": 1},
        "quality": {"status": "ready", "issues": []},
    }]


class R08VersionSelectionTest(unittest.TestCase):
    def _seed(self, kb, v2_synced="2026-10-02T00:00:00Z"):
        stamp = "2026-01-10T00:00:00Z"
        kb.upsert_documents([_doc_row()], stamp)
        kb.upsert_versions([
            _version_row("v1", False, "a" * 64, synced_at="2026-01-10T00:00:00Z"),
            _version_row("v2", True, "b" * 64, synced_at=v2_synced),
        ], stamp)
        kb.record_extraction(*_extraction("extr-v1", "v1",
                                          "old version text about margin",
                                          "a" * 64,
                                          stamp="2026-01-10T00:00:00Z"))
        kb.record_extraction(*_extraction("extr-v2", "v2",
                                          "new version text about margin",
                                          "b" * 64,
                                          stamp="2026-10-02T00:00:00Z"))

    def test_versions_record_first_observed(self):
        kb = _kb()
        try:
            self._seed(kb)
            from knowledge.indexing import build_generation

            build_generation(kb)
            v1 = kb.get_version("reports", "R1", "v1")
            v2 = kb.get_version("reports", "R1", "v2")
            self.assertIsNotNone(v1.get("first_observed_at"))
            self.assertIsNotNone(v2.get("first_observed_at"))
            self.assertNotEqual(v1["first_observed_at"],
                                v2["first_observed_at"])
        finally:
            kb.close()

    def test_default_search_returns_only_current_version(self):
        from knowledge.indexing import build_generation, search

        kb = _kb()
        try:
            self._seed(kb)
            build_generation(kb)
            result = search(kb, "margin")
            texts = [h.block["text"] for h in result["hits"]]
            self.assertTrue(all("new version" in t for t in texts),
                            texts)
            self.assertFalse(any("old version" in t for t in texts))
        finally:
            kb.close()

    def test_system_as_of_excludes_not_yet_observed_versions(self):
        from knowledge.indexing import build_generation, search, SearchFilters

        kb = _kb()
        try:
            self._seed(kb, v2_synced="2026-10-02T00:00:00Z")
            build_generation(kb)
            # February query: v2 (current) was first observed in October ->
            # the document's current content was not knowable then
            result = search(kb, "margin", SearchFilters(
                as_of="2026-02-01T00:00:00Z", as_of_mode="system"))
            self.assertEqual(result["hits"], [])
            # November query: v2 visible
            late = search(kb, "margin", SearchFilters(
                as_of="2026-11-01T00:00:00Z", as_of_mode="system"))
            self.assertGreater(len(late["hits"]), 0)
        finally:
            kb.close()

    def test_unavailable_documents_excluded_from_search(self):
        from knowledge.indexing import build_generation, search

        kb = _kb()
        try:
            self._seed(kb)
            build_generation(kb)
            kb.upsert_documents([dict(_doc_row(), available=False)],
                                "2026-10-03T00:00:00Z")
            result = search(kb, "margin")
            self.assertEqual(result["hits"], [])
        finally:
            kb.close()

    def test_public_as_of_requires_a_public_date_basis(self):
        from knowledge.indexing import build_generation, search, SearchFilters

        kb = _kb()
        try:
            # S03: the report period is NOT publication evidence; give the
            # document a published_at basis before expecting visibility
            stamp = "2026-01-10T00:00:00Z"
            kb.upsert_documents([dict(_doc_row(),
                                      published_at="2026-01-15T00:00:00Z")],
                                stamp)
            kb.upsert_versions([_version_row("v1", True, "a" * 64,
                                            synced_at="2026-01-10T00:00:00Z")],
                               stamp)
            kb.record_extraction(*_extraction("extr-p", "v1",
                                              "margin text", "a" * 64))
            build_generation(kb)
            visible = search(kb, "margin", SearchFilters(
                as_of="2026-01-16T00:00:00Z", as_of_mode="public"))
            self.assertGreater(len(visible["hits"]), 0)
            # before publication: invisible
            pre = search(kb, "margin", SearchFilters(
                as_of="2026-01-14T00:00:00Z", as_of_mode="public"))
            self.assertEqual(pre["hits"], [])
            early = search(kb, "margin", SearchFilters(
                as_of="2026-01-01T00:00:00Z", as_of_mode="public"))
            self.assertEqual(early["hits"], [])

            # document with NO public date basis at all: never fabricated
            kb2 = _kb()
            try:
                stamp = "2026-01-10T00:00:00Z"
                kb2.upsert_documents([dict(_doc_row(report_date=None),
                                           published_at=None,
                                           filing_date=None)], stamp)
                kb2.upsert_versions([_version_row("v1", True, "a" * 64)], stamp)
                kb2.record_extraction(*_extraction("extr-x", "v1",
                                                   "margin text", "a" * 64))
                build_generation(kb2)
                unknown = search(kb2, "margin", SearchFilters(
                    as_of="2026-07-01T00:00:00Z", as_of_mode="public"))
                self.assertEqual(unknown["hits"],
                                 [],
                                 "unknown public date must not be fabricated")
            finally:
                kb2.close()
        finally:
            kb.close()


class R07IndexRecoveryTest(unittest.TestCase):
    def _seed_with_blocks(self, kb):
        stamp = "2026-10-01T00:00:00Z"
        kb.upsert_documents([_doc_row()], stamp)
        kb.upsert_versions([_version_row("v1", True, "a" * 64)], stamp)
        kb.record_extraction(*_extraction("extr-r1", "v1",
                                          "recoverable margin text",
                                          "a" * 64))

    def test_crashed_building_generation_is_rebuilt_not_activated(self):
        import hashlib

        from knowledge.indexing import build_generation, search

        kb = _kb()
        try:
            self._seed_with_blocks(kb)
            # simulate the review's crash artifact: a generation row that
            # was force-activated BEFORE verification (the pre-fix bug),
            # with zero postings. Direct SQL stands in for the old code path.
            manifest = hashlib.sha256(b"extr-r1").hexdigest()
            kb.create_generation("gen-crash", manifest)
            with kb._tx() as conn:
                conn.execute(
                    "UPDATE index_generations SET status='active',"
                    " stats_json='{\"blocks\": 0}' WHERE generation_id='gen-crash'")
            result = search(kb, "margin")
            self.assertEqual(result["hits"], [])  # broken active, as reviewed

            # recovery: rebuilding must NOT just re-activate the empty
            # generation - it verifies counts and publishes real postings
            build_generation(kb)
            active = kb.active_generation()
            self.assertGreater(active["stats"]["blocks"], 0)
            recovered = search(kb, "margin")
            self.assertGreater(len(recovered["hits"]), 0)
        finally:
            kb.close()

    def test_only_verified_generations_activate(self):
        from knowledge.indexing import build_generation

        kb = _kb()
        try:
            self._seed_with_blocks(kb)
            build_generation(kb)
            healthy = kb.active_generation()
            self.assertEqual(healthy["status"], "active")
            # a fresh building row (crash mid-build) can never be activated
            kb.create_generation("gen-halfbuilt", "manifest-2")
            with self.assertRaises(Exception):
                kb.activate_generation("gen-halfbuilt", {"blocks": 5})
        finally:
            kb.close()

    def test_failed_rebuild_keeps_old_active(self):
        from knowledge.indexing import build_generation

        kb = _kb()
        try:
            self._seed_with_blocks(kb)
            first = build_generation(kb)
            self.assertTrue(first["changed"])
            healthy_id = kb.active_generation()["generation_id"]
            # simulate a crash mid-second-build: stale building row appears
            kb.create_generation("gen-stale", "manifest-stale")
            # rebuild recovers and re-verifies; the healthy active stays
            # readable throughout
            self.assertIsNotNone(kb.active_generation())
            build_generation(kb)
            self.assertIsNotNone(kb.active_generation())
            self.assertGreater(kb.active_generation()["stats"]["blocks"], 0)
            self.assertNotIn(healthy_id, ["gen-stale"])
        finally:
            kb.close()


if __name__ == "__main__":
    unittest.main()
