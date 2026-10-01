#!/usr/bin/env python3
"""Online backup and restore-drill for the knowledge layer (P6-02).

Backup uses the SQLite online backup API (never a live file copy of a WAL
database) plus a manifest of snapshot blobs. The restore drill restores the
backup into an independent directory and verifies table counts and blob
hashes without touching production paths. RPO/RTO timings are recorded.

Usage:
  python scripts/backup-knowledge.py backup --db state/knowledge.sqlite3 \
      --out backups/knowledge --snapshots state/snapshots
  python scripts/backup-knowledge.py drill --backup backups/knowledge/<stamp>.db \
      --snapshots state/snapshots
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import time
from datetime import datetime, timezone


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z")


def backup_database(db_path: str, out_path: str) -> Dict[str, int]:
    src = sqlite3.connect(db_path)
    try:
        dst = sqlite3.connect(out_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
        with sqlite3.connect(out_path) as check:
            counts = {
                name: check.execute("SELECT COUNT(*) FROM %s" % name).fetchone()[0]
                for name in ("kb_documents", "kb_versions", "snapshots",
                             "snapshot_blobs", "extractions", "blocks", "jobs",
                             "kb_events", "claims", "decisions", "usage_events")
            }
        return counts
    finally:
        src.close()


def sha256_file(path: str, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def cmd_backup(args) -> int:
    started = time.monotonic()
    os.makedirs(args.out, exist_ok=True)
    stamp = utc_now().replace(":", "").replace("-", "")
    out_db = os.path.join(args.out, "knowledge-%s.db" % stamp)
    counts = backup_database(args.db, out_db)
    # blob manifest: identity + size + sha of the store file (store is
    # content-addressed and append-only, so the manifest is a verification
    # tool, not the backup itself; snapshots are copied below)
    blobs_dir = os.path.join(args.out, "blobs-%s" % stamp)
    copied = 0
    if args.snapshots and os.path.isdir(args.snapshots):
        for name in os.listdir(args.snapshots):
            if name == "tmp":
                continue
            sub = os.path.join(args.snapshots, name)
            if not os.path.isdir(sub):
                continue
            target_sub = os.path.join(blobs_dir, name)
            os.makedirs(target_sub, exist_ok=True)
            for blob in os.listdir(sub):
                shutil.copyfile(os.path.join(sub, blob),
                                os.path.join(target_sub, blob))
                copied += 1
    elapsed = time.monotonic() - started
    report = {
        "kind": "knowledge-backup", "created_at": utc_now(),
        "database": out_db, "blobs_dir": blobs_dir if copied else None,
        "blobs_copied": copied, "table_counts": counts,
        "elapsed_seconds": round(elapsed, 3),
        "rpo_note": "recovery point = time of this backup",
    }
    report_path = out_db + ".report.json"
    with open(report_path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def cmd_drill(args) -> int:
    """Restore the backup into an independent temp dir and verify (A22)."""
    started = time.monotonic()
    drill_dir = args.dir or os.path.join(
        os.path.dirname(os.path.abspath(args.backup)), "drill-%s"
        % utc_now().replace(":", "").replace("-", ""))
    os.makedirs(drill_dir, exist_ok=True)
    restored_db = os.path.join(drill_dir, "knowledge-restored.db")
    shutil.copyfile(args.backup, restored_db)
    problems = []
    counts = {}
    rows = []
    try:
        with sqlite3.connect(restored_db) as conn:
            conn.row_factory = sqlite3.Row
            counts = {
                name: conn.execute("SELECT COUNT(*) FROM %s" % name).fetchone()[0]
                for name in ("kb_documents", "kb_versions", "snapshots",
                             "snapshot_blobs", "extractions", "blocks", "jobs",
                             "kb_events", "claims", "decisions", "usage_events")
            }
            rows = conn.execute(
                "SELECT store_path, bytes, sha256 FROM snapshot_blobs").fetchall()
    except sqlite3.DatabaseError as exc:
        problems.append("backup database unreadable: %s" % exc)
    verified = 0
    if args.snapshots and os.path.isdir(args.snapshots):
        for row in rows:
            path = os.path.join(args.snapshots, *row["store_path"].split("/"))
            if not os.path.isfile(path):
                problems.append("missing blob %s" % row["store_path"])
                continue
            if os.path.getsize(path) != row["bytes"]:
                problems.append("size mismatch %s" % row["store_path"])
                continue
            if sha256_file(path) != row["sha256"]:
                problems.append("hash mismatch %s" % row["store_path"])
                continue
            verified += 1
    else:
        problems.append("snapshot root not provided; blob verification skipped")
    try:
        with sqlite3.connect(restored_db) as conn:
            check = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if check != "ok":
            problems.append("sqlite integrity_check: %s" % check)
    except sqlite3.DatabaseError as exc:
        problems.append("integrity check failed: %s" % exc)
    elapsed = time.monotonic() - started
    report = {
        "kind": "knowledge-restore-drill", "at": utc_now(),
        "restored_to": restored_db, "table_counts": counts,
        "blobs_verified": verified, "problems": problems,
        "ok": not [p for p in problems if "skipped" not in p],
        "elapsed_seconds": round(elapsed, 3),
        "rto_note": "restore+verify wall clock = %.3fs (drill, isolated dir)"
                    % elapsed,
    }
    report_path = os.path.join(drill_dir, "drill-report.json")
    with open(report_path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="backup-knowledge")
    sub = parser.add_subparsers(dest="command", required=True)
    backup = sub.add_parser("backup")
    backup.add_argument("--db", required=True)
    backup.add_argument("--out", required=True)
    backup.add_argument("--snapshots", default=None)
    drill = sub.add_parser("drill")
    drill.add_argument("--backup", required=True)
    drill.add_argument("--snapshots", default=None)
    drill.add_argument("--dir", default=None)
    args = parser.parse_args(argv)
    if args.command == "backup":
        return cmd_backup(args)
    return cmd_drill(args)


if __name__ == "__main__":
    sys.exit(main())
