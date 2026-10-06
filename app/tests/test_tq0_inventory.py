"""TQ0: read-only corpus text-quality inventory.

Five scopes counted separately (documents / current+historical
versions / extractions / pages / files); old stdlib-pdf extractions
enter the candidate set via parser_id even without a degraded marker;
recommended actions are candidates, never damage verdicts; identical
stores produce identical manifest hashes (reproducible); a worse newer
extraction never hides the good current entry.
"""
from __future__ import annotations

import json
import os
import unittest

from fixtures import temp_dir


def _kb():
    from knowledge.store import KnowledgeStore

    return KnowledgeStore(os.path.join(temp_dir(), "k.sqlite3"))


def _seed_doc(kb, doc_id, sha, extraction_ids, status="ready",
              blocks=None, parser_id="pypdfium2", version_id="v1",
              current=True, with_blob=True):
    stamp = "2026-10-04T00:00:00Z"
    kb.upsert_documents([{
        "source": "reports", "doc_id": doc_id,
        "title": "Title %s" % doc_id, "symbol": "EX", "available": True,
        "first_seen_at": stamp, "last_seen_at": stamp}], stamp)
    kb.upsert_versions([{
        "source": "reports", "doc_id": doc_id, "version_id": version_id,
        "sha256": sha, "bytes": 10, "media_type": "application/pdf",
        "ext": "pdf", "rel_path": "x", "is_current": current,
        "state": "ready", "content_changed_at": None}], stamp)
    if with_blob:
        kb.record_blob(sha, 10, "aa/%s" % sha, stamp)
    for index, extraction_id in enumerate(extraction_ids):
        kb.record_extraction({
            "extraction_id": extraction_id, "source": "reports",
            "doc_id": doc_id, "version_id": version_id,
            "snapshot_sha256": sha, "parser_id": parser_id,
            "parser_version": "1",
            "config_digest": "digest-%s" % extraction_id,
            "status": status, "issues": [], "stats": {}},
            blocks if blocks is not None else [
                {"block_type": "paragraph",
                 "text": "健康正文：毛利率 25.3%，营收 ¥1.2bn",
                 "locator": {"kind": "pdf", "page": 1},
                 "quality": {"status": "ready", "issues": []}}])


_GARBAGE = "".join(chr(i) for i in range(1, 33)) * 4


