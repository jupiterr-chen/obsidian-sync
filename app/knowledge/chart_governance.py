"""Offline chart governance CLI. Plan is read-only; apply is explicit.

Private manifests and reports belong outside Git, under runtime/operations.
No command deletes or moves Vault files, invokes OCR, or calls a model.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from threading import RLock

from .content import (POLICY, activate, canonical, chart_signals, dependency_report,
                      has_table, revision, rollback, validate_manifest)


def read_only(path):
    conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def plan(db, manifest):
    conn = read_only(db)
    try:
        projection = validate_manifest(conn, manifest)
        return {"dry_run": True, "policy": POLICY,
                "expected_revision": revision(conn),
                "projection_id": projection["projection_id"],
                "block_id": manifest["block_id"],
                "excluded_characters": projection["excluded_characters"],
                "retained_characters": len(projection["text"]),
                "assets": [a["name"] for a in projection["assets"]],
                "source_unchanged": True}
    finally:
        conn.close()


def scan(db):
    from .effective import effective_extraction_ids
    conn = read_only(db)
    try:
        candidates = []
        scanned = 0
        for eid in effective_extraction_ids(conn):
            for row in conn.execute("SELECT block_id,text,locator_json FROM blocks WHERE extraction_id=?", (eid,)):
                scanned += 1
                signals = chart_signals(row["text"])
                if signals["requires_review"]:
                    candidates.append({"block_id": row["block_id"], "extraction_id": eid,
                                       "locator": json.loads(row["locator_json"]),
                                       "signals": signals})
        return {"dry_run": True, "scanned": scanned,
                "candidate_count": len(candidates), "candidates": candidates,
                "note": "Candidates include tables; review before any exclusion."}
    finally:
        conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare", help="render reviewed boxes from a verified local PDF")
    prep.add_argument("--spec", required=True)
    prep.add_argument("--pdf", required=True)
    prep.add_argument("--assets", required=True)
    prep.add_argument("--output", required=True)
    prep.add_argument("--db", help="read-only source DB for exact native character mapping")
    prep.add_argument("--native-mapping", action="store_true")
    for name in ("plan", "activate", "rollback", "scan", "report"):
        command = sub.add_parser(name)
        command.add_argument("--db", required=True)
        if name in ("plan", "activate"):
            command.add_argument("--manifest", required=True)
        if name in ("activate", "rollback"):
            command.add_argument("--apply", action="store_true")
        if name == "activate":
            command.add_argument("--expected-revision")
        if name == "rollback":
            command.add_argument("--block-id", required=True)
            command.add_argument("--expected-projection", required=True)
        if name == "report":
            command.add_argument("--reading-dir")
    args = parser.parse_args(argv)
    if args.command == "prepare":
        from .chart_assets import render_region
        manifest = json.loads(Path(args.spec).read_text(encoding="utf-8"))
        if args.native_mapping:
            if not args.db:
                parser.error("--native-mapping requires --db")
            from .chart_assets import map_native_regions
            from .content import digest
            conn = read_only(args.db)
            try:
                row = conn.execute("SELECT text FROM blocks WHERE block_id=?", (manifest["block_id"],)).fetchone()
                if row is None or digest(row["text"]) != manifest["text_sha256"]:
                    raise ValueError("indexed text changed since region review")
                manifest["regions"] = map_native_regions(args.pdf, manifest["snapshot_sha256"], manifest["page"], row["text"], manifest["regions"])
                manifest["mapping_method"] = "pdf-character-bbox-exact-whitespace-normalized"
            finally:
                conn.close()
        for region in manifest["regions"]:
            if region["kind"] == "chart":
                region["asset"] = render_region(args.pdf, manifest["snapshot_sha256"],
                                                 manifest["page"], region["bbox"], args.assets)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        data = canonical(manifest)
        if output.exists():
            if output.read_text(encoding="utf-8") != data:
                raise ValueError("output exists with different content; use a new manifest path")
        else:
            with output.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(data)
        result = {"prepared": True, "manifest": str(output), "production_changed": False}
    elif args.command in ("plan", "activate"):
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        result = plan(args.db, manifest)
        if args.command == "activate" and args.apply:
            if args.expected_revision is None:
                parser.error("--apply requires the exact --expected-revision from plan (empty string for first activation)")
            from .store import KnowledgeStore
            from .indexing import build_generation
            kb = KnowledgeStore(args.db)
            try:
                result = activate(kb, manifest, Path(args.db).resolve().parent / "chart-assets",
                                  expected_revision=args.expected_revision)
                result["index"] = build_generation(kb)
            finally:
                kb.close()
    elif args.command == "rollback":
        result = {"dry_run": True, "block_id": args.block_id, "expected_projection_id": args.expected_projection}
        if args.apply:
            from .store import KnowledgeStore
            from .indexing import build_generation
            kb = KnowledgeStore(args.db)
            try:
                result = rollback(kb, args.block_id, args.expected_projection)
                result["index"] = build_generation(kb)
            finally:
                kb.close()
    elif args.command == "scan":
        result = scan(args.db)
    else:
        conn = read_only(args.db)
        try:
            result = {"dry_run": True, "content_revision": revision(conn),
                      "invalidations": dependency_report(conn) if has_table(conn, "content_invalidations") else []}
            if args.reading_dir:
                from .governance import plan_file_governance
                result["vault"] = plan_file_governance(SimpleNamespace(_conn=conn, _lock=RLock()), args.reading_dir)
        finally:
            conn.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
