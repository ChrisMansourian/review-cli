"""Tests for the reviewer configuration file support."""

import json
import os
import tempfile
import unittest

from reviewer import cli
from reviewer.config import (
    ReviewerConfig,
    build_config,
    get_config,
    load_config,
    path_matches,
    set_config,
)
from reviewer.models import FileDiff, Severity, Violation
from reviewer.rules.base import BaseRule, RuleRegistry
from test_cli import _git, _make_repo, _runner

PARAMS3 = "def f(a, b, c):\n    return a\n"
PARAMS5 = "def f(a, b, c, d, e):\n    return a\n"
LONG_LINE = "x = '" + "a" * 130 + "'\n"
TRAILING = "x = 1 \n"
CLEAN = "y = 1\n"
LONG_PARAMS = "quality/long-parameter-list"


def _write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class ConfigTestCase(unittest.TestCase):
    def setUp(self):
        set_config(None)

    def tearDown(self):
        set_config(None)

    def run_cli(self, content, config_text=None, **opts):
        """Run the CLI in a temp repo; returns (result, parsed json or None)."""
        config_name = opts.get("config_name", ".reviewer.toml")
        extra = opts.get("extra", ())
        new_file = opts.get("new_file")
        with tempfile.TemporaryDirectory() as tmp:
            _make_repo(tmp, content)
            if new_file:
                rel, text = new_file
                full = os.path.join(tmp, *rel.split("/"))
                os.makedirs(os.path.dirname(full), exist_ok=True)
                _write(full, text)
                _git(["add", "."], tmp)
            if config_text is not None:
                _write(os.path.join(tmp, config_name), config_text)
            args = ["--path", tmp, "--format", "json"] + list(extra)
            result = _runner().invoke(cli.main, args)
            try:
                data = json.loads(result.stdout)
            except ValueError:
                data = None
            return result, data

    @staticmethod
    def ids(data):
        return [v["rule_id"] for v in data["violations"]]


class DefaultTests(ConfigTestCase):
    def test_defaults_match_previous_constants(self):
        cfg = ReviewerConfig()
        self.assertEqual(
            (cfg.max_params, cfg.max_nesting, cfg.max_function_lines, cfg.max_line_length),
            (4, 4, 50, 120),
        )
        self.assertEqual((cfg.elif_chain, cfg.literal_repeat, cfg.duplicate_lines), (3, 3, 3))

    def test_no_config_flags_five_params_not_three(self):
        _, data = self.run_cli(PARAMS5)
        self.assertIn(LONG_PARAMS, self.ids(data))
        _, data = self.run_cli(PARAMS3)
        self.assertNotIn(LONG_PARAMS, self.ids(data))


class DisableAndSeverityTests(ConfigTestCase):
    def test_disable_glob(self):
        _, data = self.run_cli(TRAILING + LONG_LINE)
        self.assertTrue(any(i.startswith("style/") for i in self.ids(data)))
        _, data = self.run_cli(TRAILING + LONG_LINE, 'disable = ["style/*"]\n')
        self.assertFalse(any(i.startswith("style/") for i in self.ids(data)))

    def test_disable_exact_sub_rule(self):
        _, data = self.run_cli(PARAMS5, 'disable = ["quality/long-parameter-list"]\n')
        self.assertNotIn(LONG_PARAMS, self.ids(data))

    def test_severity_override_on_sub_rule(self):
        _, data = self.run_cli(PARAMS5, '[severity]\n"quality/long-parameter-list" = "info"\n')
        found = [v for v in data["violations"] if v["rule_id"] == LONG_PARAMS]
        self.assertTrue(found)
        self.assertEqual(found[0]["severity"], "INFO")

    def test_severity_error_changes_exit_code(self):
        result, _ = self.run_cli(PARAMS5, '[severity]\n"quality/long-parameter-list" = "ERROR"\n')
        self.assertEqual(result.exit_code, 1)

    def test_registry_applies_to_commit_violations(self):
        class CommitRule(BaseRule):
            rule_id = "commit/test"

            def check(self, file_diff):
                return []

            def check_commits(self, commits):
                return [Violation("c", 0, "commit/test", "n", Severity.WARNING, "m")]

        registry = RuleRegistry()
        registry.register(CommitRule())
        commits = [{"hash": "a", "subject": "s", "body": "", "author": "x"}]
        cfg = build_config({"severity": {"commit/test": "ERROR"}}, [])
        self.assertEqual(registry.execute_all([], commits, config=cfg)[0].severity, Severity.ERROR)
        cfg = build_config({"disable": ["commit/*"]}, [])
        self.assertEqual(registry.execute_all([], commits, config=cfg), [])
        # backward compatible: no config argument and no active config
        self.assertEqual(len(registry.execute_all([], commits)), 1)


