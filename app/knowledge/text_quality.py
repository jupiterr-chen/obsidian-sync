"""TQ0: read-only corpus text-quality inventory.

Builds a reproducible manifest of the CURRENT state of every document's
text across five separately-counted scopes:

- documents (source, doc_id) - deduplicated, the primary scope;
- versions (kb_versions) - current and historical kept apart;
- extractions - per version, engine/recipe/issues/pages;
- pages - per latest extraction, classified from recorded per-page
  status and a fresh damage scan of each block;
- files - vault reading directory files mapped back to extractions
  (legacy machines, readable copies, candidates), hashed.

Every item carries a RECOMMENDED ACTION - keep / native-reextract /
ocr-candidate / missing-source / manual-review - computed from engine,
damage signals and source availability. Old stdlib-pdf extractions
WITHOUT a degraded_pdf_engine marker still enter the candidate set via
parser_id. Recommendations are CANDIDATES for an authorized batch, not
a claim of exact damage counts. Read-only: no production writes.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, List, Optional

from .quality import (LEGACY_PDF_ENGINES, damaged_reasons,
                      block_evidence_usable)

ACTION_KEEP = "keep"
ACTION_NATIVE_REEXTRACT = "native-reextract-candidate"
ACTION_OCR = "ocr-candidate"
ACTION_MISSING_SOURCE = "missing-source"
ACTION_MANUAL_REVIEW = "manual-review"

_READABLE_PREFIX = "text-"
_READABLE_SUFFIX = "-readable.md"


def reading_filename_of(source: str, doc_id: str,
                         extraction_id: str) -> str:
    from .reading import reading_filename

    return reading_filename(source, doc_id, extraction_id)


def _stats_of(row) -> Dict[str, Any]:
    try:
        return json.loads(row["stats_json"] or "{}")
    except (ValueError, TypeError):
        return {}


def _issues_of(row) -> List[str]:
    try:
        return json.loads(row["issues_json"] or "[]")
    except (ValueError, TypeError):
        return []


def classify_pages(kb, extraction_id: str) -> List[Dict[str, Any]]:
    """Per-page classification of one extraction: recorded page status
    (stats.page_ocr_status) plus a fresh damage scan of each block -
    older extractions predate per-page status recording."""
    with kb._lock:
        stats_row = kb._conn.execute(
            "SELECT stats_json FROM extractions WHERE extraction_id=?",
            (extraction_id,)).fetchone()
        blocks = kb._conn.execute(
            "SELECT block_id, text, locator_json, quality_issues_json"
            " FROM blocks WHERE extraction_id=? ORDER BY ordinal",
            (extraction_id,)).fetchall()
    page_status = (_stats_of(stats_row) or {}).get("page_ocr_status") or []
    pages: Dict[int, Dict[str, Any]] = {}

    def page_of(index: int) -> Dict[str, Any]:
        return pages.setdefault(index, {"page": index, "chars": 0,
                                        "damage": [], "recorded_status":
                                        page_status[index - 1]
                                        if index <= len(page_status)
                                        else None})
    for block in blocks:
        try:
            locator = json.loads(block["locator_json"] or "{}")
        except ValueError:
            locator = {}
        page = page_of(int(locator.get("page") or 0) or 1)
        page["chars"] += len(block["text"] or "")
        try:
            recorded = json.loads(block["quality_issues_json"] or "[]")
        except (ValueError, TypeError):
            recorded = []
        page["damage"] = sorted(set(page["damage"])
                                | set(damaged_reasons(block["text"] or ""))
                                | {i for i in recorded
                                   if i in ("control_characters",
                                            "c1_or_del_characters",
                                            "cid_style_glyph_runs",
                                            "damaged_text_layer")})
    return [pages[index] for index in sorted(pages)]


def recommend_document(parser_id: str, status: str, issues: List[str],
                       damaged_pages: int, total_pages: int,
                       usable_blocks: int, total_blocks: int,
                       source_available: bool) -> str:
    """The recommended action for one document (candidate, not verdict)."""
    if not source_available:
        return ACTION_MISSING_SOURCE
    legacy = any(parser_id.startswith(engine)
                 for engine in LEGACY_PDF_ENGINES)
    damage_markers = {"cid_font_unsupported", "control_characters",
                      "c1_or_del_characters", "cid_style_glyph_runs"}
    flagged = bool(damage_markers & set(issues)) or damaged_pages > 0
    if legacy and (flagged or usable_blocks < total_blocks):
        # legacy engine + damage markers, or some blocks already
        # unusable: prefer a NATIVE re-extraction first (TQ3) - the
        # pages needing OCR fall out of the re-extraction's own routing
        return ACTION_NATIVE_REEXTRACT
    if legacy:
        # legacy engine without damage markers: still a re-extraction
        # candidate (engine upgrade) but not urgent
        return ACTION_NATIVE_REEXTRACT
    if flagged and total_pages and damaged_pages >= max(1, total_pages//2):
        return ACTION_OCR
    if flagged or usable_blocks < total_blocks:
        return ACTION_MANUAL_REVIEW
    if status == "failed":
        return ACTION_MANUAL_REVIEW
    return ACTION_KEEP


def build_inventory(kb, reading_dir: Optional[str] = None,
                    include_history: bool = False,
                    snapshot_root: Optional[str] = None) -> Dict[str, Any]:
    """The full read-only inventory. Document scope is deduplicated on
    (source, doc_id); historical versions/extractions are counted in
    their own scopes and never mixed into current totals.

    snapshot_root (F2): when provided, source availability means the
    snapshot FILE exists under the recorded store path and matches the
    recorded size - metadata alone is reported unavailable with its
    reason. Without it the check degrades honestly to
    snapshot_root_not_checked (never silently treated as available)."""
    documents: List[Dict[str, Any]] = []
    scope_counts = {"documents": 0, "versions_current": 0,
                    "versions_historical": 0, "extractions": 0,
                    "pages": 0, "files": 0}
    action_counts: Dict[str, int] = {}
    with kb._lock:
        docs = kb._conn.execute(
            "SELECT source, doc_id FROM kb_documents"
            " ORDER BY source, doc_id").fetchall()
        for doc in docs:
            versions = kb._conn.execute(
                "SELECT version_id, is_current, sha256 FROM kb_versions"
                " WHERE source=? AND doc_id=? ORDER BY synced_at,"
                " version_id",
                (doc["source"], doc["doc_id"])).fetchall()
            current = [v for v in versions if v["is_current"]] \
                or (versions[-1:] if versions else [])
            scope_counts["versions_current"] += len(current)
            if include_history:
                scope_counts["versions_historical"] += \
                    max(0, len(versions) - len(current))
            entry: Optional[Dict[str, Any]] = None
            for version in current:
                extractions = kb._conn.execute(
                    "SELECT * FROM extractions WHERE source=? AND"
                    " doc_id=? AND version_id=? ORDER BY rowid DESC",
                    (doc["source"], doc["doc_id"],
                     version["version_id"])).fetchall()
                scope_counts["extractions"] += len(extractions)
                latest = extractions[0] if extractions else None
                if latest is None:
                    continue
                blocks = kb._conn.execute(
                    "SELECT block_id, text FROM blocks WHERE"
                    " extraction_id=? ORDER BY ordinal",
                    (latest["extraction_id"],)).fetchall()
                usable = sum(1 for b in blocks
                             if block_evidence_usable(b["text"] or "")[0])
                pages = classify_pages(kb, latest["extraction_id"])
                scope_counts["pages"] += len(pages)
                damaged_pages = sum(1 for p in pages if p["damage"])
                pages_with_blocks = sum(1 for p in pages if p["chars"])
                blob = kb._conn.execute(
                    "SELECT store_path, bytes FROM snapshot_blobs WHERE"
                    " sha256=?",
                    (version["sha256"],)).fetchone() \
                    if version["sha256"] else None
                # F2: metadata alone is NOT availability - with a
                # snapshot_root the FILE must exist (and match its
                # recorded size) to count. Without a root the status is
                # honestly UNCHECKED (reported as such, still eligible
                # for selection); a missing blob RECORD or a verified
                # missing/mismatched file is unavailable either way.
                blob_path = blob["store_path"] if blob else None
                blob_file = None
                if snapshot_root and blob_path:
                    candidate = blob_path \
                        if os.path.isabs(blob_path) \
                        else os.path.join(snapshot_root, blob_path)
                    if os.path.isfile(candidate):
                        blob_file = candidate
                file_checked = bool(snapshot_root)
                size_mismatch = False
                if blob_file and blob["bytes"]:
                    try:
                        size_mismatch = (os.path.getsize(blob_file)
                                         != blob["bytes"])
                    except OSError:
                        blob_file = None
                if not blob:
                    source_available = False
                    source_reason = "no_blob_record"
                elif size_mismatch:
                    source_available = False
                    source_reason = "size_mismatch"
                elif blob_file:
                    source_available = True
                    source_reason = "file_verified"
                elif file_checked:
                    source_available = False
                    source_reason = "file_missing"
                else:
                    # metadata present, file not checked: selectable
                    # but the report says so - an authorized batch must
                    # supply snapshot_root for a verified answer
                    source_available = True
                    source_reason = "snapshot_root_not_checked"
                issues = _issues_of(latest)
                stats = _stats_of(latest)
                action = recommend_document(
                    latest["parser_id"], latest["status"], issues,
                    damaged_pages, len(pages), usable, len(blocks),
                    source_available)
                action_counts[action] = action_counts.get(action, 0) + 1
                entry = {
                    "source": doc["source"], "doc_id": doc["doc_id"],
                    "version_id": version["version_id"],
                    "version_sha256": version["sha256"],
                    "extraction_id": latest["extraction_id"],
                    "engine": "%s@%s" % (latest["parser_id"],
                                         latest["parser_version"]),
                    "config_digest": latest["config_digest"],
                    "status": latest["status"],
                    "issues": sorted(set(issues)),
                    "pages_total": len(pages),
                    "pages_with_blocks": pages_with_blocks,
                    "pages_damaged": damaged_pages,
                    "pages": pages,
                    "blocks_total": len(blocks),
                    "blocks_usable": usable,
                    "has_degraded_marker": any(
                        "degraded_pdf_engine" in i for i in issues),
                    "source_available": source_available,
                    "source_check": {"file_checked": file_checked,
                                     "reason": source_reason},
                    "recorded_ocr_stats": {
                        k: stats.get(k) for k in
                        ("ocr_candidate_pages", "ocr_applied_pages",
                         "unmet_ocr_pages")},
                    "recommended_action": action,
                    "historical_extraction_count": len(extractions) - 1,
                }
            if entry is None:
                action_counts[ACTION_MANUAL_REVIEW] = \
                    action_counts.get(ACTION_MANUAL_REVIEW, 0) + 1
                entry = {"source": doc["source"], "doc_id": doc["doc_id"],
                         "extraction_id": None, "engine": None,
                         "recommended_action": ACTION_MANUAL_REVIEW,
                         "note": "no extraction for any version"}
            documents.append(entry)
            scope_counts["documents"] += 1

    # F2: map readable files to extractions by name identity; legacy
    # main/candidate copies list with mapping unknown (never guessed)
    readable_by_extraction: Dict[str, str] = {}
    for doc_entry in documents:
        if doc_entry.get("extraction_id"):
            readable_by_extraction[doc_entry["extraction_id"]] = \
                reading_filename_of(doc_entry["source"],
                                    doc_entry["doc_id"],
                                    doc_entry["extraction_id"])
    files: List[Dict[str, Any]] = []
    legacy_files: List[Dict[str, Any]] = []
    if reading_dir and os.path.isdir(reading_dir):
        for name in sorted(os.listdir(reading_dir)):
            path = os.path.join(reading_dir, name)
            if not os.path.isfile(path) or name.startswith("."):
                continue
            digest = hashlib.sha256(
                open(path, "rb").read()).hexdigest()
            item = {"file": name, "sha256": digest,
                    "bytes": os.path.getsize(path)}
            if name in readable_by_extraction.values():
                reverse = {v: k for k, v in
                           readable_by_extraction.items()}
                item["extraction_id"] = reverse[name]
                files.append(item)
                scope_counts["files"] += 1
            else:
                item["mapping"] = "candidate_or_legacy_unknown"
                legacy_files.append(item)
                scope_counts["files"] += 1

    # the manifest hash covers documents AND every hashed file plus the
    # per-document page digest, so any change that matters to a batch
    # decision changes the hash
    manifest_source = "\n".join(
        "%s/%s:%s:%s" % (d["source"], d["doc_id"],
                         d.get("extraction_id"),
                         d.get("recommended_action"))
        for d in documents)
    manifest_source += "\n" + "\n".join(
        "%s:%s" % (f["file"], f["sha256"])
        for f in files + legacy_files)
    manifest_source += "\n" + "\n".join(
        "%s/%s:%s" % (d["source"], d["doc_id"],
                      hashlib.sha256(json.dumps(
                          d.get("pages") or [], ensure_ascii=False,
                          sort_keys=True).encode("utf-8")).hexdigest())
        for d in documents)
    inventory = {
        "kind": "text-quality-inventory",
        "schema": "researchkb.text-quality-inventory/1",
        "read_only": True,
        "counts": scope_counts,
        "action_counts": action_counts,
        "documents": documents,
        "reading_files": files,
        "legacy_or_candidate_files": legacy_files,
        "manifest_hash": hashlib.sha256(
            manifest_source.encode("utf-8")).hexdigest(),
        "note": "recommended actions are candidates for an authorized"
                " batch, not exact damage verdicts; no OCR/reprocessing"
                " was executed by this inventory",
    }
    return inventory


def inventory_summary(inventory: Dict[str, Any]) -> str:
    """Human-readable summary line block (counts and anonymous ids only)."""
    lines = ["documents: %d" % inventory["counts"]["documents"],
             "current versions: %d" % inventory["counts"]
             ["versions_current"],
             "extractions (current versions): %d"
             % inventory["counts"]["extractions"],
             "pages classified: %d" % inventory["counts"]["pages"],
             "reading files hashed: %d" % inventory["counts"]["files"],
             "recommended actions: %s" % json.dumps(
                 inventory["action_counts"], ensure_ascii=False,
                 sort_keys=True),
             "manifest: %s" % inventory["manifest_hash"]]
    return "\n".join(lines)
