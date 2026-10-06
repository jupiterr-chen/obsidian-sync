"""S1234-followup regressions (SF01-SF06) as suite tests.

The probe scripts stay independent evidence; these pin the same
conditions inside the regular suite.
"""
from __future__ import annotations

import hashlib
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from fixtures import temp_dir


def _kb():
    from knowledge.store import KnowledgeStore

    return KnowledgeStore(os.path.join(temp_dir(), "k.sqlite3"))


def _seed_doc(kb, doc_id, symbol=None, title=None):
    stamp = "2026-10-04T00:00:00Z"
    kb.upsert_documents([{
        "source": "reports", "doc_id": doc_id,
        "title": title or doc_id, "symbol": symbol, "available": True,
        "first_seen_at": stamp, "last_seen_at": stamp}], stamp)
    kb.upsert_versions([{
        "source": "reports", "doc_id": doc_id, "version_id": "v1",
        "sha256": doc_id, "bytes": 1, "media_type": "application/pdf",
        "ext": "pdf", "rel_path": "x", "is_current": True,
        "state": "ready", "content_changed_at": None}], stamp)


def _seed_extraction(kb, doc_id, extraction_id, text, status="ready",
                     blocks=None):
    kb.record_extraction({
        "extraction_id": extraction_id, "source": "reports",
        "doc_id": doc_id, "version_id": "v1",
        "snapshot_sha256": doc_id, "parser_id": "t",
        "parser_version": "1",
        "config_digest": "digest-%s" % extraction_id,
        "status": status, "issues": [], "stats": {}},
        blocks if blocks is not None else [
            {"block_type": "paragraph", "text": text,
             "locator": {"kind": "pdf", "page": 1},
             "quality": {"status": "ready", "issues": []}}])