class IgnorePathTests(ConfigTestCase):
    def test_double_star_matching(self):
        pats = ("tests/fixtures/**",)
        self.assertTrue(path_matches("tests/fixtures/a/b.py", pats))
        self.assertTrue(path_matches("tests/fixtures/b.py", pats))
        self.assertFalse(path_matches("tests/test_x.py", pats))
        self.assertTrue(path_matches("a/b/migrations/0001.py", ("**/migrations/**",)))
        self.assertTrue(path_matches("migrations/0001.py", ("**/migrations/**",)))
        self.assertTrue(path_matches("pkg\\gen\\x.py", ("pkg/gen/**",)))
        self.assertTrue(path_matches("deep/dir/x.min.py", ("*.min.py",)))
        self.assertFalse(path_matches("a/b.py", ("src/*.py",)))

    def test_ignore_paths_skips_files_in_cli(self):
        new_file = ("tests/fixtures/bad.py", PARAMS5)
        _, data = self.run_cli(CLEAN, None, new_file=new_file)
        self.assertIn("tests/fixtures/bad.py", [v["file_path"] for v in data["violations"]])
        _, data = self.run_cli(CLEAN, 'ignore_paths = ["tests/fixtures/**"]\n', new_file=new_file)
        self.assertNotIn("tests/fixtures/bad.py", [v["file_path"] for v in data["violations"]])


class ThresholdTests(ConfigTestCase):
    def test_max_params_flags_three_and_message_reflects_value(self):
        _, data = self.run_cli(PARAMS3, "[thresholds]\nmax_params = 2\n")
        found = [v for v in data["violations"] if v["rule_id"] == LONG_PARAMS]
        self.assertEqual(len(found), 1)
        self.assertIn("(max 2)", found[0]["message"])

    def test_max_line_length(self):
        line = "x = '" + "a" * 60 + "'\n"
        _, data = self.run_cli(line)
        self.assertNotIn("style/line-too-long", self.ids(data))
        _, data = self.run_cli(line, "[thresholds]\nmax_line_length = 40\n")
        found = [v for v in data["violations"] if v["rule_id"] == "style/line-too-long"]
        self.assertEqual(len(found), 1)
        self.assertIn("maximum of 40", found[0]["message"])

    def test_max_function_lines_via_active_config(self):
        from reviewer.rules import default_registry

        text = "def g():\n" + "".join("    v%d = %d\n" % (i, i + 5) for i in range(6))
        fd = FileDiff("m.py", added_lines=list(enumerate(text.splitlines(), start=1)))
        fd.full_content = text
        self.assertNotIn("quality/god-function", [v.rule_id for v in default_registry.execute_all([fd])])
        set_config(build_config({"thresholds": {"max_function_lines": 3}}, []))
        found = [v for v in default_registry.execute_all([fd]) if v.rule_id == "quality/god-function"]
        self.assertEqual(len(found), 1)
        self.assertIn("max 3", found[0].message)

    def test_invalid_threshold_warns_and_keeps_default(self):
        warnings = []
        cfg = build_config({"thresholds": {"max_params": "x", "bogus": 1}}, warnings)
        self.assertEqual(cfg.max_params, 4)
        self.assertEqual(len(warnings), 2)


