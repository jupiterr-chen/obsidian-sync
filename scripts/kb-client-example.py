#!/usr/bin/env python3
"""Reference client for the knowledge API (P6-03, docs/05 integration).

Demonstrates the universal integration-context list every consuming app
must persist with its result so a later replay can find the same evidence:
purpose, query, filters, as_of_mode, generation_id, evidence_refs,
claim_revisions, result_digest.

Usage:
  python scripts/kb-client-example.py --base http://127.0.0.1:8766 \
      --token "$RESEARCHKB_KB_TOKEN" --query "毛利率" [--symbol EXAMPLE]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request


def request(base: str, path: str, token: str, method: str = "GET",
            body: dict | None = None) -> tuple[int, dict]:
    url = base.rstrip("/") + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "Bearer %s" % token)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="kb-client-example")
    parser.add_argument("--base", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--mode", default="keyword",
                        choices=("keyword", "hybrid"))
    args = parser.parse_args(argv)

    filters: dict = {"collections": ["source_documents"]}
    if args.symbol:
        filters["symbols"] = [args.symbol]

    status, payload = request(args.base, "/api/kb/v1/search", args.token,
                              method="POST",
                              body={"query": args.query, "mode": args.mode,
                                    "filters": filters, "limit": 10})
    if status != 200:
        print(json.dumps({"error": payload, "status": status},
                         ensure_ascii=False, indent=2))
        return 1

    context = {
        "purpose": "research-reference",
        "query": args.query,
        "filters": filters,
        "as_of_mode": filters.get("as_of_mode", "system"),
        "generation_id": payload["generation_id"],
        "evidence_refs": [
            {"block_id": h["block_id"], "extraction_id": h["extraction_id"],
             "source_version": h["source_version"], "source": h["source"],
             "doc_id": h["doc_id"]}
            for h in payload["hits"]
        ],
        "claim_revisions": [],  # filled when memory endpoints are consumed
        "result_digest": None,
    }
    canonical = json.dumps(context, ensure_ascii=False, sort_keys=True)
    context["result_digest"] = "sha256:" + hashlib.sha256(
        canonical.encode("utf-8")).hexdigest()

    print(json.dumps({
        "request_id": payload["request_id"],
        "hits": len(payload["hits"]),
        "integration_context": context,
        "first_hit": payload["hits"][0] if payload["hits"] else None,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
