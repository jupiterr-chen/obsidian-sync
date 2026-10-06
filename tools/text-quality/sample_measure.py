#!/usr/bin/env python3
"""TQ sample measurement harness (isolated; production run needs its own
authorization).

Selects the layered sample (docs/progress/TQ-SAMPLE-PLAN-20261006.md)
from a TQ0 inventory JSON and, for each selected item, re-extracts the
SNAPSHOT COPY in an isolated state directory: native engine first, page
routing second, local OCR only for pages the router demands. Reports
per-item page/OCR counts, wall time, and a damage-delta - never
touching production data or the live index.

Usage:
  python tools/text-quality/sample_measure.py \
      --inventory inventory.json --config config/knowledge.json \
      --state-dir <isolated> [--max-per-layer 2] [--json out.json]

No LLM calls, no network, no vault writes.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path[:0] = [os.path.join(ROOT, "app")]

NUMBER_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:%|％|亿|万|bn|mm)?")


def layers() -> list:
    return [
        ("L1_legacy_damaged", lambda d: (
            d.get("recommended_action") == "native-reextract-candidate"
            and (d.get("pages_damaged") or 0) > 0
            and str(d.get("engine") or "").startswith("stdlib-pdf")), 4),
        ("L2_legacy_clean", lambda d: (
            d.get("recommended_action") == "native-reextract-candidate"
            and not (d.get("pages_damaged") or 0)
            and str(d.get("engine") or "").startswith("stdlib-pdf")), 3),
        ("L3_unmet_ocr", lambda d: (
            (d.get("recorded_ocr_stats") or {}).get("unmet_ocr_pages")
            or 0) > 0, 3),
        ("L4_mixed", lambda d: (
            0 < (d.get("pages_damaged") or 0)
            < (d.get("pages_total") or 1)), 2),
        ("L5_normal_control", lambda d: (
            d.get("recommended_action") == "keep"), 2),
        ("L6_good_ocr", lambda d: (
            "rapidocr" in str(d.get("engine") or "")
            and d.get("status") == "ready"), 1),
        ("L7_missing_source", lambda d: (
            d.get("recommended_action") == "missing-source"), 1),
        ("L8_longest", lambda d: False, 1),  # filled separately
        ("L9_numbers", lambda d: False, 2),  # filled separately
    ]


def select_sample(inventory: dict, max_per_layer: int) -> list:
    docs = sorted(inventory["documents"],
                  key=lambda d: (d["source"], d["doc_id"]))
    picked = []
    used = set()

    def take(layer, predicate, count):
        taken = 0
        for doc in docs:
            if taken >= (count if max_per_layer <= 0 else
                         min(count, max_per_layer)):
                break
            key = (doc["source"], doc["doc_id"])
            if key in used or not predicate(doc):
                continue
            if not doc.get("source_available"):
                continue
            used.add(key)
            picked.append({"layer": layer, **doc})
            taken += 1

    for name, predicate, count in layers():
        if name in ("L8_longest", "L9_longest"):
            continue
        take(name, predicate, count)
    # L8: the longest available document
    available = [d for d in docs if d.get("source_available")
                 and (d["source"], d["doc_id"]) not in used]
    if available:
        longest = max(available, key=lambda d: d.get("pages_total") or 0)
        used.add((longest["source"], longest["doc_id"]))
        picked.append({"layer": "L8_longest", **longest})
    # L9: highest number density (proxy: most numeric blocks) - reported
    # as "selection needs block text access" when inventory lacks it;
    # fall back to the next unpicked damaged docs for manual pick
    for doc in available[:2]:
        if (doc["source"], doc["doc_id"]) in used:
            continue
        used.add((doc["source"], doc["doc_id"]))
        picked.append({"layer": "L9_numbers_manual_pick", **doc})
    return picked


def measure_item(item: dict, snapshot_root: str) -> dict:
    """Isolated native re-extraction of ONE item's snapshot copy."""
    from knowledge.extract import extract_pdf
    from knowledge.quality import damaged_reasons

    # locate the snapshot blob copy for the version (the inventory
    # carries the version's sha256; fall back to a name scan)
    sha = item.get("version_sha256") or item.get("_sha") or ""
    store = os.path.join(snapshot_root, "aa", sha)
    result = {"layer": item["layer"], "source": item["source"],
              "doc_id": item["doc_id"],
              "engine_before": item.get("engine"),
              "pages_before": item.get("pages_total"),
              "damaged_before": item.get("pages_damaged")}
    if sha and not os.path.isfile(store):
        found = None
        for root, _dirs, files in os.walk(snapshot_root):
            if sha in files:
                found = os.path.join(root, sha)
                break
        store = found or store
    if not os.path.isfile(store):
        result["status"] = "missing_snapshot"
        return result
    started = time.monotonic()
    try:
        with open(store, "rb") as handle:
            data = handle.read()
        # local OCR only, and only when actually installed; otherwise
        # the measurement honestly reports OCR as unavailable
        ocr = None
        ocr_note = "not_configured"
        try:
            from knowledge.ocr import OcrConfig, build_ocr_engine

            ocr = build_ocr_engine(OcrConfig(engine="local"))
            ocr_note = "local" if ocr is not None else \
                "unavailable_local_engine"
        except Exception as exc:
            ocr_note = "unavailable: %s" % type(exc).__name__
        outcome = extract_pdf(data, ocr=ocr)
        elapsed = time.monotonic() - started
        damaged_pages = sum(
            1 for block in outcome.blocks
            if damaged_reasons(block.text))
        numbers = sorted(set(NUMBER_RE.findall(
            "\n".join(b.text for b in outcome.blocks))))
        result.update({
            "status": "measured",
            "seconds": round(elapsed, 2),
            "engine_after": "%s@%s" % (outcome.parser_id,
                                       outcome.parser_version),
            "pages_after": outcome.stats.get("pages"),
            "ocr_engine": ocr_note,
            "ocr_candidate_pages": outcome.stats.get("ocr_candidate_pages"),
            "ocr_applied_pages": outcome.stats.get("ocr_applied_pages"),
            "damaged_pages_after": damaged_pages,
            "extraction_status": outcome.status,
            "numbers_sample": numbers[:20],
        })
    except Exception as exc:
        result["status"] = "error: %s: %s" % (type(exc).__name__, exc)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(prog="sample_measure")
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--snapshot-root", required=True,
                        help="ISOLATED copy of state/snapshots - never"
                             " the production tree")
    parser.add_argument("--max-per-layer", type=int, default=2,
                        help="0 = taskbook defaults per layer")
    parser.add_argument("--json", default=None)
    args = parser.parse_args()

    with open(args.inventory, "r", encoding="utf-8") as handle:
        inventory = json.load(handle)
    sample = select_sample(inventory, args.max_per_layer)
    report = {
        "kind": "tq-sample-measurement",
        "inventory_manifest": inventory.get("manifest_hash"),
        "isolated": True,
        "sample_size": len(sample),
        "items": [measure_item(item, args.snapshot_root)
                  for item in sample],
        "note": "isolated measurement only; production batches need"
                " explicit authorization; unknown fields are reported"
                " as unknown, not estimated",
    }
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json:
        with open(args.json, "w", encoding="utf-8", newline="\n") as h:
            h.write(payload + "\n")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
