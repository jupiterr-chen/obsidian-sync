"""Second-review regressions (S01-S10) - assertion-style, RED first.

Reproduces the re-review counterexamples from
docs/progress/RE-REVIEW-20261003.md with deterministic interleaving:
separate DB connections/processes for atomicity, barrier-controlled
threads for races, controlled providers and file replacement for content
races. No sleeps-as-synchronization.
"""

from __future__ import annotations

import json
import os
import threading
import unittest

from fixtures import temp_dir


def _kb(path=None):
    from knowledge.store import KnowledgeStore

    return KnowledgeStore(path or os.path.join(temp_dir(), "knowledge.sqlite3"))


# ================================================================== S01
class S01BudgetAtomicityTest(unittest.TestCase):
    def test_concurrent_reservations_cannot_overspend(self):
        """Two INDEPENDENT connections, cap 10, each reserves 6: exactly one
        wins (the review got both accepted = 12 reserved)."""
        from budget_under_test import LedgerPair

        pair = LedgerPair(cap=10)
        barrier = threading.Barrier(2)
        results = []

        def worker(ledger):
            barrier.wait()
            try:
                rid = ledger.reserve("chat", 6)
                results.append(("ok", rid))
            except Exception as exc:
                results.append(("rejected", type(exc).__name__))

        threads = [threading.Thread(target=worker, args=(ledger,))
                   for ledger in pair.ledgers]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        accepted = [r for r in results if r[0] == "ok"]
        self.assertEqual(len(accepted), 1,
                         "cap 10 must admit at most one 6-token reservation,"
                         " got %r" % (results,))
        pair.close()

    def test_page_cap_counts_pending_reservations(self):
        """cap 1 page: the second page request must be refused BEFORE the
        provider call, and unknown-settled pages still count."""
        from knowledge.budget import Budget, BudgetLedger
        from knowledge.ocr import VisionApiOcr
        from knowledge.providers import OpenAICompatibleVision, ProviderCallError, Usage

        class CountingVision(OpenAICompatibleVision):
            def __init__(self):
                super().__init__("vision_ocr", "m", "http://x", "k",
                                 egress_allowed=True)
                self.calls = 0

            def complete_with_image(self, prompt, image_bytes, mime="image/png",
                                    max_output_tokens=2000):
                self.calls += 1
                return "text", Usage(self.name, self.model, 10, 0, "t")

        kb = _kb()
        try:
            chat = CountingVision()
            ledger = BudgetLedger(kb, Budget(max_pages_total=1,
                                             max_input_tokens_per_page=100,
                                             max_total_input_tokens=1000))
            engine = VisionApiOcr(chat_provider=chat, ledger=ledger,
                                  page_token_cap=50)
            engine.run(b"PNG")  # page 1 accepted, settled
            with self.assertRaises(Exception):
                engine.run(b"PNG")  # page 2 must be refused
            self.assertEqual(chat.calls, 1)
        finally:
            kb.close()

    def test_settlement_crash_does_not_restore_budget(self):
        """settle() interrupted after the provider returned usage: the
        consumption must eventually land; retrying settle is idempotent."""
        from knowledge.budget import Budget, BudgetLedger
        from knowledge.providers import Usage

        kb = _kb()
        try:
            ledger = BudgetLedger(kb, Budget(max_total_input_tokens=10))
            rid = ledger.reserve("chat", 6)
            usage = Usage("p", "m", 6, 1, "t:none")
            # first settle attempt crashes INSIDE, before committing usage
            try:
                ledger.settle_crash_before_usage(rid, usage)
            except RuntimeError:
                pass  # the crash point under test
            totals = ledger._totals()
            # the reservation must not have silently vanished: either the
            # reservation is still outstanding or usage landed
            self.assertGreater(totals["input"], 0,
                               "interrupted settle restored the full budget")
            # idempotent retry completes exactly once
            ledger.settle(rid, usage)
            ledger.settle(rid, usage)
            rows = kb._conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE input_tokens=6"
            ).fetchone()[0]
            self.assertEqual(rows, 1)
        finally:
            kb.close()

    def test_missing_usage_on_success_is_charged_conservatively(self):
        """Provider returned text but NO usage: cannot count as zero."""
        from knowledge.budget import Budget, BudgetLedger
        from knowledge.providers import Usage

        kb = _kb()
        try:
            ledger = BudgetLedger(kb, Budget(max_total_input_tokens=1000))
            rid = ledger.reserve("chat", 200)
            ledger.settle(rid, Usage("p", "m", 0, 0, "none"))  # provider gave nothing
            # zero-usage settlement must still leave the reservation's
            # estimate accounted (not full release)
            totals = ledger._totals()
            self.assertGreaterEqual(totals["input"], 200,
                                    "missing usage must charge the estimate")
        finally:
            kb.close()


