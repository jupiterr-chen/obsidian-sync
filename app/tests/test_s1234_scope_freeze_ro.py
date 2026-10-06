"""F1/S1-S4 regressions: sample harness runs for real, scope guards
execution, effective extraction is unified, batches freeze, the CLI is
truly read-only.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from fixtures import temp_dir

REPO = Path(__file__).resolve().parents[2]


def _kb():
    from knowledge.store import KnowledgeStore

    return KnowledgeStore(os.path.join(temp_dir(), "k.sqlite3"))


def _seed_with_snapshot(kb, doc_id, sha, extraction_id, pdf_bytes,
                        parser_id="stdlib-pdf", blocks=None):
    stamp = "2026-10-04T00:00:00Z"
    kb.upsert_documents([{
        "source": "reports", "doc_id": doc_id,
        "title": "Title %s" % doc_id, "symbol": "EX", "available": True,
        "first_seen_at": stamp, "last_seen_at": stamp}], stamp)
    kb.upsert_versions([{
        "source": "reports", "doc_id": doc_id, "version_id": "v1",
        "sha256": sha, "bytes": len(pdf_bytes),
        "media_type": "application/pdf", "ext": "pdf", "rel_path": "x",
        "is_current": True, "state": "ready",
        "content_changed_at": None}], stamp)
    import hashlib

    digest = hashlib.sha256(pdf_bytes).hexdigest()
    assert digest == sha, "seed sha must be the real pdf hash"
    kb.record_blob(sha, len(pdf_bytes), "aa/%s" % sha, stamp)
    root = os.path.join(os.path.dirname(kb.path), "snaps")
    os.makedirs(os.path.join(root, "aa"), exist_ok=True)
    with open(os.path.join(root, "aa", sha), "wb") as handle:
        handle.write(pdf_bytes)
    if blocks is None:
        blocks = [
            {"block_type": "paragraph",
             "text": "旧引擎乱码 %s 第 %d 段：营收 ¥1.2bn，毛利率 25.3%%"
                     % (doc_id, i),
             "locator": {"kind": "pdf", "page": i + 1},
             "quality": {"status": "review",
                         "issues": ["control_characters"]}}
            for i in range(4)]
    if blocks:
        kb.record_extraction({
            "extraction_id": extraction_id, "source": "reports",
            "doc_id": doc_id, "version_id": "v1",
            "snapshot_sha256": sha, "parser_id": parser_id,
            "parser_version": "1",
            "config_digest": "digest-%s" % extraction_id,
            "status": "review", "issues": ["control_characters"],
            "stats": {}}, blocks)


def _numbered_pdf() -> bytes:
    """A small real PDF whose text layer carries key numbers (F1: the
    harness must actually read and extract it, not --help)."""
    content = (b"BT /F1 12 Tf 72 720 Td (Revenue 1,234.5m up 12.5%"
               b" margin 25.3%) Tj ET")
    header = b"%PDF-1.4\n"
    body = (b"3 0 obj\n<< /Length " + str(len(content)).encode()
            + b" >>\nstream\n" + content + b"\nendstream\nendobj\n"
            b"4 0 obj\n<< /Type /Page /Parent 1 0 R /Contents 3 0 R >>"
            b"\nendobj\n")
    trailer = b"trailer\n<< /Root 1 0 R >>\n%%EOF"
    return header + body + trailer


class F1SampleHarnessTest(unittest.TestCase):
    def test_end_to_end_synthetic_run(self):
        """inventory JSON -> harness -> real PDF extraction with the
        numbers present, plus a missing-snapshot case reported."""
        import hashlib

        kb = _kb()
        pdf = _numbered_pdf()
        sha = hashlib.sha256(pdf).hexdigest()
        _seed_with_snapshot(kb, "SAMPLE1", sha, "old-sample1", pdf)
        kb.close()

        db = kb.path
        snaps = os.path.join(os.path.dirname(db), "snaps")
        from knowledge.text_quality import build_inventory

        # build the inventory via the read-only shim like the CLI does
        from knowledge.readonly import open_read_only

        ro = open_read_only(db)
        try:
            inventory = build_inventory(ro, snapshot_root=snaps)
        finally:
            ro.close()
        inventory_path = os.path.join(os.path.dirname(db),
                                      "inventory.json")
        with open(inventory_path, "w", encoding="utf-8") as handle:
            json.dump(inventory, handle, ensure_ascii=False)

        # a second doc with NO snapshot file: reported missing
        kb2_db = db

        out = os.path.join(os.path.dirname(db), "measure.json")
        result = subprocess.run(
            [sys.executable,
             str(REPO / "tools" / "text-quality" / "sample_measure.py"),
             "--inventory", inventory_path,
             "--snapshot-root", snaps,
             "--max-per-layer", "2",
             "--json", out],
            capture_output=True, text=True, timeout=300, cwd=str(REPO),
            env={**os.environ,
                 "PYTHONPATH": str(REPO / "app")})
        self.assertEqual(result.returncode, 0,
                         result.stderr[-2000:])
        report = json.load(open(out, encoding="utf-8"))
        self.assertEqual(report["kind"], "tq-sample-measurement")
        self.assertGreaterEqual(report["sample_size"], 1)
        measured = next(item for item in report["items"]
                        if item["doc_id"] == "SAMPLE1")
        self.assertEqual(measured["status"], "measured", measured)
        # the REAL pdf text came back with its numbers (the extracted
        # layer may space glyph runs - compare space-normalized)
        joined = "".join(str(measured.get("numbers_sample") or [])
                         ).replace(" ", "")
        self.assertIn("25.3%", joined)
        self.assertIn("12.5%", joined)
        self.assertIn("234.5", joined)  # from 1,234.5m
        # damage delta computed from the recorded blocks
        self.assertEqual(measured["damaged_before"], 4)
        self.assertEqual(measured["damaged_pages_after"], 0,
                         "healthy pdf pages must not flag damage")

    def test_missing_snapshot_reported_not_crashed(self):
        import hashlib

        kb = _kb()
        pdf = _numbered_pdf()
        sha = hashlib.sha256(pdf).hexdigest()
        _seed_with_snapshot(kb, "GONE", sha, "old-gone", pdf)
        # remove the snapshot FILE: metadata remains, file gone
        os.remove(os.path.join(os.path.dirname(kb.path), "snaps", "aa",
                               sha))
        kb.close()
        from knowledge.readonly import open_read_only
        from knowledge.text_quality import build_inventory

        ro = open_read_only(kb.path)
        try:
            inventory = build_inventory(
                ro, snapshot_root=os.path.join(os.path.dirname(kb.path),
                                               "snaps"))
        finally:
            ro.close()
        entry = next(d for d in inventory["documents"]
                     if d["doc_id"] == "GONE")
        self.assertFalse(entry["source_available"])
        self.assertEqual(entry["source_check"]["reason"], "file_missing")


class S4ReadOnlyCLITest(unittest.TestCase):
    def test_three_clis_never_touch_a_foreign_database(self):
        import sqlite3

        tmp = temp_dir()
        db = os.path.join(tmp, "foreign.sqlite3")
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE sentinel(value TEXT)")
        conn.commit()
        conn.close()
        cfg = os.path.join(tmp, "cfg.json")
        with open(cfg, "w", encoding="utf-8") as handle:
            json.dump({"knowledge_db": db,
                       "snapshot_root": os.path.join(tmp, "s")}, handle)
        before = open(db, "rb").read()
        env = {**os.environ, "PYTHONPATH": str(REPO / "app")}
        for args in (
                ["quality-inventory", "--config", cfg],
                ["governance-plan", "--config", cfg,
                 "--reading-dir", os.path.join(tmp, "解析正文")],
                ["reprocess", "--config", cfg, "--batch-id", "x",
                 "--dry-run"]):
            result = subprocess.run(
                [sys.executable, "-m", "knowledge"] + args,
                capture_output=True, text=True, timeout=120,
                cwd=str(REPO), env=env)
            self.assertNotEqual(result.returncode, 0,
                                "%s initialized a foreign db" % args[0])
            self.assertIn("unsupported_schema", result.stdout)
        self.assertEqual(open(db, "rb").read(), before,
                         "a read-only CLI modified the database file")
        # missing file: refused without creating it
        missing = os.path.join(tmp, "missing.sqlite3")
        cfg2 = os.path.join(tmp, "cfg2.json")
        with open(cfg2, "w", encoding="utf-8") as handle:
            json.dump({"knowledge_db": missing}, handle)
        result = subprocess.run(
            [sys.executable, "-m", "knowledge", "quality-inventory",
             "--config", cfg2],
            capture_output=True, text=True, timeout=120,
            cwd=str(REPO), env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing_file", result.stdout)
        self.assertFalse(os.path.exists(missing),
                         "the CLI created the database it was asked to"
                         " read")

    def test_supported_database_unchanged_by_read_only_cli(self):
        import hashlib
        import shutil
        import sqlite3

        # a real (writable-created) store, then closed: the read-only
        # CLI must leave its bytes identical
        kb = _kb()
        _seed_with_snapshot(
            kb, "RO", hashlib.sha256(_numbered_pdf()).hexdigest(),
            "old-ro", _numbered_pdf())
        db = kb.path
        kb.close()
        # close WAL cleanly so the main file is stable
        conn = sqlite3.connect(db)
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
        cfg = os.path.join(os.path.dirname(db), "cfg.json")
        with open(cfg, "w", encoding="utf-8") as handle:
            json.dump({"knowledge_db": db,
                       "snapshot_root": os.path.join(
                           os.path.dirname(db), "snaps")},
                      handle)
        before = hashlib.sha256(open(db, "rb").read()).hexdigest()
        result = subprocess.run(
            [sys.executable, "-m", "knowledge", "quality-inventory",
             "--config", cfg],
            capture_output=True, text=True, timeout=120, cwd=str(REPO),
            env={**os.environ, "PYTHONPATH": str(REPO / "app")})
        self.assertEqual(result.returncode, 0, result.stderr[-1500:])
        after = hashlib.sha256(open(db, "rb").read()).hexdigest()
        self.assertEqual(before, after,
                         "quality-inventory mutated a valid database")


class S1ScopeExecutionTest(unittest.TestCase):
    def test_claim_respects_identity_and_empty_scope(self):
        from knowledge.analysis_tasks import (STATUS_PENDING,
                                              claim_pending_analysis_tasks,
                                              register_ready_analysis_tasks)

        kb = _kb()
        try:
            stamp = "2026-10-04T00:00:00Z"
            kb.upsert_documents([{
                "source": "reports", "doc_id": "Q", "title": "Q",
                "symbol": "EX", "available": True,
                "first_seen_at": stamp, "last_seen_at": stamp}], stamp)
            kb.upsert_versions([{
                "source": "reports", "doc_id": "Q", "version_id": "v1",
                "sha256": "q", "bytes": 1,
                "media_type": "application/pdf", "ext": "pdf",
                "rel_path": "x", "is_current": True, "state": "ready",
                "content_changed_at": None}], stamp)
            kb.record_extraction({
                "extraction_id": "extr-q", "source": "reports",
                "doc_id": "Q", "version_id": "v1", "snapshot_sha256":
                    "q", "parser_id": "t", "parser_version": "1",
                "config_digest": "c", "status": "ready", "issues": [],
                "stats": {}},
                [{"block_type": "paragraph", "text": "text " * 20,
                  "locator": {"kind": "pdf", "page": 1},
                  "quality": {"status": "ready", "issues": []}}])
            register_ready_analysis_tasks(
                kb, model_identity="previous-provider/model",
                blocked_reason=None,
                scope={"doc_ids": ["Q"]})
            # a DIFFERENT provider identity claims nothing
            self.assertEqual(claim_pending_analysis_tasks(
                kb, model_identity="new-provider/model"), [])
            # same identity but EMPTY scope claims nothing
            self.assertEqual(claim_pending_analysis_tasks(
                kb, model_identity="previous-provider/model", scope={}), [])
            # same identity + matching scope claims the task
            claimed = claim_pending_analysis_tasks(
                kb, model_identity="previous-provider/model",
                scope={"symbols": ["EX"]})
            self.assertEqual(len(claimed), 1)
        finally:
            kb.close()

    def test_c_scope_blocks_unauthorized_entity(self):
        from knowledge.summaries import STATUS_DONE, consume_updates, \
            enqueue_summary_update, pending_updates, summary_history

        class _Chat:
            name, model = "offline", "x"

            def __init__(self):
                self.calls = 0

            def complete(self, prompt):
                self.calls += 1
                from knowledge.providers import Usage

                return "summary", Usage("offline", "x", 5, 2, "test:offline")

        kb = _kb()
        try:
            stamp = "2026-10-04T00:00:00Z"
            for doc, symbol in (("IN", "AAA"), ("OUT", "BBB")):
                kb.upsert_documents([{
                    "source": "reports", "doc_id": doc,
                    "title": doc, "symbol": symbol, "available": True,
                    "first_seen_at": stamp, "last_seen_at": stamp}],
                    stamp)
                kb.upsert_versions([{
                    "source": "reports", "doc_id": doc,
                    "version_id": "v1", "sha256": doc, "bytes": 1,
                    "media_type": "application/pdf", "ext": "pdf",
                    "rel_path": "x", "is_current": True, "state": "ready",
                    "content_changed_at": None}], stamp)
                kb.record_extraction({
                    "extraction_id": "extr-%s" % doc, "source": "reports",
                    "doc_id": doc, "version_id": "v1",
                    "snapshot_sha256": doc, "parser_id": "t",
                    "parser_version": "1", "config_digest": "c",
                    "status": "ready", "issues": [], "stats": {}},
                    [{"block_type": "paragraph",
                      "text": "%s 正文足够长可以总结，毛利率 25.3%%" % doc,
                      "locator": {"kind": "pdf", "page": 1},
                      "quality": {"status": "ready", "issues": []}}])
            enqueue_summary_update(kb, "company", "AAA",
                                   "document_added", {"doc": "IN"})
            enqueue_summary_update(kb, "company", "BBB",
                                   "document_added", {"doc": "OUT"})
            chat = _Chat()
            result = consume_updates(
                kb, chat=chat,
                allowed_entities={("company", "AAA")})
            self.assertEqual(result["generated"], 1, result)
            self.assertEqual(len(result["errors"]), 1)
            self.assertEqual(chat.calls, 1,
                             "out-of-scope summary was sent")
            self.assertEqual(
                summary_history(kb, "company", "BBB"), [],
                "out-of-scope entity generated a revision")
            # the out-of-scope event stays pending for a widened scope
            pending = {(p["entity_type"], p["entity_id"])
                       for p in pending_updates(kb)}
            self.assertIn(("company", "BBB"), pending)
        finally:
            kb.close()


class F3RetrySemanticsTest(unittest.TestCase):
    def test_provider_failure_backs_off_budget_wait_does_not(self):
        """A retryable provider failure sets a REAL not-before time
        (lease_until in the future + retry_backoff error); a budget
        stop stays immediately retryable next cycle - the two are not
        conflated."""
        from datetime import datetime, timezone

        from knowledge.analysis_tasks import (STATUS_PENDING,
                                              execute_analysis_tasks,
                                              register_ready_analysis_tasks)
        from knowledge.budget import Budget, BudgetLedger
        from knowledge.providers import ProviderCallError

        stamp = "2026-10-04T00:00:00Z"

        def seed(kb, doc):
            kb.upsert_documents([{
                "source": "reports", "doc_id": doc, "title": doc,
                "symbol": "EX", "available": True,
                "first_seen_at": stamp, "last_seen_at": stamp}], stamp)
            kb.upsert_versions([{
                "source": "reports", "doc_id": doc, "version_id": "v1",
                "sha256": doc, "bytes": 1, "media_type":
                    "application/pdf", "ext": "pdf", "rel_path": "x",
                "is_current": True, "state": "ready",
                "content_changed_at": None}], stamp)
            kb.record_extraction({
                "extraction_id": "extr-%s" % doc, "source": "reports",
                "doc_id": doc, "version_id": "v1",
                "snapshot_sha256": doc, "parser_id": "t",
                "parser_version": "1", "config_digest": "c",
                "status": "ready", "issues": [], "stats": {}},
                [{"block_type": "paragraph",
                  "text": "text " * 30,
                  "locator": {"kind": "pdf", "page": 1},
                  "quality": {"status": "ready", "issues": []}}])

        class FailingChat:
            name, model = "offline", "x"

            def complete(self, prompt):
                raise ProviderCallError("transport down",
                                        retryable=True)

        kb = _kb()
        try:
            seed(kb, "FAILDOC")
            register_ready_analysis_tasks(
                kb, model_identity="offline/x", blocked_reason=None)
            execute_analysis_tasks(
                kb, FailingChat(),
                ledger=BudgetLedger(kb, Budget()))
            with kb._lock:
                row = kb._conn.execute(
                    "SELECT status, lease_until, error FROM"
                    " analysis_tasks").fetchone()
            self.assertEqual(row["status"], STATUS_PENDING)
            self.assertIn("retry_backoff", row["error"])
            lease = datetime.fromisoformat(
                row["lease_until"].replace("Z", "+00:00"))
            self.assertGreater(lease, datetime.now(timezone.utc),
                               "failure retry must back off in time")
        finally:
            kb.close()

        # budget stop: no provider failure -> immediately retryable
        kb = _kb()
        try:
            seed(kb, "WAITDOC")
            register_ready_analysis_tasks(
                kb, model_identity="offline/x", blocked_reason=None)

            class CountingChat:
                name, model = "offline", "x"
                calls = 0

                def complete(self, prompt):
                    type(self).calls += 1
                    from knowledge.providers import Usage

                    return "ok [1]", Usage("offline", "x", 5, 2, "t")

            execute_analysis_tasks(
                kb, CountingChat(),
                ledger=BudgetLedger(kb, Budget(max_requests_total=0)))
            with kb._lock:
                row = kb._conn.execute(
                    "SELECT status, lease_until, error FROM"
                    " analysis_tasks").fetchone()
            self.assertEqual(row["status"], STATUS_PENDING)
            self.assertIn("budget", row["error"])
            self.assertTrue(row["lease_until"] is None,
                            "budget wait must not borrow failure"
                            " backoff")
        finally:
            kb.close()


class S2UnifiedSelectionTest(unittest.TestCase):
    def test_reading_search_governance_agree_on_effective(self):
        from knowledge.governance import plan_file_governance
        from knowledge.indexing import _selected_blocks
        from knowledge.reading import ReadingPublisher, reading_filename

        kb = _kb()
        try:
            stamp = "2026-10-04T00:00:00Z"
            kb.upsert_documents([{
                "source": "reports", "doc_id": "UNI", "title": "UNI",
                "symbol": "EX", "available": True,
                "first_seen_at": stamp, "last_seen_at": stamp}], stamp)
            kb.upsert_versions([{
                "source": "reports", "doc_id": "UNI", "version_id": "v1",
                "sha256": "u", "bytes": 1,
                "media_type": "application/pdf", "ext": "pdf",
                "rel_path": "x", "is_current": True, "state": "ready",
                "content_changed_at": None}], stamp)
            kb.record_extraction({
                "extraction_id": "old-good", "source": "reports",
                "doc_id": "UNI", "version_id": "v1",
                "snapshot_sha256": "u", "parser_id": "t",
                "parser_version": "1", "config_digest": "c1",
                "status": "ready", "issues": [], "stats": {}},
                [{"block_type": "paragraph",
                  "text": "旧的好正文：营收 ¥1.2bn，毛利率 25.3%",
                  "locator": {"kind": "pdf", "page": 1},
                  "quality": {"status": "ready", "issues": []}}])
            # first block bad, later blocks good: still usable overall
            kb.record_extraction({
                "extraction_id": "new-mixed", "source": "reports",
                "doc_id": "UNI", "version_id": "v1",
                "snapshot_sha256": "u", "parser_id": "t",
                "parser_version": "1", "config_digest": "c2",
                "status": "review", "issues": [], "stats": {}},
                [{"block_type": "paragraph",
                  "text": "".join(chr(i) for i in range(1, 33)) * 3,
                  "locator": {"kind": "pdf", "page": 1},
                  "quality": {"status": "review",
                              "issues": ["control_characters"]}},
                 {"block_type": "paragraph",
                  "text": "新稿的健康第二页：净利率 12.1%",
                  "locator": {"kind": "pdf", "page": 2},
                  "quality": {"status": "ready", "issues": []}}])
            vault = os.path.join(temp_dir(), "vault")
            os.makedirs(vault, exist_ok=True)
            publisher = ReadingPublisher(kb, vault, base_url="http://x:1")
            for extraction in ("old-good", "new-mixed"):
                publisher.enqueue("reports", "UNI", "v1", extraction)
            publisher.consume()
            index = open(os.path.join(publisher.output, "开始阅读.md"),
                         encoding="utf-8").read()
            # S2/SF02: the old extraction is FULLY healthy; the newer
            # mixed one is partially damaged - the newer result must
            # EARN the entry, so the old one keeps serving
            self.assertIn(reading_filename("reports", "UNI", "old-good"),
                          index)
            self.assertNotIn(reading_filename("reports", "UNI",
                                              "new-mixed"), index)
            self.assertIn("暂用上一版正文", index)
            # search agrees with reading on the effective extraction
            selected = [r["extraction_id"] for r in _selected_blocks(kb)]
            self.assertEqual(selected, ["old-good"])
            # a COMPLETE healthy successor does switch the entry
            kb.record_extraction({
                "extraction_id": "new-complete", "source": "reports",
                "doc_id": "UNI", "version_id": "v1",
                "snapshot_sha256": "u", "parser_id": "t",
                "parser_version": "1", "config_digest": "c3",
                "status": "ready", "issues": [], "stats": {}},
                [{"block_type": "paragraph",
                  "text": "完整健康新稿第一页：营收 ¥1.4bn",
                  "locator": {"kind": "pdf", "page": 1},
                  "quality": {"status": "ready", "issues": []}},
                 {"block_type": "paragraph",
                  "text": "完整健康新稿第二页：净利率 12.1%",
                  "locator": {"kind": "pdf", "page": 2},
                  "quality": {"status": "ready", "issues": []}}])
            publisher.enqueue("reports", "UNI", "v1", "new-complete")
            publisher.consume()
            index = open(os.path.join(publisher.output, "开始阅读.md"),
                         encoding="utf-8").read()
            self.assertIn(reading_filename("reports", "UNI",
                                           "new-complete"), index)
            self.assertEqual({r["extraction_id"]
                              for r in _selected_blocks(kb)},
                             {"new-complete"})
            # old notes remain on disk (history, never deleted)
            for extraction in ("old-good", "new-mixed"):
                self.assertTrue(os.path.isfile(os.path.join(
                    publisher.output, reading_filename(
                        "reports", "UNI", extraction))))
            # governance: every published file keeps (delivered
            # revisions); nothing here is an archive candidate
            plan = plan_file_governance(kb, publisher.output)
            by_file = {f["file"]: f for f in plan["files"]}
            for extraction in ("old-good", "new-mixed", "new-complete"):
                self.assertEqual(by_file[reading_filename(
                    "reports", "UNI", extraction)]["disposition"],
                    "keep")
            self.assertNotIn("archive-candidate", plan["counts"])
        finally:
            kb.close()

    def test_all_polluted_new_extraction_never_wins(self):
        from knowledge.indexing import _selected_blocks
        from knowledge.reading import ReadingPublisher, reading_filename

        kb = _kb()
        try:
            stamp = "2026-10-04T00:00:00Z"
            kb.upsert_documents([{
                "source": "reports", "doc_id": "POLL", "title": "P",
                "symbol": "EX", "available": True,
                "first_seen_at": stamp, "last_seen_at": stamp}], stamp)
            kb.upsert_versions([{
                "source": "reports", "doc_id": "POLL", "version_id":
                    "v1", "sha256": "p", "bytes": 1,
                "media_type": "application/pdf", "ext": "pdf",
                "rel_path": "x", "is_current": True, "state": "ready",
                "content_changed_at": None}], stamp)
            kb.record_extraction({
                "extraction_id": "good-old", "source": "reports",
                "doc_id": "POLL", "version_id": "v1",
                "snapshot_sha256": "p", "parser_id": "t",
                "parser_version": "1", "config_digest": "c1",
                "status": "ready", "issues": [], "stats": {}},
                [{"block_type": "paragraph",
                  "text": "健康旧正文，营收 ¥980m",
                  "locator": {"kind": "pdf", "page": 1},
                  "quality": {"status": "ready", "issues": []}}])
            kb.record_extraction({
                "extraction_id": "bad-new", "source": "reports",
                "doc_id": "POLL", "version_id": "v1",
                "snapshot_sha256": "p", "parser_id": "t",
                "parser_version": "1", "config_digest": "c2",
                "status": "review", "issues": [], "stats": {}},
                [{"block_type": "paragraph",
                  "text": "".join(chr(i) for i in range(1, 33)) * 4,
                  "locator": {"kind": "pdf", "page": 1},
                  "quality": {"status": "review",
                              "issues": ["control_characters"]}}])
            vault = os.path.join(temp_dir(), "vault")
            os.makedirs(vault, exist_ok=True)
            publisher = ReadingPublisher(kb, vault, base_url="http://x:1")
            for extraction in ("good-old", "bad-new"):
                publisher.enqueue("reports", "POLL", "v1", extraction)
            publisher.consume()
            index = open(os.path.join(publisher.output, "开始阅读.md"),
                         encoding="utf-8").read()
            self.assertIn(reading_filename("reports", "POLL",
                                           "good-old"), index)
            self.assertNotIn(reading_filename("reports", "POLL",
                                              "bad-new"), index)
            self.assertIn("暂用上一版正文", index)
            self.assertEqual([r["extraction_id"]
                              for r in _selected_blocks(kb)],
                             ["good-old"])
        finally:
            kb.close()


class S3FreezeTest(unittest.TestCase):
    def test_recipe_and_membership_divergence_refused(self):
        from knowledge.repair import register_reprocess_batch

        kb = _kb()
        try:
            # minimal doc/version rows so job FKs hold
            stamp = "2026-10-04T00:00:00Z"
            for doc in ("A", "B"):
                kb.upsert_documents([{
                    "source": "reports", "doc_id": doc,
                    "title": doc, "symbol": "EX", "available": True,
                    "first_seen_at": stamp,
                    "last_seen_at": stamp}], stamp)
                kb.upsert_versions([{
                    "source": "reports", "doc_id": doc,
                    "version_id": "v1", "sha256": doc, "bytes": 1,
                    "media_type": "application/pdf", "ext": "pdf",
                    "rel_path": "x", "is_current": True,
                    "state": "ready", "content_changed_at": None}],
                    stamp)
            items = [{"source": "reports", "doc_id": "A",
                      "version_id": "v1"}]
            first = register_reprocess_batch(kb, "recipe-1", items, "b1")
            self.assertEqual(first["jobs_registered"], 1)
            # same members, different recipe -> refused
            refused = register_reprocess_batch(kb, "recipe-2", items,
                                               "b1")
            self.assertTrue(refused["refused"])
            self.assertEqual(refused["reason"], "recipe_digest_mismatch")
            # frozen members resume; different member set -> refused
            other = [{"source": "reports", "doc_id": "B",
                      "version_id": "v1"}]
            diverged = register_reprocess_batch(kb, "recipe-1", other,
                                                "b1")
            self.assertTrue(diverged["refused"])
            self.assertEqual(diverged["reason"],
                             "membership_divergence")
            with kb._lock:
                jobs = sorted(r[0] for r in kb._conn.execute(
                    "SELECT doc_id FROM jobs WHERE stage='extract'"
                ).fetchall())
            self.assertEqual(jobs, ["A"],
                             "divergent member registered a job")
        finally:
            kb.close()


if __name__ == "__main__":
    unittest.main()
