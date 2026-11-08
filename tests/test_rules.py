"""Unit tests for Reviewer custom rules."""

import unittest
from reviewer.models import FileDiff, Severity
from reviewer.rules.curly_braces import CurlyBracesRule
from reviewer.rules.secrets import SecretDetectionRule
from reviewer.rules.debug_code import NoDebugCodeRule
from reviewer.rules.style import StyleGuideRule
from reviewer.rules.commit_message import CommitMessageRule


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

    def test_bare_breakpoint_at_end_of_line_flagged(self):
        diff = FileDiff(file_path="src/app.py", added_lines=[(3, "    breakpoint()")])  # reviewer:allow-debug
        ids = [v.rule_id for v in self.rule.check(diff)]
        self.assertIn("quality/no-breakpoint", ids)

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


class TestCommitMessageRule(unittest.TestCase):
    def setUp(self):
        self.rule = CommitMessageRule()

    def test_clean_conventional_commit_passed(self):
        commits = [
            {"hash": "1234567", "subject": "feat: add user authentication", "author": "dev"}
        ]
        violations = self.rule.check_commits(commits)
        self.assertEqual(len(violations), 0)

    def test_vague_commit_flagged_as_error(self):
        commits = [
            {"hash": "1234567", "subject": "fixed stuff", "author": "dev"}
        ]
        violations = self.rule.check_commits(commits)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].rule_id, "git/commit-vague-message")
        self.assertEqual(violations[0].severity, Severity.ERROR)

    def test_overly_long_subject_flagged(self):
        long_msg = "feat: " + "a" * 80
        commits = [
            {"hash": "1234567", "subject": long_msg, "author": "dev"}
        ]
        violations = self.rule.check_commits(commits)
        rule_ids = [v.rule_id for v in violations]
        self.assertIn("git/commit-message-too-long", rule_ids)

    def test_generated_merge_commits_skipped(self):
        commits = [
            {"hash": "1", "subject": "Merge pull request #2 from someone/feat/a-very-long-branch-name-here"},
            {"hash": "2", "subject": "Merge branch 'fix/output-encoding-and-json-stdout'"},
            {"hash": "3", "subject": "Merge remote-tracking branch 'origin/main'"},
        ]
        self.assertEqual(self.rule.check_commits(commits), [])

    def test_hand_written_merge_subject_still_checked(self):
        commits = [{"hash": "1", "subject": "Merge stuff"}]
        self.assertNotEqual(self.rule.check_commits(commits), [])


