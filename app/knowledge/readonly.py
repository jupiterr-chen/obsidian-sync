"""Truly read-only store access for pre-flight/audit CLIs (S4/TA06).

The writable KnowledgeStore constructor creates directories, enables
WAL, runs SCHEMA and migrations - correct for the worker, wrong for a
command advertised as read-only: pointing it at an existing database
must never initialize or migrate it. This shim opens SQLite strictly
in mode=ro (immutable file bytes; no journal, no schema steps) and
exposes just the ``_conn``/``_lock`` surface the inventory/governance
planners use.

If the file does not exist, or lacks the tables these tools need, the
caller gets a clear error - never a newly created database. Checks that
need to WRITE must use KnowledgeStore on an isolated copy instead.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from typing import Any, List

# tables the read-only planners actually query
REQUIRED_TABLES = ("kb_documents", "kb_versions", "extractions",
                   "blocks", "snapshot_blobs")


class ReadOnlyStoreError(Exception):
    """The target cannot be read as a knowledge store without writing.

    ``kind`` is missing_file | unsupported_schema."""


class ReadOnlyStore:
    """A no-initialization read-only view of a knowledge database."""

    def __init__(self, path: str):
        if not os.path.isfile(path):
            raise ReadOnlyStoreError(
                "missing_file: %s does not exist; a read-only check"
                " never creates it" % path)
        uri = "file:%s?mode=ro" % os.path.abspath(path).replace("\\", "/")
        try:
            self._conn = sqlite3.connect(uri, uri=True)
        except sqlite3.OperationalError as exc:
            raise ReadOnlyStoreError(
                "unsupported: cannot open %s read-only: %s" % (path, exc))
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._path = path
        missing = self._missing_tables()
        if missing:
            self._conn.close()
            raise ReadOnlyStoreError(
                "unsupported_schema: %s lacks required tables (%s); this"
                " tool will not initialize or migrate it - point it at a"
                " supported database or inspect an isolated copy"
                % (path, ", ".join(missing)))

    def _missing_tables(self) -> List[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        present = {row["name"] for row in rows}
        return [name for name in REQUIRED_TABLES if name not in present]

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            pass

    # a few conveniences so planner code can treat this like the
    # read paths of KnowledgeStore without inheriting its writes
    def table_names(self) -> List[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        return sorted(row["name"] for row in rows)

    def user_version(self) -> int:
        with self._lock:
            return self._conn.execute("PRAGMA user_version").fetchone()[0]

    def __enter__(self) -> "ReadOnlyStore":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()


def open_read_only(path: str) -> ReadOnlyStore:
    """Open a strictly read-only store or explain why not."""
    return ReadOnlyStore(path)
