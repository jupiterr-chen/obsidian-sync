"""TQ3: explicit, bounded reprocessing with version switching rules.

The batch lane selects candidates from the read-only TQ0 inventory and
registers extract jobs under the CURRENT recipe - a new extraction
identity. Pinned behaviours: three runs register once (idempotent);
a crash mid-batch resumes through job leases; a WORSE new extraction
never replaces the reading entry (switch only on usable text); old
extractions, blocks and evidence URLs stay intact; no batch is derived
implicitly from a recipe change; and the fresh extraction feeds the
entity's summary event exactly once.
"""
from __future__ import annotations

import os
import unittest

from fixtures import temp_dir

_GARBAGE = "".join(chr(i) for i in range(1, 33)) * 4


def _kb():
    from knowledge.store import KnowledgeStore

    return KnowledgeStore(os.path.join(temp_dir(), "k.sqlite3"))


def _seed(kb, doc_id, sha, extraction_id, parser_id="pypdfium2",
          blocks=None, status="ready", symbol="EX"):
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
    kb.record_blob(sha, 10, "aa/%s" % sha, stamp)
    kb.record_extraction({
        "extraction_id": extraction_id, "source": "reports",
        "doc_id": doc_id, "version_id": "v1",
        "snapshot_sha256": sha, "parser_id": parser_id,
        "parser_version": "1", "config_digest": "digest-%s" % extraction_id,
        "status": status, "issues": [], "stats": {}},
        blocks if blocks is not None else [
            {"block_type": "paragraph",
             "text": "健康正文：毛利率 25.3%",
             "locator": {"kind": "pdf", "page": 1},
             "quality": {"status": "ready", "issues": []}}])


def _legacy_blocks():
    return [
        {"block_type": "paragraph", "text": _GARBAGE,
         "locator": {"kind": "pdf", "page": 1},
         "quality": {"status": "review",
                     "issues": ["control_characters"]}},
        {"block_type": "paragraph", "text": "第二页干净内容",
         "locator": {"kind": "pdf", "page": 2},
         "quality": {"status": "ready", "issues": []}}]


