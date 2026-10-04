#!/usr/bin/env python3
"""Shadow-acceptance batch runner (N5): isolated, read-only, dry-run capable.

Processes ONLY the documents in a shadow manifest into an ISOLATED
knowledge database + snapshot store, never the production state. Supports
--dry-run (report what would be processed, touch nothing). Requires only
read access to the source archives.

Usage:
  PYTHONPATH=app python tools/shadow-acceptance/shadow_run.py \
      --config /vol2/1000/10.Develop/obsidian-sync/config-knowledge.json \
      --manifest /vol2/1000/10.Develop/obsidian-sync/shadow/shadow-manifest.json \
      --state-dir /vol2/1000/10.Develop/obsidian-sync/shadow/state \
      [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "app"))

from knowledge.config import KnowledgeConfig  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(prog="shadow_run")
    parser.add_argument("--config", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--state-dir", required=True,
                        help="isolated knowledge db + snapshot root")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    base = os.path.dirname(os.path.abspath(args.config))
    config = KnowledgeConfig.load(args.config).resolve(base)
    with open(args.manifest, encoding="utf-8") as handle:
        manifest = json.load(handle)
    samples = manifest.get("samples", [])
    if not samples:
        print(json.dumps({"ok": False, "error": "empty manifest"}))
        return 1

    # U05: hard isolation FIRST - a state-dir at/inside the production
    # state or equal to any configured production path is refused BEFORE
    # any probe or write
    prod_state = os.path.realpath(
        os.path.join(os.path.dirname(base), "state"))
    state_real = os.path.realpath(args.state_dir)
    production_paths = [prod_state,
                        os.path.realpath(config.snapshot_root),
                        os.path.dirname(os.path.realpath(config.knowledge_db))]
    for forbidden in production_paths:
        if state_real == forbidden or state_real.startswith(
                forbidden + os.sep):
            print(json.dumps({
                "ok": False,
                "error": "refusing shadow state dir at/inside production"
                         " path %r" % forbidden,
            }))
            return 3

    # connectivity probe of the read-only sources
    from knowledge.sync import open_catalog_readonly

    try:
        conn = open_catalog_readonly(config.catalog_db)
        conn.execute("SELECT 1").fetchone()
        conn.close()
    except Exception as exc:
        print(json.dumps({"ok": False, "error": "catalog unreachable: %s" % exc,
                          "status": "NOT_RUN"}))
        return 2

    report = {
        "kind": "shadow-run-plan", "dry_run": args.dry_run,
        "state_dir": args.state_dir, "documents": len(samples),
        "stages": ["snapshot", "extract"],
        "estimate": {"pages_unknown_until_extract": True,
                     "ocr": "local RapidOCR (offline); fallback per config"},
    }
    if args.dry_run:
        report["plan"] = [
            {"source": s["source"], "doc_id": s["doc_id"],
             "version_id": s["version_id"], "split": s["split"]}
            for s in samples]
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    # real isolated run: dedicated knowledge db + snapshot root
    # U05: shadow runs DISABLE all model egress regardless of the
    # production config - local OCR only, no vision fallback, no chat
    shadow_extra = json.loads(json.dumps(config.extra))
    providers = shadow_extra.get("providers") or {}
    for key in list(providers):
        providers[key] = {**providers[key], "egress_allowed": False}
    shadow_extra["providers"] = providers
    shadow_extra.setdefault("ocr", {})
    shadow_extra["ocr"] = {**shadow_extra["ocr"], "fallback": None}
    shadow_config = KnowledgeConfig(
        catalog_db=config.catalog_db,
        knowledge_db=os.path.join(args.state_dir, "knowledge.sqlite3"),
        snapshot_root=os.path.join(args.state_dir, "snapshots"),
        library_config=config.library_config,
        register_stages=("snapshot", "extract"),
        extra=shadow_extra,
    )
    from library.config import Config
    from knowledge.jobs import JobRunner
    from knowledge.store import KnowledgeStore
    from knowledge.sync import SyncService

    os.makedirs(args.state_dir, exist_ok=True)
    kb = KnowledgeStore(shadow_config.knowledge_db)
    try:
        # mirror the catalog identities, then narrow the work queues to
        # EXACTLY the sampled subset (this is an isolated shadow DB; pruning
        # job registrations here touches nothing else)
        stats = SyncService(kb, shadow_config).run()
        wanted = {(s["source"], s["doc_id"], s["version_id"])
                  for s in samples}
        with kb._tx() as conn:
            rows = conn.execute(
                "SELECT id, source, doc_id, version_id FROM jobs"
                " WHERE status='pending'").fetchall()
            for row in rows:
                if (row["source"], row["doc_id"], row["version_id"])                         not in wanted:
                    conn.execute("DELETE FROM jobs WHERE id=?", (row["id"],))
        library_config = Config.load(shadow_config.library_config).resolve(
            os.path.dirname(os.path.abspath(shadow_config.library_config)))
        runner = JobRunner(kb, shadow_config, library_config)
        snap_result = runner.run_snapshot_jobs()
        ext_result = runner.run_extract_jobs()
        report.update({
            "sync": {k: stats.get(k) for k in ("documents", "versions",
                                               "new_documents", "new_versions")},
            "snapshots": {k: snap_result.get(k) for k in
                          ("processed", "done", "failed")},
            "extracts": {k: ext_result.get(k) for k in
                         ("processed", "done", "failed")},
            "ok": bool(snap_result.get("ok")) and bool(ext_result.get("ok")),
        })
    finally:
        kb.close()
    report_path = os.path.join(args.state_dir, "run-report.json")
    with open(report_path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
