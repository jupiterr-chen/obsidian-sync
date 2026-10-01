"""Safe write-back into generated areas (P5-03, docs/05).

Rules (A15): writes only into explicitly registered directories; a file is
overwritten only when its content hash still equals the last hash this
module itself wrote; any human edit or sync conflict stops the overwrite
and preserves the original plus a timestamped candidate file. Sync-conflict
files are never touched or deleted.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from typing import Any, Dict, Optional

from .store import KnowledgeStore, utc_now

MANIFEST_NAME = ".knowledge-writeback.json"
CONFLICT_MARKERS = ("sync-conflict", "conflicted copy")


class WriteBackError(Exception):
    pass


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_manifest(directory: str) -> Dict[str, Any]:
    path = os.path.join(directory, MANIFEST_NAME)
    if not os.path.isfile(path):
        return {"files": {}}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (ValueError, OSError):
        return {"files": {}}


def _save_manifest(directory: str, manifest: Dict[str, Any]) -> None:
    path = os.path.join(directory, MANIFEST_NAME)
    fd, tmp = tempfile.mkstemp(prefix=".manifest-", dir=directory)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(tmp, path)


def write_candidate(directory: str, name: str, content: str,
                    owner: str = "knowledge") -> Dict[str, Any]:
    """Write or refresh one generated file under a registered directory.

    Returns the outcome: written | unchanged | preserved_with_candidate.
    """
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise WriteBackError("invalid candidate name %r" % name)
    if any(marker in name.lower() for marker in CONFLICT_MARKERS):
        raise WriteBackError("refusing to touch conflict-marked files")
    os.makedirs(directory, exist_ok=True)
    target = os.path.join(directory, name)
    manifest = _load_manifest(directory)
    recorded = manifest["files"].get(name, {})
    new_hash = _sha256_text(content)

    if os.path.exists(target):
        with open(target, "r", encoding="utf-8") as handle:
            current = handle.read()
        current_hash = _sha256_text(current)
        if current_hash == new_hash:
            return {"outcome": "unchanged", "path": target}
        if recorded.get("last_hash") != current_hash:
            # human edit or unknown change since our last write: never overwrite
            stamp = utc_now().replace(":", "").replace("-", "")[:15]
            candidate = os.path.join(
                directory, "%s.candidate-%s.md" % (os.path.splitext(name)[0], stamp))
            with open(candidate, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
            return {"outcome": "preserved_with_candidate", "path": target,
                    "candidate_path": candidate}
    # safe to write: absent, or still exactly our last content
    fd, tmp = tempfile.mkstemp(prefix=".cand-", dir=directory)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    os.replace(tmp, target)
    manifest["files"][name] = {"last_hash": new_hash, "owner": owner,
                               "written_at": utc_now()}
    _save_manifest(directory, manifest)
    return {"outcome": "written", "path": target}


def render_claim_candidate(claim: Dict[str, Any],
                           evidence_texts: Optional[Dict[str, str]] = None
                           ) -> str:
    """Markdown candidate for one claim (pending-review marked)."""
    lines = [
        "# 研究候选：%s" % (claim.get("subject") or "未分类主题"),
        "",
        "- **状态**：%s（待审核）" % claim["status"],
        "- **claim**：`%s` rev %d" % (claim["claim_id"], claim["current_revision"]),
        "- **作者/版本**：%s / %s" % (claim.get("author"), claim.get("prompt_version")),
        "- **生成时间**：%s" % utc_now(),
        "",
        "## 陈述",
        "",
        claim["statement"],
        "",
        "## 证据",
        "",
    ]
    for ref in claim.get("evidence") or []:
        block_id = ref.get("block_id", "?")
        text = (evidence_texts or {}).get(block_id, "")
        lines.append("- `%s`（%s/%s@%s）" % (block_id, ref.get("source"),
                                            ref.get("doc_id"), ref.get("version_id")))
        if text:
            lines.append("  > %s" % text[:160].replace("\n", " "))
    counter = claim.get("counterevidence") or []
    if counter:
        lines += ["", "## 反证", ""]
        for ref in counter:
            lines.append("- `%s`（%s/%s@%s）" % (ref.get("block_id", "?"),
                                                ref.get("source"),
                                                ref.get("doc_id"),
                                                ref.get("version_id")))
    lines += ["", "> 本文件由知识服务生成，处于待审核状态；人工编辑后不会被覆盖"
              "（下次生成会另存候选文件）。", ""]
    return "\n".join(lines)


def export_claim_candidates(kb: KnowledgeStore, directory: str,
                            status: str = "accepted",
                            owner: str = "knowledge") -> Dict[str, Any]:
    """Render and safely write candidates for all claims with a status."""
    results = []
    evidence_texts: Dict[str, str] = {}
    for claim in kb.list_claims(status=status):
        for ref in claim.get("evidence") or []:
            block_id = ref.get("block_id")
            if block_id and block_id not in evidence_texts:
                row = kb.get_block_with_identity(block_id)
                evidence_texts[block_id] = row["text"] if row else ""
        name = "%s.md" % claim["claim_id"]
        results.append(write_candidate(
            directory, name, render_claim_candidate(claim, evidence_texts),
            owner=owner))
    outcomes = {r["outcome"] for r in results}
    return {"count": len(results), "outcomes": sorted(outcomes), "results": results}
