"""Rule to enforce short, clean, and clear git commit messages."""

import re
from typing import List, Dict
from reviewer.models import FileDiff, Violation, Severity
from reviewer.rules.base import BaseRule, register_rule

# Common conventional commit types
CONVENTIONAL_TYPES = {
    "feat", "fix", "docs", "style", "refactor",
    "perf", "test", "chore", "ci", "build", "revert"
}

# Vague or uninformative commit messages to block
VAGUE_MESSAGES = {
    "update", "updates", "fixed", "fix", "fixes", "wip",
    "temp", "temporary", "changes", "stuff", "asdf",
    "commit", "misc", "test", "testing", "working",
    "work in progress", "checkpoint", "quick fix", "minor fix"
}

# Subjects git/GitHub generate for merge commits; nobody authored these.
GIT_MERGE_SUBJECT_RE = re.compile(
    r"^Merge (pull request #\d+|(remote-tracking )?branch(es)? '|tag '|commit [0-9a-f]{7,})"
)


@register_rule
class CommitMessageRule(BaseRule):
    """Enforces short, clean, and clear commit messages describing exact changes."""
    rule_id = "git/commit-message-format"
    name = "Clean & Clear Commit Messages"
    description = (
        "Commit messages must be short, clean, and clearly describe what changed. "
        "Prefers conventional commit format (e.g. 'feat: add ...', 'fix: resolve ...') "
        "and limits subject lines to 72 characters."
    )
    severity = Severity.WARNING

    MAX_SUBJECT_LENGTH = 72

    def check(self, file_diff: FileDiff) -> List[Violation]:
        # Commit rules check commits rather than file diffs
        return []

    def check_commits(self, commits: List[Dict[str, str]]) -> List[Violation]:
        violations: List[Violation] = []

        for commit in commits:
            subject = commit.get("subject", "").strip()
            commit_hash = commit.get("hash", "HEAD")
            if not subject or GIT_MERGE_SUBJECT_RE.match(subject):
                continue

            # Check 1: Vague or lazy message
            normalized = subject.lower().rstrip(".!")
            words = normalized.split()
            is_vague = (
                normalized in VAGUE_MESSAGES
                or len(subject) < 6
                or all(w in VAGUE_MESSAGES for w in words)
                or any(normalized.startswith(p) for p in ["wip", "temp", "fixed stuff", "fix bug"])
            )
            if is_vague:
                violations.append(
                    Violation(
                        file_path=f"commit:{commit_hash}",
                        line_number=1,
                        rule_id="git/commit-vague-message",
                        rule_name="Vague Commit Message",
                        severity=Severity.ERROR,
                        message=(
                            f"Commit '{subject}' is too vague. State clearly what changed "
                            "(e.g., 'fix: handle missing credentials in auth service')."
                        ),
                        snippet=subject,
                        suggestion="Rewrite commit message using: '<type>: <clear summary of what was changed>'.",
                    )
                )
                continue

            # Check 2: Length exceeds 72 characters
            if len(subject) > self.MAX_SUBJECT_LENGTH:
                violations.append(
                    Violation(
                        file_path=f"commit:{commit_hash}",
                        line_number=1,
                        rule_id="git/commit-message-too-long",
                        rule_name="Commit Subject Too Long",
                        severity=Severity.WARNING,
                        message=(
                            f"Commit message subject ({len(subject)} chars) exceeds the {self.MAX_SUBJECT_LENGTH} "
                            "character limit for clean git logs."
                        ),
                        snippet=subject[:60] + "...",
                        suggestion="Keep the commit subject line under 72 characters; use the body for extra context.",
                    )
                )

            # Check 3: Conventional or structured format suggestion
            has_prefix = bool(re.match(r"^[a-zA-Z0-9_\-]+(?:\([a-zA-Z0-9_\-]+\))?!?: ", subject))
            if not has_prefix:
                # Check if it starts with an imperative capital verb
                starts_imperative = bool(re.match(
                    r"^(Add|Fix|Update|Remove|Refactor|Implement|Change|Support|Prevent|Ensure|Clean)\b",
                    subject
                ))
                if not starts_imperative:
                    violations.append(
                        Violation(
                            file_path=f"commit:{commit_hash}",
                            line_number=1,
                            rule_id="git/commit-unstructured-format",
                            rule_name="Unstructured Commit Subject",
                            severity=Severity.INFO,
                            message=f"Commit '{subject}' does not follow conventional commit format.",
                            snippet=subject,
                            suggestion="Use standard prefix like 'feat:', 'fix:', 'refactor:', 'docs:', or an imperative verb.",
                        )
                    )

        return violations
