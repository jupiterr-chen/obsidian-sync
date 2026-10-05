"""N1 (Q01): historical background packages must respect the as_of cutoff.

Proves sources/extractions/claims are selected as they were at the cutoff
(version visibility, extraction creation, claim revision), that unknown
public times never masquerade as known, that filtering happens before the
limit, and that a saved package replays byte-identically.
"""
from __future__ import annotations

import json
import os
import unittest

from fixtures import temp_dir


def _kb():
    from knowledge.store import KnowledgeStore

    return KnowledgeStore(os.path.join(temp_dir(), "k.sqlite3"))


def _seed(kb, doc_id, version_id, sha, stamp, current=True, symbol="EX"):
    kb.upsert_documents([{
        "source": "reports", "doc_id": doc_id,
        "title": "Title %s" % doc_id, "symbol": symbol, "available": True,
        "first_seen_at": stamp, "last_seen_at": stamp,
        "report_date": "2026-06-30",
    }], stamp)
    kb.upsert_versions([{
        "source": "reports", "doc_id": doc_id, "version_id": version_id,
        "sha256": sha, "bytes": 10, "media_type": "application/pdf",
        "ext": "pdf", "rel_path": "x", "is_current": current,
        "state": "ready", "content_changed_at": None,
    }], stamp)


def _extract(kb, doc_id, version_id, extraction_id, stamp, status="ready"):
    kb.record_extraction({
        "extraction_id": extraction_id, "source": "reports",
        "doc_id": doc_id, "version_id": version_id,
        "snapshot_sha256": "sha-%s" % extraction_id,
        "parser_id": "t", "parser_version": "1", "config_digest": "c",
        "status": status, "issues": [], "stats": {}},
        [{"block_type": "paragraph", "text": "block",
          "locator": {"kind": "pdf", "page": 1},
          "quality": {"status": "ready", "issues": []}}])
    # pin the extraction's creation time for cutoff comparisons
    with kb._tx() as conn:
        conn.execute("UPDATE extractions SET created_at=? WHERE"
                     " extraction_id=?", (stamp, extraction_id))


