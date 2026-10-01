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
from typing import Any, Dict, List, Optional, Tuple

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
CREATE TABLE IF NOT EXISTS index_generations (
    generation_id TEXT PRIMARY KEY,
    manifest_hash TEXT NOT NULL,
    status TEXT NOT NULL,             -- building | active | retired
    stats_json TEXT,
    created_at TEXT NOT NULL,
    activated_at TEXT
);
CREATE TABLE IF NOT EXISTS index_postings (
    generation_id TEXT NOT NULL REFERENCES index_generations(generation_id),
    term TEXT NOT NULL,
    block_id TEXT NOT NULL,
    tf INTEGER NOT NULL,
    PRIMARY KEY (generation_id, term, block_id)
);
CREATE INDEX IF NOT EXISTS idx_postings_term
    ON index_postings(generation_id, term);
CREATE TABLE IF NOT EXISTS index_doc_terms (
    generation_id TEXT NOT NULL REFERENCES index_generations(generation_id),
    block_id TEXT NOT NULL,
    terms INTEGER NOT NULL,
    length INTEGER NOT NULL,
    PRIMARY KEY (generation_id, block_id)
);
CREATE TABLE IF NOT EXISTS kb_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    source TEXT,
    doc_id TEXT,
    version_id TEXT,
    occurred_at TEXT NOT NULL,
    payload_version INTEGER NOT NULL DEFAULT 1,
    payload_json TEXT
);
CREATE TABLE IF NOT EXISTS block_embeddings (
    model TEXT NOT NULL,
    block_id TEXT NOT NULL,
    dim INTEGER NOT NULL,
    vector_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (model, block_id)
);
CREATE TABLE IF NOT EXISTS analysis_runs (
    run_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,             -- pending | running | done | failed
    query TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'keyword',
    prompt_version TEXT,
    draft TEXT,
    citations_json TEXT,
    verification_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS usage_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    kind TEXT NOT NULL,               -- embedding | chat
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_basis TEXT NOT NULL DEFAULT 'unknown',
    run_id TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_created ON usage_events(created_at);
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

    def upsert_versions(self, rows: List[Dict[str, Any]], synced_at: str) -> Dict[str, Any]:
        """Idempotent mirror of catalog versions; identity columns never change."""
        new_versions = 0
        new_rows: List[Dict[str, Any]] = []
        with self._tx() as conn:
            for row in rows:
                exists = conn.execute(
                    "SELECT 1 FROM kb_versions WHERE source=? AND doc_id=? AND version_id=?",
                    (row["source"], row["doc_id"], row["version_id"]),
                ).fetchone()
                if not exists:
                    new_versions += 1
                    new_rows.append(row)
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
        return {"versions": len(rows), "new_versions": new_versions,
                "new_version_rows": new_rows}

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
    # ------------------------------------------------------- index generations
    def create_generation(self, generation_id: str, manifest_hash: str) -> None:
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO index_generations (generation_id, manifest_hash, status,"
                " stats_json, created_at) VALUES (?,?,?,?,?)",
                (generation_id, manifest_hash, "building", None, utc_now()),
            )

    def active_generation(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM index_generations WHERE status='active'"
                " ORDER BY activated_at DESC LIMIT 1").fetchone()
        if not row:
            return None
        result = dict(row)
        result["stats"] = json.loads(result.pop("stats_json") or "{}")
        return result

    def get_generation(self, generation_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM index_generations WHERE generation_id=?",
                (generation_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["stats"] = json.loads(result.pop("stats_json") or "{}")
        return result

    def activate_generation(self, generation_id: str, stats: Dict[str, Any]) -> None:
        """Atomically publish one generation and retire any previous active."""
        with self._tx() as conn:
            current = conn.execute(
                "SELECT generation_id FROM index_generations WHERE status='active'"
            ).fetchone()
            if current and current["generation_id"] == generation_id:
                return
            conn.execute(
                "UPDATE index_generations SET status='retired' WHERE status='active'")
            conn.execute(
                "UPDATE index_generations SET status='active', activated_at=?,"
                " stats_json=? WHERE generation_id=?",
                (utc_now(), json.dumps(stats, ensure_ascii=False), generation_id),
            )

    def write_postings(self, generation_id: str,
                       postings: List[Tuple[str, str, int]],
                       doc_terms: List[Tuple[str, int, int]]) -> None:
        with self._tx() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO index_postings (generation_id, term, block_id, tf)"
                " VALUES (?,?,?,?)",
                [(generation_id, term, block_id, tf) for term, block_id, tf in postings],
            )
            conn.executemany(
                "INSERT OR REPLACE INTO index_doc_terms (generation_id, block_id,"
                " terms, length) VALUES (?,?,?,?)",
                [(generation_id, block_id, terms, length)
                 for block_id, terms, length in doc_terms],
            )

    def postings_for_terms(self, generation_id: str,
                           terms: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        placeholders = ",".join("?" for _ in terms)
        with self._lock:
            rows = self._conn.execute(
                "SELECT term, block_id, tf FROM index_postings"
                " WHERE generation_id=? AND term IN (%s)" % placeholders,
                (generation_id, *terms),
            ).fetchall()
        result: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            result.setdefault(row["term"], []).append(
                {"block_id": row["block_id"], "tf": row["tf"]})
        return result

    def doc_term_stats(self, generation_id: str) -> Dict[str, int]:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) blocks, COALESCE(SUM(terms),0) terms,"
                " COALESCE(SUM(length),0) length FROM index_doc_terms"
                " WHERE generation_id=?",
                (generation_id,)).fetchone()
        return {"blocks": row["blocks"], "terms": row["terms"],
                "total_length": row["length"]}

    def block_lengths(self, generation_id: str,
                      block_ids: List[str]) -> Dict[str, int]:
        if not block_ids:
            return {}
        placeholders = ",".join("?" for _ in block_ids)
        with self._lock:
            rows = self._conn.execute(
                "SELECT block_id, length FROM index_doc_terms"
                " WHERE generation_id=? AND block_id IN (%s)" % placeholders,
                (generation_id, *block_ids),
            ).fetchall()
        return {row["block_id"]: row["length"] for row in rows}

    def blocks_by_ids(self, block_ids: List[str]) -> List[Dict[str, Any]]:
        if not block_ids:
            return []
        placeholders = ",".join("?" for _ in block_ids)
        with self._lock:
            rows = self._conn.execute(
                "SELECT b.block_id, b.ordinal, b.block_type, b.text, b.locator_json,"
                " b.quality_status, b.quality_issues_json,"
                " e.extraction_id, e.source, e.doc_id, e.version_id, e.snapshot_sha256,"
                " e.status AS extraction_status"
                " FROM blocks b JOIN extractions e ON e.extraction_id = b.extraction_id"
                " WHERE b.block_id IN (%s)" % placeholders,
                block_ids,
            ).fetchall()
        ordered = []
        by_id = {}
        for row in rows:
            item = dict(row)
            item["locator"] = json.loads(item.pop("locator_json") or "{}")
            item["quality"] = {
                "status": item.pop("quality_status"),
                "issues": json.loads(item.pop("quality_issues_json") or "[]"),
            }
            by_id[item["block_id"]] = item
        for block_id in block_ids:
            if block_id in by_id:
                ordered.append(by_id[block_id])
        return ordered

    def searchable_block_ids(self, generation_id: str) -> int:
        with self._lock:
            return self._conn.execute(
                "SELECT COUNT(*) FROM index_doc_terms WHERE generation_id=?",
                (generation_id,)).fetchone()[0]

    def retire_orphan_generations(self) -> int:
        """Retire 'building' generations left over by interrupted rebuilds."""
        with self._tx() as conn:
            cur = conn.execute(
                "UPDATE index_generations SET status='retired'"
                " WHERE status='building'")
            return cur.rowcount

    # ------------------------------------------------------------- kb events
    def emit_event(self, event_type: str, source: Optional[str], doc_id: Optional[str],
                   version_id: Optional[str], payload: Optional[Dict[str, Any]] = None,
                   payload_version: int = 1, event_id: Optional[str] = None) -> str:
        if event_id is None:
            identity = "\x00".join((event_type, str(source), str(doc_id),
                                    str(version_id), json.dumps(payload or {},
                                                                sort_keys=True)))
            event_id = "evt-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO kb_events (event_id, event_type, source, doc_id,"
                " version_id, occurred_at, payload_version, payload_json)"
                " VALUES (?,?,?,?,?,?,?,?)"
                " ON CONFLICT(event_id) DO NOTHING",
                (event_id, event_type, source, doc_id, version_id, utc_now(),
                 payload_version, json.dumps(payload or {}, ensure_ascii=False)),
            )
        return event_id

    def events_after(self, sequence: int, limit: int = 100) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM kb_events WHERE sequence > ? ORDER BY sequence LIMIT ?",
                (sequence, limit),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
            result.append(item)
        return result

    def latest_event_sequence(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(sequence),0) s FROM kb_events").fetchone()
        return row["s"]

    # ----------------------------------------------------- embeddings & runs
    def get_embedding(self, model: str, block_id: str) -> Optional[List[float]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT vector_json FROM block_embeddings WHERE model=? AND block_id=?",
                (model, block_id)).fetchone()
        return json.loads(row["vector_json"]) if row else None

    def put_embeddings(self, model: str, vectors: Dict[str, List[float]]) -> None:
        now = utc_now()
        with self._tx() as conn:
            for block_id, vector in vectors.items():
                conn.execute(
                    "INSERT INTO block_embeddings (model, block_id, dim, vector_json,"
                    " created_at) VALUES (?,?,?,?,?)"
                    " ON CONFLICT(model, block_id) DO UPDATE SET"
                    " vector_json=excluded.vector_json, dim=excluded.dim",
                    (model, block_id, len(vector),
                     json.dumps(vector), now),
                )

    def create_analysis_run(self, query: str, mode: str = "keyword",
                            prompt_version: str = "pv1") -> Dict[str, Any]:
        run_id = "run-" + hashlib.sha256(
            ("\x00".join((query, mode, prompt_version,
                          utc_now()))).encode("utf-8")).hexdigest()[:24]
        now = utc_now()
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO analysis_runs (run_id, status, query, mode,"
                " prompt_version, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?)"
                " ON CONFLICT(run_id) DO NOTHING",
                (run_id, "pending", query, mode, prompt_version, now, now),
            )
        return {"run_id": run_id, "status": "pending", "query": query, "mode": mode}

    def get_analysis_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM analysis_runs WHERE run_id=?", (run_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        for key in ("citations", "verification"):
            json_key = key + "_json"
            if json_key in result:
                try:
                    result[key] = json.loads(result.pop(json_key) or "null")
                except (ValueError, TypeError):
                    result[key] = None
        return result

    def update_analysis_run(self, run_id: str, **fields: Any) -> None:
        allowed = {"status", "draft", "citations_json", "verification_json",
                   "error", "finished_at", "mode"}
        mapped = {}
        if "citations" in fields:
            mapped["citations_json"] = json.dumps(
                fields.pop("citations"), ensure_ascii=False)
        if "verification" in fields:
            mapped["verification_json"] = json.dumps(
                fields.pop("verification"), ensure_ascii=False)
        mapped.update({k: v for k, v in fields.items() if k in allowed})
        if not mapped:
            return
        mapped["updated_at"] = utc_now()
        assignments = ", ".join("%s=?" % k for k in mapped)
        with self._tx() as conn:
            conn.execute("UPDATE analysis_runs SET %s WHERE run_id=?" % assignments,
                         (*mapped.values(), run_id))

    def record_usage(self, provider: str, model: str, kind: str,
                     input_tokens: int, output_tokens: int,
                     cost_basis: str, run_id: Optional[str] = None) -> None:
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO usage_events (provider, model, kind, input_tokens,"
                " output_tokens, cost_basis, run_id, created_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (provider, model, kind, int(input_tokens), int(output_tokens),
                 cost_basis, run_id, utc_now()),
            )

    def usage_totals(self, since: Optional[str] = None) -> Dict[str, int]:
        where = " WHERE created_at >= ?" if since else ""
        params = (since,) if since else ()
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(input_tokens),0) i, COALESCE(SUM(output_tokens),0) o,"
                " COUNT(*) calls FROM usage_events" + where, params).fetchone()
        return {"input_tokens": row["i"], "output_tokens": row["o"],
                "calls": row["calls"]}

    def usage_for_run(self, run_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM usage_events WHERE run_id=? ORDER BY id",
                (run_id,)).fetchall()
        return [dict(r) for r in rows]

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
