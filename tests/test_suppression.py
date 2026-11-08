"""Targeted inline suppressions and the findings baseline."""

import json
import os
import tempfile
import unittest

from reviewer import cli
from reviewer.baseline import BASELINE_FILENAME
from reviewer.models import FileDiff
from reviewer.rules import default_registry
from reviewer.rules.code_quality import _is_bypass

from test_cli import _git, _make_repo, _runner

DEBUG_LINE = "import pdb"  # reviewer:allow-debug (fixture must trigger the rule)
MUTABLE = "def f(x=[]):"


def _diff(lines, full_content=None):
    return FileDiff(
        file_path="app.py",
        added_lines=[(i + 1, text) for i, text in enumerate(lines)],
        full_content=full_content,
    )


def _ids(lines, full_content=None):
    found = default_registry.execute_all([_diff(lines, full_content)])
    return {v.rule_id for v in found}


class InlineIgnoreTests(unittest.TestCase):
    def test_precondition_mutable_default_reported(self):
        self.assertIn("quality/mutable-default-argument", _ids([MUTABLE, "    pass"]))

    def test_targeted_ignore_suppresses_only_named_rule(self):
        line = MUTABLE + "  # reviewer:ignore[quality/mutable-default-argument]"
        self.assertNotIn("quality/mutable-default-argument", _ids([line, "    pass"]))
        other = MUTABLE + "  # reviewer:ignore[quality/deep-nesting]"
        self.assertIn("quality/mutable-default-argument", _ids([other, "    pass"]))

    def test_is_bypass_ignores_bracketed_form(self):
        self.assertFalse(_is_bypass("x = 1  # reviewer:ignore[quality/deep-nesting]"))
        self.assertTrue(_is_bypass("x = 1  # reviewer:ignore"))
        self.assertTrue(_is_bypass("x = 1  # noqa"))

    def test_glob_targeted_ignore(self):
        line = MUTABLE + "  # reviewer:ignore[security/*, quality/*]"
        self.assertNotIn("quality/mutable-default-argument", _ids([line, "    pass"]))
        line = MUTABLE + "  # reviewer:ignore[security/*]"
        self.assertIn("quality/mutable-default-argument", _ids([line, "    pass"]))

    def test_bare_ignore_suppresses_all_on_line(self):
        line = MUTABLE + "  # reviewer:ignore"
        self.assertNotIn("quality/mutable-default-argument", _ids([line, "    pass"]))

    def test_ignore_file_bare(self):
        lines = ["# reviewer:ignore-file", MUTABLE, "    pass"]
        self.assertNotIn("quality/mutable-default-argument", _ids(lines))

    def test_ignore_file_targeted(self):
        lines = ["# reviewer:ignore-file[quality/mutable-*]", MUTABLE, "    pass"]
        self.assertNotIn("quality/mutable-default-argument", _ids(lines))
        lines = ["# reviewer:ignore-file[security/*]", MUTABLE, "    pass"]
        self.assertIn("quality/mutable-default-argument", _ids(lines))

    def test_ignore_file_uses_full_content_and_window(self):
        full = "# reviewer:ignore-file\n" + MUTABLE + "\n    pass\n"
        self.assertNotIn("quality/mutable-default-argument", _ids(["def f(x=[]):", "    pass"], full))
        late = "\n".join(["a = 1"] * 5 + ["# reviewer:ignore-file", MUTABLE, "    pass"])
        self.assertIn("quality/mutable-default-argument", _ids(late.splitlines(), late))


class BaselineTests(unittest.TestCase):
    def _invoke(self, tmp, *extra):
        return _runner().invoke(cli.main, ["--path", tmp, "--format", "json"] + list(extra))

    def _repo(self, tmp, content):
        _make_repo(tmp, content)

    def test_baseline_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._repo(tmp, "import pdb\n")  # reviewer:allow-debug
            self.assertEqual(self._invoke(tmp).exit_code, 1)

            result = self._invoke(tmp, "--update-baseline")
            self.assertEqual(result.exit_code, 1)  # report still printed and judged
            self.assertTrue(json.loads(result.stdout)["violations"])
            path = os.path.join(tmp, BASELINE_FILENAME)
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertEqual(data["version"], 1)
            self.assertTrue(data["fingerprints"])
            self.assertNotIn("line", json.dumps(data["fingerprints"]).replace("file_path", ""))

            result = self._invoke(tmp)
            self.assertEqual(result.exit_code, 0)
            self.assertEqual(json.loads(result.stdout)["violations"], [])
            self.assertIn("baselined findings hidden", result.stderr)

            result = self._invoke(tmp, "--no-baseline")
            self.assertEqual(result.exit_code, 1)
            self.assertNotIn("baselined", result.stderr)

            with open(os.path.join(tmp, "app.py"), "a", encoding="utf-8") as fh:
                fh.write("import pdb, os\n")  # reviewer:allow-debug
            result = self._invoke(tmp)
            self.assertEqual(result.exit_code, 1)

    def test_changed_snippet_reappears(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._repo(tmp, "import pdb\n")  # reviewer:allow-debug
            self._invoke(tmp, "--update-baseline")
            with open(os.path.join(tmp, "app.py"), "w", encoding="utf-8") as fh:
                fh.write("a = 0\nimport pdb; x = 1\n")  # reviewer:allow-debug
            result = self._invoke(tmp)
            self.assertEqual(result.exit_code, 1)

    def test_line_shift_resilience(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._repo(tmp, "import pdb\n")  # reviewer:allow-debug
            self._invoke(tmp, "--update-baseline")
            with open(os.path.join(tmp, "app.py"), "w", encoding="utf-8") as fh:
                fh.write("a = 0\nb = 1\nc = 2\nd = 3\nimport pdb\n")  # reviewer:allow-debug
            result = self._invoke(tmp)
            self.assertEqual(result.exit_code, 0)
            self.assertEqual(json.loads(result.stdout)["violations"], [])

    def test_commit_violations_never_baselined(self):
        from reviewer.baseline import apply_baseline, fingerprint, write_baseline
        from reviewer.models import Severity, Violation

        v = Violation("commit:abc1234", 0, "git/commit-message-format", "n", Severity.ERROR, "m", "wip")
        with tempfile.TemporaryDirectory() as tmp:
            write_baseline(tmp, [v])
            with open(os.path.join(tmp, BASELINE_FILENAME), encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["fingerprints"], {})
        remaining, hidden = apply_baseline([v], {fingerprint(v): {}})
        self.assertEqual((len(remaining), hidden), (1, 0))


if __name__ == "__main__":
    unittest.main()
