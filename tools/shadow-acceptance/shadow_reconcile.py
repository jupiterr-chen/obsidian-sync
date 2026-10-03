#!/usr/bin/env python3
"""Shadow reconciliation report (N5): A01/A02/A03/A14 evidence from an
isolated shadow state vs its manifest. Read-only; writes a JSON report.

Usage:
  PYTHONPATH=app python tools/shadow-acceptance/shadow_reconcile.py \
      --manifest .../shadow-manifest.json --state-dir .../shadow/state \
      [--out .../shadow/reconcile.json]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "app"))

from knowledge.store import KnowledgeStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(prog="shadow_reconcile")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    with open(args.manifest, encoding="utf-8") as handle:
        manifest = json.load(handle)
    kb = KnowledgeStore(os.path.join(args.state_dir, "knowledge.sqlite3"))
    try:
        rows = []
        for sample in manifest.get("samples", []):
            snap = kb.get_snapshot(sample["source"], sample["doc_id"],
                                   sample["version_id"])
            extraction = kb.latest_extraction(sample["source"],
                                              sample["doc_id"],
                                              sample["version_id"])
            blocks = (kb.get_blocks(extraction["extraction_id"])
                      if extraction else [])
            rows.append({
                "source": sample["source"], "doc_id": sample["doc_id"],
                "version_id": sample["version_id"], "split": sample["split"],
                "snapshot": "verified" if snap and snap.get(
                    "state", "verified") == "verified" else (
                    "missing" if snap is None else snap.get("state")),
                "extraction_status": extraction["status"] if extraction
                else "none",
                "blocks": len(blocks),
                "quality_issues": (extraction.get("issues") or [])[:5]
                if extraction else [],
            })
        # A02: three-run stability is asserted by the caller re-running
        # shadow_run; here we report counts for the ledger
        report = {
            "kind": "shadow-reconcile",
            "documents": len(rows),
            "with_snapshot": sum(1 for r in rows if r["snapshot"] == "verified"),
            "with_extraction": sum(1 for r in rows
                                   if r["extraction_status"] != "none"),
            "ready": sum(1 for r in rows if r["extraction_status"] == "ready"),
            "review": sum(1 for r in rows if r["extraction_status"] == "review"),
            "failed": sum(1 for r in rows if r["extraction_status"] == "failed"),
            "rows": rows,
        }
    finally:
        kb.close()
    out = args.out or os.path.join(os.path.dirname(args.state_dir),
                                   "reconcile.json")
    with open(out, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({k: v for k, v in report.items() if k != "rows"},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
