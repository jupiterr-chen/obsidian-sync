"""Command-line entrypoint for the knowledge layer: sync, run-snapshots, status."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from .config import KnowledgeConfig
from .jobs import run_knowledge_command

DEFAULT_CONFIG = os.environ.get("RESEARCHKB_KNOWLEDGE_CONFIG", "config/knowledge.json")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="knowledge", description="Research KB knowledge layer")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("sync", "run-snapshots", "run-extracts", "rebuild-index",
                 "serve-kb", "worker", "status", "sample", "measure",
                 "evidence-links", "export-analysis", "repair-queue",
                 "publish-reading", "ops-status", "quality-inventory",
                 "reprocess", "governance-plan"):
        child = sub.add_parser(name)
        child.add_argument("--config", default=DEFAULT_CONFIG)
        if name in ("run-snapshots", "run-extracts"):
            child.add_argument("--limit", type=int, default=None,
                               help="process at most N jobs in this run")
        if name == "worker":
            child.add_argument("--interval", type=int, default=3600)
            child.add_argument("--once", action="store_true",
                               help="run a single cycle and exit")
        if name == "rebuild-index":
            child.add_argument("--force", action="store_true",
                               help="rebuild even when the manifest is unchanged")
        if name == "repair-queue":
            child.add_argument("--max", type=int, default=25,
                               help="bounded repair queue size (A2)")
            child.add_argument("--register", action="store_true",
                               help="register extract jobs for the queue")
        if name == "publish-reading":
            child.add_argument("--vault-dir", required=True,
                               help="vault root containing 解析正文/")
            child.add_argument("--limit", type=int, default=200,
                               help="consume at most N pending publishes")
        if name == "governance-plan":
            child.add_argument("--reading-dir", required=True,
                               help="the vault 解析正文/ directory")
            child.add_argument("--out", default=None)
        if name == "reprocess":
            child.add_argument("--batch-id", required=True,
                               help="explicit audit id for this batch")
            child.add_argument("--max", type=int, default=20,
                               help="bounded batch size")
            child.add_argument("--actions", default=None,
                               help="comma-separated recommended actions"
                                    " (default native-reextract,ocr)")
            child.add_argument("--dry-run", action="store_true",
                               help="list the selection without"
                                    " registering anything")
        if name == "quality-inventory":
            child.add_argument("--out", default=None,
                               help="write the full inventory JSON here")
            child.add_argument("--reading-dir", default=None,
                               help="hash vault reading files (解析正文/)")
            child.add_argument("--include-history", action="store_true",
                               help="count historical versions separately")
        if name == "ops-status":
            child.add_argument("--hours", type=int, default=24,
                               help="failure window (E)")
        if name == "evidence-links":
            child.add_argument("--source", required=True)
            child.add_argument("--doc-id", required=True)
            child.add_argument("--out", default=None,
                               help="write markdown fragment to this path")
        if name == "export-analysis":
            child.add_argument("--run-id", default=None)
            child.add_argument("--limit", type=int, default=10)
            child.add_argument("--out", default=None,
                               help="override the configured writeback dir")
        if name in ("sample", "measure"):
            child.add_argument("--out", required=True,
                               help="write the JSON result to this path")
            child.add_argument("--total", type=int, default=30)
            child.add_argument("--tune", type=int, default=20)
            child.add_argument("--blind", type=int, default=10)
            child.add_argument("--seed", type=int, default=20261001)
        if name == "measure":
            child.add_argument("--manifest", required=True,
                               help="sample manifest produced by 'sample'")
            child.add_argument("--token-counter", default="heuristic")
    args = parser.parse_args(argv)

    base = os.path.dirname(os.path.abspath(args.config))
    config = KnowledgeConfig.load(args.config).resolve(base)
    if args.command == "sample":
        from .sampling import select_sample

        from .store import KnowledgeStore

        kb = KnowledgeStore(config.knowledge_db)
        try:
            plan = select_sample(kb, total=args.total, tune=args.tune,
                                 blind=args.blind, seed=args.seed)
            manifest = plan.to_manifest()
        finally:
            kb.close()
        with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        print(json.dumps({"ok": True, "out": args.out,
                          "total": manifest["actual"]["total"],
                          "warnings": manifest["warnings"]}, ensure_ascii=False))
        return 0
    if args.command == "measure":
        from .measure import measure_sample
        from .snapshot import SnapshotStore
        from .store import KnowledgeStore

        with open(args.manifest, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        kb = KnowledgeStore(config.knowledge_db)
        try:
            blobs = SnapshotStore(config.snapshot_root)
            report = measure_sample(kb, blobs, manifest,
                                    counter_name=args.token_counter)
        finally:
            kb.close()
        with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        summary = report["summary"]
        print(json.dumps({"ok": True, "out": args.out, "summary": summary},
                         ensure_ascii=False))
        return 0

    if args.command == "worker":
        from library.config import Config
        from .store import KnowledgeStore
        from .worker import (KnowledgeWorker, resolve_analysis_runtime,
                             run_cycle)

        library_config = Config.load(config.library_config).resolve(
            os.path.dirname(os.path.abspath(config.library_config)))
        if args.once:
            # R3: the provider runtime comes from the config through the
            # same explicit-off resolver the long-running worker uses
            runtime_kb = KnowledgeStore(config.knowledge_db)
            try:
                chat, ledger, settings = resolve_analysis_runtime(
                    config, kb=runtime_kb)
            except Exception:
                runtime_kb.close()
                raise
            try:
                result = run_cycle(
                    config, library_config, chat=chat, ledger=ledger,
                    analysis_prompt_version=str(
                        settings.get("prompt_version", "pv1")),
                    analysis_limit=int(settings.get(
                        "max_tasks_per_cycle", 5)),
                    analysis_scope=settings.get("scope"))
            finally:
                runtime_kb.close()
            print(json.dumps(result, ensure_ascii=False, indent=2,
                             default=str))
            return 0 if result.get("ok") else 1
        worker = KnowledgeWorker(config, library_config,
                                 interval_seconds=args.interval)
        worker.start()
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            worker.stop()
        return 0

    if args.command == "repair-queue":
        from knowledge.repair import build_repair_queue, register_repair_jobs
        from knowledge.extract import extract_config_digest
        from knowledge.store import KnowledgeStore

        kb = KnowledgeStore(config.knowledge_db)
        try:
            if getattr(args, "register", False):
                result = register_repair_jobs(
                    kb, extract_config_digest(
                        config.ocr_config(),
                        config.extra.get("providers") or {}),
                    max_items=getattr(args, "max", 25))
            else:
                queue = build_repair_queue(
                    kb, max_items=getattr(args, "max", 25))
                result = {"queue_size": len(queue), "items": [
                    {"source": i["source"], "doc_id": i["doc_id"],
                     "version_id": i["version_id"],
                     "extraction_status": i["extraction_status"],
                     "readable_blocks": i["readable"]} for i in queue]}
        finally:
            kb.close()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "publish-reading":
        from .reading import ReadingPublisher
        from .store import KnowledgeStore

        kb = KnowledgeStore(config.knowledge_db)
        try:
            publisher = ReadingPublisher(
                kb, args.vault_dir,
                base_url=(config.extra.get("public_base_url")
                          or "http://192.168.1.150:8765"))
            result = publisher.consume(limit=args.limit)
        finally:
            kb.close()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("published", 0) >= 0 else 1
    if args.command == "governance-plan":
        from knowledge.governance import plan_file_governance
        from knowledge.readonly import ReadOnlyStoreError, open_read_only

        try:
            ro = open_read_only(config.knowledge_db)
        except ReadOnlyStoreError as exc:
            print(json.dumps({"ok": False, "error": str(exc)},
                             ensure_ascii=False))
            return 2
        try:
            plan = plan_file_governance(ro, args.reading_dir)
        finally:
            ro.close()
        payload = json.dumps(plan, ensure_ascii=False, indent=2)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.write(chr(10))
        print(payload)
        return 0
    if args.command == "reprocess":
        from knowledge.repair import (register_reprocess_batch,
                                      select_reprocess_items)
        from knowledge.text_quality import build_inventory
        from knowledge.readonly import ReadOnlyStoreError, open_read_only

        # S4: both the dry-run preview and the selection scan are truly
        # read-only - a pre-flight command must never initialize or
        # migrate the database it inspects
        try:
            ro = open_read_only(config.knowledge_db)
        except ReadOnlyStoreError as exc:
            print(json.dumps({"ok": False, "error": str(exc)},
                             ensure_ascii=False))
            return 2
        try:
            if args.dry_run:
                inventory = build_inventory(ro)
                actions = [a.strip() for a in args.actions.split(",")] \
                    if args.actions else None
                items = select_reprocess_items(
                    inventory, actions=actions, max_items=args.max)
                result = {"batch_id": args.batch_id, "dry_run": True,
                          "selected": [
                              {"source": i["source"], "doc_id": i["doc_id"],
                               "engine": i.get("engine"),
                               "recommended_action":
                                   i.get("recommended_action")}
                              for i in items]}
            else:
                # registration writes: run on the writable store, but the
                # selection still comes from the read-only scan above
                inventory = build_inventory(ro)
                actions = [a.strip() for a in args.actions.split(",")] \
                    if args.actions else None
                items = select_reprocess_items(
                    inventory, actions=actions, max_items=args.max)
                ro.close()
                from knowledge.extract import extract_config_digest
                from knowledge.store import KnowledgeStore

                digest = extract_config_digest(
                    config.ocr_config(), config.extra or {})
                kb = KnowledgeStore(config.knowledge_db)
                try:
                    result = register_reprocess_batch(
                        kb, digest, items, args.batch_id)
                finally:
                    kb.close()
                result["note"] = ("jobs run with the normal worker"
                                  " cycle; old extractions/evidence stay"
                                  " intact")
        finally:
            ro.close()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "quality-inventory":
        from .readonly import ReadOnlyStoreError, open_read_only
        from .text_quality import build_inventory, inventory_summary

        # S4/TA06: strictly read-only - an advertised audit command must
        # never initialize, migrate or journal the database it inspects
        try:
            ro = open_read_only(config.knowledge_db)
        except ReadOnlyStoreError as exc:
            print(json.dumps({"ok": False, "error": str(exc)},
                             ensure_ascii=False))
            return 2
        try:
            reading_dir = args.reading_dir or (
                (config.extra or {}).get("vault_dir")
                and os.path.join((config.extra or {}).get("vault_dir"),
                                 "解析正文"))
            inventory = build_inventory(
                ro, reading_dir=reading_dir,
                include_history=bool(args.include_history),
                snapshot_root=config.snapshot_root)
        finally:
            ro.close()
        payload = json.dumps(inventory, ensure_ascii=False, indent=2)
        if args.out:
            with open(args.out, "w", encoding="utf-8",
                      newline="\n") as handle:
                handle.write(payload)
                handle.write("\n")
        print(inventory_summary(inventory))
        print(json.dumps({"full_inventory": args.out or "not written"},
                         ensure_ascii=False))
        return 0
    if args.command == "ops-status":
        from .store import KnowledgeStore
        import sqlite3

        kb = KnowledgeStore(config.knowledge_db)
        try:
            def q(sql, params=()):
                return kb._conn.execute(sql, params).fetchall()

            jobs = q("SELECT stage, status, COUNT(*) c FROM jobs"
                     " GROUP BY stage, status ORDER BY stage, status")
            window = "%d hours" % args.hours
            failed = q("SELECT stage, COUNT(*) c FROM jobs"
                       " WHERE status='failed' AND updated_at >="
                       " datetime('now', ?) GROUP BY stage",
                       ('-%d hours' % args.hours,))
            outboxes = {}
            for table in ("publish_outbox", "impact_outbox",
                          "summary_outbox"):
                try:
                    row = q("SELECT status, COUNT(*) c FROM %s"
                            " GROUP BY status" % table)
                    outboxes[table] = {r["status"]: r["c"] for r in row}
                except sqlite3.OperationalError:
                    outboxes[table] = "missing"
            gen = q("SELECT generation_id, status, activated_at FROM"
                    " index_generations WHERE status='active'"
                    " ORDER BY created_at DESC LIMIT 1")
            result = {"ok": True, "window": window,
                      "jobs": [{"stage": r["stage"], "status": r["status"],
                                "count": r["c"]} for r in jobs],
                      "failed_window": [{"stage": r["stage"],
                                         "count": r["c"]} for r in failed],
                      "outboxes": outboxes,
                      "active_generation": dict(gen[0]) if gen else None}
        finally:
            kb.close()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "rebuild-index":
        from .indexing import build_generation
        from .store import KnowledgeStore

        kb = KnowledgeStore(config.knowledge_db)
        try:
            result = build_generation(kb, force=getattr(args, "force", False))
        finally:
            kb.close()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1
    if args.command == "export-analysis":
        from .store import KnowledgeStore
        from .writeback import export_analysis_runs

        directory = args.out or ((config.extra.get("writeback") or {}).get(
            "analysis_dir"))
        if not directory:
            print(json.dumps({"ok": False,
                              "error": "no writeback.analysis_dir configured "
                                       "and no --out given"}))
            return 1
        kb = KnowledgeStore(config.knowledge_db)
        try:
            result = export_analysis_runs(kb, directory,
                                          run_id=args.run_id,
                                          limit=args.limit)
        finally:
            kb.close()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("count", 0) else 1
    if args.command == "evidence-links":
        from .cards import evidence_links_for_document, render_evidence_index_markdown
        from .store import KnowledgeStore

        kb = KnowledgeStore(config.knowledge_db)
        try:
            links = evidence_links_for_document(kb, args.source, args.doc_id)
        finally:
            kb.close()
        if args.out:
            with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(render_evidence_index_markdown(links))
        print(json.dumps(links, ensure_ascii=False, indent=2))
        return 0
    if args.command == "serve-kb":
        from .budget import load_budget
        from .kbapi import build_kb_server, load_tokens
        from .providers import OpenAICompatibleVision, load_providers
        from .store import KnowledgeStore

        kb = KnowledgeStore(config.knowledge_db)
        tokens = load_tokens(config.extra)
        providers = load_providers(config.extra)
        # Explicit role binding (R03): a vision model never impersonates chat
        chat = providers.get("chat")
        if isinstance(chat, OpenAICompatibleVision):
            chat = None
        embedder = providers.get("embedding")
        vision = providers.get("vision_ocr")
        budget = load_budget(config.extra)  # top-level first, legacy nested
        # F0-5: pass the CONFIGURED snapshot root into the API so fixed
        # snapshot serving works from any cwd (the migration hit this:
        # the default fell back to a cwd-relative path and 404'd)
        server = build_kb_server(kb, tokens, config.kb_bind_host,
                                 config.kb_bind_port,
                                 embedder=embedder, chat=chat, budget=budget,
                                 vision=vision,
                                 snapshot_root=config.snapshot_root)
        print("knowledge api serving on http://%s:%d/api/kb/v1"
              % (config.kb_bind_host, config.kb_bind_port), flush=True)
        try:
            server.serve_forever(poll_interval=1)
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
            kb.close()
        return 0

    result = run_knowledge_command(config, args.command, limit=getattr(args, "limit", None))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main())
