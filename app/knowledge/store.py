"""Knowledge layer SQLite store: mirrored identities, snapshots, stage jobs.

The knowledge database is fully separate from the first-layer catalog
(ADR0003). Document/version identities are mirrored here by the sync service;
snapshots and job state live only here. Job idempotency is enforced by a
UNIQUE constraint on (source, doc_id, version_id, stage, config_digest).
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS kb_documents (
    source TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    title TEXT,
    display_title TEXT,
    market TEXT,
    symbol TEXT,
    doc_type TEXT,
    language TEXT,
    report_period TEXT,
    filing_date TEXT,
    published_at TEXT,
    report_date TEXT,
    available INTEGER NOT NULL DEFAULT 0,
    first_seen_at TEXT,
    last_seen_at TEXT,
    synced_at TEXT NOT NULL,
    PRIMARY KEY (source, doc_id)
);
CREATE TABLE IF NOT EXISTS kb_versions (
    source TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    sha256 TEXT,
    bytes INTEGER,
    media_type TEXT,
    ext TEXT,
    rel_path TEXT,
    is_current INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL,
    content_changed_at TEXT,
    synced_at TEXT NOT NULL,
    PRIMARY KEY (source, doc_id, version_id)
);
CREATE INDEX IF NOT EXISTS idx_kb_versions_state ON kb_versions(state);
CREATE TABLE IF NOT EXISTS snapshot_blobs (
    sha256 TEXT PRIMARY KEY,
    bytes INTEGER NOT NULL,
    store_path TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS snapshots (
    source TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    store_path TEXT NOT NULL,
    bytes INTEGER NOT NULL,
    verified_at TEXT NOT NULL,
    PRIMARY KEY (source, doc_id, version_id)
);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    config_digest TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    lease_until TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (source, doc_id, version_id, stage, config_digest),
    FOREIGN KEY (source, doc_id, version_id)
        REFERENCES kb_versions(source, doc_id, version_id)
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, stage);
CREATE TABLE IF NOT EXISTS sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    ok INTEGER,
    documents INTEGER NOT NULL DEFAULT 0,
    versions INTEGER NOT NULL DEFAULT 0,
    new_documents INTEGER NOT NULL DEFAULT 0,
    new_versions INTEGER NOT NULL DEFAULT 0,
    jobs_registered INTEGER NOT NULL DEFAULT 0,
    error TEXT
);
CREATE TABLE IF NOT EXISTS extractions (
    extraction_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    snapshot_sha256 TEXT NOT NULL,
    parser_id TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    config_digest TEXT NOT NULL,
    status TEXT NOT NULL,
    issues_json TEXT NOT NULL DEFAULT '[]',
    stats_json TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (source, doc_id, version_id, parser_id, parser_version, config_digest),
    FOREIGN KEY (source, doc_id, version_id)
        REFERENCES kb_versions(source, doc_id, version_id)
);
CREATE INDEX IF NOT EXISTS idx_extractions_version
    ON extractions(source, doc_id, version_id);
CREATE TABLE IF NOT EXISTS blocks (
    block_id TEXT PRIMARY KEY,
    extraction_id TEXT NOT NULL REFERENCES extractions(extraction_id),
    ordinal INTEGER NOT NULL,
    block_type TEXT NOT NULL,
    text TEXT NOT NULL,
    locator_json TEXT NOT NULL,
    quality_status TEXT NOT NULL,
    quality_issues_json TEXT NOT NULL DEFAULT '[]',
    UNIQUE (extraction_id, ordinal)
);
CREATE INDEX IF NOT EXISTS idx_blocks_extraction ON blocks(extraction_id);
"""

