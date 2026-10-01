"""Command-line entrypoint for the knowledge layer: sync, run-snapshots, status."""

from __future__ import annotations

import argparse
import json
import os
import sys

from .config import KnowledgeConfig
from .jobs import run_knowledge_command

DEFAULT_CONFIG = os.environ.get("RESEARCHKB_KNOWLEDGE_CONFIG", "config/knowledge.json")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="knowledge", description="Research KB knowledge layer")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("sync", "run-snapshots", "run-extracts", "rebuild-index",
                 "serve-kb", "status", "sample", "measure", "evidence-links"):
        child = sub.add_parser(name)
        child.add_argument("--config", default=DEFAULT_CONFIG)
        if name in ("run-snapshots", "run-extracts"):
            child.add_argument("--limit", type=int, default=None,
                               help="process at most N jobs in this run")
        if name == "rebuild-index":
            child.add_argument("--force", action="store_true",
                               help="rebuild even when the manifest is unchanged")
        if name == "evidence-links":
            child.add_argument("--source", required=True)
            child.add_argument("--doc-id", required=True)
            child.add_argument("--out", default=None,
                               help="write markdown fragment to this path")
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

    result = run_knowledge_command(config, args.command, limit=getattr(args, "limit", None))
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
        from .kbapi import build_kb_server, load_tokens
        from .store import KnowledgeStore

        kb = KnowledgeStore(config.knowledge_db)
        tokens = load_tokens(config.extra)
        server = build_kb_server(kb, tokens, config.kb_bind_host, config.kb_bind_port)
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
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main())
