"""Third-review regressions (T01-T07) - assertion-style, RED first.

T01 uses a REAL old-schema database fixture (the SCHEMA text from git
baseline 0a473d9, before reservation_id existed) with data in it, so the
upgrade path is exercised instead of a fresh-database smoke.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import unittest

from fixtures import temp_dir

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")

# The SCHEMA as of baseline 0a473d9 (pre reservation_id / public time /
# impact outbox columns). Kept verbatim so upgrades are tested against the
# shape real deployments had.
OLD_SCHEMA = """
CREATE TABLE IF NOT EXISTS kb_documents (
    source TEXT NOT NULL, doc_id TEXT NOT NULL, title TEXT, display_title TEXT,
    market TEXT, symbol TEXT, doc_type TEXT, language TEXT, report_period TEXT,
    filing_date TEXT, published_at TEXT, report_date TEXT, status TEXT,
    available INTEGER NOT NULL DEFAULT 0, source_url TEXT, metadata_json TEXT,
    first_seen_at TEXT, last_seen_at TEXT, synced_at TEXT NOT NULL,
    PRIMARY KEY (source, doc_id));
CREATE TABLE IF NOT EXISTS kb_versions (
    source TEXT NOT NULL, doc_id TEXT NOT NULL, version_id TEXT NOT NULL,
    sha256 TEXT, bytes INTEGER, media_type TEXT, ext TEXT, rel_path TEXT,
    is_current INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL,
    content_changed_at TEXT, synced_at TEXT NOT NULL,
    PRIMARY KEY (source, doc_id, version_id));
CREATE TABLE IF NOT EXISTS snapshot_blobs (
    sha256 TEXT PRIMARY KEY, bytes INTEGER NOT NULL, store_path TEXT NOT NULL,
    created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS snapshots (
    source TEXT NOT NULL, doc_id TEXT NOT NULL, version_id TEXT NOT NULL,
    sha256 TEXT NOT NULL, store_path TEXT NOT NULL, bytes INTEGER NOT NULL,
    verified_at TEXT NOT NULL,
    PRIMARY KEY (source, doc_id, version_id));
CREATE TABLE IF NOT EXISTS extractions (
    extraction_id TEXT PRIMARY KEY, source TEXT NOT NULL, doc_id TEXT NOT NULL,
    version_id TEXT NOT NULL, snapshot_sha256 TEXT NOT NULL, parser_id TEXT NOT NULL,
    parser_version TEXT NOT NULL, config_digest TEXT NOT NULL, status TEXT NOT NULL,
    issues_json TEXT NOT NULL DEFAULT '[]', stats_json TEXT, created_at TEXT NOT NULL,
    UNIQUE (source, doc_id, version_id, parser_id, parser_version, config_digest));
CREATE TABLE IF NOT EXISTS blocks (
    block_id TEXT PRIMARY KEY, extraction_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
    block_type TEXT NOT NULL, text TEXT NOT NULL, locator_json TEXT NOT NULL,
    quality_status TEXT NOT NULL, quality_issues_json TEXT NOT NULL DEFAULT '[]',
    UNIQUE (extraction_id, ordinal));
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, doc_id TEXT NOT NULL,
    version_id TEXT NOT NULL, stage TEXT NOT NULL, config_digest TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
    lease_until TEXT, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    UNIQUE (source, doc_id, version_id, stage, config_digest));
CREATE TABLE IF NOT EXISTS usage_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT NOT NULL, model TEXT NOT NULL,
    kind TEXT NOT NULL, input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0, cost_basis TEXT NOT NULL DEFAULT 'unknown',
    run_id TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS index_generations (
    generation_id TEXT PRIMARY KEY, manifest_hash TEXT NOT NULL, status TEXT NOT NULL,
    stats_json TEXT, created_at TEXT NOT NULL, activated_at TEXT);
