"""TQ4: vault legacy-file governance planning (DRY RUN ONLY).

Plans per-file dispositions for the generated reading directory
(解析正文/): which files are the CURRENT entry, which are superseded
machine copies (replaced by a newer usable extraction), which are
candidates that may carry HUMAN edits (content hash differs from the
writeback manifest), and which are orphans/unknown.

The plan is computed from the writeback manifest + actual file hashes +
reference relationships (publish_outbox, current reading entry). It
NEVER deletes, moves or rewrites anything: executing a plan requires a
separate, precisely-scoped authorization. Files with human edits or
unknown ownership are always KEEP (conflict listed for a human), never
auto-archived. Machine-generated superseded copies are marked
archive-candidates with their full identity (path, sha256, extraction)
so a later authorized archive can restore and verify them.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, List, Optional

DISPOSITION_KEEP = "keep"
DISPOSITION_ARCHIVE_CANDIDATE = "archive-candidate"
DISPOSITION_CONFLICT_HUMAN_EDIT = "conflict-human-edit"
DISPOSITION_UNKNOWN = "unknown-owner"


def _sha256_file(path: str) -> Optional[str]:
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _writeback_manifest(directory: str) -> Dict[str, Any]:
    path = os.path.join(directory, ".knowledge-writeback.json")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data.get("files") or {}
    except (OSError, ValueError):
        return {}


def plan_file_governance(kb, reading_dir: str) -> Dict[str, Any]:
    """Build the read-only disposition plan for one reading directory."""
    if not os.path.isdir(reading_dir):
        return {"kind": "reading-governance-plan", "dry_run": True,
                "directory": reading_dir, "files": [], "counts": {},
                "note": "directory not found"}

    manifest = _writeback_manifest(reading_dir)
    plan: List[Dict[str, Any]] = []
    counts: Dict[str, int] = {}

    # the current entry per current version = the shared EFFECTIVE
    # extraction (same predicate as the reading index and the search
    # index - S2)
    current_entry_files = _current_entry_files(kb)

    # files referenced by consumed publish events (machine provenance)
    with kb._lock:
        try:
            consumed = kb._conn.execute(
                "SELECT source, doc_id, version_id, extraction_id FROM"
                " publish_outbox WHERE status='consumed'").fetchall()
        except Exception:
            consumed = []

    referenced = set()
    for row in consumed:
        from .reading import reading_filename

        referenced.add(reading_filename(row["source"], row["doc_id"],
                                        row["extraction_id"]))

    # S2/TA04: ACTUAL markdown references - every file linked from the
    # current entry pages (开始阅读.md) is load-bearing for a reader
    # following the index, whatever its extraction status is
    linked_from_index = _files_linked_from_index(reading_dir)
    # derived entry pages themselves are load-bearing by definition -
    # they ARE the index readers open; never archive candidates
    derived_pages = {"开始阅读.md", "处理状态.md"}

    for name in sorted(os.listdir(reading_dir)):
        path = os.path.join(reading_dir, name)
        if not os.path.isfile(path) or name.startswith("."):
            continue
        digest = _sha256_file(path)
        entry = {"file": name, "sha256": digest,
                 "bytes": os.path.getsize(path)}
        recorded = manifest.get(name) or {}
        entry["manifest_owner"] = recorded.get("owner")
        entry["manifest_last_hash"] = recorded.get("last_hash")
        entry["referenced_by_publish"] = name in referenced
        entry["linked_from_current_index"] = name in linked_from_index
        entry["is_current_entry"] = name in current_entry_files

        human_edit = (recorded.get("last_hash") is not None
                      and digest != recorded.get("last_hash"))
        no_manifest = not recorded
        if human_edit:
            entry["disposition"] = DISPOSITION_CONFLICT_HUMAN_EDIT
            entry["reason"] = ("content differs from the manifest's last"
                               " system write - a human edit is present;"
                               " keep and let a human resolve")
        elif (entry["is_current_entry"] or name in linked_from_index
              or name in derived_pages):
            entry["disposition"] = DISPOSITION_KEEP
            entry["reason"] = ("load-bearing: current entry, derived"
                               " index/status page, or actually linked"
                               " from the current reading index -"
                               " archiving it would break the entry")
        elif entry["referenced_by_publish"]:
            # S2/TA04: a consumed publish event names this file - the
            # machine still holds it as a delivered revision; keep until
            # the entry provably moved away AND the event is superseded
            entry["disposition"] = DISPOSITION_KEEP
            entry["reason"] = ("referenced by a consumed publish event"
                               " (delivered revision); keep")
        elif no_manifest:
            entry["disposition"] = DISPOSITION_UNKNOWN
            entry["reason"] = ("no writeback manifest record - ownership"
                               " unknown (early export or external file);"
                               " keep")
        elif recorded.get("owner") in ("reading-publisher",
                                       "existing-text-export"):
            entry["disposition"] = DISPOSITION_ARCHIVE_CANDIDATE
            entry["reason"] = ("machine-generated, not the current entry,"
                               " not referenced by any publish event or"
                               " index link; archive-candidate for an"
                               " authorized, verifiable archive outside"
                               " the vault")
        else:
            entry["disposition"] = DISPOSITION_KEEP
            entry["reason"] = ("owner %r is not a reading generator"
                               % recorded.get("owner"))
        counts[entry["disposition"]] = counts.get(entry["disposition"],
                                                  0) + 1
        plan.append(entry)

    return {"kind": "reading-governance-plan",
            "schema": "researchkb.reading-governance/1",
            "dry_run": True, "directory": reading_dir,
            "files": plan, "counts": counts,
            "note": "plan only - no file was deleted, moved or modified;"
                    " executing archive/move steps requires explicit"
                    " per-path authorization with restore verification"}


def _files_linked_from_index(reading_dir: str) -> set:
    """File names actually linked from the CURRENT reading index pages
    (开始阅读.md, and any markdown note linking siblings). A file a
    reader can reach by following the index is load-bearing - never an
    archive candidate, whatever its extraction status (S2/TA04)."""
    import re

    linked = set()
    try:
        names = sorted(os.listdir(reading_dir))
    except OSError:
        return linked
    for name in names:
        if not name.endswith(".md") or name.startswith("."):
            continue
        try:
            with open(os.path.join(reading_dir, name), "r",
                      encoding="utf-8") as handle:
                text = handle.read()
        except (OSError, ValueError):
            continue
        for target in re.findall(r"\]\(([^)]+\.md)\)", text):
            linked.add(os.path.basename(target))
    return linked


def _current_entry_files(kb) -> set:
    """Filenames serving as the CURRENT entry - the shared EFFECTIVE
    extraction predicate (knowledge.effective), same as the reading and
    search indexes (S2)."""
    from .effective import effective_extraction
    from .reading import reading_filename

    entries = set()
    with kb._lock:
        versions = kb._conn.execute(
            "SELECT source, doc_id, version_id FROM kb_versions"
            " WHERE is_current=1").fetchall()
        for version in versions:
            chosen = effective_extraction(
                kb._conn, version["source"], version["doc_id"],
                version["version_id"])
            if chosen:
                entries.add(reading_filename(
                    version["source"], version["doc_id"],
                    chosen["extraction_id"]))
    return entries
