#!/usr/bin/env python3
"""Shadow reconciliation (V02): STRICT read-only verification.

Opens the shadow knowledge DB in mode=ro (never creates/migrates it),
resolves the snapshot root from the manifest's state dir, and verifies for
every sample: snapshot row exists, blob file exists, size and SHA256 match
both the snapshot row AND the manifest's pinned source hash, extraction
exists under the manifest's expected recipe, and the extraction's snapshot
binding equals the verified bytes. Any missing DB, missing/mismatched/
corrupt blob, or wrong recipe is a FAILURE (exit 1); insufficient data is
reported as NOT_RUN (exit 2). Exit 0 requires every sample PASS.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "app"))


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(1 << 20)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(prog="shadow_reconcile")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    with open(args.manifest, encoding="utf-8") as handle:
        manifest = json.load(handle)
    samples = manifest.get("samples", [])
    expected_digest = manifest.get("expected_extraction_digest")
    if not samples:
        print(json.dumps({"ok": False, "status": "NOT_RUN",
                          "error": "manifest has no samples"}))
        return 2

    db_path = os.path.join(args.state_dir, "knowledge.sqlite3")
    if not os.path.isfile(db_path):
        print(json.dumps({"ok": False, "status": "NOT_RUN",
                          "error": "shadow database not found (run the"
                                   " shadow batch first): %s" % db_path}))
        return 2

    # strict read-only: never KnowledgeStore (it migrates), never create
    conn = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
    conn.row_factory = sqlite3.Row

    rows, problems = [], []
    for sample in samples:
        entry = {"source": sample["source"], "doc_id": sample["doc_id"],
                 "version_id": sample["version_id"]}
        snap = conn.execute(
            "SELECT * FROM snapshots WHERE source=? AND doc_id=? AND"
            " version_id=?", (sample["source"], sample["doc_id"],
                              sample["version_id"])).fetchone()
        if snap is None:
            entry["result"] = "FAIL"
            entry["reason"] = "snapshot row missing"
            problems.append(entry)
            rows.append(entry)
            continue
        blob_path = os.path.join(args.state_dir, "snapshots",
                                 *snap["store_path"].split("/"))
        if not os.path.isfile(blob_path):
            entry["result"] = "FAIL"
            entry["reason"] = "blob file missing"
            problems.append(entry)
            rows.append(entry)
            continue
        actual = _sha256_file(blob_path)
        entry["blob_sha256"] = actual
        entry["blob_bytes"] = os.path.getsize(blob_path)
        if actual != snap["sha256"] or entry["blob_bytes"] != snap["bytes"]:
            entry["result"] = "FAIL"
            entry["reason"] = "blob hash/size mismatch vs snapshot row"
            problems.append(entry)
            rows.append(entry)
            continue
        if sample.get("sha256") and actual != sample["sha256"]:
            entry["result"] = "FAIL"
            entry["reason"] = "blob hash mismatch vs manifest source hash"
            problems.append(entry)
            rows.append(entry)
            continue
        extraction = conn.execute(
            "SELECT * FROM extractions WHERE source=? AND doc_id=? AND"
            " version_id=? AND config_digest=?",
            (sample["source"], sample["doc_id"], sample["version_id"],
             expected_digest)).fetchone() if expected_digest else conn.execute(
            "SELECT * FROM extractions WHERE source=? AND doc_id=? AND"
            " version_id=? ORDER BY rowid DESC LIMIT 1",
            (sample["source"], sample["doc_id"], sample["version_id"])).fetchone()
        if extraction is None:
            entry["result"] = "FAIL"
            entry["reason"] = ("no extraction under expected recipe"
                               if expected_digest else "no extraction")
            problems.append(entry)
            rows.append(entry)
            continue
        if extraction["snapshot_sha256"] != actual:
            entry["result"] = "FAIL"
            entry["reason"] = "extraction bound to different bytes"
            problems.append(entry)
            rows.append(entry)
            continue
        entry["result"] = "PASS"
        entry["extraction_status"] = extraction["status"]
        entry["blocks"] = conn.execute(
            "SELECT COUNT(*) FROM blocks WHERE extraction_id=?",
            (extraction["extraction_id"],)).fetchone()[0]
        rows.append(entry)
    conn.close()

    passed = [r for r in rows if r["result"] == "PASS"]
    report = {
        "kind": "shadow-reconcile-strict",
        "read_only": True,
        "expected_extraction_digest": expected_digest,
        "documents": len(rows),
        "passed": len(passed),
        "failed": len(problems),
        "ok": not problems and len(passed) == len(rows),
        "problems": problems,
        "rows": rows,
    }
    out = args.out or os.path.join(os.path.dirname(args.state_dir),
                                   "reconcile.json")
    with open(out, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({k: v for k, v in report.items() if k != "rows"},
                     ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
