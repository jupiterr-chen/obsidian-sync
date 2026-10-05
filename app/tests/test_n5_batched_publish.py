"""N5 (Q04): a batched publish must never leave dangling index links.

consume() processes at most `limit` notes per call, but rebuild_index
linked EVERY current version's note file - with 2 pending and limit=1
the index pointed at a file that did not exist. The index must only
link files that are on disk; not-yet-published entries show as 待发布
with the original-document link, and complete on the next consume.
"""
from __future__ import annotations

import os
import unittest

from fixtures import temp_dir


def _kb():
    from knowledge.store import KnowledgeStore

    return KnowledgeStore(os.path.join(temp_dir(), "k.sqlite3"))


def _seed(kb, doc_id, sha, extraction_id):
    from test_abcde_delivery import _record_extraction, _seed_version

    _seed_version(kb, doc_id, sha=sha)
    _record_extraction(kb, doc_id, "v1", extraction_id, blocks=1, sha=sha)


class N5BatchedPublishTest(unittest.TestCase):
    def _publisher(self, kb):
        from knowledge.reading import ReadingPublisher

        vault = os.path.join(temp_dir(), "vault")
        os.makedirs(vault, exist_ok=True)
        return ReadingPublisher(kb, vault, base_url="http://x:1")

    def test_partial_batch_marks_pending_without_dangling_link(self):
        from knowledge.reading import reading_filename

        kb = _kb()
        try:
            _seed(kb, "B0", "0", "extr-b0")
            _seed(kb, "B1", "1", "extr-b1")
            publisher = self._publisher(kb)
            publisher.enqueue("reports", "B0", "v1", "extr-b0")
            publisher.enqueue("reports", "B1", "v1", "extr-b1")
            outcome = publisher.consume(limit=1)
            self.assertEqual(outcome["published"], 1)
            self.assertEqual(len(publisher.pending()), 1)

            index = open(os.path.join(publisher.output, "开始阅读.md"),
                         encoding="utf-8").read()
            missing = reading_filename("reports", "B1", "extr-b1")
            linked = "(%s)" % missing in index
            on_disk = os.path.exists(
                os.path.join(publisher.output, missing))
            self.assertFalse(
                linked and not on_disk,
                "index links a note that was not published in this batch")
            # the unpublished doc is visible as 待发布, never silently
            # missing from the directory
            self.assertIn("待发布", index)
            self.assertIn("Title B1", index)
            # published doc links normally
            self.assertIn("(%s)" % reading_filename(
                "reports", "B0", "extr-b0"), index)

            # next round completes the backlog: now B1 links for real
            outcome = publisher.consume()
            self.assertEqual(outcome["published"], 1)
            index = open(os.path.join(publisher.output, "开始阅读.md"),
                         encoding="utf-8").read()
            self.assertIn("(%s)" % missing, index)
            self.assertTrue(os.path.exists(
                os.path.join(publisher.output, missing)))
            self.assertNotIn("待发布", index)
        finally:
            kb.close()

    def test_interrupted_publish_recovers_without_dangling_links(self):
        """A crash mid-batch (some notes written, outbox rows still
        pending) must leave an index whose links all resolve."""
        from knowledge.reading import reading_filename

        kb = _kb()
        try:
            for i in range(3):
                _seed(kb, "C%d" % i, str(i), "extr-c%d" % i)
                publisher = self._publisher(kb)
            for i in range(3):
                publisher.enqueue("reports", "C%d" % i, "v1", "extr-c%d" % i)
            # simulate: one note published, then the process died before
            # the row was consumed - the rest stay pending
            publisher._publish_note_for(publisher.pending()[0])
            publisher.rebuild_index()
            index = open(os.path.join(publisher.output, "开始阅读.md"),
                         encoding="utf-8").read()
            for i in range(3):
                name = reading_filename("reports", "C%d" % i,
                                        "extr-c%d" % i)
                linked = "(%s)" % name in index
                on_disk = os.path.exists(
                    os.path.join(publisher.output, name))
                self.assertFalse(
                    linked and not on_disk,
                    "dangling link for %s after interrupted publish" % name)
            # recovery: consume drains the rest, index completes
            outcome = publisher.consume()
            self.assertEqual(outcome["published"], 3)
            index = open(os.path.join(publisher.output, "开始阅读.md"),
                         encoding="utf-8").read()
            for i in range(3):
                self.assertIn("(%s)" % reading_filename(
                    "reports", "C%d" % i, "extr-c%d" % i), index)
        finally:
            kb.close()

    def test_status_page_shows_pending_stage_too(self):
        kb = _kb()
        try:
            _seed(kb, "S0", "0", "extr-s0")
            publisher = self._publisher(kb)
            # enqueue without consuming: nothing on disk yet
            publisher.enqueue("reports", "S0", "v1", "extr-s0")
            publisher.rebuild_index()
            status = open(os.path.join(publisher.output, "处理状态.md"),
                          encoding="utf-8").read()
            self.assertIn("待发布", status)
        finally:
            kb.close()


if __name__ == "__main__":
    unittest.main()
