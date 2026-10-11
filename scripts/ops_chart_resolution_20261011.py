#!/usr/bin/env python3
"""Read-only B3-1 chart proposal diagnostics and bounded review-plan builder."""
from __future__ import annotations
import argparse
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT/"app") not in sys.path:sys.path.insert(0,str(ROOT/"app"))
from knowledge.chart_resolution import discover_inputs,read_json,run_audit

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--operation",type=Path,required=True,help="private GLM chart operation root")
    p.add_argument("--candidates",type=Path,help="frozen chart-batch-candidates/1 manifest (default: operation/frozen/candidates.json)")
    p.add_argument("--db",type=Path,required=True)
    p.add_argument("--snapshot-root",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True,help="private output directory, outside DB and snapshot root")
    p.add_argument("--visual-review",type=Path,help="optional accepted visual-review-v2.json to avoid repeating the same items")
    a=p.parse_args(argv)
    try:
        op=a.operation.resolve(strict=True);candidate=a.candidates or op/"frozen/candidates.json"
        reports=discover_inputs(op)
        result=run_audit(a.db,a.snapshot_root,candidate,reports,op,a.out,a.visual_review)
        print(__import__("json").dumps({"stage":"complete","candidate_count":result["candidate_count"],"dual_valid":result["dual_valid"],"proposal_status_counts":result["proposal_status_counts"],"activation_allowed":False},sort_keys=True))
        return 0
    except Exception as exc:
        print("chart resolution audit blocked: %s"%type(exc).__name__,file=sys.stderr);return 2

if __name__=="__main__":raise SystemExit(main())
