"""Plan or execute the pinned continuation chain for one merged chart bundle."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
from typing import Any, Callable

PINNED_CHAIN_SHA256 = "9210cc0b750846e55bbc215195e3c92f88df4c9232e5d7db076288cba1a8013d"
PINNED_CHECKER_SHA256 = "ceeedb25acdb356055f18ab9b06233664c76a5e7af6bb9adafbd53afed2513a4"
PINNED_IMAGE = "sha256:a3bab76c9e34b5c6c686142591f18860e6686c0e8f8e8759c9f303a6c0d8e2a8"
SEQUENCE_MARKERS = ("sequence-started.json", "sequence-result.json", "sequence-current.json")


class SequenceError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_object(path: Path) -> dict[str, Any]:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise SequenceError("required release metadata is missing or unsafe")
    attrs = getattr(path.lstat(), "st_file_attributes", 0)
    if attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
        raise SequenceError("required release metadata is a reparse point")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SequenceError("required release metadata is missing or invalid") from exc
    if not isinstance(value, dict):
        raise SequenceError("release metadata must be an object")
    return value


def _safe_directory(path: Path, label: str) -> Path:
    path = Path(os.path.abspath(Path(path)))
    if path.is_symlink() or not path.is_dir():
        raise SequenceError(f"{label} must be an existing regular directory")
    # Reject junctions/reparse points as well as symbolic links in the path chain.
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current = current / component
        if not current.exists():
            continue
        stat = current.lstat()
        attrs = getattr(stat, "st_file_attributes", 0)
        if current.is_symlink() or attrs & getattr(__import__("stat"), "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            raise SequenceError(f"{label} path contains a symlink/junction/reparse point")
    return path


def validate_bundle(bundle_path: Path, expected_bundle_sha: str) -> dict[str, Any]:
    bundle = _safe_directory(bundle_path, "bundle")
    result_path = bundle / "bundle-result.json"
    hashes_path = bundle / "input-hashes.json"
    approval_path = bundle / "native-visual-acceptance.json"
    for file_path in (result_path, hashes_path, approval_path):
        if file_path.is_symlink() or not file_path.is_file():
            raise SequenceError("bundle metadata file is missing or unsafe")
    if sha256_file(result_path) != expected_bundle_sha.lower():
        raise SequenceError("bundle result SHA256 differs from the approved pin")
    result = read_object(result_path)
    if (result.get("schema") != "chart-release-bundle/1"
            or result.get("stage") != "merged_verified_inputs"
            or result.get("activation_allowed") is not False):
        raise SequenceError("bundle result is not a verified non-activating merge")
    manifest_dir = _safe_directory(bundle / "manifests", "bundle manifests")
    asset_dir = _safe_directory(bundle / "assets", "bundle assets")
    actual_manifest = {}
    actual_asset = {}
    for path in manifest_dir.iterdir():
        if path.is_symlink() or not path.is_file() or path.suffix.lower() != ".json":
            raise SequenceError("bundle manifest directory contains an unsafe entry")
        actual_manifest[path.name] = sha256_file(path)
    for path in asset_dir.iterdir():
        if path.is_symlink() or not path.is_file() or path.suffix.lower() != ".png":
            raise SequenceError("bundle asset directory contains an unsafe entry")
        actual_asset[path.name] = sha256_file(path)
    if (not actual_manifest or not actual_asset
            or actual_manifest != result.get("manifest_hashes")
            or actual_asset != result.get("asset_hashes")):
        raise SequenceError("bundle manifest/asset inventory differs from pinned merge result")
    inventory = read_object(hashes_path)
    expected_inventory = {f"manifests/{name}": sha for name, sha in actual_manifest.items()}
    expected_inventory.update({f"assets/{name}": sha for name, sha in actual_asset.items()})
    if inventory != expected_inventory:
        raise SequenceError("bundle checker inventory does not match files")
    approval = read_object(approval_path)
    if (sha256_file(hashes_path) != result.get("input_hashes_sha256")
            or sha256_file(approval_path) != result.get("merged_approval_sha256")):
        raise SequenceError("bundle approval/inventory provenance hash differs from pinned merge result")
    if (approval.get("stage") != "visual_and_exact_mapping_accepted"
            or approval.get("manifest_hashes") != actual_manifest
            or approval.get("activation_allowed") is not False):
        raise SequenceError("merged approval does not bind the exact manifest set")
    checker = bundle / "data_release_check.py"
    if not checker.is_file() or checker.is_symlink() or sha256_file(checker) != PINNED_CHECKER_SHA256:
        raise SequenceError("bundle lacks the fixed pinned data_release_check.py")
    if (result.get("page_count") != len(actual_manifest)
            or result.get("asset_count") != len(actual_asset)):
        raise SequenceError("bundle counts differ from verified inventory")
    return {"path": bundle, "result": result, "manifest_count": len(actual_manifest),
            "asset_count": len(actual_asset), "checker": checker}


def validate_previous_release(previous: Path, inspect: Callable[[str], dict[str, Any]]) -> dict[str, Any]:
    root = _safe_directory(previous, "previous release")
    verification = read_object(root / "server-verification.json")
    checker = verification.get("checker", {})
    if (verification.get("status") != "published"
            or checker.get("stage") != "passed" or checker.get("mode") != "production"
            or checker.get("production_changed") is not True
            or checker.get("rollback_verified") is not False
            or checker.get("idempotent_repeats") != 2):
        raise SequenceError("previous release is not a completed published production batch")
    final_inspection = read_object(root / "service-final-inspection.json")
    running = final_inspection.get("running")
    if not isinstance(running, dict) or not running or any(value is not True for value in running.values()):
        raise SequenceError("previous release final service inspection is not fully running")
    apply = read_object(root / "apply-launch.json")
    ident = apply.get("container_id")
    if not isinstance(ident, str) or not ident:
        raise SequenceError("previous apply container ID is missing")
    info = inspect(ident)
    state = info.get("State", {})
    if (info.get("Id") != ident or info.get("Config", {}).get("Image") != apply.get("image")
            or apply.get("image") != PINNED_IMAGE or state.get("Running") is not False
            or state.get("ExitCode") != 0):
        raise SequenceError("previous apply container identity/image/exit state is invalid")
    return {"path": root, "container_id": ident,
            "manifest_count": checker.get("manifest_count"), "asset_count": checker.get("asset_count")}


def load_chain(path: Path):
    helper = Path(path).resolve()
    if sha256_file(helper) != PINNED_CHAIN_SHA256:
        raise SequenceError("pinned batch chain helper SHA256 mismatch")
    spec = importlib.util.spec_from_file_location("pinned_chart_batch_chain", helper)
    if spec is None or spec.loader is None:
        raise SequenceError("cannot import the pinned batch chain helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _inspect_docker(ident: str) -> dict[str, Any]:
    proc = subprocess.run(["docker", "inspect", ident], text=True, capture_output=True, check=False)
    if proc.returncode:
        raise SequenceError("read-only Docker inspect failed")
    try:
        records = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise SequenceError("Docker inspect response is invalid") from exc
    if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict):
        raise SequenceError("Docker inspect did not return exactly one container")
    return records[0]


def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--plan", action="store_true", help="validate immutable inputs and print sanitized plan")
    p.add_argument("--execute", action="store_true", help="invoke the pinned chain after all gates pass")
    p.add_argument("--chain-helper", type=Path, required=True)
    p.add_argument("--chain-sha256", required=True)
    p.add_argument("--bundle", type=Path, required=True)
    p.add_argument("--bundle-sha", required=True, help="SHA256 of bundle-result.json")
    p.add_argument("--previous-release", type=Path, required=True)
    p.add_argument("--operation", type=Path, required=True, help="new, distinct chain checkpoint directory")
    p.add_argument("--isolated-name", required=True)
    p.add_argument("--prepare-launch", type=Path, required=True)
    p.add_argument("--isolated-root", type=Path, required=True)
    for arg in ("state", "snapshot-root", "worker-state", "live-db", "vault", "config",
                "adapter", "previous-supervisor"):
        p.add_argument("--" + arg, type=Path, required=True)
    p.add_argument("--expected-library-id", required=True)
    p.add_argument("--adapter-sha256", required=True)
    p.add_argument("--previous-supervisor-sha256", required=True)
    p.add_argument("--prepare-timeout", type=float, default=21600)
    p.add_argument("--isolated-timeout", type=float, default=21600)
    p.add_argument("--supervisor-timeout", type=float, default=21600)
    p.add_argument("--poll", type=float, default=30)
    return p


def run(argv: list[str] | None = None, *, inspect: Callable[[str], dict[str, Any]] = _inspect_docker,
        chain_module: Any | None = None) -> dict[str, Any]:
    args = make_parser().parse_args(argv)
    if args.plan == args.execute:
        raise SequenceError("select exactly one of --plan or --execute")
    if args.chain_sha256.lower() != PINNED_CHAIN_SHA256:
        raise SequenceError("caller chain SHA256 does not match the fixed pin")
    operation = _safe_directory(args.operation, "new operation")
    bundle_path = _safe_directory(args.bundle, "bundle")
    previous_path = _safe_directory(args.previous_release, "previous release")
    if bundle_path.parent != operation:
        raise SequenceError("bundle must be an immediate child of the new operation")
    if operation == previous_path or operation in previous_path.parents or previous_path in operation.parents:
        raise SequenceError("new operation and previous release must be distinct trees")
    for marker in SEQUENCE_MARKERS:
        if (operation / marker).exists():
            raise SequenceError("sequence checkpoint already exists; refusing repeat execution")
    if any(operation.glob("sequence-stage-*.json")):
        raise SequenceError("sequence stage checkpoint already exists; refusing repeat execution")
    if (operation / "sequence-started.json").is_symlink():
        raise SequenceError("sequence checkpoint path is unsafe")
    if not args.isolated_name or any(c.isspace() for c in args.isolated_name):
        raise SequenceError("isolated name must be a unique Docker name")

    bundle = validate_bundle(bundle_path, args.bundle_sha)
    previous = validate_previous_release(previous_path, inspect)
    helper = Path(args.chain_helper).resolve()
    if sha256_file(helper) != PINNED_CHAIN_SHA256:
        raise SequenceError("pinned chain helper SHA256 mismatch")
    chain = chain_module if chain_module is not None else load_chain(helper)
    # The old chain owns its fixed image/checker and all subsequent release gates.
    if getattr(chain, "IMAGE", None) != PINNED_IMAGE or getattr(chain, "CHECKER_SHA256", None) != PINNED_CHECKER_SHA256:
        raise SequenceError("pinned chain image/checker constants differ")
    if args.execute:
        if getattr(chain, "__file__", str(helper)) and Path(getattr(chain, "__file__", helper)).resolve() != helper:
            raise SequenceError("injected chain module does not correspond to the pinned helper")
        chain.ISOLATED_NAME = args.isolated_name
        chain.EXPECTED_MANIFESTS = bundle["manifest_count"]
        chain.EXPECTED_ASSETS = bundle["asset_count"]
        chain_argv = [
            "--current-operation", str(operation), "--release-operation", str(bundle_path),
            "--prepare-launch", str(args.prepare_launch), "--isolated-root", str(args.isolated_root),
            "--state", str(args.state), "--snapshot-root", str(args.snapshot_root),
            "--worker-state", str(args.worker_state), "--live-db", str(args.live_db),
            "--vault", str(args.vault), "--config", str(args.config),
            "--expected-library-id", args.expected_library_id,
            "--adapter", str(args.adapter), "--adapter-sha256", args.adapter_sha256,
            "--previous-supervisor", str(args.previous_supervisor),
            "--previous-supervisor-sha256", args.previous_supervisor_sha256,
            "--prepare-timeout", str(args.prepare_timeout), "--isolated-timeout", str(args.isolated_timeout),
            "--supervisor-timeout", str(args.supervisor_timeout), "--poll", str(args.poll)]
        chain.main(chain_argv)
    return {"stage": "ready_to_execute" if args.plan else "chain_invoked",
            "operation": str(operation), "bundle": str(bundle_path),
            "previous_release": str(previous_path), "manifest_count": bundle["manifest_count"],
            "asset_count": bundle["asset_count"], "previous_apply_id": previous["container_id"],
            "isolated_name": args.isolated_name, "chain_sha256": PINNED_CHAIN_SHA256,
            "production_chain_invoked": args.execute, "activation_allowed": False}


def main(argv: list[str] | None = None) -> int:
    result = run(argv)
    print(json.dumps({key: result[key] for key in (
        "stage", "manifest_count", "asset_count", "isolated_name", "chain_sha256",
        "activation_allowed", "production_chain_invoked")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
