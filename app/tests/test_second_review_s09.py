"""S09 deployment regressions: per-service commands, build failure
propagation, cutover path discipline."""

from __future__ import annotations

import os
import unittest

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")


class S09DeployTest(unittest.TestCase):
    def test_every_full_stack_service_has_explicit_command(self):
        import yaml

        with open(os.path.join(REPO_ROOT, "deploy", "docker-compose.full.yml"),
                  encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
        services = data["services"]
        self.assertEqual(set(services), {
            "library", "syncthing", "status-collector",
            "knowledge-worker", "knowledge-api"})
        # the shared image CMD is the knowledge worker - every service that
        # must run something else needs an explicit command
        for name in ("library", "status-collector", "knowledge-worker",
                     "knowledge-api"):
            cmd = services[name].get("command")
            self.assertTrue(cmd, "%s must set an explicit command" % name)
        library_cmd = " ".join(services["library"]["command"])
        self.assertIn("library", library_cmd)
        self.assertIn("serve", library_cmd)
        self.assertNotIn("knowledge worker", library_cmd)

    def test_dockerfile_fails_hard_on_dependency_or_warmup_failure(self):
        content = open(os.path.join(REPO_ROOT, "Dockerfile.knowledge"),
                       encoding="utf-8").read()
        run_lines = [line for line in content.splitlines()
                     if line.strip().upper().startswith("RUN")]
        self.assertTrue(run_lines)
        for line in run_lines:
            self.assertNotIn("|| true", line,
                             "build must fail when deps/OCR warm-up fail: %r"
                             % line)
        self.assertIn("pip install", content)
        self.assertIn("RapidOCR()", content)

    def test_cutover_uses_absolute_cd_and_container_paths(self):
        content = open(os.path.join(REPO_ROOT, "deploy", "CUTOVER.md"),
                       encoding="utf-8").read()
        # step discipline: every docker compose invocation is preceded by cd
        self.assertIn("cd $NEW/repo/deploy", content)
        # writeback uses the CONTAINER view of the vault mount
        self.assertIn("/vault/自动研究候选", content)
        self.assertIn("/state/snapshots", content)


if __name__ == "__main__":
    unittest.main()
