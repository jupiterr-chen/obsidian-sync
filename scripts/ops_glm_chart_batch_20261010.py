#!/usr/bin/env python3
"""Freeze and run proposal-only GLM chart classification batches."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT / "app"))

from knowledge.chart_batch import (  # noqa: E402
    BatchError, GLMChartRunner, canonical_bytes, freeze_candidates, read_json,
    read_secret, sha256_bytes,
)


def readonly_database(path: Path):
    resolved = path.resolve(strict=True)
    conn = sqlite3.connect(resolved.as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    if conn.execute("PRAGMA query_only").fetchone()[0] != 1:
        conn.close()
        raise BatchError("SQLite query_only could not be enabled")
    return conn


def _ensure_operation_outside(operation: Path, snapshot_root: Path, db: Path) -> Path:
    op = operation.resolve()
    snap = snapshot_root.resolve(strict=True)
    database = db.resolve(strict=True)
    if op == snap or snap in op.parents or op == database:
        raise BatchError("operation must be separate from snapshot storage and the database")
    if op.exists() and op.is_file():
        raise BatchError("operation path must be a directory")
    return op


def _source_digest() -> str:
    module = ROOT / "app" / "knowledge" / "chart_batch.py"
    script = Path(__file__).resolve()
    return sha256_bytes(canonical_bytes({
        "module_sha256": hashlib.sha256(module.read_bytes()).hexdigest(),
        "script_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
    }))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    freeze = sub.add_parser("freeze", help="refresh candidate identities and write immutable manifests")
    freeze.add_argument("--db", type=Path, required=True)
    freeze.add_argument("--snapshot-root", type=Path, required=True)
    freeze.add_argument("--audit-after", type=Path, required=True)
    freeze.add_argument("--operation", type=Path, required=True)
    freeze.add_argument("--pilot-size", type=int, default=10,
                        help="items per native/OCR/unknown stratum (default: 10)")
    freeze.add_argument("--seed", type=int, default=20261010)
    run = sub.add_parser("run", help="run two independent proposal rounds from a frozen manifest")
    run.add_argument("--db", type=Path, required=True)
    run.add_argument("--snapshot-root", type=Path, required=True)
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--operation", type=Path, required=True)
    run.add_argument("--secret", type=Path, required=True)
    run.add_argument("--workers", type=int, default=4)
    run.add_argument("--resume-from", type=Path, action="append", default=[],
                     help="reuse verified cache/results from an earlier operation; may be repeated")
    run.add_argument("--allow-egress", action="store_true",
                     help="explicitly permit requests to the fixed GLM endpoint")
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        op = _ensure_operation_outside(args.operation, args.snapshot_root, args.db)
        if args.command == "freeze":
            if args.pilot_size < 1:
                raise BatchError("pilot-size must be positive")
            conn = readonly_database(args.db)
            try:
                summary = freeze_candidates(conn, args.audit_after, args.snapshot_root,
                                            op, args.seed, args.pilot_size)
            finally:
                conn.close()
            print(json.dumps({key: value for key, value in summary.items()
                              if key not in ("manifest", "pilot")}, ensure_ascii=False, sort_keys=True))
            return 0

        if not args.allow_egress:
            raise BatchError("live provider requests require explicit --allow-egress")
        if any(path.resolve() == op for path in args.resume_from):
            raise BatchError("resume source and destination operation must differ")
        secret = read_secret(args.secret)
        manifest = read_json(args.manifest)
        conn = readonly_database(args.db)
        try:
            runner = GLMChartRunner(op, secret=secret, allow_egress=True,
                                    workers=args.workers, source_digest=_source_digest(),
                                    resume_from=args.resume_from)
            summary = runner.run(conn, manifest, args.snapshot_root)
        finally:
            conn.close()
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        # Avoid displaying exception data that could include source text or secrets.
        print(json.dumps({"error_type": type(exc).__name__}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