class LoadingTests(ConfigTestCase):
    def test_pyproject_tool_reviewer(self):
        text = '[project]\nname = "x"\n\n[tool.reviewer.thresholds]\nmax_params = 2\n'
        _, data = self.run_cli(PARAMS3, text, config_name="pyproject.toml")
        self.assertIn(LONG_PARAMS, self.ids(data))

    def test_pyproject_wins_over_reviewer_toml(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(os.path.join(tmp, "pyproject.toml"), "[tool.reviewer.thresholds]\nmax_params = 7\n")
            _write(os.path.join(tmp, ".reviewer.toml"), "[thresholds]\nmax_params = 2\n")
            cfg, warnings = load_config(tmp)
        self.assertEqual(cfg.max_params, 7)
        self.assertEqual(warnings, [])

    def test_pyproject_without_table_falls_back_to_reviewer_toml(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(os.path.join(tmp, "pyproject.toml"), '[project]\nname = "x"\n')
            _write(os.path.join(tmp, ".reviewer.toml"), "[thresholds]\nmax_params = 2\n")
            cfg, _ = load_config(tmp)
        self.assertEqual(cfg.max_params, 2)

    def test_reviewer_toml_fallback_in_cli(self):
        _, data = self.run_cli(PARAMS3, "[thresholds]\nmax_params = 2\n")
        self.assertIn(LONG_PARAMS, self.ids(data))

    def test_explicit_config_path(self):
        with tempfile.TemporaryDirectory() as other:
            custom = os.path.join(other, "custom.toml")
            _write(custom, "[thresholds]\nmax_params = 2\n")
            _, data = self.run_cli(PARAMS3, None, extra=["--config", custom])
        self.assertIn(LONG_PARAMS, self.ids(data))

    def test_explicit_pyproject_path_uses_tool_table(self):
        with tempfile.TemporaryDirectory() as other:
            custom = os.path.join(other, "pyproject.toml")
            _write(custom, "[tool.reviewer.thresholds]\nmax_params = 2\n")
            _, data = self.run_cli(PARAMS3, None, extra=["--config", custom])
        self.assertIn(LONG_PARAMS, self.ids(data))

    def test_missing_explicit_config_warns(self):
        result, data = self.run_cli(CLEAN, None, extra=["--config", "nope.toml"])
        self.assertIsNotNone(data)
        self.assertIn("file not found", result.stderr)

    def test_unknown_key_and_bad_severity_warn_on_stderr(self):
        text = 'bogus = 1\n[severity]\n"quality/god-function" = "LOUD"\n'
        result, data = self.run_cli(CLEAN, text)
        self.assertIsNotNone(data)  # stdout is still pure JSON
        self.assertIn("unknown key 'bogus'", result.stderr)
        self.assertIn("invalid severity", result.stderr)
        self.assertNotIn("unknown key", result.stdout)

    def test_invalid_toml_does_not_crash(self):
        result, data = self.run_cli(CLEAN, "this is = = not toml\n")
        self.assertIsNotNone(data)
        self.assertIn("could not read", result.stderr)

    def test_missing_toml_parser_warns_and_continues(self):
        import reviewer.config as config_module

        saved = config_module._toml
        config_module._toml = None
        try:
            with tempfile.TemporaryDirectory() as tmp:
                _write(os.path.join(tmp, ".reviewer.toml"), "[thresholds]\nmax_params = 2\n")
                cfg, warnings = load_config(tmp)
        finally:
            config_module._toml = saved
        self.assertEqual(cfg, ReviewerConfig())
        self.assertIn("tomli", warnings[0])

    def test_no_config_file_gives_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, warnings = load_config(tmp)
        self.assertEqual(cfg, ReviewerConfig())
        self.assertEqual(warnings, [])
        self.assertEqual(get_config(), ReviewerConfig())


if __name__ == "__main__":
    unittest.main()
