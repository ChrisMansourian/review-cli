"""CLI regression tests: JSON stdout purity, exit codes, non-UTF-8 consoles."""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

from click.testing import CliRunner

from reviewer import cli

ERROR_LINE = "import pdb\n"  # reviewer:allow-debug (fixture must trigger the rule)
WARN_LINE = "print('hello')\n"
CLEAN_LINE = "x = 1\n"


def _runner():
    """CliRunner with stderr kept out of result.stdout.

    click < 8.2 (the newest available on Python 3.9) mixes stderr into stdout
    unless ``mix_stderr=False``; click >= 8.2 always separates them and removed
    the argument.
    """
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


def _git(args, cwd):
    subprocess.run(["git"] + args, cwd=cwd, check=True, capture_output=True)


def _make_repo(tmp, new_content):
    _git(["init", "-q"], tmp)
    _git(["config", "user.name", "Test User"], tmp)
    _git(["config", "user.email", "test@example.com"], tmp)
    path = os.path.join(tmp, "app.py")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("a = 0\n")
    _git(["add", "."], tmp)
    _git(["commit", "-q", "-m", "feat: add app module"], tmp)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(new_content)


class CliTests(unittest.TestCase):
    def _run(self, content, *extra):
        with tempfile.TemporaryDirectory() as tmp:
            _make_repo(tmp, content)
            return _runner().invoke(cli.main, ["--path", tmp, "--format", "json"] + list(extra))

    def test_json_stdout_is_only_the_document(self):
        result = self._run(CLEAN_LINE)
        data = json.loads(result.stdout)
        self.assertIn("violations", data)
        self.assertNotIn("Saved reports", result.stdout)

    def test_exit_code_one_on_error(self):
        result = self._run(ERROR_LINE)
        data = json.loads(result.stdout)
        self.assertTrue(any(v["severity"] == "ERROR" for v in data["violations"]))
        self.assertEqual(result.exit_code, 1)

    def test_exit_code_zero_when_clean(self):
        self.assertEqual(self._run(CLEAN_LINE).exit_code, 0)

    def test_strict_fails_on_warning(self):
        relaxed = self._run(WARN_LINE)
        data = json.loads(relaxed.stdout)
        severities = {v["severity"] for v in data["violations"]}
        self.assertEqual(severities, {"WARNING"})
        self.assertEqual(relaxed.exit_code, 0)
        self.assertEqual(self._run(WARN_LINE, "--strict").exit_code, 1)


class EncodingTests(unittest.TestCase):
    def test_streams_made_safe_for_cp1252(self):
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding="cp1252")
        old = sys.stdout
        sys.stdout = stream
        try:
            cli._make_streams_safe()
            stream.write("\U0001f50d ok")
            stream.flush()
        finally:
            sys.stdout = old
        self.assertIn(b"ok", raw.getvalue())

    def test_table_output_survives_cp1252_console(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_repo(tmp, CLEAN_LINE)
            env = dict(os.environ)
            env.pop("PYTHONIOENCODING", None)
            env["PYTHONUTF8"] = "0"
            code = (
                "import sys, io;"
                "sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='cp1252');"
                "from reviewer.cli import main;"
                "main(['--path', %r], standalone_mode=False)" % tmp
            )
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            proc = subprocess.run(
                [sys.executable, "-c", code], env=env, capture_output=True, cwd=root,
            )
            self.assertNotIn(b"UnicodeEncodeError", proc.stderr)


if __name__ == "__main__":
    unittest.main()
