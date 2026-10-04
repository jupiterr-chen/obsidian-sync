#!/usr/bin/env python3
"""Reference client for the investment-framework background package (docs/25 D).

Fetches POST /api/kb/v1/background-package for a company (by symbol) or a
topic (by title keyword) and persists the decision-context bundle so a
later replay can find the exact evidence a decision was based on:

  schema researchkb.decision-context/1
    query          - entity type/id plus filters actually sent
    as_of_semantics- "system" (what the KB believed at fetch time) or
                     "published" (only evidence public at the as_of date;
                     requires V03-bound public times)
    generation     - active search-index generation id
    package        - sources with extraction status, claims with
                     revisions, risks/counter-evidence, missing-information
    result_digest  - sha256 over the canonical package json; the server
                     recomputes this on replay so a changed knowledge base
                     is detectable

The bundle is the persisted decision record; later knowledge updates do
not rewrite it, and replaying an old digest against today's KB shows what
changed since the decision.

Usage:
  python scripts/kb-background-client.py --base http://127.0.0.1:8766 \
      --token "$RESEARCHKB_KB_TOKEN" --company 600519 \
      --save decisions/600519-20261001.json
"""

from __future__ import annotations

import argparse
import datetime
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
        with urllib.request.urlopen(req, timeout=60) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def canonical_digest(package: dict) -> str:
    """Recompute the server's digest: sha256 over the package WITHOUT
    result_digest, dumped with sort_keys and default separators - must
    stay byte-identical to knowledge.background.build_background_package."""
    body = {k: v for k, v in package.items() if k != "result_digest"}
    blob = json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="kb-background-client")
    parser.add_argument("--base", required=True,
                        help="knowledge API base, e.g. http://127.0.0.1:8766")
    parser.add_argument("--token", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--company", help="company symbol, e.g. 600519")
    group.add_argument("--topic", help="topic keyword matched against titles")
    parser.add_argument("--as-of", default=None,
                        help="as-of date YYYY-MM-DD (published mode needs"
                             " V03-bound public times)")
    parser.add_argument("--as-of-mode", default="system",
                        choices=("system", "published"))
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--save", default=None,
                        help="persist the decision-context bundle here")
    args = parser.parse_args(argv)

    entity_type = "company" if args.company else "topic"
    entity_id = args.company or args.topic
    filters: dict = {"as_of_mode": args.as_of_mode}
    if args.as_of:
        filters["as_of"] = args.as_of

    status, package = request(
        args.base, "/api/kb/v1/background-package", args.token,
        method="POST",
        body={"entity_type": entity_type, "entity_id": entity_id,
              "filters": filters, "limit": args.limit})
    if status != 200:
        print(json.dumps({"error": package, "status": status},
                         ensure_ascii=False, indent=2))
        return 1

    client_digest = canonical_digest(package)
    server_digest = package.get("result_digest")
    mismatch = (server_digest is not None
                and server_digest != client_digest)

    bundle = {
        "schema": "researchkb.decision-context/1",
        "fetched_at_utc": datetime.datetime.now(
            datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        "query": {"entity_type": entity_type, "entity_id": entity_id},
        "filters": filters,
        "base_url": args.base,
        "generation": package.get("generation"),
        "as_of_semantics": args.as_of_mode,
        "package": package,
        "result_digest_client": client_digest,
    }
    if mismatch:
        bundle["result_digest_mismatch"] = {
            "server": server_digest, "client": client_digest}

    text = json.dumps(bundle, ensure_ascii=False, indent=2) + "\n"
    if args.save:
        import os

        directory = os.path.dirname(os.path.abspath(args.save))
        os.makedirs(directory, exist_ok=True)
        with open(args.save, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    print(text)
    if mismatch:
        print("WARNING: server result_digest does not match the client-side"
              " digest of the received package", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
