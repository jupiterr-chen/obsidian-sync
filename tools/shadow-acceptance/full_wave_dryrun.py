#!/usr/bin/env python3
"""Full-wave dry-run planner (N6): NEW recipe vs existing products.

Reports, WITHOUT processing: which (source, doc_id, version) entries would
be re-snapshotted / re-extracted under the CURRENT effective recipe
identity, how many old products remain readable (immutability), page/OCR
estimates from existing stats, and the expected job counts. Read-only
against the production knowledge DB.

Usage:
  PYTHONPATH=app python tools/shadow-acceptance/full_wave_dryrun.py \
      --config /vol2/1000/10.Develop/obsidian-sync/config-knowledge.json \
      [--json-out wave-plan.json]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "app"))

from knowledge.config import KnowledgeConfig  # noqa: E402
from knowledge.extract import (  # noqa: E402
    STAGE_EXTRACT,
    compute_extraction_id,
    extract_config_digest,
    extractor_info,
)
from knowledge.sampling import format_of  # noqa: E402
from knowledge.store import KnowledgeStore, config_digest  # noqa: E402
from knowledge.snapshot import STAGE_CONFIG  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(prog="full_wave_dryrun")
    parser.add_argument("--config", required=True)
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args()

    base = os.path.dirname(os.path.abspath(args.config))
    config = KnowledgeConfig.load(args.config).resolve(base)
    # open the production knowledge DB READ-ONLY
    import sqlite3

    uri = "file:%s?mode=ro" % os.path.abspath(
        config.knowledge_db).replace("\\", "/")
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row

    new_extract_digest = extract_config_digest(
        config.ocr_config(), config.extra.get("providers") or {})
    snapshot_digest = config_digest(STAGE_CONFIG)

    rows = conn.execute(
        "SELECT v.source, v.doc_id, v.version_id, v.media_type, v.ext,"
        " s.sha256 AS snap_sha, e.extraction_id AS latest_extraction,"
        " e.config_digest AS latest_digest, e.stats_json"
        " FROM kb_versions v"
        " LEFT JOIN snapshots s ON s.source=v.source AND s.doc_id=v.doc_id"
        "   AND s.version_id=v.version_id"
        " LEFT JOIN extractions e ON e.extraction_id = ("
        "   SELECT e2.extraction_id FROM extractions e2"
        "   WHERE e2.source=v.source AND e2.doc_id=v.doc_id"
        "     AND e2.version_id=v.version_id"
        "   ORDER BY e2.rowid DESC LIMIT 1)"
        " WHERE v.state='ready' ORDER BY v.source, v.doc_id").fetchall()

    re_snapshot = have_snapshot = 0
    re_extract = have_current_extract = 0
    pages = ocr_pages = 0
    by_source: dict = {}
    for row in rows:
        source = row["source"]
        stats = by_source.setdefault(source, {"versions": 0, "re_extract": 0,
                                              "re_snapshot": 0})
        stats["versions"] += 1
        if row["snap_sha"]:
            have_snapshot += 1
        else:
            re_snapshot += 1
            stats["re_snapshot"] += 1
        if row["latest_digest"] == new_extract_digest:
            have_current_extract += 1
        else:
            fmt = format_of(row["media_type"], row["ext"])
            try:
                parser_id, parser_version = extractor_info(fmt)
            except Exception:
                continue
            candidate = compute_extraction_id(
                row["source"], row["doc_id"], row["version_id"],
                row["snap_sha"] or "", parser_id, parser_version,
                new_extract_digest)
            existing = conn.execute(
                "SELECT 1 FROM extractions WHERE extraction_id=?",
                (candidate,)).fetchone()
            if existing:
                have_current_extract += 1
            else:
                re_extract += 1
                stats["re_extract"] += 1
                try:
                    s = json.loads(row["stats_json"] or "{}")
                    pages += s.get("pages") or 0
                    ocr_pages += (s.get("ocr_candidate_pages") or 0)
                except (ValueError, TypeError):
                    pass
    total_extractions = conn.execute(
        "SELECT COUNT(*) FROM extractions").fetchone()[0]
    total_blocks = conn.execute(
        "SELECT COUNT(*) FROM blocks").fetchone()[0]
    conn.close()

    report = {
        "kind": "full-wave-dry-run",
        "read_only": True,
        "recipe": {
            "new_extract_digest": new_extract_digest,
            "snapshot_digest": snapshot_digest,
        },
        "ready_versions": len(rows),
        "by_source": by_source,
        "snapshot_jobs": {"needed": re_snapshot,
                          "already_have": have_snapshot},
        "extract_jobs": {"needed": re_extract,
                         "already_current": have_current_extract},
        "estimated_pages_to_process": pages,
        "estimated_ocr_candidate_pages": ocr_pages,
        "immutability": {
            "existing_extractions_preserved": total_extractions,
            "existing_blocks_preserved": total_blocks,
            "note": "old products are never modified; the new recipe adds"
                    " NEW extraction rows and evidence block ids",
        },
        "recovery": "jobs are idempotent (unique stage+config identity); any"
                    " interruption resumes without duplicates",
    }
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
