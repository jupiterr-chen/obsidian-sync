"""Minimal validator for contracts/evidence-block.schema.json (v1).

Hand-written against the published schema so tests and the API layer can
validate evidence blocks without adding a jsonschema dependency. If the
contract schema changes, this validator must be updated in the same change.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_BLOCK_TYPES = {"paragraph", "heading", "table", "caption", "footnote"}
_LOCATOR_KINDS = {"pdf", "html", "image", "text"}
_LOCATOR_KEYS = {
    "kind", "page", "bbox", "coordinate_system", "dom_path", "anchor",
    "start_char", "end_char",
}
_REQUIRED = [
    "schema_version", "source", "doc_id", "source_version", "source_sha256",
    "extraction_id", "block_id", "block_type", "text", "locator", "quality",
]


def validate_evidence_block(block: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    for key in _REQUIRED:
        if key not in block:
            errors.append("missing field: %s" % key)
    if errors:
        return errors
    if block["schema_version"] != "1":
        errors.append("schema_version must be '1'")
    for key in ("source", "doc_id", "source_version", "extraction_id", "block_id"):
        if not isinstance(block[key], str) or not block[key]:
            errors.append("%s must be a non-empty string" % key)
    if not _SHA256_RE.match(str(block["source_sha256"])):
        errors.append("source_sha256 must be 64 lowercase hex chars")
    if block["block_type"] not in _BLOCK_TYPES:
        errors.append("block_type must be one of %s" % sorted(_BLOCK_TYPES))
    if not isinstance(block["text"], str):
        errors.append("text must be a string")

    locator = block["locator"]
    if not isinstance(locator, dict):
        return errors + ["locator must be an object"]
    if "kind" not in locator:
        errors.append("locator missing kind")
    elif locator["kind"] not in _LOCATOR_KINDS:
        errors.append("locator.kind must be one of %s" % sorted(_LOCATOR_KINDS))
    extra = set(locator) - _LOCATOR_KEYS
    if extra:
        errors.append("locator has unknown keys: %s" % sorted(extra))
    kind = locator.get("kind")
    if kind == "pdf":
        page = locator.get("page")
        if not isinstance(page, int) or isinstance(page, bool) or page < 1:
            errors.append("pdf locator requires integer page >= 1")
    if kind in ("html", "text"):
        for key in ("start_char", "end_char"):
            value = locator.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                errors.append("%s locator requires integer %s >= 0" % (kind, key))
    if kind == "html" and not locator.get("dom_path"):
        errors.append("html locator requires dom_path")
    bbox = locator.get("bbox")
    if bbox is not None:
        if (not isinstance(bbox, list) or len(bbox) != 4
                or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                           for v in bbox)):
            errors.append("bbox must be 4 numbers")
        elif not locator.get("coordinate_system"):
            errors.append("bbox requires coordinate_system")

    quality = block["quality"]
    if not isinstance(quality, dict):
        return errors + ["quality must be an object"]
    if quality.get("status") not in {"ready", "review", "failed"}:
        errors.append("quality.status must be ready/review/failed")
    issues = quality.get("issues")
    if not isinstance(issues, list) or not all(isinstance(i, str) for i in issues):
        errors.append("quality.issues must be a list of strings")

    allowed = set(_REQUIRED)
    extra_top = set(block) - allowed
    if extra_top:
        errors.append("unknown fields: %s" % sorted(extra_top))
    return errors
