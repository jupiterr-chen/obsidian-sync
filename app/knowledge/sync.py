"""Reconcile the first-layer catalog into the knowledge store (idempotent).

Reads the catalog database through a *read-only* SQLite connection (the
knowledge layer never writes to the catalog). Full enumeration is the
authoritative reconciliation; the library change ledger is only an
acceleration hint and is not required for correctness (ADR0003).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from .config import KnowledgeConfig
from .snapshot import STAGE_CONFIG
from .store import KnowledgeStore, config_digest, utc_now


class CatalogUnavailable(Exception):
    pass


def open_catalog_readonly(catalog_db: str) -> sqlite3.Connection:
    path = Path(catalog_db).resolve()
    if not path.is_file():
        raise CatalogUnavailable("catalog database not found: %s" % path)
    uri = "file:%s?mode=ro" % path.as_posix()
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def iter_catalog_documents(conn: sqlite3.Connection, batch_size: int) -> Iterator[Dict[str, Any]]:
    """Yield document rows joined with their version rows, ordered stably."""
    sql = (
        "SELECT d.source, d.doc_id, d.title, d.display_title, d.market, d.symbol,"
        " d.doc_type, d.language, d.report_period, d.filing_date, d.published_at,"
        " d.report_date, d.available, d.first_seen_at, d.last_seen_at,"
        " v.version_id, v.sha256, v.bytes, v.media_type, v.ext, v.rel_path,"
        " v.is_current, v.state, v.content_changed_at"
        " FROM documents d LEFT JOIN versions v"
        " ON v.source = d.source AND v.doc_id = d.doc_id"
        " ORDER BY d.source, d.doc_id, v.version_id"
    )
    cursor = conn.execute(sql)
    while True:
        rows = cursor.fetchmany(batch_size)
        if not rows:
            return
        for row in rows:
            yield dict(row)


class SyncService:
    def __init__(self, kb: KnowledgeStore, config: KnowledgeConfig):
        self.kb = kb
        self.config = config

    def run(self) -> Dict[str, Any]:
        """One full reconciliation pass. Safe to run repeatedly (A02)."""
        run_id = self.kb.start_sync_run()
        stats: Dict[str, Any] = {
            "documents": 0, "versions": 0, "new_documents": 0,
            "new_versions": 0, "jobs_registered": 0, "sources": {},
        }
        error: Optional[str] = None
        try:
            conn = open_catalog_readonly(self.config.catalog_db)
        except (CatalogUnavailable, sqlite3.Error) as exc:
            error = "%s: %s" % (type(exc).__name__, exc)
            self.kb.finish_sync_run(run_id, False, stats, error)
            raise CatalogUnavailable(error)

        digest = config_digest(STAGE_CONFIG)
        seen_docs: Dict[str, Dict[str, Any]] = {}
        seen_versions: List[Dict[str, Any]] = []
        current_doc: Optional[Dict[str, Any]] = None
        try:
            for row in iter_catalog_documents(conn, self.config.sync_batch_size):
                key = (row["source"], row["doc_id"])
                if current_doc is None or (current_doc["source"], current_doc["doc_id"]) != key:
                    if current_doc is not None:
                        self._commit_document(current_doc, seen_versions, stats, digest)
                    current_doc = {
                        "source": row["source"], "doc_id": row["doc_id"],
                        "title": row["title"], "display_title": row["display_title"],
                        "market": row["market"], "symbol": row["symbol"],
                        "doc_type": row["doc_type"], "language": row["language"],
                        "report_period": row["report_period"], "filing_date": row["filing_date"],
                        "published_at": row["published_at"], "report_date": row["report_date"],
                        "available": bool(row["available"]),
                        "first_seen_at": row["first_seen_at"],
                        "last_seen_at": row["last_seen_at"],
                    }
                    seen_versions = []
                if row["version_id"] is not None:
                    seen_versions.append({
                        "source": row["source"], "doc_id": row["doc_id"],
                        "version_id": row["version_id"], "sha256": row["sha256"],
                        "bytes": row["bytes"], "media_type": row["media_type"],
                        "ext": row["ext"], "rel_path": row["rel_path"],
                        "is_current": bool(row["is_current"]),
                        "state": row["state"] or "ready",
                        "content_changed_at": row["content_changed_at"],
                    })
            if current_doc is not None:
                self._commit_document(current_doc, seen_versions, stats, digest)
        except sqlite3.Error as exc:
            error = "%s: %s" % (type(exc).__name__, exc)
            self.kb.finish_sync_run(run_id, False, stats, error)
            raise CatalogUnavailable(error)
        finally:
            conn.close()

        self.kb.finish_sync_run(run_id, error is None, stats, error)
        stats["ok"] = error is None
        return stats

    def _commit_document(self, doc: Dict[str, Any], versions: List[Dict[str, Any]],
                         stats: Dict[str, Any], digest: str) -> None:
        synced_at = utc_now()
        doc_stats = self.kb.upsert_documents([doc], synced_at)
        stats["documents"] += 1
        stats["new_documents"] += doc_stats["new_documents"]
        if versions:
            ver_stats = self.kb.upsert_versions(versions, synced_at)
            stats["versions"] += ver_stats["versions"]
            stats["new_versions"] += ver_stats["new_versions"]
        source_stats = stats["sources"].setdefault(doc["source"], {
            "documents": 0, "versions": 0, "snapshot_jobs_registered": 0})
        source_stats["documents"] += 1
        source_stats["versions"] += len(versions)
        if "snapshot" in self.config.register_stages:
            for version in versions:
                # Only ready versions are snapshottable; conflict/missing are
                # mirrored as-is and never enqueued (their bytes are untrusted).
                if version["state"] != "ready":
                    continue
                if self.kb.register_job(
                        version["source"], version["doc_id"], version["version_id"],
                        "snapshot", digest):
                    stats["jobs_registered"] += 1
                    source_stats["snapshot_jobs_registered"] += 1