# ================================================================== S02
class S02WritebackAppendOnlyTest(unittest.TestCase):
    def setUp(self):
        from knowledge.writeback import register_write_root

        self.dir = os.path.join(temp_dir(), "vault-gen")
        os.makedirs(self.dir, exist_ok=True)
        register_write_root(self.dir)

    def test_post_check_edit_never_loses_human_content(self):
        """Deterministic race: a human write is injected AFTER the final
        hash check but BEFORE the replace. The human text must survive."""
        from knowledge import writeback as wb

        target = os.path.join(self.dir, "clm-race.md")
        wb.write_candidate(self.dir, "clm-race.md", "machine-v1")
        original_replace = os.replace
        gate = threading.Event()

        def racing_replace(src, dst, *args, **kwargs):
            # the external editor writes between check and replace
            if dst == target and not gate.is_set():
                gate.set()
                with open(dst, "w", encoding="utf-8") as handle:
                    handle.write("HUMAN CONTENT WRITTEN IN THE WINDOW")
            return original_replace(src, dst, *args, **kwargs)

        wb.os.replace = racing_replace
        try:
            result = wb.write_candidate(self.dir, "clm-race.md", "machine-v2")
        finally:
            wb.os.replace = original_replace
        with open(target, "r", encoding="utf-8") as handle:
            final = handle.read()
        self.assertIn("HUMAN CONTENT WRITTEN IN THE WINDOW", final,
                      "post-check overwrite destroyed human content (%r)" % result)

    def test_machine_outputs_are_immutable_appends(self):
        """Generated outputs go to unique append-only names; a 'latest'
        pointer, if any, is machine-owned metadata, never a human-editable
        file the service rewrites."""
        from knowledge.writeback import write_candidate

        first = write_candidate(self.dir, "doc.md", "v1")
        second = write_candidate(self.dir, "doc.md", "v2 after human edit")
        # simulate a human editing the machine file between exports
        target = os.path.join(self.dir, "doc.md")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("human rewrite")
        third = write_candidate(self.dir, "doc.md", "v3")
        with open(target, "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "human rewrite")


# ================================================================== S03
class S03PublicAsOfTest(unittest.TestCase):
    def _seed(self, kb, report_date="2026-06-30", published_at=None,
              filing_date=None):
        from knowledge.indexing import build_generation

        stamp = "2026-01-10T00:00:00Z"
        kb.upsert_documents([{
            "source": "reports", "doc_id": "R1", "title": "R1",
            "symbol": "EX", "available": True, "first_seen_at": stamp,
            "last_seen_at": stamp, "report_date": report_date,
            "published_at": published_at, "filing_date": filing_date,
        }], stamp)
        kb.upsert_versions([{
            "source": "reports", "doc_id": "R1", "version_id": "v1",
            "sha256": "a" * 64, "bytes": 10, "media_type": "application/pdf",
            "ext": "pdf", "rel_path": "x", "is_current": True,
            "state": "ready", "content_changed_at": None,
            "first_observed_at": stamp,
        }], stamp)
        kb.record_extraction({
            "extraction_id": "extr-r1", "source": "reports", "doc_id": "R1",
            "version_id": "v1", "snapshot_sha256": "a" * 64,
            "parser_id": "t", "parser_version": "1", "config_digest": "c",
            "status": "ready", "issues": [], "stats": {},
        }, [{
            "block_type": "paragraph", "text": "margin evidence text",
            "locator": {"kind": "pdf", "page": 1},
            "quality": {"status": "ready", "issues": []},
        }])
        build_generation(kb)

    def test_report_period_is_not_publication_time(self):
        """Report period 6/30, published 8/20: a cutoff of 7/1 must NOT
        see the document (the review's leak)."""
        from knowledge.indexing import SearchFilters, search

        kb = _kb()
        try:
            self._seed(kb, report_date="2026-06-30",
                       published_at="2026-08-20T12:00:00Z")
            result = search(kb, "margin", SearchFilters(
                as_of="2026-07-01T00:00:00Z", as_of_mode="public"))
            self.assertEqual(result["hits"], [],
                             "report date leaked as publication time")
            after = search(kb, "margin", SearchFilters(
                as_of="2026-08-21T00:00:00Z", as_of_mode="public"))
            self.assertGreater(len(after["hits"]), 0)
        finally:
            kb.close()

    def test_version_level_public_time_basis(self):
        """The public basis must be recorded per version with a source and
        an explicit unknown state - not inferred from document dates alone."""
        kb = _kb()
        try:
            stamp = "2026-01-10T00:00:00Z"
            kb.upsert_documents([{
                "source": "reports", "doc_id": "R1", "title": "R1",
                "available": True, "first_seen_at": stamp,
                "last_seen_at": stamp,
            }], stamp)
            kb.upsert_versions([{
                "source": "reports", "doc_id": "R1", "version_id": "v1",
                "sha256": "a" * 64, "bytes": 10, "media_type": "application/pdf",
                "ext": "pdf", "rel_path": "x", "is_current": True,
                "state": "ready", "content_changed_at": None,
            }], stamp)
            version = kb.get_version("reports", "R1", "v1")
            self.assertIn("public_available_at", version)
            self.assertIn("public_time_basis", version)
            # no document dates at all -> unknown, never fabricated
            self.assertIsNone(version["public_available_at"])
            self.assertEqual(version["public_time_basis"], "unknown")
        finally:
            kb.close()


# ================================================================== S04
class S04SnapshotBytesTest(unittest.TestCase):
    def test_returned_bytes_are_verified_once_and_match_etag(self):
        """Blob rewritten between verification and read: the API must
        return the ORIGINAL verified bytes or refuse - never new bytes with
        the old ETag."""
        import hashlib
        import tempfile

        from knowledge.kbapi import KbApi
        from knowledge.snapshot import SnapshotStore, snapshot_version

        kb = _kb()
        store_root = os.path.join(temp_dir(), "blobs")
        blobs = SnapshotStore(store_root)
        try:
            stamp = "2026-10-01T00:00:00Z"
            payload = b"ORIGINAL VERIFIED BYTES"
            kb.upsert_documents([{
                "source": "reports", "doc_id": "R1", "title": "R1",
                "available": True, "first_seen_at": stamp,
                "last_seen_at": stamp,
            }], stamp)
            kb.upsert_versions([{
                "source": "reports", "doc_id": "R1", "version_id": "v1",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload), "media_type": "application/pdf",
                "ext": "pdf", "rel_path": "x", "is_current": True,
                "state": "ready", "content_changed_at": None,
            }], stamp)
            fd, path = tempfile.mkstemp()
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
            with open(path, "rb") as handle:
                sha = snapshot_version(kb, blobs, handle, "reports", "R1",
                                       "v1", None, len(payload))
            snap = kb.get_snapshot("reports", "R1", "v1")
            blob_path = os.path.join(store_root,
                                     *snap["store_path"].split("/"))

            api = KbApi(kb, {"t": ["research.read"]},
                        snapshot_root=store_root)
            from knowledge import kbapi as kbapi_module
            original_open = open
            gate = threading.Event()

            def racing_open(file, *args, **kwargs):
                handle = original_open(file, *args, **kwargs)
                if file == blob_path and "rb" in str(args[:1]) and not gate.is_set():
                    gate.set()
                    # external writer replaces content after verification
                    with original_open(blob_path, "wb") as writer:
                        writer.write(b"EVIL REPLACEMENT")
                return handle

            kbapi_module.open = racing_open  # if kbapi uses module-level open
            try:
                result = api.snapshot_bytes("reports", "R1", "v1")
            except Exception:
                result = None  # refusal is acceptable
            finally:
                kbapi_module.open = original_open
            if result is not None:
                self.assertEqual(result["data"], b"ORIGINAL VERIFIED BYTES",
                                 "returned bytes differ from the verified copy")
                self.assertEqual(result["etag"], '"%s"' % sha)
        finally:
            kb.close()