class SFFollowupRegressions(unittest.TestCase):
    def test_sf01_topic_evidence_filtered_by_document_scope(self):
        from knowledge.summaries import _summary_evidence

        kb = _kb()
        from knowledge.summaries import ensure_schema as _ensure

        _ensure(kb)
        try:
            for doc, sentinel in (("ALLOWED", "AUTHORIZED_TEXT"),
                                  ("DENIED", "DENIED_SENTINEL")):
                _seed_doc(kb, doc, symbol=None,
                          title="liquidity %s" % doc)
                _seed_extraction(kb, doc, "extr-%s" % doc,
                                 "%s liquidity view margin 25" % sentinel)
            stamp = "2026-10-04T00:00:00Z"
            with kb._tx() as conn:
                for doc in ("ALLOWED", "DENIED"):
                    conn.execute(
                        "INSERT OR IGNORE INTO entity_documents"
                        " (entity_type, entity_id, source, doc_id,"
                        " first_mapped_at) VALUES ('topic',"
                        " 'liquidity', 'reports', ?, ?)",
                        (doc, stamp))
            allowed = {("reports", "ALLOWED")}
            evidence = _summary_evidence(kb, "topic", "liquidity",
                                         allowed_documents=allowed)
            texts = [item.get("text", "") for item in evidence]
            self.assertTrue(texts, "authorized doc must feed evidence")
            self.assertTrue(all("DENIED_SENTINEL" not in t
                                for t in texts),
                            "out-of-scope document leaked into evidence")
            unfiltered = _summary_evidence(kb, "topic", "liquidity")
            self.assertTrue(any("DENIED_SENTINEL" in
                                item.get("text", "")
                                for item in unfiltered))
        finally:
            kb.close()

    def test_sf02_partial_damage_does_not_displace_complete_old(self):
        from knowledge.indexing import _selected_blocks
        from knowledge.effective import effective_extraction

        kb = _kb()
        try:
            _seed_doc(kb, "PAGES")
            _seed_extraction(kb, "PAGES", "good-old", "x", blocks=[
                {"block_type": "paragraph",
                 "text": "healthy page one revenue 123",
                 "locator": {"kind": "pdf", "page": 1},
                 "quality": {"status": "ready", "issues": []}},
                {"block_type": "paragraph",
                 "text": "healthy page two margin 25%",
                 "locator": {"kind": "pdf", "page": 2},
                 "quality": {"status": "ready", "issues": []}}])
            garbage = "".join(chr(i) for i in range(1, 33)) * 4
            _seed_extraction(kb, "PAGES", "mixed-new", "x",
                             status="review", blocks=[
                {"block_type": "paragraph", "text": garbage,
                 "locator": {"kind": "pdf", "page": 1},
                 "quality": {"status": "review",
                             "issues": ["damaged_text_layer"]}},
                {"block_type": "paragraph",
                 "text": "healthy page two margin 25%",
                 "locator": {"kind": "pdf", "page": 2},
                 "quality": {"status": "ready", "issues": []}}])
            chosen = effective_extraction(kb._conn, "reports", "PAGES",
                                          "v1")
            self.assertEqual(chosen["extraction_id"], "good-old")
            selected = _selected_blocks(kb)
            self.assertEqual(len(selected), 2,
                             "old complete text must keep both blocks"
                             " in the default index")
            # degraded fallback: with NO fully-usable extraction the
            # partially usable newer one serves (better than nothing)
            _seed_doc(kb, "ONLY")
            kb.record_extraction({
                "extraction_id": "only-partial", "source": "reports",
                "doc_id": "ONLY", "version_id": "v1",
                "snapshot_sha256": "ONLY", "parser_id": "t",
                "parser_version": "1",
                "config_digest": "digest-only-partial",
                "status": "review", "issues": [], "stats": {}},
                [{"block_type": "paragraph", "text": garbage,
                  "locator": {"kind": "pdf", "page": 1},
                  "quality": {"status": "review",
                              "issues": ["damaged_text_layer"]}},
                 {"block_type": "paragraph",
                  "text": "only healthy page",
                  "locator": {"kind": "pdf", "page": 2},
                  "quality": {"status": "ready", "issues": []}}])
            kb.record_extraction({
                "extraction_id": "only-old", "source": "reports",
                "doc_id": "ONLY", "version_id": "v1",
                "snapshot_sha256": "ONLY", "parser_id": "t",
                "parser_version": "1", "config_digest": "digest-only-old",
                "status": "ready", "issues": [], "stats": {}},
                [{"block_type": "paragraph",
                  "text": "older but also damaged " + garbage,
                  "locator": {"kind": "pdf", "page": 1},
                  "quality": {"status": "review",
                              "issues": ["control_characters"]}}])
            chosen2 = effective_extraction(kb._conn, "reports", "ONLY",
                                           "v1")
            self.assertEqual(chosen2["extraction_id"], "only-partial",
                             "no fully-usable candidate: newest partial"
                             " serves as the degraded fallback")
        finally:
            kb.close()

    def test_sf03_wikilink_fragment_reference_keeps_file(self):
        import hashlib

        from knowledge.governance import plan_file_governance

        kb = _kb()
        try:
            vault = os.path.join(temp_dir(), "vault")
            reading = os.path.join(vault, "解析正文")
            os.makedirs(reading, exist_ok=True)
            legacy = os.path.join(reading, "text-legacy.md")
            with open(legacy, "w", encoding="utf-8") as handle:
                handle.write("machine legacy content")
            manifest_path = os.path.join(reading,
                                         ".knowledge-writeback.json")
            import json

            with open(manifest_path, "w", encoding="utf-8") as handle:
                json.dump({"files": {"text-legacy.md": {
                    "owner": "existing-text-export",
                    "last_hash": hashlib.sha256(
                        open(legacy, "rb").read()).hexdigest()}}},
                    handle)
            # human note OUTSIDE the generated dir, wikilink with path
            # prefix + fragment anchor
            note_dir = os.path.join(vault, "公司研究")
            os.makedirs(note_dir, exist_ok=True)
            with open(os.path.join(note_dir, "note.md"), "w",
                      encoding="utf-8") as handle:
                handle.write("研究引用 [[解析正文/text-legacy#^evidence]]"
                             " 以及 [[解析正文/text-legacy|别名]]")
            plan = plan_file_governance(kb, reading)
            entry = next(f for f in plan["files"]
                         if f["file"] == "text-legacy.md")
            self.assertTrue(entry["referenced_from_vault"])
            self.assertNotEqual(entry["disposition"],
                                "archive-candidate")
            self.assertEqual(entry["disposition"], "keep")
        finally:
            kb.close()

    def test_sf04_runner_refuses_frozen_recipe_job(self):
        from knowledge.config import KnowledgeConfig
        from knowledge.jobs import JobRunner

        kb = _kb()
        try:
            root = Path(temp_dir())
            raw = b"synthetic revenue text for recipe freeze\n" * 4
            sha = hashlib.sha256(raw).hexdigest()
            (root / "blob.txt").write_bytes(raw)
            stamp = "2026-10-04T00:00:00Z"
            kb.upsert_documents([{
                "source": "reports", "doc_id": "R", "title": "R",
                "symbol": "EX", "available": True,
                "first_seen_at": stamp, "last_seen_at": stamp}], stamp)
            kb.upsert_versions([{
                "source": "reports", "doc_id": "R", "version_id": "v1",
                "sha256": sha, "bytes": len(raw),
                "media_type": "text/plain", "ext": "txt",
                "rel_path": "x", "is_current": True, "state": "ready",
                "content_changed_at": None}], stamp)
            kb.record_blob(sha, len(raw), "blob.txt", stamp)
            kb.record_snapshot("reports", "R", "v1", sha, len(raw),
                               "blob.txt", stamp)
            approved = KnowledgeConfig(
                knowledge_db=kb.path, snapshot_root=str(root),
                extra={"ocr": {"engine": "off", "max_pages_per_doc": 1}})
            approved_digest = JobRunner(kb, approved, None).extract_digest
            kb.register_job("reports", "R", "v1", "extract",
                            approved_digest)
            other = KnowledgeConfig(
                knowledge_db=kb.path, snapshot_root=str(root),
                extra={"ocr": {"engine": "off", "max_pages_per_doc": 2}})
            runner = JobRunner(kb, other, None)
            self.assertNotEqual(runner.extract_digest, approved_digest)
            outcome = runner.run_extract_jobs(limit=1)
            self.assertEqual(outcome["done"], 0)
            self.assertGreaterEqual(outcome["recipe_refused"], 1)
            with kb._lock:
                row = kb._conn.execute(
                    "SELECT config_digest FROM extractions WHERE"
                    " doc_id='R'").fetchone()
                job = kb._conn.execute(
                    "SELECT status FROM jobs WHERE stage='extract'"
                    " AND doc_id='R'").fetchone()
            self.assertIsNone(row,
                              "extraction recorded under wrong recipe")
            self.assertEqual(job["status"], "running",
                             "refused job keeps its lease for recovery")
            # the approved-recipe runner CAN still execute it once the
            # refusal lease expires (simulate time passing)
            with kb._tx() as conn:
                conn.execute(
                    "UPDATE jobs SET lease_until='2020-01-01T00:00:00Z'"
                    " WHERE stage='extract' AND doc_id='R'")
            kb.recover_stale_jobs("extract")
            outcome2 = JobRunner(kb, approved, None).run_extract_jobs(
                limit=1)
            self.assertEqual(outcome2["done"], 1, outcome2)
        finally:
            kb.close()

    def test_sf06_crash_mid_registration_resumes_full_batch(self):
        from knowledge.repair import register_reprocess_batch

        kb = _kb()
        try:
            for doc in ("A", "B"):
                _seed_doc(kb, doc)
            items = [{"source": "reports", "doc_id": d,
                      "version_id": "v1"} for d in ("A", "B")]
            with patch.object(kb, "register_job",
                              side_effect=RuntimeError("crash")):
                with self.assertRaises(RuntimeError):
                    register_reprocess_batch(kb, "recipe", items, "b")
            resumed = register_reprocess_batch(kb, "recipe", items, "b")
            self.assertFalse(resumed.get("refused"), resumed)
            self.assertEqual(resumed["jobs_registered"], 2)
            with kb._lock:
                members = sorted(r[0] for r in kb._conn.execute(
                    "SELECT doc_id FROM reprocess_batches WHERE"
                    " batch_id='b'"))
                jobs = sorted(r[0] for r in kb._conn.execute(
                    "SELECT doc_id FROM jobs WHERE stage='extract'"))
            self.assertEqual(members, ["A", "B"],
                             "the freeze must persist the COMPLETE list")
            self.assertEqual(jobs, ["A", "B"])
        finally:
            kb.close()

    def test_sf05_budget_waits_then_recovery_succeeds(self):
        from knowledge.analysis_tasks import (execute_analysis_tasks,
                                              register_ready_analysis_tasks)
        from knowledge.budget import Budget, BudgetLedger

        class Chat:
            name, model = "offline-fake", "fake-model"
            calls = 0

            def complete(self, prompt):
                type(self).calls += 1
                from knowledge.providers import Usage

                return "summary [1]", Usage(self.name, self.model,
                                            5, 2, "test:offline")

        kb = _kb()
        try:
            _seed_doc(kb, "W")
            _seed_extraction(kb, "W", "extr-w", "waiting text " * 20)
            register_ready_analysis_tasks(
                kb, model_identity="offline-fake/fake-model",
                blocked_reason=None)
            for _ in range(3):
                execute_analysis_tasks(
                    kb, Chat(), max_attempts=3,
                    ledger=BudgetLedger(kb, Budget(
                        max_requests_total=0)))
            self.assertEqual(Chat.calls, 0)
            with kb._lock:
                row = kb._conn.execute(
                    "SELECT status, attempts FROM analysis_tasks"
                ).fetchone()
            self.assertEqual(row["status"], "pending")
            self.assertEqual(row["attempts"], 0,
                             "budget waits must not consume attempts")
            outcome = execute_analysis_tasks(
                kb, Chat(), max_attempts=3,
                ledger=BudgetLedger(kb, Budget()))
            self.assertEqual(outcome["done"], 1)
            self.assertEqual(Chat.calls, 1)
        finally:
            kb.close()


if __name__ == "__main__":
    unittest.main()
