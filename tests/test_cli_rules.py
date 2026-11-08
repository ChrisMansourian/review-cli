"""Tests for ``reviewer rules`` / ``reviewer explain`` and the default-command group."""

import json
import os
import re
import tempfile
import unittest

from reviewer import cli
from reviewer.config import set_config
from reviewer.models import FileDiff
from reviewer.rules import default_registry

from test_cli import CLEAN_LINE, ERROR_LINE, _make_repo, _runner

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TABLE_ID_RE = re.compile(r"^\|\s*`([^`]+)`", re.MULTILINE)


def _readme_rule_ids():
    with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
        text = fh.read()
    start = text.index("## 🛡️ Built-in Custom Rules")
    end = text.index("\n---", start)
    return set(TABLE_ID_RE.findall(text[start:end]))


def _diff(path, lines):
    return FileDiff(file_path=path, added_lines=list(enumerate(lines, start=1)))


KNOWN_BAD = [
    ("a.js", ["if (x) return y;", "console.log(1);", "debugger;", "// TO" "DO fix", "el.innerHTML = x;"]),
    ("a.py", ["print('x')", "import pdb", "eval(code)", "h = hashlib.md5(b)", "x = 1  # noqa", "x == None"]),
    ("a.py", ["k = 'AKIA' 'ABCDEFGHIJKLMNOP'", "r = 1 ", "\t  y = 2"]),
    ("a.rs", ["dbg!(x);"]),
    ("a.php", ["var_dump($x);"]),
]


class CatalogTests(unittest.TestCase):
    def setUp(self):
        set_config(None)
        self.addCleanup(set_config, None)

    def test_catalog_sorted_unique(self):
        ids = [info.rule_id for info in default_registry.catalog()]
        self.assertEqual(ids, sorted(set(ids)))
        self.assertGreater(len(ids), 40)

    def test_readme_table_and_catalog_agree(self):
        catalog_ids = {info.rule_id for info in default_registry.catalog()}
        readme_ids = _readme_rule_ids()
        self.assertEqual(readme_ids - catalog_ids, set(), "README ids missing from catalog")
        self.assertEqual(catalog_ids - readme_ids, set(), "catalog ids missing from README")

    def test_emitted_ids_are_in_catalog(self):
        catalog_ids = {info.rule_id for info in default_registry.catalog()}
        emitted = set()
        for path, lines in KNOWN_BAD:
            for violation in default_registry.execute_all([_diff(path, lines)]):
                emitted.add(violation.rule_id)
        commits = [{"hash": "abc1234", "subject": "wip"}, {"hash": "def5678", "subject": "x" * 80}]
        emitted.update(v.rule_id for v in default_registry.execute_all([], commits=commits))
        self.assertGreater(len(emitted), 8)
        self.assertEqual(emitted - catalog_ids, set())


class RulesCommandTests(unittest.TestCase):
    def _config_repo(self, tmp, body):
        with open(os.path.join(tmp, ".reviewer.toml"), "w", encoding="utf-8") as fh:
            fh.write(body)

    def test_json_lists_every_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = _runner().invoke(cli.main, ["rules", "--format", "json", "--path", tmp])
        self.assertEqual(result.exit_code, 0)
        data = json.loads(result.stdout)
        self.assertEqual(len(data), len(default_registry.catalog()))
        row = next(r for r in data if r["rule_id"] == "quality/god-function")
        self.assertEqual(row["severity"], "WARNING")
        self.assertFalse(row["overridden"])
        self.assertFalse(row["disabled"])

    def test_table_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = _runner().invoke(cli.main, ["rules", "--path", tmp])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("quality/deep-nesting", result.stdout)
        self.assertIn("Severity", result.stdout)

    def test_config_override_and_disable(self):
        body = 'disable = ["style/*"]\n[severity]\n"quality/god-function" = "INFO"\n'
        with tempfile.TemporaryDirectory() as tmp:
            self._config_repo(tmp, body)
            result = _runner().invoke(cli.main, ["rules", "--format", "json", "--path", tmp])
            table = _runner().invoke(cli.main, ["rules", "--path", tmp])
        data = {r["rule_id"]: r for r in json.loads(result.stdout)}
        self.assertEqual(data["quality/god-function"]["severity"], "INFO")
        self.assertTrue(data["quality/god-function"]["overridden"])
        self.assertTrue(data["style/line-too-long"]["disabled"])
        self.assertIn("quality/god-function", table.stdout)
        self.assertIn("INFO *", table.stdout)
        self.assertIn("disabled", table.stdout)


class ExplainCommandTests(unittest.TestCase):
    def test_known_rule_with_playbook(self):
        result = _runner().invoke(cli.main, ["explain", "quality/deep-nesting", "--path", ROOT])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Deeply Nested Control Flow", result.stdout)
        self.assertIn("Severity:    WARNING", result.stdout)
        self.assertIn("Suggestion:", result.stdout)
        self.assertRegex(result.stdout, r"SKILL\.md:\d+")

    def test_known_rule_without_playbook(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = _runner().invoke(cli.main, ["explain", "quality/deep-nesting", "--path", tmp])
        self.assertEqual(result.exit_code, 0)
        self.assertNotIn("Playbook", result.stdout)

    def test_unknown_rule_suggests(self):
        result = _runner().invoke(cli.main, ["explain", "quality/deep-nestin"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Did you mean", result.stderr)
        self.assertIn("quality/deep-nesting", result.stderr)
        self.assertEqual(result.stdout.strip(), "")


class DefaultCommandTests(unittest.TestCase):
    def _run(self, content, args):
        with tempfile.TemporaryDirectory() as tmp:
            _make_repo(tmp, content)
            return _runner().invoke(cli.main, args(tmp))

    def test_old_style_and_explicit_review_match(self):
        old = self._run(ERROR_LINE, lambda t: ["--path", t, "--format", "json"])
        new = self._run(ERROR_LINE, lambda t: ["review", "--path", t, "--format", "json"])
        self.assertEqual(old.exit_code, 1)
        self.assertEqual(new.exit_code, 1)
        self.assertEqual(
            [v["rule_id"] for v in json.loads(old.stdout)["violations"]],
            [v["rule_id"] for v in json.loads(new.stdout)["violations"]],
        )

    def test_clean_diff_passes(self):
        result = self._run(CLEAN_LINE, lambda t: ["--path", t, "--format", "json"])
        self.assertEqual(result.exit_code, 0)

    def test_group_help_lists_subcommands(self):
        result = _runner().invoke(cli.main, ["--help"])
        self.assertEqual(result.exit_code, 0)
        for name in ("review", "rules", "explain"):
            self.assertIn(name, result.stdout)


if __name__ == "__main__":
    unittest.main()