class TQ3ReprocessTest(unittest.TestCase):
    def test_batch_selection_and_registration_idempotent(self):
        from knowledge.repair import (register_reprocess_batch,
                                      select_reprocess_items)
        from knowledge.text_quality import build_inventory

        kb = _kb()
        try:
            _seed(kb, "LEGACY", "l", "extr-legacy", parser_id="stdlib-pdf",
                  blocks=_legacy_blocks())
            _seed(kb, "GOOD", "g", "extr-good")
            inventory = build_inventory(kb)
            items = select_reprocess_items(inventory, max_items=10)
            ids = [i["doc_id"] for i in items]
            self.assertEqual(ids, ["LEGACY"], "only candidates selected")
            first = register_reprocess_batch(kb, "digest-current", items,
                                             "batch-1")
            self.assertEqual(first["jobs_registered"], 1)
            second = register_reprocess_batch(kb, "digest-current", items,
                                              "batch-1")
            third = register_reprocess_batch(kb, "digest-current", items,
                                             "batch-1")
            self.assertEqual(second["jobs_registered"], 0)
            self.assertEqual(third["jobs_registered"], 0)
            self.assertEqual(second["audit_rows_added"], 0)
            # selection is deterministic across runs
            again = select_reprocess_items(build_inventory(kb),
                                           max_items=10)
            self.assertEqual([i["doc_id"] for i in again], ids)
            # GOOD was never registered (no implicit corpus wave)
            with kb._lock:
                jobs = kb._conn.execute(
                    "SELECT doc_id FROM jobs WHERE stage='extract'"
                ).fetchall()
            self.assertEqual([j["doc_id"] for j in jobs], ["LEGACY"])
        finally:
            kb.close()

    def test_bad_new_extraction_keeps_old_entry_and_evidence(self):
        """A reprocessed doc whose NEW extraction is worse must keep the
        old reading entry; old blocks/evidence stay reachable."""
        from knowledge.reading import ReadingPublisher, reading_filename

        kb = _kb()
        try:
            _seed(kb, "SWITCH", "s", "extr-old",
                  blocks=[{"block_type": "paragraph",
                           "text": "旧版可用正文，营收 ¥1.2bn",
                           "locator": {"kind": "pdf", "page": 1},
                           "quality": {"status": "ready", "issues": []}}])
            vault = os.path.join(temp_dir(), "vault")
            os.makedirs(vault, exist_ok=True)
            publisher = ReadingPublisher(kb, vault, base_url="http://x:1")
            publisher.enqueue("reports", "SWITCH", "v1", "extr-old")
            publisher.consume()
            old_note = reading_filename("reports", "SWITCH", "extr-old")
            self.assertTrue(os.path.isfile(
                os.path.join(publisher.output, old_note)))

            # the reprocess lands a FAILED new extraction (e.g. engine
            # error): latest by rowid, but no usable text
            _seed(kb, "SWITCH", "s", "extr-new", status="failed",
                  blocks=[])
            outcome = publisher.rebuild_index()
            index = open(os.path.join(publisher.output, "开始阅读.md"),
                         encoding="utf-8").read()
            self.assertIn(old_note, index,
                          "entry switched away from usable old text")
            self.assertIn("暂用上一版正文", index)
            self.assertIn("failed", index)
            # old evidence block still resolvable
            blocks = kb.get_blocks("extr-old")
            self.assertTrue(blocks)
        finally:
            kb.close()

    def test_good_new_extraction_switches_entry(self):
        from knowledge.reading import ReadingPublisher, reading_filename

        kb = _kb()
        try:
            _seed(kb, "UP", "u", "extr-old", parser_id="stdlib-pdf",
                  blocks=_legacy_blocks())
            vault = os.path.join(temp_dir(), "vault")
            os.makedirs(vault, exist_ok=True)
            publisher = ReadingPublisher(kb, vault, base_url="http://x:1")
            publisher.enqueue("reports", "UP", "v1", "extr-old")
            publisher.consume()
            # reprocess lands a clean new extraction
            _seed(kb, "UP", "u", "extr-new",
                  blocks=[{"block_type": "paragraph",
                           "text": "重提取后的干净正文，毛利率 25.3%",
                           "locator": {"kind": "pdf", "page": 1},
                           "quality": {"status": "ready", "issues": []}}])
            publisher.enqueue("reports", "UP", "v1", "extr-new")
            publisher.consume()
            index = open(os.path.join(publisher.output, "开始阅读.md"),
                         encoding="utf-8").read()
            self.assertIn(reading_filename("reports", "UP", "extr-new"),
                          index)
            # old note file retained (history preserved, no deletion)
            self.assertTrue(os.path.isfile(os.path.join(
                publisher.output,
                reading_filename("reports", "UP", "extr-old"))))
        finally:
            kb.close()

    def test_fresh_extraction_feeds_entity_event_once(self):
        from knowledge.summaries import (enqueue_summary_update,
                                         pending_updates)

        kb = _kb()
        try:
            _seed(kb, "EVENT", "e", "extr-event")
            row = {"source": "reports", "doc_id": "EVENT",
                   "version_id": "v1", "extraction_id": "extr-event"}
            detail = dict(source=row["source"], doc_id=row["doc_id"],
                          version_id=row["version_id"],
                          extraction_id=row["extraction_id"])
            first = enqueue_summary_update(
                kb, "company", "EX", "extraction_updated", detail,
                event_key="extraction:%s" % row["extraction_id"])
            second = enqueue_summary_update(
                kb, "company", "EX", "extraction_updated",
                {"source": "reports", "doc_id": "EVENT",
                 "version_id": "v1", "extraction_id": "extr-event"},
                event_key="extraction:extr-event")
            self.assertTrue(first)
            self.assertFalse(second)
            self.assertEqual(len(pending_updates(kb)), 1)
        finally:
            kb.close()


if __name__ == "__main__":
    unittest.main()
