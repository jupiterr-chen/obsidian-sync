"""Merge already approved chart-release batches into one checker-compatible bundle.

This is a local, offline file operation. It validates every source batch before
creating the new output and copies manifest/asset bytes without rewriting them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any

ACCEPTED_STAGE = "visual_and_exact_mapping_accepted"
MANIFEST_SUFFIX = ".json"
ASSET_SUFFIX = ".png"
IDENTITY_FIELDS = ("source", "doc_id", "version_id", "extraction_id", "block_id",
                   "snapshot_sha256", "text_sha256", "page")


class BundleError(ValueError):
    pass


def _reject_reparse_chain(path: Path, *, include_leaf: bool = True) -> None:
    """Reject symlinks/junctions on every existing component of a path."""
    absolute = Path(os.path.abspath(Path(path)))
    parts = [absolute.anchor]
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        parts.append(str(current))
    if not include_leaf and parts:
        parts = parts[:-1]
    for value in parts:
        candidate = Path(value)
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        attrs = getattr(info, "st_file_attributes", 0)
        reparse = bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
        if stat.S_ISLNK(info.st_mode) or reparse:
            raise BundleError("symlink/junction/reparse path is not allowed")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json_bytes(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BundleError(f"invalid JSON input: {label}") from exc
    if not isinstance(value, dict):
        raise BundleError(f"JSON input must be an object: {label}")
    return value


def _regular_flat_files(directory: Path, suffix: str, *, label: str) -> dict[str, bytes]:
    _reject_reparse_chain(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise BundleError(f"missing or unsafe {label} directory")
    found: dict[str, bytes] = {}
    for child in sorted(directory.iterdir(), key=lambda p: p.name):
        if child.is_symlink() or not child.is_file() or child.suffix.lower() != suffix:
            raise BundleError(f"unexpected file or path in {label} directory")
        if child.name in found:
            raise BundleError(f"duplicate filename in {label} directory")
        found[child.name] = child.read_bytes()
    if not found:
        raise BundleError(f"empty {label} directory")
    return found


def _validate_manifest(filename: str, raw: bytes) -> tuple[dict[str, Any], tuple[str, str, str, int], str]:
    manifest = read_json_bytes(raw, filename)
    if any(not isinstance(manifest.get(field), str) or not manifest[field]
           for field in IDENTITY_FIELDS if field != "page"):
        raise BundleError(f"manifest identity is incomplete: {filename}")
    page = manifest.get("page")
    if type(page) is not int or page < 1:
        raise BundleError(f"manifest page is invalid: {filename}")
    block_id = manifest["block_id"]
    if Path(filename).name != filename or not filename.endswith(MANIFEST_SUFFIX):
        raise BundleError("unsafe manifest filename")
    if (manifest.get("policy") != "chart-content-v1"
            or manifest.get("review_state") != "confirmed"
            or not isinstance(manifest.get("reviewer"), str)
            or not manifest.get("reviewer").strip()):
        raise BundleError(f"source manifest is not individually confirmed: {filename}")
    if manifest.get("activation_allowed") is True:
        raise BundleError("manifest cannot grant operation-level activation authority")
    region_rows = manifest.get("regions")
    if not isinstance(region_rows, list) or not region_rows:
        raise BundleError(f"manifest regions are missing: {filename}")
    asset_names = []
    for region in region_rows:
        if not isinstance(region, dict):
            raise BundleError(f"invalid manifest region: {filename}")
        if region.get("kind") == "chart" and region.get("review_state") != "confirmed":
            raise BundleError(f"manifest region is not individually confirmed: {filename}")
        if region.get("kind") == "chart":
            asset = region.get("asset")
            if not isinstance(asset, dict):
                raise BundleError(f"chart manifest lacks asset metadata: {filename}")
            name, digest = asset.get("name"), asset.get("sha256")
            if (not isinstance(digest, str) or len(digest) != 64
                    or any(c not in "0123456789abcdef" for c in digest)
                    or name != digest + ".png" or Path(name).name != name):
                raise BundleError(f"manifest asset path/hash is invalid: {filename}")
            asset_names.append(name)
    if not asset_names:
        raise BundleError(f"manifest contains no chart asset: {filename}")
    page_key = (manifest["source"], manifest["doc_id"], manifest["version_id"], page)
    identity = sha256_bytes(json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                                       separators=(",", ":")).encode("utf-8"))
    return {**manifest, "_bundle_asset_names": asset_names}, page_key, identity


def validate_batch(batch_dir: Path) -> dict[str, Any]:
    root = Path(os.path.abspath(Path(batch_dir)))
    _reject_reparse_chain(root)
    if Path(batch_dir).is_symlink() or not root.is_dir():
        raise BundleError("batch root is not a regular directory")
    manifests_raw = _regular_flat_files(root / "manifests", MANIFEST_SUFFIX, label="manifests")
    assets_raw = _regular_flat_files(root / "assets", ASSET_SUFFIX, label="assets")
    hashes_path = root / "input-hashes.json"
    approval_path = root / "native-visual-acceptance.json"
    _reject_reparse_chain(hashes_path)
    _reject_reparse_chain(approval_path)
    if not hashes_path.is_file() or not approval_path.is_file():
        raise BundleError("required inventory/approval file is missing")
    hashes_raw = hashes_path.read_bytes()
    approval_raw = approval_path.read_bytes()
    expected_hashes = read_json_bytes(hashes_raw, "input-hashes.json")
    approval = read_json_bytes(approval_raw, "native-visual-acceptance.json")
    actual_hashes = {
        **{f"manifests/{name}": sha256_bytes(raw) for name, raw in manifests_raw.items()},
        **{f"assets/{name}": sha256_bytes(raw) for name, raw in assets_raw.items()},
    }
    if expected_hashes != actual_hashes:
        raise BundleError("input-hashes inventory differs from actual batch files")
    manifest_hashes = {name: sha256_bytes(raw) for name, raw in manifests_raw.items()}
    if (approval.get("stage") != ACCEPTED_STAGE
            or approval.get("manifest_hashes") != manifest_hashes
            or approval.get("activation_allowed") is True):
        raise BundleError("visual acceptance does not bind this exact manifest set")

    parsed = {}
    references: set[str] = set()
    page_keys = {}
    block_ids = {}
    source_doc_version = {}
    source_doc = {}
    for name, raw in manifests_raw.items():
        manifest, page_key, identity_hash = _validate_manifest(name, raw)
        if page_key in page_keys:
            raise BundleError("duplicate physical source page within a batch")
        if manifest["block_id"] in block_ids:
            raise BundleError("duplicate block identity within a batch")
        source_doc_key = (manifest["source"], manifest["doc_id"])
        prior_version = source_doc.get(source_doc_key)
        if prior_version is not None and prior_version != manifest["version_id"]:
            raise BundleError("one source document has conflicting versions")
        source_doc[source_doc_key] = manifest["version_id"]
        version_key = (*source_doc_key, manifest["version_id"])
        prior_snapshot = source_doc_version.get(version_key)
        provenance = (manifest["extraction_id"], manifest["snapshot_sha256"])
        if prior_snapshot is not None and prior_snapshot != provenance:
            raise BundleError("one source version has conflicting extraction/snapshot provenance")
        source_doc_version[version_key] = provenance
        page_keys[page_key] = name
        block_ids[manifest["block_id"]] = name
        references.update(manifest.pop("_bundle_asset_names"))
        parsed[name] = {"manifest": manifest, "page_key": page_key, "identity_sha256": identity_hash}
    if references != set(assets_raw):
        raise BundleError("asset files differ from manifest asset references")
    for name, raw in assets_raw.items():
        expected = Path(name).stem
        if sha256_bytes(raw) != expected:
            raise BundleError("asset bytes do not match content-addressed filename")
    return {"root": root, "manifests": manifests_raw, "assets": assets_raw,
            "hashes_raw": hashes_raw, "approval_raw": approval_raw,
            "manifest_hashes": manifest_hashes, "parsed": parsed,
            "page_keys": page_keys, "block_ids": block_ids}


def merge_batches(batch_dirs: list[Path], out: Path) -> dict[str, Any]:
    if not batch_dirs:
        raise BundleError("at least one --batch is required")
    output = Path(os.path.abspath(Path(out)))
    _reject_reparse_chain(output)
    if os.path.lexists(str(output)):
        raise FileExistsError("output already exists; choose a new directory")
    validated = [validate_batch(path) for path in batch_dirs]
    roots = [entry["root"] for entry in validated]
    for root in roots:
        _reject_reparse_chain(root)
        try:
            common = Path(os.path.commonpath((str(output), str(root))))
        except ValueError:
            continue
        if common == output or common == root:
            raise BundleError("output path overlaps a source batch")

    merged_manifests: dict[str, bytes] = {}
    merged_assets: dict[str, bytes] = {}
    page_seen = {}
    block_seen = {}
    source_doc = {}
    source_doc_version = {}
    source_records = []
    for ordinal, batch in enumerate(validated, 1):
        for name, row in batch["parsed"].items():
            key = row["page_key"]
            block_id = row["manifest"]["block_id"]
            manifest = row["manifest"]
            source_doc_key = (manifest["source"], manifest["doc_id"])
            prior_version = source_doc.get(source_doc_key)
            if prior_version is not None and prior_version != manifest["version_id"]:
                raise BundleError("one source document has conflicting versions across batches")
            source_doc[source_doc_key] = manifest["version_id"]
            version_key = (*source_doc_key, manifest["version_id"])
            provenance = (manifest["extraction_id"], manifest["snapshot_sha256"])
            prior_provenance = source_doc_version.get(version_key)
            if prior_provenance is not None and prior_provenance != provenance:
                raise BundleError("one source version has conflicting extraction/snapshot provenance across batches")
            source_doc_version[version_key] = provenance
            if key in page_seen:
                raise BundleError("duplicate physical page across approved batches")
            if block_id in block_seen:
                raise BundleError("duplicate block identity across approved batches")
            if name in merged_manifests:
                raise BundleError("manifest filename collision across batches")
            page_seen[key] = ordinal
            block_seen[block_id] = ordinal
            merged_manifests[name] = batch["manifests"][name]
        for name, raw in batch["assets"].items():
            previous = merged_assets.get(name)
            if previous is not None and previous != raw:
                raise BundleError("asset filename collision with differing bytes")
            merged_assets[name] = raw
        source_records.append({
            "ordinal": ordinal,
            "source_batch": str(batch["root"]),
            "visual_approval_sha256": sha256_bytes(batch["approval_raw"]),
            "input_hashes_sha256": sha256_bytes(batch["hashes_raw"]),
            "manifest_hashes": batch["manifest_hashes"],
            "asset_hashes": {name: sha256_bytes(raw) for name, raw in sorted(batch["assets"].items())},
            "visual_approval": read_json_bytes(batch["approval_raw"], "native-visual-acceptance.json"),
        })

    merged_hashes = {
        **{f"manifests/{name}": sha256_bytes(raw) for name, raw in sorted(merged_manifests.items())},
        **{f"assets/{name}": sha256_bytes(raw) for name, raw in sorted(merged_assets.items())},
    }
    merged_manifest_hashes = {name: sha256_bytes(raw) for name, raw in sorted(merged_manifests.items())}
    if not merged_manifests or not merged_assets:
        raise BundleError("merged bundle must contain at least one page and one asset")

    # All validation completes before the output path is created.
    output.mkdir(parents=True, exist_ok=False)
    (output / "manifests").mkdir()
    (output / "assets").mkdir()
    for name, raw in merged_manifests.items():
        with (output / "manifests" / name).open("xb") as stream:
            stream.write(raw)
    for name, raw in merged_assets.items():
        with (output / "assets" / name).open("xb") as stream:
            stream.write(raw)
    (output / "input-hashes.json").write_text(
        json.dumps(merged_hashes, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    approval_bundle = {
        "stage": ACCEPTED_STAGE,
        "manifest_hashes": merged_manifest_hashes,
        "approval_scope": "verified_union_of_source_approvals",
        "source_approvals": source_records,
        "review_state": "source_manifests_preserved_verbatim",
        "activation_allowed": False,
    }
    (output / "native-visual-acceptance.json").write_text(
        json.dumps(approval_bundle, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    result = {
        "schema": "chart-release-bundle/1",
        "stage": "merged_verified_inputs",
        "batch_count": len(validated),
        "page_count": len(merged_manifests),
        "asset_count": len(merged_assets),
        "source_batches": source_records,
        "manifest_hashes": merged_manifest_hashes,
        "asset_hashes": {name: sha256_bytes(raw) for name, raw in sorted(merged_assets.items())},
        "input_hashes_sha256": sha256_file(output / "input-hashes.json"),
        "merged_approval_sha256": sha256_file(output / "native-visual-acceptance.json"),
        "stages": ["all_source_batches_validated", "cross_batch_identity_unique",
                   "manifest_asset_union_verified", "raw_bytes_copied", "checker_inventory_written"],
        "review_state": "source_manifests_preserved_verbatim",
        "activation_allowed": False,
    }
    (output / "bundle-result.json").write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", action="append", required=True, type=Path,
                        help="approved release directory; repeat once per source batch")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    result = merge_batches(args.batch, args.out)
    print(json.dumps({"stage": result["stage"], "batch_count": result["batch_count"],
                      "page_count": result["page_count"], "asset_count": result["asset_count"],
                      "activation_allowed": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