class TQ0InventoryTest(unittest.TestCase):
    def test_scopes_actions_and_manifest_reproducible(self):
        from knowledge.text_quality import (ACTION_NATIVE_REEXTRACT,
                                             ACTION_KEEP,
                                             ACTION_MISSING_SOURCE,
                                             build_inventory)

        kb = _kb()
        try:
            # healthy current engine -> keep
            _seed_doc(kb, "GOOD", "g", ["extr-good"])
            # legacy stdlib engine WITHOUT degraded marker + damage
            # -> native-reextract candidate (not missed by marker filter)
            _seed_doc(kb, "LEGACY", "l", ["extr-legacy"],
                      parser_id="stdlib-pdf",
                      blocks=[{"block_type": "paragraph",
                               "text": _GARBAGE,
                               "locator": {"kind": "pdf", "page": 1},
                               "quality": {"status": "review",
                                           "issues": [
                                               "control_characters"]}},
                              {"block_type": "paragraph",
                               "text": "干净第二页正文内容",
                               "locator": {"kind": "pdf", "page": 2},
                               "quality": {"status": "ready",
                                           "issues": []}}])
            # no snapshot blob -> missing-source
            _seed_doc(kb, "NOSRC", "n", ["extr-nosrc"], with_blob=False)
            # doc without any extraction -> manual-review entry
            kb.upsert_documents([{
                "source": "reports", "doc_id": "EMPTY", "title": "E",
                "symbol": "EX", "available": True,
                "first_seen_at": "2026-10-04T00:00:00Z",
                "last_seen_at": "2026-10-04T00:00:00Z"}],
                "2026-10-04T00:00:00Z")

            inventory = build_inventory(kb)
            self.assertEqual(inventory["counts"]["documents"], 4)
            self.assertEqual(inventory["counts"]["versions_current"], 3)
            self.assertEqual(inventory["counts"]["extractions"], 3)
            actions = {d["doc_id"]: d["recommended_action"]
                       for d in inventory["documents"]}
            self.assertEqual(actions["GOOD"], ACTION_KEEP)
            self.assertEqual(actions["LEGACY"],
                             ACTION_NATIVE_REEXTRACT)
            self.assertEqual(actions["NOSRC"], ACTION_MISSING_SOURCE)
            self.assertEqual(actions["EMPTY"], "manual-review")
            legacy = next(d for d in inventory["documents"]
                          if d["doc_id"] == "LEGACY")
            self.assertEqual(legacy["pages_damaged"], 1)
            self.assertEqual(legacy["pages_total"], 2)
            self.assertFalse(legacy["has_degraded_marker"],
                             "candidate must not depend on the marker")
            self.assertEqual(legacy["engine"], "stdlib-pdf@1")
            # reproducible: same store -> same manifest hash
            again = build_inventory(kb)
            self.assertEqual(inventory["manifest_hash"],
                             again["manifest_hash"])
            # read-only claim carried in the payload
            self.assertTrue(inventory["read_only"])
        finally:
            kb.close()

    def test_history_counted_separately(self):
        from knowledge.text_quality import build_inventory

        kb = _kb()
        try:
            _seed_doc(kb, "H", "h1", ["extr-h1"])
            _seed_doc(kb, "H", "h2", ["extr-h2"], version_id="v2",
                      current=False)
            inventory = build_inventory(kb, include_history=True)
            self.assertEqual(inventory["counts"]["documents"], 1)
            self.assertEqual(inventory["counts"]["versions_current"], 1)
            self.assertEqual(inventory["counts"]["versions_historical"],
                             1)
            doc = inventory["documents"][0]
            self.assertEqual(doc["version_id"], "v1")
        finally:
            kb.close()

    def test_reading_files_hashed_and_mapped(self):
        from knowledge.text_quality import build_inventory
        from knowledge.reading import reading_filename

        kb = _kb()
        try:
            _seed_doc(kb, "F", "f", ["extr-f"])
            reading_dir = os.path.join(temp_dir(), "解析正文")
            os.makedirs(reading_dir, exist_ok=True)
            name = reading_filename("reports", "F", "extr-f")
            with open(os.path.join(reading_dir, name), "w",
                      encoding="utf-8") as handle:
                handle.write("# note\n")
            inventory = build_inventory(kb, reading_dir=reading_dir)
            self.assertEqual(inventory["counts"]["files"], 1)
            entry = inventory["reading_files"][0]
            self.assertEqual(entry["file"], name)
            self.assertRegex(entry["sha256"], "^[0-9a-f]{64}$")
        finally:
            kb.close()

    def test_cli_writes_full_inventory(self):
        import subprocess
        import sys

        kb = _kb()
        db = kb.path
        _seed_doc(kb, "CLI", "c", ["extr-cli"])
        kb.close()
        out = os.path.join(temp_dir(), "inventory.json")
        cfg = os.path.join(temp_dir(), "cfg.json")
        with open(cfg, "w", encoding="utf-8") as handle:
            json.dump({"knowledge_db": db,
                       "snapshot_root": os.path.join(temp_dir(), "s")},
                      handle)
        result = subprocess.run(
            [sys.executable, "-m", "knowledge", "quality-inventory",
             "--config", cfg, "--out", out],
            capture_output=True, text=True, timeout=120,
            cwd=os.path.abspath(os.path.join(os.path.dirname(__file__),
                                             "..", "..")),
            env={**os.environ,
                 "PYTHONPATH": os.path.abspath(
                     os.path.join(os.path.dirname(__file__), ".."))})
        self.assertEqual(result.returncode, 0, result.stderr[-1500:])
        payload = json.load(open(out, encoding="utf-8"))
        self.assertEqual(payload["kind"], "text-quality-inventory")
        self.assertEqual(payload["counts"]["documents"], 1)
        self.assertIn("recommended actions", result.stdout)


if __name__ == "__main__":
    unittest.main()