CREATE TABLE IF NOT EXISTS index_postings (
    generation_id TEXT NOT NULL, term TEXT NOT NULL, block_id TEXT NOT NULL,
    tf INTEGER NOT NULL, PRIMARY KEY (generation_id, term, block_id));
CREATE TABLE IF NOT EXISTS index_doc_terms (
    generation_id TEXT NOT NULL, block_id TEXT NOT NULL, terms INTEGER NOT NULL,
    length INTEGER NOT NULL, PRIMARY KEY (generation_id, block_id));
CREATE TABLE IF NOT EXISTS kb_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL, source TEXT, doc_id TEXT, version_id TEXT,
    occurred_at TEXT NOT NULL, payload_version INTEGER NOT NULL DEFAULT 1,
    payload_json TEXT);
CREATE TABLE IF NOT EXISTS claims (
    claim_id TEXT PRIMARY KEY, current_revision INTEGER NOT NULL, subject TEXT,
    statement TEXT NOT NULL, status TEXT NOT NULL, author TEXT, prompt_version TEXT,
    evidence_json TEXT NOT NULL DEFAULT '[]', counterevidence_json TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS claim_revisions (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, claim_id TEXT NOT NULL,
    revision INTEGER NOT NULL, statement TEXT NOT NULL, status TEXT NOT NULL,
    evidence_json TEXT, counterevidence_json TEXT, reviewer TEXT, reviewed_at TEXT,
    review_note TEXT, supersedes_revision INTEGER, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS decisions (
    decision_id TEXT PRIMARY KEY, recorded_at TEXT NOT NULL, context TEXT,
    rationale TEXT, claim_refs_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS review_proposals (
    proposal_id TEXT PRIMARY KEY, claim_id TEXT NOT NULL, reason TEXT NOT NULL,
    detail_json TEXT, status TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL);
"""


def build_old_database(path: str) -> None:
    """Create a populated database in the PRE-upgrade shape (T01)."""
    conn = sqlite3.connect(path)
    conn.executescript(OLD_SCHEMA)
    stamp = "2026-09-01T00:00:00Z"
    conn.execute("INSERT INTO kb_documents (source, doc_id, title, available,"
                 " first_seen_at, last_seen_at, synced_at)"
                 " VALUES ('reports','R1','legacy doc',1,?,?,?)",
                 (stamp, stamp, stamp))
    conn.execute("INSERT INTO kb_versions (source, doc_id, version_id, sha256,"
                 " bytes, is_current, state, synced_at)"
                 " VALUES ('reports','R1','v1','a',10,1,'ready',?)", (stamp,))
    conn.execute("INSERT INTO extractions (extraction_id, source, doc_id,"
                 " version_id, snapshot_sha256, parser_id, parser_version,"
                 " config_digest, status, created_at)"
                 " VALUES ('extr-old','reports','R1','v1','a','p','1','c',"
                 " 'ready',?)", (stamp,))
    conn.execute("INSERT INTO blocks (block_id, extraction_id, ordinal,"
                 " block_type, \"text\", locator_json, quality_status)"
                 " VALUES ('extr-old-b0000','extr-old',0,'paragraph',"
                 "'legacy text','{}','ready')")
    conn.execute("INSERT INTO usage_events (provider, model, kind,"
                 " input_tokens, output_tokens, cost_basis, created_at)"
                 " VALUES ('old','m','chat',7,0,'legacy',?)", (stamp,))
    conn.execute("INSERT INTO jobs (source, doc_id, version_id, stage,"
                 " config_digest, status, attempts, created_at, updated_at)"
                 " VALUES ('reports','R1','v1','snapshot','d','done',1,?,?)",
                 (stamp, stamp))
    conn.commit()
    conn.close()


def _kb():
    from knowledge.store import KnowledgeStore

    return KnowledgeStore(os.path.join(temp_dir(), "k.sqlite3"))


# ================================================================== T01
class T01OldDatabaseUpgradeTest(unittest.TestCase):
    def test_old_schema_database_opens_and_upgrades(self):
        from knowledge.store import KnowledgeStore

        path = os.path.join(temp_dir(), "old-upgrade.sqlite3")
        build_old_database(path)
        # opening must migrate, not raise "no such column"
        store = KnowledgeStore(path)
        try:
            # migrated columns exist
            cols = {row[1] for row in store._conn.execute(
                "PRAGMA table_info(usage_events)")}
            self.assertIn("reservation_id", cols)
            vcols = {row[1] for row in store._conn.execute(
                "PRAGMA table_info(kb_versions)")}
            self.assertIn("first_observed_at", vcols)
            self.assertIn("public_available_at", vcols)
            # legacy data survived
            usage = store.usage_totals()
            self.assertEqual(usage["input_tokens"], 7)
            blocks = store._conn.execute(
                "SELECT COUNT(*) FROM blocks").fetchone()[0]
            self.assertEqual(blocks, 1)
            jobs = store._conn.execute(
                "SELECT COUNT(*) FROM jobs").fetchone()[0]
            self.assertEqual(jobs, 1)
        finally:
            store.close()
        # reopening (idempotent migration) also works
        store2 = KnowledgeStore(path)
        store2.close()

    def test_upgrade_failure_leaves_database_usable(self):
        from knowledge.store import KnowledgeStore

        path = os.path.join(temp_dir(), "old-fail.sqlite3")
        build_old_database(path)
        # corrupt migration via an incompatible duplicate column simulates a
        # half-migrated db: pre-add ONE of the columns so the ALTER fails,
        # then verify open() still succeeds (ALTER IF-absent check) or fails
        # cleanly without destroying data
        conn = sqlite3.connect(path)
        conn.execute("ALTER TABLE kb_versions ADD COLUMN public_time_basis"
                     " TEXT DEFAULT 'weird'")
        conn.commit()
        conn.close()
        store = KnowledgeStore(path)  # must not raise nor wipe
        try:
            self.assertEqual(store.usage_totals()["input_tokens"], 7)
        finally:
            store.close()


# ================================================================== T02
class T02BudgetStateMachineTest(unittest.TestCase):
    def _ledger(self, cap=10):
        from knowledge.budget import Budget, BudgetLedger

        kb = _kb()
        return kb, BudgetLedger(kb, Budget(max_total_input_tokens=cap))

    def test_unknown_settlement_crash_keeps_consumption(self):
        """fail_unknown interrupted before its usage write: budget must NOT
        restore to full (probe: remaining went back to 10)."""
        kb, ledger = self._ledger(cap=10)
        try:
            rid = ledger.reserve("chat", 8)
            # fault injection INSIDE the real persistence path: make the
            # usage insert fail mid-transaction (sqlite3.Connection.execute
            # is read-only, so wrap at the ledger's own call seam)
            import knowledge.budget as budget_module

            original_int = budget_module.int if hasattr(budget_module, "int")                 else None
            # inject via sqlite3 progress handler: abort on the usage insert
            triggered = {"hit": False}

            def auth_handler(action, arg1, arg2, db, stmt):
                return 0  # allow

            # simplest deterministic seam: monkeypatch the INSERT by making
            # the connection raise through a busy timeout on the target
            # statement via set_trace_callback
            statements = []

            def trace(stmt):
                statements.append(stmt)
                if "INSERT INTO usage_events" in stmt and not triggered["hit"]:
                    triggered["hit"] = True
                    raise sqlite3.OperationalError(
                        "disk i/o error (injected)")

            conn = ledger.kb._conn
            conn.set_trace_callback(trace)
            try:
                ledger.fail_unknown(rid)
            except sqlite3.OperationalError:
                pass
            finally:
                conn.set_trace_callback(None)
            totals = ledger._totals()
            self.assertLess(totals["input"], 10,
                            "interrupted unknown-settle restored the budget"
                            " (totals=%r)" % totals)
        finally:
            kb.close()

    def test_repeated_fail_unknown_charges_once(self):
        kb, ledger = self._ledger()
        try:
            rid = ledger.reserve("chat", 8)
            ledger.fail_unknown(rid)
            ledger.fail_unknown(rid)  # replay
            ledger.fail_unknown(rid)
            usage = kb.usage_totals()
            self.assertEqual(usage["input_tokens"], 8,
                             "double-charged unknown (probe saw 16/2 calls)")
            self.assertEqual(usage["calls"], 1)
        finally:
            kb.close()

    def test_paid_bad_vector_response_not_released(self):
        """Provider returned vectors AND usage; shape invalid: the paid
        tokens must stay consumed (probe: release() restored everything)."""
        from knowledge.analysis import budgeted_embed
        from knowledge.providers import MockEmbedder

        class BadShape(MockEmbedder):
            def embed(self, texts):
                vectors, usage = super().embed(texts)
                return vectors[:max(0, len(vectors) - 1)], usage  # wrong count

        kb = _kb()
        try:
            from knowledge.budget import Budget, BudgetLedger

            ledger = BudgetLedger(kb, Budget(max_total_input_tokens=100))
            embedder = BadShape(dimensions=8)
            try:
                budgeted_embed(embedder, ["a", "b"], ledger=ledger, kb=kb)
                self.fail("expected ValueError")
            except ValueError:
                pass
            totals = ledger._totals()
            self.assertGreater(totals["input"], 0,
                               "already-paid bad response released to zero")
        finally:
            kb.close()

    def test_each_http_attempt_passes_the_request_gate(self):
        """Request cap 1 with an internally-retrying HTTP layer: the retry
        itself must be gated (probe: 2 HTTP attempts, ledger saw 1). The
        provider's retry loop must consult the ledger per ATTEMPT."""
        from knowledge.providers import OpenAICompatibleChat, ProviderCallError

        class RetryChat(OpenAICompatibleChat):
            attempts = 0

            def _transport(self, url, body):
                RetryChat.attempts += 1
                raise OSError("timeout")

        chat = RetryChat("c", "m", "http://x", "k", egress_allowed=True,
                         max_retries=1)
        kb = _kb()
        try:
            from knowledge.budget import Budget, BudgetLedger

            ledger = BudgetLedger(kb, Budget(max_requests_total=1))
            chat.attempt_ledger = ledger
            with self.assertRaises(ProviderCallError):
                chat.complete("x")
            # cap 1 blocks the internal retry: only ONE physical attempt
            self.assertEqual(RetryChat.attempts, 1,
                             "retry bypassed the request gate (%d attempts)"
                             % RetryChat.attempts)
        finally:
            kb.close()


# ================================================================== T03
class T03VersionPublicTimeTest(unittest.TestCase):
    def test_new_version_does_not_inherit_document_public_date(self):
        """v1 published in January; v2 first observed in August with NO
        publication evidence of its own. A July public cutoff must not see
        v2 (probe filled v2.public_available_at = January)."""
        from knowledge.indexing import build_generation, search, SearchFilters

        kb = _kb()
        try:
            stamp = "2026-01-01T00:00:00Z"
            kb.upsert_documents([{
                "source": "reports", "doc_id": "R1", "title": "R1",
                "available": True, "first_seen_at": stamp,
                "last_seen_at": stamp,
                "published_at": "2026-01-01T00:00:00Z",
            }], stamp)
            kb.upsert_versions([{
                "source": "reports", "doc_id": "R1", "version_id": "v1",
                "sha256": "a" * 64, "bytes": 10,
                "media_type": "application/pdf", "ext": "pdf",
                "rel_path": "x", "is_current": True, "state": "ready",
                "content_changed_at": None,
            }], stamp)
            # v2 arrives in August, no publication evidence of its own
            kb.upsert_documents([{
                "source": "reports", "doc_id": "R1", "title": "R1",
                "available": True, "first_seen_at": stamp,
                "last_seen_at": "2026-08-01T00:00:00Z",
                "published_at": "2026-01-01T00:00:00Z",
            }], "2026-08-01T00:00:00Z")
            kb.upsert_versions([
                {"source": "reports", "doc_id": "R1", "version_id": "v1",
                 "sha256": "a" * 64, "bytes": 10,
                 "media_type": "application/pdf", "ext": "pdf",
                 "rel_path": "x", "is_current": False, "state": "ready",
                 "content_changed_at": None},
                {"source": "reports", "doc_id": "R1", "version_id": "v2",
                 "sha256": "b" * 64, "bytes": 10,
                 "media_type": "application/pdf", "ext": "pdf",
                 "rel_path": "y", "is_current": True, "state": "ready",
                 "content_changed_at": None,
                 "first_observed_at": "2026-08-01T00:00:00Z"},
            ], "2026-08-01T00:00:00Z")
            v2 = kb.get_version("reports", "R1", "v2")
            self.assertIsNone(v2["public_available_at"],
                              "v2 inherited the document's January date")
            self.assertEqual(v2["public_time_basis"], "unknown")

            for vid, text in (("v1", "old margin text"),
                              ("v2", "new margin text")):
                kb.record_extraction({
                    "extraction_id": "extr-%s" % vid, "source": "reports",
                    "doc_id": "R1", "version_id": vid,
                    "snapshot_sha256": ("a" if vid == "v1" else "b") * 64,
                    "parser_id": "t", "parser_version": "1",
                    "config_digest": "c", "status": "ready", "issues": [],
                    "stats": {}}, [{
                        "block_type": "paragraph", "text": text,
                        "locator": {"kind": "pdf", "page": 1},
                        "quality": {"status": "ready", "issues": []}}])
            build_generation(kb)
            july = search(kb, "margin", SearchFilters(
                as_of="2026-07-01T00:00:00Z", as_of_mode="public"))
            texts = [h.block["text"] for h in july["hits"]]
            self.assertFalse(any("new margin" in t for t in texts),
                             "future revision leaked into July public query")
        finally:
            kb.close()


# ================================================================== T04
class T04MetadataEpochTest(unittest.TestCase):
    def _seed(self, kb):
        from knowledge.indexing import build_generation

        stamp = "2026-10-01T00:00:00Z"
        for doc_id in ("A", "B"):
            kb.upsert_documents([{
                "source": "reports", "doc_id": doc_id, "title": doc_id,
                "symbol": "AAA", "available": True,
                "first_seen_at": stamp, "last_seen_at": stamp,
            }], stamp)
            kb.upsert_versions([{
                "source": "reports", "doc_id": doc_id, "version_id": "v1",
                "sha256": "a" * 64, "bytes": 10,
                "media_type": "application/pdf", "ext": "pdf",
                "rel_path": "x", "is_current": True, "state": "ready",
                "content_changed_at": None,
            }], stamp)
            kb.record_extraction({
                "extraction_id": "extr-%s" % doc_id, "source": "reports",
                "doc_id": doc_id, "version_id": "v1",
                "snapshot_sha256": "a" * 64, "parser_id": "t",
                "parser_version": "1", "config_digest": "c",
                "status": "ready", "issues": [], "stats": {}},
                [{"block_type": "paragraph",
                  "text": "common %s" % doc_id,
                  "locator": {"kind": "pdf", "page": 1},
                  "quality": {"status": "ready", "issues": []}}])
        build_generation(kb)

    def test_same_length_symbol_change_invalidates_cursor(self):
        from knowledge.kbapi import KbApi, KbApiError

        kb = _kb()
        try:
            self._seed(kb)
            api = KbApi(kb, {"t": ["research.read"]})
            first = api.do_search({"query": "common", "limit": 1})
            self.assertEqual(len(first["hits"]), 1)
            # SAME-LENGTH symbol revision (probe: epoch identical -> page 2
            # silently empty while visible results remained)
            kb.upsert_documents([dict(source="reports", doc_id="A",
                                      title="A", symbol="BBB", available=True,
                                      first_seen_at="2026-10-01T00:00:00Z",
                                      last_seen_at="2026-10-02T00:00:00Z")],
                                "2026-10-02T00:00:00Z")
            with self.assertRaises(KbApiError) as ctx:
                api.do_search({"query": "common", "limit": 1,
                               "cursor": first["next_cursor"]})
            self.assertEqual(ctx.exception.status, 409)
        finally:
            kb.close()

    def test_available_offsetting_changes_invalidate_cursor(self):
        """One withdrawal + one newly-available doc: COUNT-based epochs stay
        identical, so value hashing (not counts) must drive invalidation."""
        from knowledge.kbapi import KbApi, KbApiError

        kb = _kb()
        try:
            self._seed(kb)
            api = KbApi(kb, {"t": ["research.read"]})
            first = api.do_search({"query": "common", "limit": 1})
            epoch_before = api.metadata_epoch()
            kb.upsert_documents([
                dict(source="reports", doc_id="A", title="A", symbol="AAA",
                     available=False, first_seen_at="2026-10-01T00:00:00Z",
                     last_seen_at="2026-10-02T00:00:00Z"),
                dict(source="reports", doc_id="B", title="B", symbol="AAA",
                     available=True, first_seen_at="2026-10-01T00:00:00Z",
                     last_seen_at="2026-10-02T00:00:00Z")],
                "2026-10-02T00:00:00Z")
            epoch_after = api.metadata_epoch()
            self.assertNotEqual(epoch_before, epoch_after,
                                "offsetting revision left the epoch identical")
            with self.assertRaises(KbApiError):
                api.do_search({"query": "common", "limit": 1,
                               "cursor": first["next_cursor"]})
        finally:
            kb.close()


# ================================================================== T05
class T05MixedPdfAndRecipeTest(unittest.TestCase):
    @staticmethod
    def _make_pdf(objects):
        out = bytearray(b"%PDF-1.4\n")
        offsets = {}
        for num in sorted(objects):
            offsets[num] = len(out)
            out += b"%d 0 obj\n" % num + objects[num] + b"\nendobj\n"
        xref = len(out)
        mx = max(objects)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (mx + 1)
        for n in range(1, mx + 1):
            out += (b"%010d 00000 n \n" % offsets[n]) if n in offsets \
                else b"0000000000 65535 f \n"
        out += (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF"
                % (mx + 1, xref))
        return bytes(out)

    @classmethod
    def _page(cls, parent, contents):
        return (b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 612 792]"
                b" /Contents %d 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
                % (parent, contents))

    @classmethod
    def _stream(cls, content):
        return b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream"

    def _mixed_pdf(self):
        texts = [b"BT /F1 12 Tf 72 720 Td (dense body page two) Tj ET",
                 b"BT /F1 12 Tf 72 720 Td (dense body page three) Tj ET"]
        objects = {
            1: b"<< /Type /Catalog /Pages 2 0 R >>",
            2: b"<< /Type /Pages /Kids [3 0 R 6 0 R 7 0 R] /Count 3 >>",
            3: b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>",  # no content
            5: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            4: self._stream(b"BT /F1 12 Tf 72 720 Td () Tj ET"),  # empty-ish layer
            6: self._page(2, 8),
            8: self._stream(texts[0]),
            7: self._page(2, 9),
            9: self._stream(texts[1]),
        }
        return self._make_pdf(objects)

    def test_mixed_pdf_empty_ocr_page_blocks_ready(self):
        from knowledge.extract import extract_pdf
        from knowledge.ocr import OcrConfig

        class EmptyOcr:
            name = "empty"

            def run(self, image_bytes):
                return ("", 0.0)

        class FailingFallback:
            name = "fb"

            def run(self, image_bytes):
                raise RuntimeError("fallback exploded")

        result = extract_pdf(self._mixed_pdf(), ocr=EmptyOcr(),
                             ocr_config=OcrConfig(min_confidence=0.6),
                             renderer=lambda r, p, dpi=200: b"PNG",
                             fallback_ocr=FailingFallback())
        self.assertNotEqual(result.status, "ready",
                            "empty-OCR page with failed fallback must not"
                            " leave the document ready")
        statuses = result.stats.get("page_ocr_status") or []
        self.assertIn("needs_ocr_unmet", statuses + result.stats.get(
            "page_ocr_status", []) if isinstance(statuses, list) else [])

    def test_quality_logic_change_alters_processing_identity(self):
        """The S05 quality-behavior change must produce a NEW digest (probe:
        digests identical across the change)."""
        from knowledge.extract import effective_extract_config
        from knowledge.ocr import OcrConfig
        from knowledge.quality import QUALITY_CONFIG

        old_config = dict(QUALITY_CONFIG)
        try:
            # the quality gate added by S05 (page confidence) changed
            # behavior; the recipe must version it explicitly
            digest_now = effective_extract_config(OcrConfig(engine="local"))
            QUALITY_CONFIG["page_gate"] = "confidence-v2"
            digest_changed = effective_extract_config(OcrConfig(engine="local"))
            self.assertNotEqual(digest_now, digest_changed,
                                "recipe digest ignores quality-logic changes")
        finally:
            QUALITY_CONFIG.clear()
            QUALITY_CONFIG.update(old_config)


# ================================================================== T06
class T06FullRecallAndCacheTest(unittest.TestCase):
    def _seed_many(self, kb, n_docs=205):
        from knowledge.indexing import build_generation

        stamp = "2026-10-01T00:00:00Z"
        for i in range(n_docs):
            doc_id = "D%03d" % i
            kb.upsert_documents([{
                "source": "reports", "doc_id": doc_id, "title": doc_id,
                "available": True, "first_seen_at": stamp,
                "last_seen_at": stamp,
            }], stamp)
            kb.upsert_versions([{
                "source": "reports", "doc_id": doc_id, "version_id": "v1",
                "sha256": "a" * 64, "bytes": 10,
                "media_type": "application/pdf", "ext": "pdf",
                "rel_path": "x", "is_current": True, "state": "ready",
                "content_changed_at": None,
            }], stamp)
            text = ("filler unrelated content %d" % i if i < n_docs - 1
                    else "entirely different wording semantically about"
                         " gross margin profitability")
            kb.record_extraction({
                "extraction_id": "extr-%s" % doc_id, "source": "reports",
                "doc_id": doc_id, "version_id": "v1",
                "snapshot_sha256": "a" * 64, "parser_id": "t",
                "parser_version": "1", "config_digest": "c",
                "status": "ready", "issues": [], "stats": {}},
                [{"block_type": "paragraph", "text": text,
                  "locator": {"kind": "pdf", "page": 1},
                  "quality": {"status": "ready", "issues": []}}])
        build_generation(kb)

    def test_semantic_target_beyond_first_200_is_recalled(self):
        from knowledge.analysis import hybrid_search
        from knowledge.indexing import SearchFilters
        from knowledge.providers import MockEmbedder

        kb = _kb()
        try:
            self._seed_many(kb, 205)  # target is doc #205 (last in order)
            embedder = MockEmbedder(dimensions=32)

            class QueryBoost(MockEmbedder):
                def embed(self, texts):
                    if len(texts) == 1:
                        self._boost = {"entirely", "semantically",
                                       "profitability", "gross"}
                    return super().embed(texts)

            embedder = QueryBoost(dimensions=32)
            result = hybrid_search(kb, "gross margin profitability", embedder,
                                   SearchFilters(), embed_top=200)
            docs = [h["block"]["doc_id"] for h in result["hits"]]
            self.assertIn("D204", docs,
                          "semantic target at position 205 never recalled: %r"
                          % docs[:10])
        finally:
            kb.close()

    def test_same_name_same_dims_cross_provider_no_cache_reuse(self):
        from knowledge.analysis import ensure_block_embeddings
        from knowledge.providers import MockEmbedder

        kb = _kb()
        try:
            stamp = "2026-10-01T00:00:00Z"
            kb.upsert_documents([{
                "source": "reports", "doc_id": "D", "title": "D",
                "available": True, "first_seen_at": stamp,
                "last_seen_at": stamp,
            }], stamp)
            kb.upsert_versions([{
                "source": "reports", "doc_id": "D", "version_id": "v1",
                "sha256": "a" * 64, "bytes": 10,
                "media_type": "application/pdf", "ext": "pdf",
                "rel_path": "x", "is_current": True, "state": "ready",
                "content_changed_at": None,
            }], stamp)
            kb.record_extraction({
                "extraction_id": "extr-d", "source": "reports",
                "doc_id": "D", "version_id": "v1",
                "snapshot_sha256": "a" * 64, "parser_id": "t",
                "parser_version": "1", "config_digest": "c",
                "status": "ready", "issues": [], "stats": {}},
                [{"block_type": "paragraph", "text": "cache test",
                  "locator": {"kind": "pdf", "page": 1},
                  "quality": {"status": "ready", "issues": []}}])
            provider_a = MockEmbedder(dimensions=8)
            provider_a.model = "same-model"
            provider_a.name = "provider-a"
            provider_b = MockEmbedder(dimensions=8)   # SAME dims
            provider_b.model = "same-model"
            provider_b.name = "provider-b"
            calls = {"b": 0}
            original_b = provider_b.embed

            def counting_b(texts):
                calls["b"] += 1
                return original_b(texts)

            provider_b.embed = counting_b
            ensure_block_embeddings(kb, provider_a, ["extr-d-b0000"])
            ensure_block_embeddings(kb, provider_b, ["extr-d-b0000"])
            self.assertGreaterEqual(calls["b"], 1,
                                    "provider B reused A's vectors without"
                                    " calling its own embedding")
        finally:
            kb.close()


# ================================================================== T07
class T07IdempotentCandidatesTest(unittest.TestCase):
    def test_same_revision_repeated_export_publishes_once(self):
        from knowledge.writeback import register_write_root, write_candidate

        directory = os.path.join(temp_dir(), "vault")
        os.makedirs(directory, exist_ok=True)
        register_write_root(directory)
        write_candidate(directory, "doc.md", "machine-v1")
        # export identical v2 three times: the FIRST lands in exactly one
        # append-only candidate; repeats recognize the identity and add
        # nothing (probe: 3 duplicate files)
        results = [write_candidate(directory, "doc.md", "machine-v2")
                   for _ in range(3)]
        first = results[0]
        self.assertEqual(first["outcome"], "preserved_with_candidate")
        for repeat in results[1:]:
            self.assertEqual(repeat["outcome"], "unchanged",
                             "duplicate delivery of identical content")
            self.assertEqual(repeat.get("candidate_path"),
                             first["candidate_path"])
        # a repeated export after "restart" (same identity) adds nothing
        again = write_candidate(directory, "doc.md", "machine-v2")
        self.assertEqual(again["outcome"], "unchanged")
        files = [f for f in os.listdir(directory)
                 if f.startswith("doc.candidate-")]
        self.assertEqual(len(files), 1,
                         "identical v2 published %d times (probe: 3)"
                         % len(files))
        with open(first["candidate_path"], encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "machine-v2")


if __name__ == "__main__":
    unittest.main()