# ================================================================== S05
class S05OcrConfidenceGateTest(unittest.TestCase):
    def _pdf(self):
        return (b"%PDF-1.4\n"
                b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
                b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
                b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
                b" /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n"
                b"4 0 obj\n<< /Length 44 >>\nstream\nBT /F1 12 Tf 72 720 Td () Tj ET\n"
                b"endstream\nendobj\n"
                b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
                b"xref\n0 6\n0000000000 65535 f \n"
                + b"0000000009 00000 n \n" * 0 +  # offsets approximate; pdfium tolerant
                b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n0\n%%EOF")

    def test_low_confidence_ocr_is_not_ready(self):
        from knowledge.extract import extract_pdf
        from knowledge.ocr import OcrConfig

        class LowConfOcr:
            name = "low-engine"

            def run(self, image_bytes):
                return ("OCR 识别出的长文本内容用于绕过最短长度检查" * 3, 0.1)

        result = extract_pdf(self._pdf(), ocr=LowConfOcr(),
                             ocr_config=OcrConfig(min_confidence=0.6),
                             renderer=lambda r, p, dpi=200: b"PNG")
        self.assertNotEqual(result.status, "ready",
                            "conf=0.1 page must not be document-ready")
        self.assertTrue(all(b.quality.status != "ready" or
                            "ocr" not in (b.quality.issues and " ".join(b.quality.issues) or "")
                            for b in result.blocks))
        # per-page confidence must be queryable, not buried in a string
        self.assertIn("page_confidences", result.stats)
        self.assertLess(result.stats["page_confidences"][0], 0.6)

    def test_empty_ocr_and_fallback_failure_degrade(self):
        from knowledge.extract import extract_pdf
        from knowledge.ocr import OcrConfig

        class EmptyOcr:
            name = "empty-engine"

            def run(self, image_bytes):
                return ("", 0.0)

        class FailingFallback:
            name = "fb"

            def run(self, image_bytes):
                raise RuntimeError("fallback exploded")

        result = extract_pdf(self._pdf(), ocr=EmptyOcr(),
                             ocr_config=OcrConfig(min_confidence=0.6),
                             renderer=lambda r, p, dpi=200: b"PNG",
                             fallback_ocr=FailingFallback())
        self.assertNotEqual(result.status, "ready")


# ================================================================== S06
class S06ImageDuplicateOcrTest(unittest.TestCase):
    def test_same_image_reuse_skips_ocr_entirely(self):
        import os

        from fixtures import make_config
        from knowledge.config import KnowledgeConfig
        from knowledge.jobs import JobRunner
        from knowledge.snapshot import SnapshotStore
        from knowledge.store import KnowledgeStore
        from knowledge.sync import SyncService

        tmp = temp_dir()
        library_config, reports, discord = make_config(tmp)
        from library.ingest import Ingestor

        ingestor = Ingestor(library_config)
        self.assertTrue(ingestor.run()["ok"])
        ingestor.close()
        config = KnowledgeConfig(
            catalog_db=library_config.catalog_db,
            knowledge_db=os.path.join(tmp, "state", "knowledge.sqlite3"),
            snapshot_root=os.path.join(tmp, "state", "snapshots"),
            library_config="unused",
            register_stages=("snapshot",))
        kb = KnowledgeStore(config.knowledge_db)
        SyncService(kb, config).run()
        runner = JobRunner(kb, config, library_config,
                           blobs=SnapshotStore(config.snapshot_root))
        self.assertTrue(runner.run_snapshot_jobs()["ok"])

        config.register_stages = ("snapshot", "extract")
        # controlled OCR engine counts invocations
        calls = []

        from knowledge.ocr import OcrEngineError
        from knowledge import ocr as ocr_module

        class CountingEngine:
            name = "counting"

            def run(self, image_bytes):
                calls.append(1)
                return ("chart text interpretation " * 5, 0.95)

        real_build = ocr_module.build_ocr_engine

        def build_with_counting(ocr_config=None, providers=None,
                                provider_specs=None, ledger=None):
            return CountingEngine()

        ocr_module.build_ocr_engine = build_with_counting
        try:
            import knowledge.jobs as jobs_module
            jobs_module.build_ocr_engine = build_with_counting
            first = runner.run_extract_jobs()
            self.assertTrue(first["ok"], first.get("errors"))
            before = len(calls)
            with kb._tx() as conn:
                conn.execute("UPDATE jobs SET status='pending'"
                             " WHERE stage='extract'")
            second = runner.run_extract_jobs()
            self.assertTrue(second["ok"], second.get("errors"))
            self.assertEqual(len(calls) - before, 0,
                             "identical config rerun re-invoked OCR %d times"
                             % (len(calls) - before))
        finally:
            ocr_module.build_ocr_engine = real_build
            jobs_module.build_ocr_engine = real_build
            kb.close()


# ================================================================== S07
class S07OutboxAtomicTest(unittest.TestCase):
    def test_crash_between_upsert_and_enqueue_recovers_on_resync(self):
        import os

        from fixtures import make_config
        from knowledge.config import KnowledgeConfig
        from knowledge.jobs import JobRunner
        from knowledge.memory import create_claim
        from knowledge.snapshot import SnapshotStore
        from knowledge.store import KnowledgeStore
        from knowledge.sync import SyncService

        tmp = temp_dir()
        library_config, reports, discord = make_config(tmp)
        from library.ingest import Ingestor

        ingestor = Ingestor(library_config)
        self.assertTrue(ingestor.run()["ok"])
        ingestor.close()
        config = KnowledgeConfig(
            catalog_db=library_config.catalog_db,
            knowledge_db=os.path.join(tmp, "state", "knowledge.sqlite3"),
            snapshot_root=os.path.join(tmp, "state", "snapshots"),
            library_config="unused")
        kb = KnowledgeStore(config.knowledge_db)
        runner = JobRunner(kb, config, library_config,
                           blobs=SnapshotStore(config.snapshot_root))
        create_claim(kb, "claim on a111",
                     [{"source": "reports", "doc_id": "a1111111111111111111",
                       "version_id": "b2222222222222222222", "block_id": "x",
                       "extraction_id": "y"}], subject="EX")

        # add a new artifact to the archive, re-ingest library
        import hashlib
        import sqlite3

        data = b"%PDF-1.4 s03 wave content"
        rel = ("CN/600519/x__a1111111111111111111__e0000000000000000009.pdf")
        path = os.path.join(reports["root"], rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)
        conn = sqlite3.connect(reports["db"])
        conn.execute(
            "INSERT INTO artifacts VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("e0000000000000000009", "a1111111111111111111",
             hashlib.sha256(data).hexdigest(), len(data),
             "application/pdf", "/app/reports/" + rel,
             "2026-07-10T00:00:00Z", "ready", "http://e", None))
        conn.execute("UPDATE manifest SET current_artifact_id="
                     "'e0000000000000000009' WHERE report_id="
                     "'a1111111111111111111'")
        conn.commit()
        conn.close()
        ingestor = Ingestor(library_config)
        self.assertTrue(ingestor.run()["ok"])
        ingestor.close()

        # crash exactly inside the version-commit transaction, at the
        # outbox enqueue step (S07: both must now roll back together)
        real_enqueue = KnowledgeStore._enqueue_impact_conn
        crashed = {"done": False}

        def crashing_enqueue(self, conn, rows):
            if not crashed["done"]:
                crashed["done"] = True
                raise RuntimeError("simulated crash at enqueue")
            return real_enqueue(self, conn, rows)

        KnowledgeStore._enqueue_impact_conn = crashing_enqueue
        try:
            try:
                SyncService(kb, config).run()
            except RuntimeError:
                pass  # the crash point under test
        finally:
            KnowledgeStore._enqueue_impact_conn = real_enqueue

        # S07 atomicity: the crash rolled the version insert back WITH the
        # enqueue, so the retry sees the version as new again and re-runs
        # both - the impact task is never lost
        stats = SyncService(kb, config).run()
        self.assertGreaterEqual(stats.get("new_versions"), 1)
        pending = kb.pending_impacts()
        target = [p for p in pending
                  if p["version_id"] == "e0000000000000000009"]
        self.assertEqual(len(target), 1,
                         "crash-lost enqueue must exist EXACTLY once after"
                         " the atomic retry (pending=%d, target=%d)"
                         % (len(pending), len(target)))
        try:
            kb.close()
        except Exception:
            pass


