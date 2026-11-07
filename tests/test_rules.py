"""Unit tests for Reviewer custom rules."""

import unittest
from reviewer.models import FileDiff, Severity
from reviewer.rules.curly_braces import CurlyBracesRule
from reviewer.rules.secrets import SecretDetectionRule
from reviewer.rules.debug_code import NoDebugCodeRule
from reviewer.rules.style import StyleGuideRule


class TestCurlyBracesRule(unittest.TestCase):
    def setUp(self):
        self.rule = CurlyBracesRule()

    def test_single_line_if_detected(self):
        diff = FileDiff(
            file_path="src/auth.ts",
            added_lines=[
                (10, "if (!user) return null;"),
            ],
        )
        violations = self.rule.check(diff)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].rule_id, "syntax/curly-braces-required")
        self.assertEqual(violations[0].severity, Severity.ERROR)

    def test_single_line_else_detected(self):
        diff = FileDiff(
            file_path="src/index.js",
            added_lines=[
                (15, "else doSomething();"),
            ],
        )
        violations = self.rule.check(diff)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].rule_id, "syntax/curly-braces-required")

    def test_braced_if_allowed(self):
        diff = FileDiff(
            file_path="src/auth.ts",
            added_lines=[
                (10, "if (!user) {"),
                (11, "    return null;"),
                (12, "}"),
            ],
        )
        violations = self.rule.check(diff)
        self.assertEqual(len(violations), 0)

    def test_python_file_ignored(self):
        diff = FileDiff(
            file_path="src/auth.py",
            added_lines=[
                (10, "if not user: return None"),
            ],
        )
        violations = self.rule.check(diff)
        self.assertEqual(len(violations), 0)


class TestSecretDetectionRule(unittest.TestCase):
    def setUp(self):
        self.rule = SecretDetectionRule()

    def test_aws_key_detected(self):
        diff = FileDiff(
            file_path="config/aws.py",
            added_lines=[
                (5, "AWS_ACCESS_KEY = 'AKIAIOSFODNN7EXAMPLE'"),  # reviewer:ignore
            ],
        )
        violations = self.rule.check(diff)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].rule_id, "security/aws-access-key")
        self.assertEqual(violations[0].severity, Severity.ERROR)
        # Secret should be redacted in snippet
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", violations[0].snippet)  # reviewer:ignore
        self.assertIn("AKIA...MPLE", violations[0].snippet)

    def test_github_token_detected(self):
        diff = FileDiff(
            file_path="scripts/ci.sh",
            added_lines=[
                (3, "export GH_TOKEN=ghp_1234567890abcdefghijklmnopqrstuvwxyz"),  # reviewer:ignore
            ],
        )
        violations = self.rule.check(diff)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].rule_id, "security/github-token")

    def test_database_connection_string_with_password(self):
        diff = FileDiff(
            file_path="server.js",
            added_lines=[
                (12, "const uri = 'postgres://admin:SecretPass123@localhost:5432/mydb';"),  # reviewer:ignore
            ],
        )
        violations = self.rule.check(diff)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].rule_id, "security/connection-string-credential")


class TestNoDebugCodeRule(unittest.TestCase):
    def setUp(self):
        self.rule = NoDebugCodeRule()

    def test_console_log_flagged(self):
        diff = FileDiff(
            file_path="src/component.tsx",
            added_lines=[
                (22, "console.log('Rendering widget', data);"),
            ],
        )
        violations = self.rule.check(diff)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].rule_id, "quality/no-console-log")

    def test_debugger_flagged_as_error(self):
        diff = FileDiff(
            file_path="src/component.tsx",
            added_lines=[
                (30, "debugger;"),
            ],
        )
        violations = self.rule.check(diff)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].severity, Severity.ERROR)

    def test_todo_comment_flagged_as_info(self):
        diff = FileDiff(
            file_path="src/service.py",
            added_lines=[
                (45, "# TODO: Implement rate limiting"),  # reviewer:ignore
            ],
        )
        violations = self.rule.check(diff)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].rule_id, "quality/no-todo-comments")
        self.assertEqual(violations[0].severity, Severity.INFO)

    def test_tracked_todo_allowed(self):
        diff = FileDiff(
            file_path="src/service.py",
            added_lines=[
                (45, "# TODO(#123): Refactor when v2 API is stable"),
                (46, "# TODO(PROJ-456): Tracked backlog task"),
            ],
        )
        violations = self.rule.check(diff)
        self.assertEqual(len(violations), 0)

    def test_allow_debug_directive_respected(self):
        diff = FileDiff(
            file_path="src/component.tsx",
            added_lines=[
                (22, "console.log('Intentional output', data); // reviewer:allow-debug"),
                (23, "debugger; // noqa"),
            ],
        )
        violations = self.rule.check(diff)
        self.assertEqual(len(violations), 0)


class TestStyleGuideRule(unittest.TestCase):
    def setUp(self):
        self.rule = StyleGuideRule()

    def test_mixed_indentation_detected(self):
        diff = FileDiff(
            file_path="lib/helper.js",
            added_lines=[
                (10, "\t   const a = 1;"),
            ],
        )
        violations = self.rule.check(diff)
        rule_ids = [v.rule_id for v in violations]
        self.assertIn("style/mixed-indentation", rule_ids)

    def test_eval_detected(self):
        diff = FileDiff(
            file_path="lib/calc.js",
            added_lines=[
                (5, "const res = eval(inputExpr);"),  # reviewer:ignore
            ],
        )
        violations = self.rule.check(diff)
        rule_ids = [v.rule_id for v in violations]
        self.assertIn("security/no-eval", rule_ids)


if __name__ == "__main__":
    unittest.main()
