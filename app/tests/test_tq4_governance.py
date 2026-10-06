"""TQ4: vault governance dry-run - plan only, never execute.

Current entries keep; machine superseded copies become archive
CANDIDATES with full identity; human edits and unknown ownership are
conflicts that always KEEP; nothing is deleted, moved or rewritten by
the planner.
"""
from __future__ import annotations

import os
import unittest

from fixtures import temp_dir


def _kb():
    from knowledge.store import KnowledgeStore

    return KnowledgeStore(os.path.join(temp_dir(), "k.sqlite3"))


def _seed(kb, doc_id, sha, extraction_id, blocks_text=("旧版正文",),
          symbol="EX"):
    stamp = "2026-10-04T00:00:00Z"
    kb.upsert_documents([{
        "source": "reports", "doc_id": doc_id,
        "title": "Title %s" % doc_id, "symbol": symbol, "available": True,
        "first_seen_at": stamp, "last_seen_at": stamp}], stamp)
    kb.upsert_versions([{
        "source": "reports", "doc_id": doc_id, "version_id": "v1",
        "sha256": sha, "bytes": 10, "media_type": "application/pdf",
        "ext": "pdf", "rel_path": "x", "is_current": True,
        "state": "ready", "content_changed_at": None}], stamp)
    kb.record_extraction({
        "extraction_id": extraction_id, "source": "reports",
        "doc_id": doc_id, "version_id": "v1",
        "snapshot_sha256": sha, "parser_id": "t", "parser_version": "1",
        "config_digest": "digest-%s" % extraction_id,
        "status": "ready", "issues": [], "stats": {}},
        [{"block_type": "paragraph", "text": text,
          "locator": {"kind": "pdf", "page": 1},
          "quality": {"status": "ready", "issues": []}}
         for text in blocks_text])


class TQ4GovernanceTest(unittest.TestCase):
    def test_plan_dispositions_and_no_writes(self):
        from knowledge.governance import (DISPOSITION_ARCHIVE_CANDIDATE,
                                          DISPOSITION_CONFLICT_HUMAN_EDIT,
                                          DISPOSITION_KEEP, DISPOSITION_UNKNOWN,
                                          plan_file_governance)
        from knowledge.reading import ReadingPublisher, reading_filename
        from knowledge.writeback import _load_manifest, _save_manifest

        kb = _kb()
        try:
            _seed(kb, "GOV", "g", "extr-gov-old")
            vault = os.path.join(temp_dir(), "vault")
            os.makedirs(vault, exist_ok=True)
            publisher = ReadingPublisher(kb, vault, base_url="http://x:1")
            publisher.enqueue("reports", "GOV", "v1", "extr-gov-old")
            publisher.consume()
            # a newer usable extraction becomes the entry; the old note
            # is now a superseded machine copy
            _seed(kb, "GOV", "g", "extr-gov-new",
                  blocks_text=("新版正文，毛利率 25.3%",))
            publisher.enqueue("reports", "GOV", "v1", "extr-gov-new")
            publisher.consume()

            # human edits one machine file -> conflict
            current = reading_filename("reports", "GOV", "extr-gov-new")
            human_path = os.path.join(publisher.output, current)
            before = open(human_path, "rb").read()
            with open(human_path, "a", encoding="utf-8") as handle:
                handle.write("人工批注")
            # an unmanaged stray file -> unknown owner
            stray = os.path.join(publisher.output, "text-stray.md")
            with open(stray, "w", encoding="utf-8") as handle:
                handle.write("外部文件")

            before_state = sorted(os.listdir(publisher.output))
            plan = plan_file_governance(kb, publisher.output)
            after_state = sorted(os.listdir(publisher.output))
            # DRY RUN: nothing changed on disk
            self.assertEqual(before_state, after_state)

            by_file = {f["file"]: f for f in plan["files"]}
            old = reading_filename("reports", "GOV", "extr-gov-old")
            self.assertEqual(by_file[old]["disposition"],
                             DISPOSITION_ARCHIVE_CANDIDATE)
            self.assertEqual(by_file[current]["disposition"],
                             DISPOSITION_CONFLICT_HUMAN_EDIT)
            self.assertEqual(by_file["text-stray.md"]["disposition"],
                             DISPOSITION_UNKNOWN)
            # archive candidate carries full identity for a later
            # verifiable archive
            self.assertTrue(by_file[old]["sha256"])
            self.assertEqual(by_file[old]["manifest_owner"],
                             "reading-publisher")
            self.assertIn("archive-candidate", plan["counts"])
        finally:
            kb.close()

    def test_current_entry_always_keep(self):
        from knowledge.governance import (DISPOSITION_KEEP,
                                          plan_file_governance)
        from knowledge.reading import ReadingPublisher, reading_filename

        kb = _kb()
        try:
            _seed(kb, "SOLO", "s", "extr-solo")
            vault = os.path.join(temp_dir(), "vault")
            os.makedirs(vault, exist_ok=True)
            publisher = ReadingPublisher(kb, vault, base_url="http://x:1")
            publisher.enqueue("reports", "SOLO", "v1", "extr-solo")
            publisher.consume()
            plan = plan_file_governance(kb, publisher.output)
            note = reading_filename("reports", "SOLO", "extr-solo")
            by_file = {f["file"]: f for f in plan["files"]}
            self.assertEqual(by_file[note]["disposition"], DISPOSITION_KEEP)
            self.assertTrue(by_file[note]["is_current_entry"])
        finally:
            kb.close()


if __name__ == "__main__":
    unittest.main()
