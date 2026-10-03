"""RF6 regression tests (R13 deploy artifacts, R14 restore-drill strictness)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

from fixtures import make_config, temp_dir

from knowledge.config import KnowledgeConfig
from knowledge.worker import run_cycle

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                       "scripts")
REPO_ROOT = os.path.join(SCRIPTS, "..")


class R13DeployArtifactsTest(unittest.TestCase):
    def test_compose_files_parse_as_yaml(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed locally")
        for name in ("deploy/docker-compose.full.yml",
                     "deploy/docker-compose.knowledge.yml"):
            path = os.path.join(REPO_ROOT, name)
            with open(path, "r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle)
            self.assertIsInstance(data, dict, name)
            for service, spec in (data.get("services") or {}).items():
                healthcheck = spec.get("healthcheck") or {}
                self.assertNotIn(
                    "expected", str(healthcheck).lower(),
                    "%s service %r healthcheck must be a valid list/string"
                    % (name, service))

    def test_healthcheck_commands_are_single_strings(self):
        for name in ("deploy/docker-compose.full.yml",
                     "deploy/docker-compose.knowledge.yml"):
            try:
                import yaml
            except ImportError:
                self.skipTest("PyYAML not installed locally")
            with open(os.path.join(REPO_ROOT, name), encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
            for service, spec in (data.get("services") or {}).items():
                check = (spec.get("healthcheck") or {}).get("test")
                if not check:
                    continue
                self.assertTrue(
                    all(isinstance(part, str) for part in check),
                    "%s/%s healthcheck must be string parts, not python-style"
                    " implicit concatenation" % (name, service))
                self.assertNotIn('"', " ".join(check),
                                 "nested double quotes break YAML lists")

    def test_knowledge_image_requirements_pinned(self):
        path = os.path.join(REPO_ROOT, "requirements-knowledge.txt")
        self.assertTrue(os.path.isfile(path))
        content = open(path, encoding="utf-8").read()
        for dep in ("pypdfium2", "rapidocr-onnxruntime", "Pillow"):
            self.assertIn(dep, content)
        for line in content.splitlines():
            if line and not line.startswith("#"):
                self.assertIn("==", line,
                              "dependency must be pinned: %r" % line)

    def test_dockerfile_knowledge_installs_requirements(self):
        path = os.path.join(REPO_ROOT, "Dockerfile.knowledge")
        self.assertTrue(os.path.isfile(path))
        content = open(path, encoding="utf-8").read()
        self.assertIn("requirements-knowledge.txt", content)

    def test_cutover_has_real_paths_and_writer_freeze(self):
        content = open(os.path.join(REPO_ROOT, "deploy", "CUTOVER.md"),
                       encoding="utf-8").read()
        self.assertNotIn("OLD_CATALOG", content)  # placeholder db path (R13)
        self.assertNotIn("NEW_CATALOG", content)
        self.assertIn("sqlite3", content)         # real online-backup snippet
        self.assertIn("run-extracts", content)    # backfill writer frozen
        self.assertIn("回滚", content)


class R14DrillStrictnessTest(unittest.TestCase):
    def setUp(self):
        self.tmp = temp_dir()
        self.library_config, self.reports, self.discord = make_config(self.tmp)
        from library.ingest import Ingestor

        ingestor = Ingestor(self.library_config)
        self.assertTrue(ingestor.run()["ok"])
        ingestor.close()
        self.kb_config = KnowledgeConfig(
            catalog_db=self.library_config.catalog_db,
            knowledge_db=os.path.join(self.tmp, "state", "knowledge.sqlite3"),
            snapshot_root=os.path.join(self.tmp, "state", "snapshots"),
            library_config="unused",
            register_stages=("snapshot", "extract"),
        )
        cycle = run_cycle(self.kb_config, self.library_config)
        self.assertTrue(cycle["ok"], cycle.get("error"))

    def _run(self, *args):
        result = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "backup-knowledge.py"),
             *args],
            capture_output=True, text=True, cwd=self.tmp, timeout=180)
        return result.returncode, result.stdout, result.stderr

    def _backup(self, out_dir, with_blobs=True):
        args = ["backup", "--db", self.kb_config.knowledge_db, "--out", out_dir]
        if with_blobs:
            args += ["--snapshots", self.kb_config.snapshot_root]
        code, out, _ = self._run(*args)
        self.assertEqual(code, 0, out)
        return json.loads(out)

    def test_drill_defaults_to_backup_blob_directory(self):
        out_dir = os.path.join(self.tmp, "backups")
        report = self._backup(out_dir, with_blobs=True)
        # drill WITHOUT --snapshots: must use the backup's own blobs dir
        code, out, _ = self._run("drill", "--backup", report["database"])
        self.assertEqual(code, 0, out)
        drill = json.loads(out)
        self.assertTrue(drill["ok"], drill["problems"])
        self.assertGreater(drill["blobs_verified"], 0)

    def test_backup_without_blobs_fails_drill(self):
        out_dir = os.path.join(self.tmp, "backups-noblobs")
        report = self._backup(out_dir, with_blobs=False)
        self.assertEqual(report["blobs_copied"], 0)
        code, out, _ = self._run("drill", "--backup", report["database"])
        self.assertNotEqual(code, 0)  # referenced blobs missing -> failure
        drill = json.loads(out)
        self.assertFalse(drill["ok"])

    def test_database_only_mode_reports_partial_not_success(self):
        out_dir = os.path.join(self.tmp, "backups-partial")
        report = self._backup(out_dir, with_blobs=False)
        code, out, _ = self._run("drill", "--backup", report["database"],
                                 "--database-only")
        drill = json.loads(out)
        self.assertTrue(drill.get("partial"))
        self.assertFalse(drill.get("ok"))
        self.assertIn("partial", drill.get("rto_note", "").lower()
                      or drill.get("note", "").lower())
        self.assertNotEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
