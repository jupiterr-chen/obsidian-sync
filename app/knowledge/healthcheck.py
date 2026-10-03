"""Container healthcheck entrypoints (no inline python -c quoting).

Usage: python -m knowledge.healthcheck worker|api
"""

from __future__ import annotations

import sys


def main() -> int:
    if len(sys.argv) < 2:
        return 2
    target = sys.argv[1]
    if target == "worker":
        from .worker import worker_is_stale

        state = "/state/knowledge-worker.json"
        fresh = worker_is_stale(state, max_age_seconds=300)
        # fresh is False -> healthy heartbeat; True -> stale; None -> no
        # state file yet (container just started) -> healthy
        return 0 if fresh is not True else 1
    if target == "api":
        import json
        import urllib.request

        with urllib.request.urlopen(
                "http://127.0.0.1:8766/api/kb/v1/health", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return 0 if payload.get("status") == "ok" else 1
    if target == "library":
        import urllib.request

        urllib.request.urlopen("http://127.0.0.1:8765/healthz",
                               timeout=5).read()
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