class TestCodeQualityRule(unittest.TestCase):
    """Tests for the Code Quality / Anti-AI-Slop rule."""

    def setUp(self):
        from reviewer.rules.code_quality import CodeQualityRule
        self.rule = CodeQualityRule()

    def _diff(self, path, lines):
        from reviewer.models import FileDiff
        return FileDiff(file_path=path, added_lines=lines)

    # -- unnecessary else after return ---------------------------------------

    def test_unnecessary_else_after_return_flagged(self):
        diff = self._diff("src/auth.py", [
            (1, "    return None"),
            (2, "else:"),
        ])
        violations = self.rule.check(diff)
        ids = [v.rule_id for v in violations]
        self.assertIn("quality/unnecessary-else-after-return", ids)

    def test_unnecessary_else_cstyle_flagged(self):
        diff = self._diff("src/index.ts", [
            (1, "        return value;"),
            (2, "    } else {"),
        ])
        violations = self.rule.check(diff)
        ids = [v.rule_id for v in violations]
        self.assertIn("quality/unnecessary-else-after-return", ids)

    def test_else_without_preceding_return_allowed(self):
        diff = self._diff("src/index.ts", [
            (1, "        doSomething();"),
            (2, "    } else {"),
        ])
        violations = self.rule.check(diff)
        ids = [v.rule_id for v in violations]
        self.assertNotIn("quality/unnecessary-else-after-return", ids)

    # -- complex elif chain -------------------------------------------------

    def test_long_elif_chain_flagged(self):
        diff = self._diff("src/handler.py", [
            (1, "if action == 'create':"),
            (2, "    create()"),
            (3, "elif action == 'update':"),
            (4, "    update()"),
            (5, "elif action == 'delete':"),
            (6, "    delete()"),
            (7, "elif action == 'list':"),
            (8, "    list_items()"),
        ])
        violations = self.rule.check(diff)
        ids = [v.rule_id for v in violations]
        self.assertIn("quality/complex-if-else-chain", ids)

    def test_short_elif_chain_allowed(self):
        diff = self._diff("src/handler.py", [
            (1, "if action == 'create':"),
            (2, "    create()"),
            (3, "elif action == 'update':"),
            (4, "    update()"),
        ])
        violations = self.rule.check(diff)
        ids = [v.rule_id for v in violations]
        self.assertNotIn("quality/complex-if-else-chain", ids)

    def test_long_cstyle_else_if_chain_flagged(self):
        diff = self._diff("src/router.ts", [
            (1,  "if (method === 'GET') {"),
            (2,  "} else if (method === 'POST') {"),
            (3,  "} else if (method === 'PUT') {"),
            (4,  "} else if (method === 'PATCH') {"),
            (5,  "} else if (method === 'DELETE') {"),
        ])
        violations = self.rule.check(diff)
        ids = [v.rule_id for v in violations]
        self.assertIn("quality/complex-if-else-chain", ids)

    # -- magic literal repetition -------------------------------------------

    def test_repeated_literal_flagged(self):
        diff = self._diff("src/config.py", [
            (1, "    timeout = 30"),
            (2, "    max_wait = 30"),
            (3, "    retry_delay = 30"),
        ])
        violations = self.rule.check(diff)
        ids = [v.rule_id for v in violations]
        self.assertIn("quality/magic-literal-repetition", ids)

    def test_repeated_string_literal_flagged(self):
        diff = self._diff("src/routes.py", [
            (1,  "    url = '/api/v1/users'"),
            (2,  "    base = '/api/v1/users'"),
            (3,  "    prefix = '/api/v1/users'"),
        ])
        violations = self.rule.check(diff)
        ids = [v.rule_id for v in violations]
        self.assertIn("quality/magic-literal-repetition", ids)

    def test_common_literal_ignored(self):
        """0 and 1 are too common to flag."""
        diff = self._diff("src/loop.py", [
            (1, "    i = 0"),
            (2, "    j = 0"),
            (3, "    k = 0"),
        ])
        violations = self.rule.check(diff)
        ids = [v.rule_id for v in violations]
        self.assertNotIn("quality/magic-literal-repetition", ids)

    # -- duplicated adjacent lines ------------------------------------------

    def test_duplicate_adjacent_lines_flagged(self):
        diff = self._diff("src/setup.py", [
            (1, "    db.execute(INSERT_USER_SQL, params)"),
            (2, "    db.execute(INSERT_USER_SQL, params)"),
            (3, "    db.execute(INSERT_USER_SQL, params)"),
        ])
        violations = self.rule.check(diff)
        ids = [v.rule_id for v in violations]
        self.assertIn("quality/duplicated-code-pattern", ids)

    def test_varied_adjacent_lines_allowed(self):
        diff = self._diff("src/setup.py", [
            (1, "    db.execute(INSERT_USER_SQL, params)"),
            (2, "    db.execute(INSERT_ROLE_SQL, role_params)"),
            (3, "    db.execute(INSERT_PERM_SQL, perm_params)"),
        ])
        violations = self.rule.check(diff)
        ids = [v.rule_id for v in violations]
        self.assertNotIn("quality/duplicated-code-pattern", ids)

    # -- markdown files skipped ---------------------------------------------

    def test_markdown_files_skipped(self):
        diff = self._diff("README.md", [
            (1, "    return None"),
            (2, "else:"),
        ])
        violations = self.rule.check(diff)
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