# ================================================================== S08
class S08CursorMetadataTest(unittest.TestCase):
    def test_metadata_change_invalidates_or_consistently_pages(self):
        from knowledge.indexing import build_generation, search
        from knowledge.kbapi import KbApi, KbApiError

        kb = _kb()
        try:
            stamp = "2026-10-01T00:00:00Z"
            for doc_id, symbol in (("A", "SA"), ("B", "SB")):
                kb.upsert_documents([{
                    "source": "reports", "doc_id": doc_id, "title": doc_id,
                    "symbol": symbol, "available": True,
                    "first_seen_at": stamp, "last_seen_at": stamp,
                }], stamp)
                kb.upsert_versions([{
                    "source": "reports", "doc_id": doc_id,
                    "version_id": "v1", "sha256": "a" * 64, "bytes": 10,
                    "media_type": "application/pdf", "ext": "pdf",
                    "rel_path": "x", "is_current": True, "state": "ready",
                    "content_changed_at": None,
                }], stamp)
                kb.record_extraction({
                    "extraction_id": "extr-%s" % doc_id, "source": "reports",
                    "doc_id": doc_id, "version_id": "v1",
                    "snapshot_sha256": "a" * 64, "parser_id": "t",
                    "parser_version": "1", "config_digest": "c",
                    "status": "ready", "issues": [], "stats": {},
                }, [{
                    "block_type": "paragraph",
                    "text": "common margin evidence %s block %d" % (doc_id, i),
                    "locator": {"kind": "pdf", "page": i + 1},
                    "quality": {"status": "ready", "issues": []},
                } for i in range(2)])
            build_generation(kb)
            api = KbApi(kb, {"t": ["research.read"]})
            first = api.do_search({"query": "common", "limit": 2})
            self.assertEqual(len(first["hits"]), 2)
            self.assertIsNotNone(first["next_cursor"])
            # metadata revision between pages: doc A withdrawn
            kb.upsert_documents([dict(available=False, doc_id="A",
                                      source="reports", title="A")],
                                "2026-10-02T00:00:00Z")
            # B's two blocks remain visible: page 2 must surface them or
            # the API must explicitly refuse the stale cursor (409) -
            # never a silent empty page that strands B
            refused = False
            try:
                second = api.do_search({"query": "common", "limit": 2,
                                        "cursor": first["next_cursor"]})
            except KbApiError as exc:
                self.assertEqual(exc.status, 409)
                refused = True
                second = None
            if not refused:
                seen = [h["doc_id"] for h in first["hits"]] +                        [h["doc_id"] for h in second["hits"]]
                self.assertIn("B", seen,
                              "B became invisible across pages: %r" % seen)
                self.assertEqual(len(seen), len(set(seen)))
        finally:
            kb.close()


