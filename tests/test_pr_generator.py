"""Unit tests for PR description generator."""

import unittest
from reviewer.models import FileDiff, ReviewReport
from reviewer.pr_generator import generate_pr_payload, categorize_file, detect_pr_type


class TestPRGenerator(unittest.TestCase):
    def test_categorize_file(self):
        self.assertEqual(categorize_file("tests/test_app.py"), "Tests")
        self.assertEqual(categorize_file("README.md"), "Documentation")
        self.assertEqual(categorize_file("package.json"), "Configuration & Infrastructure")
        self.assertEqual(categorize_file("scripts/run.sh"), "Scripts & Tooling")
        self.assertEqual(categorize_file("src/service.ts"), "Core Logic & Application")

    def test_detect_pr_type(self):
        commits = [{"subject": "feat: add user authentication", "author": "dev", "hash": "abc"}]
        self.assertEqual(detect_pr_type(commits, []), "feat")

        commits_fix = [{"subject": "fix: resolve memory leak", "author": "dev", "hash": "abc"}]
        self.assertEqual(detect_pr_type(commits_fix, []), "fix")

    def test_generate_pr_payload(self):
        diff = FileDiff(
            file_path="src/index.ts",
            added_lines=[(1, "export const x = 1;")],
        )
        report = ReviewReport(
            target_ref="feature",
            base_ref="main",
            files_analyzed=1,
            lines_analyzed=1,
            violations=[],
        )
        payload = generate_pr_payload(
            file_diffs=[diff],
            report=report,
            base_branch="main",
        )
        self.assertIn("title", payload)
        self.assertIn("body", payload)
        self.assertIn("head", payload)
        self.assertEqual(payload["base"], "main")
        self.assertIn("Automated Local Review Gate", payload["body"])


if __name__ == "__main__":
    unittest.main()