class N1HistoricalBackgroundTest(unittest.TestCase):
    def test_future_material_excluded_both_modes(self):
        from knowledge.background import build_background_package

        kb = _kb()
        try:
            _seed(kb, "FUT", "v1", "a", "2026-10-04T00:00:00Z")
            _extract(kb, "FUT", "v1", "extr-fut", "2026-10-04T01:00:00Z")
            for mode in ("system", "public"):
                package = build_background_package(
                    kb, "company", "EX", as_of="2000-01-01T00:00:00Z",
                    as_of_mode=mode)
                self.assertEqual(
                    package["sources"], [],
                    "material first observed 2026-10-04 leaked into a"
                    " %s-mode package for as_of 2000-01-01" % mode)
                self.assertEqual(package["claims"], [])
            # no cutoff keeps today's behaviour
            current = build_background_package(kb, "company", "EX")
            self.assertEqual(len(current["sources"]), 1)
        finally:
            kb.close()

    def test_two_versions_selects_version_visible_at_cutoff(self):
        from knowledge.background import build_background_package

        kb = _kb()
        try:
            _seed(kb, "DOC", "v1", "a", "2026-01-01T00:00:00Z")
            _extract(kb, "DOC", "v1", "extr-v1", "2026-01-01T01:00:00Z")
            _seed(kb, "DOC", "v2", "b", "2026-09-01T00:00:00Z",
                  current=False)
            _extract(kb, "DOC", "v2", "extr-v2", "2026-09-01T01:00:00Z")
            # v2 is marked not-current in this synthetic store to prove
            # selection is driven by visibility times, not is_current
            with kb._tx() as conn:
                conn.execute(
                    "UPDATE kb_versions SET is_current=1 WHERE version_id="
                    "'v2' AND source='reports' AND doc_id='DOC'")
            mid = build_background_package(
                kb, "company", "EX", as_of="2026-05-01T00:00:00Z",
                as_of_mode="system")
            self.assertEqual(len(mid["sources"]), 1)
            self.assertEqual(mid["sources"][0]["version_id"], "v1",
                             "version visible at cutoff must be v1")
            self.assertEqual(mid["sources"][0]["extraction_id"], "extr-v1")
            late = build_background_package(
                kb, "company", "EX", as_of="2026-12-01T00:00:00Z",
                as_of_mode="system")
            self.assertEqual(late["sources"][0]["version_id"], "v2")
        finally:
            kb.close()

    def test_extraction_after_cutoff_not_pretended_known(self):
        from knowledge.background import build_background_package

        kb = _kb()
        try:
            _seed(kb, "DOC", "v1", "a", "2026-01-01T00:00:00Z")
            _extract(kb, "DOC", "v1", "extr-late", "2026-06-01T00:00:00Z")
            package = build_background_package(
                kb, "company", "EX", as_of="2026-02-01T00:00:00Z",
                as_of_mode="system")
            self.assertEqual(package["sources"][0]["extraction_status"], None,
                             "extraction created after the cutoff must not"
                             " appear as known")
            self.assertEqual(package["sources"][0]["evidence_refs"], [])
        finally:
            kb.close()

    def test_claims_respect_cutoff_and_revisions(self):
        from knowledge.background import build_background_package
        from knowledge.memory import create_claim, review_claim

        kb = _kb()
        try:
            _seed(kb, "C1", "v1", "a", "2026-01-01T00:00:00Z")
            _extract(kb, "C1", "v1", "extr-c1", "2026-01-01T01:00:00Z")
            created = create_claim(
                kb, "early claim",
                [{"source": "reports", "doc_id": "C1", "version_id": "v1",
                  "block_id": "extr-c1-b0000", "extraction_id": "extr-c1"}],
                subject="EX")
            review_claim(kb, created["claim_id"], "accept", reviewer="a")
            # pin revision times: rev1 early, rev2 later
            with kb._tx() as conn:
                conn.execute(
                    "UPDATE claim_revisions SET created_at=? WHERE claim_id=?"
                    " AND revision=1", ("2026-02-01T00:00:00Z",
                                        created["claim_id"]))
                conn.execute(
                    "UPDATE claim_revisions SET created_at=? WHERE claim_id=?"
                    " AND revision=2", ("2026-08-01T00:00:00Z",
                                        created["claim_id"]))
                conn.execute(
                    "UPDATE claims SET created_at=?, updated_at=? WHERE"
                    " claim_id=?",
                    ("2026-02-01T00:00:00Z", "2026-08-01T00:00:00Z",
                     created["claim_id"]))

            early = build_background_package(
                kb, "company", "EX", as_of="2026-03-01T00:00:00Z",
                as_of_mode="system")
            self.assertEqual(len(early["claims"]), 1)
            self.assertEqual(early["claims"][0]["revision"], 1,
                             "revision 2 (created 2026-08) must not be"
                             " visible at 2026-03")
            late = build_background_package(
                kb, "company", "EX", as_of="2026-12-01T00:00:00Z",
                as_of_mode="system")
            self.assertEqual(late["claims"][0]["revision"], 2)

            before_claim = build_background_package(
                kb, "company", "EX", as_of="2026-01-15T00:00:00Z",
                as_of_mode="system")
            self.assertEqual(before_claim["claims"], [],
                             "claim did not exist at cutoff")
        finally:
            kb.close()

    def test_public_mode_requires_bound_public_time(self):
        from knowledge.background import build_background_package

        kb = _kb()
        try:
            # system time known, public time never bound (V03 semantics:
            # NULL = unknown, must not masquerade as known)
            _seed(kb, "PUB", "v1", "a", "2026-01-01T00:00:00Z")
            _extract(kb, "PUB", "v1", "extr-pub", "2026-01-01T01:00:00Z")
            package = build_background_package(
                kb, "company", "EX", as_of="2026-12-01T00:00:00Z",
                as_of_mode="public")
            self.assertEqual(
                package["sources"], [],
                "version without a bound public time must not appear in a"
                " public-mode package even after its system observation")
        finally:
            kb.close()

    def test_filter_before_limit_and_replay_stability(self):
        from knowledge.background import build_background_package

        kb = _kb()
        try:
            # 3 docs; only the two old ones are visible at the cutoff.
            # limit=2 must yield the two OLD docs, not 2 arbitrary docs
            # filtered down further.
            for i, stamp in enumerate(("2026-01-0%dT00:00:00Z" % (i + 1)
                                        for i in range(3))):
                pass
            stamps = ["2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z",
                      "2026-11-01T00:00:00Z"]
            for i, stamp in enumerate(stamps):
                _seed(kb, "L%d" % i, "v1", "l%d" % i, stamp)
                _extract(kb, "L%d" % i, "v1", "extr-l%d" % i,
                         stamp.replace("00:00:00", "01:00:00"))
            package = build_background_package(
                kb, "company", "EX", as_of="2026-06-01T00:00:00Z",
                as_of_mode="system", limit=2)
            ids = sorted(s["doc_id"] for s in package["sources"])
            self.assertEqual(ids, ["L0", "L1"],
                             "limit applied after visibility filtering")
            # replay: identical store -> identical digest
            again = build_background_package(
                kb, "company", "EX", as_of="2026-06-01T00:00:00Z",
                as_of_mode="system", limit=2)
            self.assertEqual(package["result_digest"],
                             again["result_digest"])
            # the package must carry the generation explicitly; None is
            # honest for a store without an active index generation
            self.assertIn("generation", package)
            for source in package["sources"]:
                self.assertIn("version_id", source)
                self.assertIn("extraction_id", source)
        finally:
            kb.close()

    def test_invalid_as_of_rejected(self):
        from knowledge.background import build_background_package

        kb = _kb()
        try:
            with self.assertRaises(ValueError):
                build_background_package(kb, "company", "EX",
                                         as_of="not-a-date")
            with self.assertRaises(ValueError):
                build_background_package(kb, "company", "EX",
                                         as_of="2026-13-45T99:00:00Z",
                                         as_of_mode="system")
        finally:
            kb.close()


if __name__ == "__main__":
    unittest.main()
