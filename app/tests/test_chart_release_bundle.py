import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ops_chart_release_bundle.py"
SPEC = importlib.util.spec_from_file_location("ops_chart_release_bundle", SCRIPT)
bundle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bundle)

SEQUENCE_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ops_chart_release_sequence.py"
SEQUENCE_SPEC = importlib.util.spec_from_file_location("ops_chart_release_sequence", SEQUENCE_SCRIPT)
sequence = importlib.util.module_from_spec(SEQUENCE_SPEC)
SEQUENCE_SPEC.loader.exec_module(sequence)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def put(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


def put_json(path: Path, value: dict) -> bytes:
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    put(path, raw)
    return raw


def make_batch(root: Path, number: int, *, page: int | None = None) -> tuple[Path, bytes, bytes]:
    manifest_dir, asset_dir = root / "manifests", root / "assets"
    manifest_dir.mkdir(parents=True)
    asset_dir.mkdir()
    asset_raw = f"chart-pixels-{number}".encode()
    asset_hash = sha(asset_raw)
    asset_name = asset_hash + ".png"
    put(asset_dir / asset_name, asset_raw)
    item_page = page if page is not None else number
    manifest = {
        "policy": "chart-content-v1",
        "review_state": "confirmed", "reviewer": "human-review",
        "source": "source-a", "doc_id": "document-a", "version_id": "version-1",
        "extraction_id": "extract-shared", "block_id": f"block-{number}",
        "snapshot_sha256": "a" * 64, "text_sha256": "b" * 64, "page": item_page,
        "mapping_method": "visually-reviewed-exact-spans",
        "coordinate_system": "normalized-top-left",
        "regions": [{"id": "chart-1", "kind": "chart", "review_state": "confirmed",
                     "bbox": [0.1, 0.1, 0.9, 0.8],
                     "caption": "source caption", "spans": [],
                     "asset": {"name": asset_name, "sha256": asset_hash}}],
    }
    manifest_name = f"block-{number}.json"
    manifest_raw = put_json(manifest_dir / manifest_name, manifest)
    hashes = {f"manifests/{manifest_name}": sha(manifest_raw), f"assets/{asset_name}": asset_hash}
    put_json(root / "input-hashes.json", hashes)
    put_json(root / "native-visual-acceptance.json", {
        "stage": bundle.ACCEPTED_STAGE, "manifest_hashes": {manifest_name: sha(manifest_raw)},
        "reviewer": "human-review", "activation_allowed": False})
    return root, manifest_raw, asset_raw


class ChartReleaseBundleTests(unittest.TestCase):
    def setUp(self):
        # Retain fixture directories; this test does not recursively delete data.
        self.root = Path(tempfile.mkdtemp(prefix="chart-release-bundle-test-"))

    def test_two_approved_batches_merge_bytes_and_checker_inventory(self):
        a, manifest_a, asset_a = make_batch(self.root / "batch-a", 1)
        b, manifest_b, asset_b = make_batch(self.root / "batch-b", 2)
        out = self.root / "bundle"
        result = bundle.merge_batches([a, b], out)
        self.assertEqual((result["page_count"], result["asset_count"], result["batch_count"]), (2, 2, 2))
        self.assertEqual((out / "manifests" / "block-1.json").read_bytes(), manifest_a)
        self.assertEqual((out / "manifests" / "block-2.json").read_bytes(), manifest_b)
        assets = sorted((out / "assets").iterdir())
        self.assertEqual({p.read_bytes() for p in assets}, {asset_a, asset_b})
        inventory = json.loads((out / "input-hashes.json").read_text(encoding="utf-8"))
        self.assertEqual(set(inventory), {f"manifests/{p.name}" for p in (out / "manifests").iterdir()} |
                         {f"assets/{p.name}" for p in assets})
        approval = json.loads((out / "native-visual-acceptance.json").read_text(encoding="utf-8"))
        self.assertEqual(approval["stage"], bundle.ACCEPTED_STAGE)
        self.assertEqual(len(approval["source_approvals"]), 2)
        self.assertIs(approval["activation_allowed"], False)

    def test_duplicate_physical_page_across_batches_is_rejected(self):
        a = make_batch(self.root / "batch-a", 1, page=4)[0]
        b = make_batch(self.root / "batch-b", 2, page=4)[0]
        with self.assertRaisesRegex(bundle.BundleError, "duplicate physical page"):
            bundle.merge_batches([a, b], self.root / "bundle")
        self.assertFalse((self.root / "bundle").exists())

    def test_tampered_manifest_or_visual_approval_is_rejected(self):
        batch = make_batch(self.root / "batch", 1)[0]
        manifest_path = next((batch / "manifests").glob("*.json"))
        with manifest_path.open("ab") as stream:
            stream.write(b" ")
        with self.assertRaisesRegex(bundle.BundleError, "input-hashes"):
            bundle.merge_batches([batch], self.root / "tampered-manifest-out")
        self.assertFalse((self.root / "tampered-manifest-out").exists())

        clean = make_batch(self.root / "clean", 2)[0]
        approval_path = clean / "native-visual-acceptance.json"
        approval = json.loads(approval_path.read_text(encoding="utf-8"))
        approval["manifest_hashes"] = {"block-2.json": "0" * 64}
        put_json(approval_path, approval)
        with self.assertRaisesRegex(bundle.BundleError, "visual acceptance"):
            bundle.merge_batches([clean], self.root / "tampered-approval-out")
        self.assertFalse((self.root / "tampered-approval-out").exists())

    def test_missing_changed_or_unsafe_assets_are_rejected(self):
        batch = make_batch(self.root / "changed", 1)[0]
        asset = next((batch / "assets").iterdir())
        asset.write_bytes(b"altered bytes")
        with self.assertRaisesRegex(bundle.BundleError, "input-hashes|content-addressed"):
            bundle.merge_batches([batch], self.root / "changed-out")

        unsafe = make_batch(self.root / "unsafe", 2)[0]
        manifest_path = next((unsafe / "manifests").glob("*.json"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["regions"][0]["asset"]["name"] = "../outside.png"
        put_json(manifest_path, manifest)
        hashes = {"manifests/" + manifest_path.name: sha(manifest_path.read_bytes())}
        asset_path = next((unsafe / "assets").iterdir())
        hashes["assets/" + asset_path.name] = sha(asset_path.read_bytes())
        put_json(unsafe / "input-hashes.json", hashes)
        approval = json.loads((unsafe / "native-visual-acceptance.json").read_text(encoding="utf-8"))
        approval["manifest_hashes"] = {manifest_path.name: sha(manifest_path.read_bytes())}
        put_json(unsafe / "native-visual-acceptance.json", approval)
        with self.assertRaisesRegex(bundle.BundleError, "asset path/hash"):
            bundle.merge_batches([unsafe], self.root / "unsafe-out")

    def test_existing_output_is_never_overwritten(self):
        batch = make_batch(self.root / "batch", 1)[0]
        out = self.root / "existing"
        out.mkdir()
        marker = out / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            bundle.merge_batches([batch], out)
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_conflicting_version_or_extraction_provenance_is_rejected(self):
        a = make_batch(self.root / "batch-a", 1)[0]
        b = make_batch(self.root / "batch-b", 2)[0]
        path = next((b / "manifests").glob("*.json"))
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["version_id"] = "version-2"
        manifest_raw = put_json(path, manifest)
        asset_path = next((b / "assets").glob("*.png"))
        put_json(b / "input-hashes.json", {
            "manifests/" + path.name: sha(manifest_raw), "assets/" + asset_path.name: sha(asset_path.read_bytes())})
        approval = json.loads((b / "native-visual-acceptance.json").read_text(encoding="utf-8"))
        approval["manifest_hashes"] = {path.name: sha(manifest_raw)}
        put_json(b / "native-visual-acceptance.json", approval)
        with self.assertRaisesRegex(bundle.BundleError, "conflicting versions"):
            bundle.merge_batches([a, b], self.root / "conflicting-version")

        # Same version with a different extraction is also not a safe union.
        manifest["version_id"] = "version-1"
        manifest["extraction_id"] = "extract-other"
        manifest_raw = put_json(path, manifest)
        put_json(b / "input-hashes.json", {
            "manifests/" + path.name: sha(manifest_raw), "assets/" + asset_path.name: sha(asset_path.read_bytes())})
        approval["manifest_hashes"] = {path.name: sha(manifest_raw)}
        put_json(b / "native-visual-acceptance.json", approval)
        with self.assertRaisesRegex(bundle.BundleError, "extraction/snapshot provenance"):
            bundle.merge_batches([a, b], self.root / "conflicting-extraction")

    def test_review_state_required_for_each_region(self):
        batch = make_batch(self.root / "batch", 1)[0]
        path = next((batch / "manifests").glob("*.json"))
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["regions"][0]["review_state"] = "proposal_only"
        raw = put_json(path, manifest)
        asset_path = next((batch / "assets").glob("*.png"))
        put_json(batch / "input-hashes.json", {
            "manifests/" + path.name: sha(raw), "assets/" + asset_path.name: sha(asset_path.read_bytes())})
        approval = json.loads((batch / "native-visual-acceptance.json").read_text(encoding="utf-8"))
        approval["manifest_hashes"] = {path.name: sha(raw)}
        put_json(batch / "native-visual-acceptance.json", approval)
        with self.assertRaisesRegex(bundle.BundleError, "region is not individually confirmed"):
            bundle.merge_batches([batch], self.root / "region-unconfirmed")

    def test_symlink_inventory_and_dangling_output_are_rejected(self):
        batch = make_batch(self.root / "batch", 1)[0]
        link = batch / "approval-link.json"
        try:
            link.symlink_to(batch / "native-visual-acceptance.json")
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation is unavailable on this Windows host")
        link.unlink()
        approval = batch / "native-visual-acceptance.json"
        saved = approval.read_bytes()
        approval.unlink()
        approval.symlink_to(batch / "missing-approval.json")
        with self.assertRaisesRegex(bundle.BundleError, "symlink/junction/reparse"):
            bundle.merge_batches([batch], self.root / "unsafe-approval-link-out")
        approval.unlink()
        approval.write_bytes(saved)
        dangling = self.root / "dangling-output"
        dangling.symlink_to(self.root / "not-created")
        with self.assertRaisesRegex(bundle.BundleError, "symlink/junction/reparse"):
            bundle.merge_batches([batch], dangling)

    def test_dangling_output_reparse_is_rejected_without_windows_symlink_support(self):
        batch = make_batch(self.root / "batch", 1)[0]
        output = self.root / "dangling-output"
        real_lstat = Path.lstat
        def fake_lstat(path):
            if path == output:
                return SimpleNamespace(st_mode=0o120777, st_file_attributes=0x400)
            return real_lstat(path)
        with patch.object(Path, "lstat", fake_lstat):
            with self.assertRaisesRegex(bundle.BundleError, "symlink/junction/reparse"):
                bundle.merge_batches([batch], output)


class ChartReleaseSequenceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="chart-release-sequence-test-"))
        self.operation = self.root / "new-operation"
        self.operation.mkdir()
        helper_raw = b"# isolated test-only pinned helper fixture\n"
        self.helper = self.root / "chain-helper.py"
        self.helper.write_bytes(helper_raw)
        checker_raw = b"# isolated test-only checker fixture\n"
        checker_sha = sha(checker_raw)
        pin_patcher = patch.object(sequence, "PINNED_CHAIN_SHA256", sha(helper_raw))
        checker_patcher = patch.object(sequence, "PINNED_CHECKER_SHA256", checker_sha)
        pin_patcher.start()
        checker_patcher.start()
        self.addCleanup(pin_patcher.stop)
        self.addCleanup(checker_patcher.stop)
        self.chain = SimpleNamespace(__file__=str(self.helper), IMAGE=sequence.PINNED_IMAGE,
                                     CHECKER_SHA256=checker_sha, EXPECTED_MANIFESTS=0,
                                     EXPECTED_ASSETS=0, ISOLATED_NAME="unused")
        self.chain_calls = []
        self.chain.main = lambda forwarded: self.chain_calls.append(list(forwarded))
        batch = make_batch(self.root / "source-batch", 1)[0]
        self.bundle_dir = self.operation / "bundle"
        merged = bundle.merge_batches([batch], self.bundle_dir)
        (self.bundle_dir / "data_release_check.py").write_bytes(checker_raw)
        self.bundle_sha = sequence.sha256_file(self.bundle_dir / "bundle-result.json")
        self.previous = self.root / "previous"
        self.previous.mkdir()
        put_json(self.previous / "server-verification.json", {
            "status": "published", "checker": {"stage": "passed", "mode": "production",
            "production_changed": True, "rollback_verified": False, "idempotent_repeats": 2,
            "manifest_count": merged["page_count"], "asset_count": merged["asset_count"]}})
        put_json(self.previous / "service-final-inspection.json", {"running": {
            "api-id": True, "worker-id": True, "library-id": True, "sync-id": True}})
        put_json(self.previous / "apply-launch.json", {
            "container_id": "previous-apply", "image": sequence.PINNED_IMAGE})
        self.base_args = ["--plan", "--chain-helper", str(self.helper),
            "--chain-sha256", sequence.PINNED_CHAIN_SHA256, "--bundle", str(self.bundle_dir),
            "--bundle-sha", self.bundle_sha, "--previous-release", str(self.previous),
            "--operation", str(self.operation), "--isolated-name", "chart-isolated-new",
            "--prepare-launch", str(self.operation / "prepare-launch.json"),
            "--isolated-root", str(self.operation / "isolated"),
            "--state", str(self.root / "state"), "--snapshot-root", str(self.root / "snapshots"),
            "--worker-state", str(self.root / "worker.json"), "--live-db", str(self.root / "live.sqlite"),
            "--vault", str(self.root / "vault"), "--config", str(self.root / "config.json"),
            "--adapter", str(self.root / "adapter.py"), "--adapter-sha256", "a" * 64,
            "--previous-supervisor", str(self.root / "supervisor.py"),
            "--previous-supervisor-sha256", "b" * 64, "--expected-library-id", "library-id"]

    def fake_inspect(self, ident: str):
        self.assertEqual(ident, "previous-apply")
        return {"Id": ident, "Config": {"Image": sequence.PINNED_IMAGE},
                "State": {"Running": False, "ExitCode": 0}}

    def test_plan_validates_fixture_pins_and_previous_release_without_writes(self):
        result = sequence.run(self.base_args, inspect=self.fake_inspect, chain_module=self.chain)
        self.assertEqual(result["stage"], "ready_to_execute")
        self.assertEqual(result["manifest_count"], 1)
        self.assertFalse((self.operation / "sequence-started.json").exists())

    def test_execute_forwards_dynamic_counts_to_pinned_chain(self):
        argv = list(self.base_args)
        argv[0] = "--execute"
        result = sequence.run(argv, inspect=self.fake_inspect, chain_module=self.chain)
        self.assertEqual(result["stage"], "chain_invoked")
        self.assertEqual((self.chain.EXPECTED_MANIFESTS, self.chain.EXPECTED_ASSETS), (1, 1))
        self.assertEqual(self.chain.ISOLATED_NAME, "chart-isolated-new")
        self.assertIn(str(self.bundle_dir), self.chain_calls[0])

    def test_previous_release_gate_and_helper_pin_fail_closed(self):
        bad_args = list(self.base_args)
        bad_args[bad_args.index(sequence.PINNED_CHAIN_SHA256)] = "0" * 64
        with self.assertRaisesRegex(sequence.SequenceError, "caller chain SHA256"):
            sequence.run(bad_args, inspect=self.fake_inspect, chain_module=self.chain)
        put_json(self.previous / "service-final-inspection.json", {"running": {"api-id": False}})
        with self.assertRaisesRegex(sequence.SequenceError, "service inspection"):
            sequence.run(self.base_args, inspect=self.fake_inspect, chain_module=self.chain)

    def test_bundle_hash_and_existing_sequence_checkpoint_are_rejected(self):
        bad_args = list(self.base_args)
        bad_args[bad_args.index(self.bundle_sha)] = "0" * 64
        with self.assertRaisesRegex(sequence.SequenceError, "bundle result SHA256"):
            sequence.run(bad_args, inspect=self.fake_inspect, chain_module=self.chain)
        (self.operation / "sequence-started.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(sequence.SequenceError, "checkpoint already exists"):
            sequence.run(self.base_args, inspect=self.fake_inspect, chain_module=self.chain)

    def test_approval_provenance_tampering_is_rejected(self):
        approval_path = self.bundle_dir / "native-visual-acceptance.json"
        approval = json.loads(approval_path.read_text(encoding="utf-8"))
        approval["source_approvals"][0]["visual_approval_sha256"] = "0" * 64
        put_json(approval_path, approval)
        with self.assertRaisesRegex(sequence.SequenceError, "approval/inventory provenance hash"):
            sequence.run(self.base_args, inspect=self.fake_inspect, chain_module=self.chain)


if __name__ == "__main__":
    unittest.main()
