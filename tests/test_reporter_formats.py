"""Tests for SARIF and GitHub annotation output formats."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from reviewer import __version__, cli  # noqa: E402
from reviewer.formats import (  # noqa: E402
    format_github_command,
    generate_github,
    generate_sarif,
)
from reviewer.models import ReviewReport, Severity, Violation  # noqa: E402
from test_cli import ERROR_LINE, _make_repo, _runner  # noqa: E402


def _v(*, path="a.py", line=3, rule="security/x", sev=Severity.ERROR, msg="bad", sug="fix it", snippet="x = 1"):
    return Violation(
        file_path=path,
        line_number=line,
        rule_id=rule,
        rule_name="Rule " + rule,
        severity=sev,
        message=msg,
        snippet=snippet,
        suggestion=sug,
    )


def _report(violations):
    return ReviewReport("HEAD", "main", 1, 1, violations=violations)


class SarifTests(unittest.TestCase):
    def test_top_level_structure(self):
        doc = generate_sarif(_report([_v()]))
        self.assertEqual(doc["$schema"], "https://json.schemastore.org/sarif-2.1.0.json")
        self.assertEqual(doc["version"], "2.1.0")
        self.assertEqual(len(doc["runs"]), 1)
        driver = doc["runs"][0]["tool"]["driver"]
        self.assertEqual(driver["name"], "reviewer")
        self.assertEqual(driver["version"], __version__)
        self.assertIn("informationUri", driver)
        result = doc["runs"][0]["results"][0]
        for key in ("ruleId", "ruleIndex", "level", "message", "locations", "partialFingerprints"):
            self.assertIn(key, result)
        self.assertIn("bad", result["message"]["text"])
        self.assertIn("fix it", result["message"]["text"])

    def test_level_mapping(self):
        doc = generate_sarif(_report([
            _v(rule="r/e", sev=Severity.ERROR),
            _v(rule="r/w", sev=Severity.WARNING),
            _v(rule="r/i", sev=Severity.INFO),
        ]))
        levels = [r["level"] for r in doc["runs"][0]["results"]]
        self.assertEqual(levels, ["error", "warning", "note"])
        rule_levels = [r["defaultConfiguration"]["level"] for r in doc["runs"][0]["tool"]["driver"]["rules"]]
        self.assertEqual(rule_levels, ["error", "warning", "note"])

    def test_rules_and_rule_index_consistent(self):
        doc = generate_sarif(_report([_v(rule="a/1"), _v(rule="b/2"), _v(rule="a/1", line=9)]))
        run = doc["runs"][0]
        rules = run["tool"]["driver"]["rules"]
        self.assertEqual([r["id"] for r in rules], ["a/1", "b/2"])
        for result in run["results"]:
            self.assertEqual(rules[result["ruleIndex"]]["id"], result["ruleId"])
        self.assertEqual(rules[0]["help"]["text"], "fix it")

    def test_uri_is_relative_forward_slash(self):
        for raw in ("src\\pkg\\mod.py", "./src/pkg/mod.py", "src/pkg/mod.py"):
            doc = generate_sarif(_report([_v(path=raw)]))
            loc = doc["runs"][0]["results"][0]["locations"][0]["physicalLocation"]
            self.assertEqual(loc["artifactLocation"]["uri"], "src/pkg/mod.py")

    def test_start_line_at_least_one(self):
        doc = generate_sarif(_report([_v(line=0)]))
        loc = doc["runs"][0]["results"][0]["locations"][0]["physicalLocation"]
        self.assertEqual(loc["region"]["startLine"], 1)

    def test_commit_violation_has_no_locations(self):
        doc = generate_sarif(_report([_v(path="commit:abc123", line=0, rule="git/commit")]))
        result = doc["runs"][0]["results"][0]
        self.assertNotIn("locations", result)
        self.assertEqual(result["properties"]["commit"], "abc123")

    def test_fingerprint_stable_and_distinct(self):
        a = generate_sarif(_report([_v(snippet="x  =  1")]))["runs"][0]["results"][0]
        b = generate_sarif(_report([_v(snippet="x = 1", line=50)]))["runs"][0]["results"][0]
        c = generate_sarif(_report([_v(snippet="y = 2")]))["runs"][0]["results"][0]
        key = "primaryLocationLineHash"
        self.assertEqual(a["partialFingerprints"][key], b["partialFingerprints"][key])
        self.assertNotEqual(a["partialFingerprints"][key], c["partialFingerprints"][key])

    def test_empty_report(self):
        doc = generate_sarif(_report([]))
        self.assertEqual(doc["runs"][0]["results"], [])
        self.assertEqual(doc["runs"][0]["tool"]["driver"]["rules"], [])


class GithubTests(unittest.TestCase):
    def test_severities(self):
        self.assertTrue(format_github_command(_v(sev=Severity.ERROR)).startswith("::error "))
        self.assertTrue(format_github_command(_v(sev=Severity.WARNING)).startswith("::warning "))
        self.assertTrue(format_github_command(_v(sev=Severity.INFO)).startswith("::notice "))

    def test_full_command(self):
        cmd = format_github_command(_v(path="src\\a.py", line=7, rule="quality/deep-nesting", msg="too deep"))
        self.assertEqual(cmd, "::error file=src/a.py,line=7,title=quality/deep-nesting::too deep")

    def test_message_escaping(self):
        cmd = format_github_command(_v(msg="100% bad: a, b\r\nnext"))
        self.assertTrue(cmd.endswith("::100%25 bad: a, b%0D%0Anext"))

    def test_property_escaping(self):
        cmd = format_github_command(_v(path="dir/a:b,c.py", rule="r:1,2"))
        self.assertIn("file=dir/a%3Ab%2Cc.py,", cmd)
        self.assertIn("title=r%3A1%2C2::", cmd)

    def test_commit_omits_file_and_line(self):
        cmd = format_github_command(_v(path="commit:abc", rule="git/x", sev=Severity.WARNING))
        self.assertEqual(cmd, "::warning title=git/x::bad")

    def test_one_line_per_violation(self):
        out = generate_github(_report([_v(), _v(line=4)]))
        self.assertEqual(len(out.splitlines()), 2)


class CliFormatTests(unittest.TestCase):
    def _run(self, fmt):
        with tempfile.TemporaryDirectory() as tmp:
            _make_repo(tmp, ERROR_LINE)
            return _runner().invoke(cli.main, ["--path", tmp, "--format", fmt])

    def test_sarif_stdout_is_valid_json(self):
        result = self._run("sarif")
        doc = json.loads(result.stdout)
        self.assertEqual(doc["version"], "2.1.0")
        self.assertTrue(doc["runs"][0]["results"])
        self.assertNotIn("Saved reports", result.stdout)
        self.assertEqual(result.exit_code, 1)
        uri = doc["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
        self.assertEqual(uri, "app.py")

    def test_github_stdout_only_commands(self):
        result = self._run("github")
        lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
        self.assertTrue(lines)
        for line in lines:
            self.assertTrue(line.startswith(("::error ", "::warning ", "::notice ")), line)
        self.assertNotIn("Saved reports", result.stdout)
        self.assertEqual(result.exit_code, 1)


if __name__ == "__main__":
    unittest.main()