# ================================================================== S10
class S10IndependentRecallTest(unittest.TestCase):
    def test_semantic_only_doc_enters_fusion_despite_keyword_hits(self):
        from knowledge.analysis import hybrid_search
        from knowledge.indexing import SearchFilters, build_generation
        from knowledge.providers import MockEmbedder

        kb = _kb()
        try:
            stamp = "2026-10-01T00:00:00Z"
            texts = {
                "K": "毛利率 keyword match document about margins",
                "S": "an entirely different wording that never mentions the"
                     " query terms but is semantically about gross margin"
                     " profitability analysis",
            }
            for doc_id, text in texts.items():
                kb.upsert_documents([{
                    "source": "reports", "doc_id": doc_id, "title": doc_id,
                    "available": True, "first_seen_at": stamp,
                    "last_seen_at": stamp,
                }], stamp)
                kb.upsert_versions([{
                    "source": "reports", "doc_id": doc_id,
                    "version_id": "v1", "sha256": "a" * 64, "bytes": 10,
                    "media_type": "application/pdf", "ext": "pdf",
                    "rel_path": "x", "is_current": True, "state": "ready",
                    "content_changed_at": None,
                }], stamp)
                kb.record_extraction({
                    "extraction_id": "extr-%s" % doc_id, "source": "reports",
                    "doc_id": doc_id, "version_id": "v1",
                    "snapshot_sha256": "a" * 64, "parser_id": "t",
                    "parser_version": "1", "config_digest": "c",
                    "status": "ready", "issues": [], "stats": {},
                }, [{
                    "block_type": "paragraph", "text": text,
                    "locator": {"kind": "pdf", "page": 1},
                    "quality": {"status": "ready", "issues": []},
                }])
            build_generation(kb)

            # deterministic embedder: the QUERY is semantically close to S
            # (same hash bucket boost) and far from K
            class SemanticMock(MockEmbedder):
                def __init__(self):
                    super().__init__(dimensions=32)
                    self.target_terms = None

                def _vector(self, text):
                    import hashlib as h
                    vec = [0.0] * 32
                    for term in set(text.lower().split()):
                        slot = int.from_bytes(
                            h.sha256(term.encode()).digest()[:4], "big") % 32
                        weight = 3.0 if (self.target_terms and
                                         term in self.target_terms) else 1.0
                        vec[slot] += weight
                    norm = sum(v * v for v in vec) ** 0.5 or 1.0
                    return [v / norm for v in vec]

                def embed(self, texts):
                    # boost the semantic doc's distinctive terms so the
                    # query lands near S even when K wins the keyword side
                    if len(texts) == 1:
                        self.target_terms = {
                            "entirely", "semantically", "profitability"}
                    return super().embed(texts)

            embedder = SemanticMock()
            # the query matches K lexically (margin/keyword) and has ZERO
            # lexical overlap with S - S may only arrive via vector recall
            result = hybrid_search(kb, "毛利率 keyword", embedder,
                                   SearchFilters())
            docs = [h["block"]["doc_id"] for h in result["hits"]]
            self.assertIn("S", docs,
                          "semantic-only doc missing from fusion: %r" % docs)
        finally:
            kb.close()

    def test_embedding_cache_isolated_by_provider_and_dimensions(self):
        from knowledge.providers import MockEmbedder
        from knowledge.store import KnowledgeStore

        kb = _kb()
        try:
            from knowledge.analysis import ensure_block_embeddings
            embedder_a = MockEmbedder(dimensions=8)
            embedder_a.model = "shared-name"
            embedder_b = MockEmbedder(dimensions=16)
            embedder_b.model = "shared-name"  # same model name, other dims
            ensure_block_embeddings(kb, embedder_a, ["block-1"])
            vector = kb.get_embedding("shared-name", "block-1")
            self.assertEqual(len(vector), 8)
            # the 16-dim provider must NOT reuse the 8-dim cache entry
            ensure_block_embeddings(kb, embedder_b, ["block-1"])
            vector_b = kb.get_embedding_for("shared-name", 16, "block-1")
            self.assertIsNotNone(vector_b)
            self.assertEqual(len(vector_b), 16)
        finally:
            kb.close()


if __name__ == "__main__":
    unittest.main()
