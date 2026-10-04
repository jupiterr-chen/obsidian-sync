#!/usr/bin/env python3
"""Operations status snapshot (E): backlog, failures, retries, cost, cycles.

Read-only aggregation over the knowledge DB + worker state + first-layer
catalog health. Output: a single JSON snapshot suitable for a status page
or alerting feed. No secrets, no paths beyond configured roots.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "app"))

from knowledge.config import KnowledgeConfig  # noqa: E402


def snapshot(config: KnowledgeConfig) -> dict:
    uri = "file:%s?mode=ro" % os.path.abspath(config.knowledge_db).replace("\\", "/")
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    report: dict = {"kind": "knowledge-ops-status"}
    try:
        report["jobs"] = {r["stage"] + ":" + r["status"]: r["c"] for r in conn.execute(
            "SELECT stage, status, COUNT(*) c FROM jobs GROUP BY stage, status")}
        report["documents"] = conn.execute(
            "SELECT COUNT(*) c FROM kb_versions WHERE is_current=1").fetchone()["c"]
        ready = conn.execute(
            "SELECT COUNT(*) c FROM extractions e WHERE e.status='ready' AND"
            " e.rowid IN (SELECT MAX(rowid) FROM extractions GROUP BY"
            " source, doc_id, version_id)").fetchone()["c"]
        report["extractions_ready"] = ready
        report["publish_outbox"] = {r["status"]: r["c"] for r in conn.execute(
            "SELECT status, COUNT(*) c FROM publish_outbox GROUP BY status")}
        report["impact_outbox"] = {r["status"]: r["c"] for r in conn.execute(
            "SELECT status, COUNT(*) c FROM impact_outbox GROUP BY status")}
        report["analysis_tasks"] = {r["status"]: r["c"] for r in conn.execute(
            "SELECT status, COUNT(*) c FROM analysis_tasks GROUP BY status")}
        report["usage_totals"] = {
            "input_tokens": conn.execute(
                "SELECT COALESCE(SUM(input_tokens),0) c FROM usage_events"
            ).fetchone()["c"],
            "output_tokens": conn.execute(
                "SELECT COALESCE(SUM(output_tokens),0) c FROM usage_events"
            ).fetchone()["c"],
            "calls": conn.execute(
                "SELECT COUNT(*) c FROM usage_events").fetchone()["c"],
        }
        report["failed_extractions_24h"] = conn.execute(
            "SELECT COUNT(*) c FROM jobs WHERE stage='extract' AND"
            " status='failed' AND updated_at >= datetime('now','-1 day')"
        ).fetchone()["c"]
        report["sync_runs"] = {str(r["ok"]): r["c"] for r in conn.execute(
            "SELECT ok, COUNT(*) c FROM sync_runs GROUP BY ok")}
        gen = conn.execute(
            "SELECT generation_id, status, activated_at FROM"
            " index_generations WHERE status='active'").fetchone()
        report["index"] = dict(gen) if gen else None
    finally:
        conn.close()

    # worker heartbeat freshness
    from knowledge.worker import worker_is_stale, worker_state_path

    state_path = worker_state_path(config.knowledge_db)
    report["worker_state_found"] = os.path.isfile(state_path)
    if report["worker_state_found"]:
        stale = worker_is_stale(state_path, max_age_seconds=3 * 3600 + 300)
        report["worker_heartbeat"] = "stale" if stale else "fresh"
    else:
        report["worker_heartbeat"] = "absent"

    # first-layer catalog reachable?
    try:
        catalog_uri = "file:%s?mode=ro" % os.path.abspath(
            config.catalog_db).replace("\\", "/")
        cat = sqlite3.connect(catalog_uri, uri=True)
        report["first_layer_documents"] = cat.execute(
            "SELECT COUNT(*) FROM documents").fetchone()[0]
        cat.close()
        report["first_layer_reachable"] = True
    except Exception:
        report["first_layer_reachable"] = False
    return report


def main() -> int:
    parser = argparse.ArgumentParser(prog="ops_status")
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    config = KnowledgeConfig.load(args.config).resolve(
        os.path.dirname(os.path.abspath(args.config)))
    report = snapshot(config)
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
