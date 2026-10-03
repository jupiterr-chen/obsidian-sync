"""Safe write-back into generated areas (P5-03, docs/05).

Rules (A15, R10): writes only into explicitly REGISTERED directories; a
file is overwritten only when its content hash still equals the last hash
this module itself wrote (re-checked immediately before the atomic
replace); any human edit or sync conflict stops the overwrite and
preserves the original plus a UNIQUE append-only candidate file.
Candidates use exclusive creation with random identity - same-second
exports never collide and previously written candidates are never
modified. Sync-conflict files are never touched or deleted.

Ownership limits (documented, per the remediation taskbook): external
editors and Syncthing do not obey our locks, so the hash re-check narrows
- but cannot fully close - the read/replace race; the manifest itself is
guarded by a per-directory advisory file lock for multi-process writers.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
from typing import Any, Dict, Optional

from library.locking import FileLock

from .store import KnowledgeStore, utc_now

MANIFEST_NAME = ".knowledge-writeback.json"
MANIFEST_LOCK = ".knowledge-writeback.lock"
CONFLICT_MARKERS = ("sync-conflict", "conflicted copy")

_WRITE_ROOTS: set = set()


class WriteBackError(Exception):
    pass


def register_write_root(path: str) -> None:
    """Whitelist a directory tree that generated output may live in."""
    _WRITE_ROOTS.add(os.path.realpath(path))


def _require_registered_root(directory: str) -> None:
    real = os.path.realpath(directory)
    for root in _WRITE_ROOTS:
        if real == root or real.startswith(root + os.sep):
            return
    raise WriteBackError(
        "write target %r is not a registered write root" % directory)


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


def _exclusive_create(path: str, content: str) -> bool:
    """Create a new file exclusively; False when it already exists."""
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    return True


def _content_identity(directory: str, name: str, content: str) -> str:
    """T07: stable identity for a candidate = target name + content hash.

    Random suffixes made every export of the SAME content a new file; the
    identity is deterministic so repeat deliveries are recognized and
    published exactly once (manifest-tracked)."""
    return "%s.%s" % (name, _sha256_text(content)[:16])


def _candidate_for_identity(directory: str, identity: str) -> Optional[str]:
    manifest = _load_manifest(directory)
    entry = manifest.get("candidates", {}).get(identity)
    return entry if entry and os.path.isfile(entry) else None


def _unique_candidate(directory: str, name: str, content: str) -> str:
    """R10/T07: append-only candidate with DETERMINISTIC identity (name +
    content hash): identical content re-delivered finds its existing file
    (idempotent, no new copy); genuinely new content gets a fresh file
    stamped with the publish time. No candidate is ever overwritten."""
    identity = _content_identity(directory, name, content)
    existing = _candidate_for_identity(directory, identity)
    if existing is not None:
        return existing  # same content already published exactly once
    base = os.path.splitext(name)[0]
    stamp = utc_now().replace(":", "").replace("-", "")[:15]
    while True:
        candidate = os.path.join(
            directory, "%s.candidate-%s-%s.md"
            % (base, stamp, secrets.token_hex(4)))
        if _exclusive_create(candidate, content):
            manifest = _load_manifest(directory)
            manifest.setdefault("candidates", {})[identity] = candidate
            _save_manifest(directory, manifest)
            return candidate


def write_candidate(directory: str, name: str, content: str,
                    owner: str = "knowledge") -> Dict[str, Any]:
    """Write or refresh one generated file under a registered directory.

    Returns the outcome: written | unchanged | preserved_with_candidate.
    """
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise WriteBackError("invalid candidate name %r" % name)
    if any(marker in name.lower() for marker in CONFLICT_MARKERS):
        raise WriteBackError("refusing to touch conflict-marked files")
    _require_registered_root(directory)
    os.makedirs(directory, exist_ok=True)
    target = os.path.join(directory, name)
    lock = FileLock(os.path.join(directory, MANIFEST_LOCK))
    if not lock.acquire(blocking=True, timeout=10):
        raise WriteBackError("manifest lock busy in %r" % directory)
    try:
        manifest = _load_manifest(directory)
        recorded = manifest["files"].get(name, {})
        new_hash = _sha256_text(content)

        if os.path.exists(target):
            # S02: the main name is written exactly ONCE (exclusive first
            # create). Every later export - even when the file still looks
            # untouched - is an append-only candidate: no read-hash-then-
            # replace sequence remains for an external editor to race, so
            # the main file can never lose human content.
            if recorded.get("last_hash") == new_hash:
                with open(target, "r", encoding="utf-8") as handle:
                    if _sha256_text(handle.read()) == new_hash:
                        return {"outcome": "unchanged", "path": target}
            identity = _content_identity(directory, name, content)
            already = _candidate_for_identity(directory, identity)
            if already is not None:
                # T07: this exact content was already delivered beside the
                # main file - publish once, never duplicate
                return {"outcome": "unchanged", "path": target,
                        "candidate_path": already}
            candidate = _unique_candidate(directory, name, content)
            return {"outcome": "preserved_with_candidate", "path": target,
                    "candidate_path": candidate}
        # first creation: exclusive create; a losing racer falls back to a
        # candidate instead of overwriting the winner
        if _exclusive_create(target, content):
            manifest["files"][name] = {"last_hash": new_hash, "owner": owner,
                                       "written_at": utc_now()}
            _save_manifest(directory, manifest)
            return {"outcome": "written", "path": target}
        candidate = _unique_candidate(directory, name, content)
        return {"outcome": "preserved_with_candidate", "path": target,
                "candidate_path": candidate}
    finally:
        lock.release()


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


def render_analysis_candidate(run: Dict[str, Any]) -> str:
    """Markdown export of one analysis run (pending-review marked)."""
    lines = [
        "# 分析草稿：%s" % (run.get("query") or "")[:60],
        "",
        "- **run_id**：`%s`" % run.get("run_id"),
        "- **状态**：%s（模型草稿，待人工审核）" % run.get("status"),
        "- **模式**：%s | **提示词版本**：%s" % (run.get("mode"),
                                                  run.get("prompt_version")),
        "- **生成时间**：%s" % run.get("created_at"),
        "",
        "## 草稿",
        "",
        run.get("draft") or "（无草稿：%s）" % (run.get("error") or "unknown"),
        "",
        "## 引用证据",
        "",
    ]
    citations = run.get("citations") or []
    if not citations:
        lines.append("-（无引用）")
    for citation in citations:
        lines.append("- `%s`（%s/%s@%s）→ %s" % (
            citation.get("block_id", "?"), citation.get("source"),
            citation.get("doc_id"), citation.get("source_version", ""),
            citation.get("evidence_url")))
    verification = run.get("verification") or {}
    lines += [
        "",
        "## 引用验证",
        "",
        "- 全部有效：%s" % verification.get("all_valid"),
        "- 无效引用：%s" % (verification.get("invalid") or "无"),
        "",
        "> 本文件由知识服务生成；人工编辑后不会被覆盖（下次导出另存候选）。",
        "",
    ]
    return "\n".join(lines)


def export_analysis_runs(kb: KnowledgeStore, directory: str,
                         run_id: Optional[str] = None, limit: int = 10,
                         owner: str = "knowledge") -> Dict[str, Any]:
    """Export analysis runs as markdown candidates into a generated area."""
    if run_id:
        runs = [kb.get_analysis_run(run_id)]
        runs = [r for r in runs if r]
        if not runs:
            return {"count": 0, "outcomes": [], "results": [],
                    "error": "run not found"}
    else:
        with kb._lock:
            rows = kb._conn.execute(
                "SELECT run_id FROM analysis_runs ORDER BY created_at DESC"
                " LIMIT ?", (max(1, min(int(limit), 100)),)).fetchall()
        runs = [kb.get_analysis_run(r["run_id"]) for r in rows]
        runs = [r for r in runs if r]
    results = []
    for run in runs:
        name = "%s.md" % run["run_id"]
        results.append(write_candidate(
            directory, name, render_analysis_candidate(run), owner=owner))
    outcomes = {r["outcome"] for r in results}
    return {"count": len(results), "outcomes": sorted(outcomes),
            "results": results}
