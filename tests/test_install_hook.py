"""Tests for ``reviewer install-hook`` and the pre-commit hook manifest."""

import os
import shutil
import subprocess
import tempfile
import unittest

from reviewer import cli
from reviewer.hooks import HOOK_MARKER

from test_cli import _git, _runner

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class InstallHookTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = self._tmp.name
        _git(["init", "-q"], self.repo)
        self.hooks = os.path.join(self.repo, ".git", "hooks")
        self.hook = os.path.join(self.hooks, "pre-commit")

    def _invoke(self, *args):
        return _runner().invoke(cli.main, ["install-hook", "--path", self.repo] + list(args))

    def _read(self, path):
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def _write(self, path, text):
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)

    def test_install_creates_hook(self):
        result = self._invoke()
        self.assertEqual(result.exit_code, 0, result.stderr)
        text = self._read(self.hook)
        self.assertTrue(text.startswith("#!/bin/sh\n"))
        self.assertIn(HOOK_MARKER, text)
        self.assertIn("reviewer --staged", text)
        self.assertIn("-m reviewer.cli --staged", text)
        self.assertNotIn("\r", text)
        self.assertIn("Installed", result.stderr)
        self.assertEqual(result.stdout, "")
        if os.name != "nt":
            self.assertTrue(os.access(self.hook, os.X_OK))

    @unittest.skipUnless(shutil.which("sh"), "sh not available")
    def test_script_is_valid_sh(self):
        self._invoke()
        subprocess.run(["sh", "-n", self.hook], check=True)

    def test_second_install_refused(self):
        self._write(self.hook, "#!/bin/sh\necho mine\n")
        result = self._invoke()
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("--force", result.stderr)
        self.assertEqual(self._read(self.hook), "#!/bin/sh\necho mine\n")

    def test_force_backs_up_old_hook(self):
        self._write(self.hook, "#!/bin/sh\necho mine\n")
        result = self._invoke("--force")
        self.assertEqual(result.exit_code, 0, result.stderr)
        self.assertEqual(self._read(self.hook + ".bak"), "#!/bin/sh\necho mine\n")
        self.assertIn(HOOK_MARKER, self._read(self.hook))
        self.assertIn("Backed up", result.stderr)

    def test_uninstall_removes_only_reviewer_hook(self):
        self._invoke()
        result = self._invoke("--uninstall")
        self.assertEqual(result.exit_code, 0, result.stderr)
        self.assertFalse(os.path.exists(self.hook))

        self._write(self.hook, "#!/bin/sh\necho mine\n")
        result = self._invoke("--uninstall")
        self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(self._read(self.hook), "#!/bin/sh\necho mine\n")

    def test_uninstall_without_hook_is_noop(self):
        result = self._invoke("--uninstall")
        self.assertEqual(result.exit_code, 0)
        self.assertIn("nothing to remove", result.stderr)

    def test_path_in_subdirectory(self):
        sub = os.path.join(self.repo, "pkg", "inner")
        os.makedirs(sub)
        result = _runner().invoke(cli.main, ["install-hook", "--path", sub])
        self.assertEqual(result.exit_code, 0, result.stderr)
        self.assertTrue(os.path.isfile(self.hook))

    def test_honours_core_hooks_path(self):
        custom = os.path.join(self.repo, "custom-hooks")
        _git(["config", "core.hooksPath", custom], self.repo)
        result = self._invoke()
        self.assertEqual(result.exit_code, 0, result.stderr)
        self.assertTrue(os.path.isfile(os.path.join(custom, "pre-commit")))
        self.assertFalse(os.path.exists(self.hook))

    def test_outside_repo_fails(self):
        with tempfile.TemporaryDirectory() as outside:
            result = _runner().invoke(cli.main, ["install-hook", "--path", outside])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("git repository", result.stderr)


class ManifestTests(unittest.TestCase):
    def test_pre_commit_hooks_yaml(self):
        with open(os.path.join(ROOT, ".pre-commit-hooks.yaml"), encoding="utf-8") as fh:
            text = fh.read()
        for expected in (
            "id: reviewer", "name: reviewer", "entry: reviewer --staged",
            "language: python", "pass_filenames: false", "stages: [pre-commit]",
        ):
            self.assertIn(expected, text)


if __name__ == "__main__":
    unittest.main()