JOB_PENDING = "pending"
JOB_RUNNING = "running"
JOB_DONE = "done"
JOB_FAILED = "failed"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_utc(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def config_digest(config: Dict[str, Any]) -> str:
    """Deterministic digest of a stage configuration (sorted keys)."""
    canonical = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def idempotency_key(source: str, doc_id: str, version_id: str, stage: str,
                    digest: str) -> str:
    parts = "\x00".join((source, doc_id, version_id, stage, digest))
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()


class KnowledgeStore:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.RLock()
        directory = os.path.dirname(os.path.abspath(path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=15000")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def _tx(self):
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    # ------------------------------------------------------------- mirrors
    def upsert_documents(self, rows: List[Dict[str, Any]], synced_at: str) -> Dict[str, int]:
        """Idempotent mirror of catalog documents; returns first-seen counts."""
        new_documents = 0
        with self._tx() as conn:
            for row in rows:
                exists = conn.execute(
                    "SELECT 1 FROM kb_documents WHERE source=? AND doc_id=?",
                    (row["source"], row["doc_id"]),
                ).fetchone()
                if not exists:
                    new_documents += 1
                conn.execute(
                    "INSERT INTO kb_documents ("
                    " source, doc_id, title, display_title, market, symbol, doc_type, language,"
                    " report_period, filing_date, published_at, report_date, available,"
                    " first_seen_at, last_seen_at, synced_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
                    " ON CONFLICT(source, doc_id) DO UPDATE SET"
                    "  title=excluded.title, display_title=excluded.display_title,"
                    "  market=excluded.market, symbol=excluded.symbol, doc_type=excluded.doc_type,"
                    "  language=excluded.language, report_period=excluded.report_period,"
                    "  filing_date=excluded.filing_date, published_at=excluded.published_at,"
                    "  report_date=excluded.report_date, available=excluded.available,"
                    "  last_seen_at=excluded.last_seen_at, synced_at=excluded.synced_at",
                    (
                        row["source"], row["doc_id"], row.get("title"), row.get("display_title"),
                        row.get("market"), row.get("symbol"), row.get("doc_type"),
                        row.get("language"), row.get("report_period"), row.get("filing_date"),
                        row.get("published_at"), row.get("report_date"),
                        1 if row.get("available") else 0,
                        row.get("first_seen_at"), row.get("last_seen_at"), synced_at,
                    ),
                )
        return {"documents": len(rows), "new_documents": new_documents}

    def upsert_versions(self, rows: List[Dict[str, Any]], synced_at: str) -> Dict[str, int]:
        """Idempotent mirror of catalog versions; identity columns never change."""
        new_versions = 0
        with self._tx() as conn:
            for row in rows:
                exists = conn.execute(
                    "SELECT 1 FROM kb_versions WHERE source=? AND doc_id=? AND version_id=?",
                    (row["source"], row["doc_id"], row["version_id"]),
                ).fetchone()
                if not exists:
                    new_versions += 1
                conn.execute(
                    "INSERT INTO kb_versions ("
                    " source, doc_id, version_id, sha256, bytes, media_type, ext, rel_path,"
                    " is_current, state, content_changed_at, synced_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
                    " ON CONFLICT(source, doc_id, version_id) DO UPDATE SET"
                    "  is_current=excluded.is_current, state=excluded.state,"
                    "  rel_path=excluded.rel_path, synced_at=excluded.synced_at",
                    (
                        row["source"], row["doc_id"], row["version_id"],
                        row.get("sha256"), row.get("bytes"), row.get("media_type"),
                        row.get("ext"), row.get("rel_path"),
                        1 if row.get("is_current") else 0, row.get("state") or "ready",
                        row.get("content_changed_at"), synced_at,
                    ),
                )
        return {"versions": len(rows), "new_versions": new_versions}

    # ------------------------------------------------------------ snapshots
    def record_blob(self, sha256: str, size: int, store_path: str, created_at: str) -> None:
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO snapshot_blobs (sha256, bytes, store_path, created_at)"
                " VALUES (?,?,?,?)"
                " ON CONFLICT(sha256) DO NOTHING",
                (sha256, size, store_path, created_at),
            )

    def get_blob(self, sha256: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM snapshot_blobs WHERE sha256=?", (sha256,)).fetchone()
        return dict(row) if row else None

    def record_snapshot(self, source: str, doc_id: str, version_id: str, sha256: str,
                        size: int, store_path: str, verified_at: str) -> None:
        """Bind a version to a snapshot blob; identity must never be rewritten."""
        with self._tx() as conn:
            existing = conn.execute(
                "SELECT sha256 FROM snapshots WHERE source=? AND doc_id=? AND version_id=?",
                (source, doc_id, version_id),
            ).fetchone()
            if existing and existing["sha256"] != sha256:
                raise IntegrityError(
                    "snapshot identity rewrite refused for %s/%s@%s" % (source, doc_id, version_id))
            conn.execute(
                "INSERT INTO snapshots (source, doc_id, version_id, sha256, store_path,"
                " bytes, verified_at) VALUES (?,?,?,?,?,?,?)"
                " ON CONFLICT(source, doc_id, version_id) DO NOTHING",
                (source, doc_id, version_id, sha256, store_path, size, verified_at),
            )

    def get_snapshot(self, source: str, doc_id: str, version_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM snapshots WHERE source=? AND doc_id=? AND version_id=?",
                (source, doc_id, version_id)).fetchone()
        return dict(row) if row else None

    # ----------------------------------------------------------------- jobs
    def register_job(self, source: str, doc_id: str, version_id: str, stage: str,
                     digest: str) -> bool:
        """Register an idempotent stage job; True when newly inserted."""
        now = utc_now()
        with self._tx() as conn:
            cur = conn.execute(
                "INSERT INTO jobs (source, doc_id, version_id, stage, config_digest,"
                " status, attempts, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,0,?,?)"
                " ON CONFLICT(source, doc_id, version_id, stage, config_digest) DO NOTHING",
                (source, doc_id, version_id, stage, digest, JOB_PENDING, now, now),
            )
            return cur.rowcount == 1

    def claim_next_job(self, stage: str, lease_seconds: int,
                       now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
        """Claim the next runnable job: pending, or running with an expired lease."""
        moment = now or datetime.now(timezone.utc)
        lease_until = (moment + timedelta(seconds=max(1, lease_seconds))).replace(
            microsecond=0).isoformat().replace("+00:00", "Z")
        stamp = moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        with self._tx() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE stage=? AND (status=? OR (status=? AND lease_until < ?))"
                " ORDER BY id LIMIT 1",
                (stage, JOB_PENDING, JOB_RUNNING, stamp),
            ).fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE jobs SET status=?, attempts=attempts+1, lease_until=?, updated_at=?"
                " WHERE id=?",
                (JOB_RUNNING, lease_until, stamp, row["id"]),
            )
            job = dict(row)
            job["status"] = JOB_RUNNING
            job["attempts"] = row["attempts"] + 1
            job["lease_until"] = lease_until
            return job

    def finish_job(self, job_id: int, ok: bool, error: Optional[str] = None,
                   max_attempts: int = 5) -> None:
        now = utc_now()
        status = JOB_DONE if ok else JOB_FAILED
        with self._tx() as conn:
            row = conn.execute("SELECT attempts FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                return
            if not ok and row["attempts"] < max_attempts:
                # transient failure: back to pending for retry (bounded by attempts)
                status = JOB_PENDING
            conn.execute(
                "UPDATE jobs SET status=?, lease_until=NULL, error=?, updated_at=? WHERE id=?",
                (status, error[:2000] if error else None, now, job_id),
            )

    def recover_stale_jobs(self, stage: Optional[str] = None,
                           now: Optional[datetime] = None) -> int:
        """Reset running jobs whose lease expired back to pending (crash recovery)."""
        stamp = (now or datetime.now(timezone.utc)).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z")
        with self._tx() as conn:
            if stage:
                cur = conn.execute(
                    "UPDATE jobs SET status=?, lease_until=NULL, updated_at=?"
                    " WHERE status=? AND lease_until IS NOT NULL AND lease_until < ? AND stage=?",
                    (JOB_PENDING, stamp, JOB_RUNNING, stamp, stage),
                )
            else:
                cur = conn.execute(
                    "UPDATE jobs SET status=?, lease_until=NULL, updated_at=?"
                    " WHERE status=? AND lease_until IS NOT NULL AND lease_until < ?",
                    (JOB_PENDING, stamp, JOB_RUNNING, stamp),
                )
            return cur.rowcount

    def job_counts(self, stage: Optional[str] = None) -> Dict[str, int]:
        where = " WHERE stage=?" if stage else ""
        params = (stage,) if stage else ()
        with self._lock:
            rows = self._conn.execute(
                "SELECT status, COUNT(*) c FROM jobs%s GROUP BY status" % where, params).fetchall()
        counts = {JOB_PENDING: 0, JOB_RUNNING: 0, JOB_DONE: 0, JOB_FAILED: 0}
        for row in rows:
            counts[row["status"]] = row["c"]
        return counts

    def get_version(self, source: str, doc_id: str, version_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM kb_versions WHERE source=? AND doc_id=? AND version_id=?",
                (source, doc_id, version_id)).fetchone()
        return dict(row) if row else None

    def versions_needing_stage(self, stage: str, digest: str,
                               state: str = "ready") -> List[Dict[str, Any]]:
        """Ready versions that do not yet have a job row for this stage+digest."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT v.* FROM kb_versions v WHERE v.state=? AND NOT EXISTS ("
                "  SELECT 1 FROM jobs j WHERE j.source=v.source AND j.doc_id=v.doc_id"
                "  AND j.version_id=v.version_id AND j.stage=? AND j.config_digest=?)"
                " ORDER BY v.source, v.doc_id, v.version_id",
                (state, stage, digest),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------ sync runs
    def has_extraction(self, extraction_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM extractions WHERE extraction_id=?",
                (extraction_id,)).fetchone()
        return row is not None

    def record_extraction(self, extraction: Dict[str, Any],
                          blocks: List[Dict[str, Any]]) -> bool:
        """Insert an extraction with its blocks atomically; no-op when present.

        Returns True when newly recorded. An existing extraction_id is never
        rewritten: re-extraction with different input must produce a different
        extraction_id by construction.
        """
        now = utc_now()
        with self._tx() as conn:
            existing = conn.execute(
                "SELECT 1 FROM extractions WHERE extraction_id=?",
                (extraction["extraction_id"],)).fetchone()
            if existing:
                return False
            conn.execute(
                "INSERT INTO extractions (extraction_id, source, doc_id, version_id,"
                " snapshot_sha256, parser_id, parser_version, config_digest,"
                " status, issues_json, stats_json, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    extraction["extraction_id"], extraction["source"],
                    extraction["doc_id"], extraction["version_id"],
                    extraction["snapshot_sha256"], extraction["parser_id"],
                    extraction["parser_version"], extraction["config_digest"],
                    extraction["status"],
                    json.dumps(extraction.get("issues") or [], ensure_ascii=False),
                    json.dumps(extraction.get("stats") or {}, ensure_ascii=False),
                    now,
                ),
            )
            for ordinal, block in enumerate(blocks):
                conn.execute(
                    "INSERT INTO blocks (block_id, extraction_id, ordinal, block_type,"
                    " text, locator_json, quality_status, quality_issues_json)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (
                        "%s-b%04d" % (extraction["extraction_id"], ordinal),
                        extraction["extraction_id"], ordinal,
                        block["block_type"], block["text"],
                        json.dumps(block["locator"], ensure_ascii=False),
                        block["quality"]["status"],
                        json.dumps(block["quality"].get("issues") or [],
                                   ensure_ascii=False),
                    ),
                )
        return True

    def get_extraction(self, extraction_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM extractions WHERE extraction_id=?",
                (extraction_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["issues"] = json.loads(result.pop("issues_json") or "[]")
        result["stats"] = json.loads(result.pop("stats_json") or "{}")
        return result

    def latest_extraction(self, source: str, doc_id: str,
                          version_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM extractions WHERE source=? AND doc_id=? AND version_id=?"
                " ORDER BY created_at DESC, extraction_id LIMIT 1",
                (source, doc_id, version_id)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["issues"] = json.loads(result.pop("issues_json") or "[]")
        result["stats"] = json.loads(result.pop("stats_json") or "{}")
        return result

    def get_blocks(self, extraction_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM blocks WHERE extraction_id=? ORDER BY ordinal",
                (extraction_id,)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["locator"] = json.loads(item.pop("locator_json") or "{}")
            item["quality"] = {
                "status": item.pop("quality_status"),
                "issues": json.loads(item.pop("quality_issues_json") or "[]"),
            }
            result.append(item)
        return result

    def get_block_with_identity(self, block_id: str) -> Optional[Dict[str, Any]]:
        """Block joined with its extraction identity, ready for evidence export."""
        with self._lock:
            row = self._conn.execute(
                "SELECT b.block_id, b.ordinal, b.block_type, b.text, b.locator_json,"
                " b.quality_status, b.quality_issues_json,"
                " e.extraction_id, e.source, e.doc_id, e.version_id, e.snapshot_sha256"
                " FROM blocks b JOIN extractions e ON e.extraction_id = b.extraction_id"
                " WHERE b.block_id=?", (block_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["locator"] = json.loads(item.pop("locator_json") or "{}")
        item["quality"] = {
            "status": item.pop("quality_status"),
            "issues": json.loads(item.pop("quality_issues_json") or "[]"),
        }
        return item

    def snapshots_missing_extract_jobs(self, stage_digest: str) -> List[Dict[str, Any]]:
        """Snapshot bindings that have no extract job for this stage digest."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT s.source, s.doc_id, s.version_id, s.sha256 FROM snapshots s"
                " WHERE NOT EXISTS (SELECT 1 FROM jobs j WHERE j.source=s.source"
                " AND j.doc_id=s.doc_id AND j.version_id=s.version_id"
                " AND j.stage='extract' AND j.config_digest=?)", (stage_digest,)
            ).fetchall()
        return [dict(r) for r in rows]

    def start_sync_run(self) -> int:
        with self._tx() as conn:
            cur = conn.execute(
                "INSERT INTO sync_runs (started_at, ok) VALUES (?, 0)", (utc_now(),))
            return cur.lastrowid

    def finish_sync_run(self, run_id: int, ok: bool, stats: Dict[str, Any],
                        error: Optional[str] = None) -> None:
        with self._tx() as conn:
            conn.execute(
                "UPDATE sync_runs SET finished_at=?, ok=?, documents=?, versions=?,"
                " new_documents=?, new_versions=?, jobs_registered=?, error=? WHERE id=?",
                (utc_now(), 1 if ok else 0, stats.get("documents", 0), stats.get("versions", 0),
                 stats.get("new_documents", 0), stats.get("new_versions", 0),
                 stats.get("jobs_registered", 0), error[:2000] if error else None, run_id),
            )

    def counts(self) -> Dict[str, Any]:
        with self._lock:
            def one(sql: str, params: tuple = ()) -> int:
                return self._conn.execute(sql, params).fetchone()[0]

            return {
                "documents": one("SELECT COUNT(*) FROM kb_documents"),
                "versions": one("SELECT COUNT(*) FROM kb_versions"),
                "snapshots": one("SELECT COUNT(*) FROM snapshots"),
                "blobs": one("SELECT COUNT(*) FROM snapshot_blobs"),
                "jobs": one("SELECT COUNT(*) FROM jobs"),
            }


class IntegrityError(Exception):
    """Raised when stored snapshot identity/blob state is inconsistent."""
