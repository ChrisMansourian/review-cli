"""Style guide and dangerous pattern checks."""

import os
import re
from typing import List
from reviewer.models import FileDiff, Violation, Severity
from reviewer.rules.base import BaseRule, register_rule

CODE_EXTENSIONS = {
    ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx",
    ".py", ".rb", ".go", ".rs", ".php", ".c", ".cpp", ".cs", ".java"
}

DANGEROUS_PATTERNS = [
    (
        "security/no-eval",
        "Dynamic code evaluation (eval / Function constructor)",
        re.compile(r"(?<!['\"`a-zA-Z0-9_])eval\s*\([^)]*\)"),
        Severity.ERROR,
        "Avoid dynamic code execution with eval(); use safer serialization or parsing alternatives.",
    ),
    (
        "security/subprocess-shell-true",
        "Subprocess execution with shell=True",
        re.compile(r"\bsubprocess\.(Popen|run|call|check_output)\s*\(.*shell\s*=\s*True"),
        Severity.ERROR,
        "Invoking subprocess with shell=True is susceptible to shell injection vulnerabilities. Pass arguments as a list.",
    ),
]


@register_rule
class StyleGuideRule(BaseRule):
    """Enforces style standards including indentation, line length, and trailing whitespace."""
    rule_id = "style/formatting"
    name = "Style Guide Compliance"
    description = "Checks line length, trailing whitespace, and indentation consistency."
    severity = Severity.WARNING

    MAX_LINE_LENGTH = 120

    def check(self, file_diff: FileDiff) -> List[Violation]:
        violations: List[Violation] = []
        ext = os.path.splitext(file_diff.file_path)[1].lower()

        # Markdown / docs / text files can have long links or wrapping
        is_doc = ext in [".md", ".txt", ".rst"]

        for line_no, line_text in file_diff.added_lines:
            # Respect inline bypass directives
            if any(marker in line_text.lower() for marker in [
                "reviewer:ignore",
                "reviewer:allow",
                "noqa",
            ]):
                continue
            # Trailing whitespace check (excluding blank lines)
            if line_text.endswith(" ") or line_text.endswith("\t"):
                if line_text.strip():  # Not an entirely empty line
                    violations.append(
                        Violation(
                            file_path=file_diff.file_path,
                            line_number=line_no,
                            rule_id="style/trailing-whitespace",
                            rule_name="Trailing Whitespace",
                            severity=Severity.INFO,
                            message="Line contains trailing whitespace.",
                            snippet=line_text.rstrip() + " ⮐",
                            suggestion="Remove trailing spaces/tabs before line endings.",
                        )
                    )

            # Mixed indentation check (both tabs and spaces in leading whitespace)
            leading_whitespace = re.match(r"^(\s*)", line_text).group(1)
            if "\t" in leading_whitespace and " " in leading_whitespace:
                violations.append(
                    Violation(
                        file_path=file_diff.file_path,
                        line_number=line_no,
                        rule_id="style/mixed-indentation",
                        rule_name="Mixed Indentation",
                        severity=Severity.WARNING,
                        message="Line mixes tabs and spaces for indentation.",
                        snippet=line_text.strip(),
                        suggestion="Standardize indentation to either spaces or tabs consistently.",
                    )
                )

            # Line length check
            if not is_doc and len(line_text) > self.MAX_LINE_LENGTH:
                # Don't flag URLs or long strings
                if not re.search(r"https?://", line_text):
                    violations.append(
                        Violation(
                            file_path=file_diff.file_path,
                            line_number=line_no,
                            rule_id="style/line-too-long",
                            rule_name="Line Exceeds Length Limit",
                            severity=Severity.INFO,
                            message=f"Line length ({len(line_text)}) exceeds maximum of {self.MAX_LINE_LENGTH} characters.",
                            snippet=line_text[:80] + "...",
                            suggestion="Refactor or wrap line to conform to 120 character limit.",
                        )
                    )

            # Dangerous pattern checks (only for supported code extensions, not docs)
            if ext in CODE_EXTENSIONS:
                stripped = line_text.strip()
                # Ignore string literals, docstrings, and comments
                if not (stripped.startswith("#") or stripped.startswith("//") or stripped.startswith("*")
                        or stripped.startswith('"') or stripped.startswith("'")):
                    for rule_id, rule_name, pattern, severity, suggestion in DANGEROUS_PATTERNS:
                        if pattern.search(line_text):
                            violations.append(
                                Violation(
                                    file_path=file_diff.file_path,
                                    line_number=line_no,
                                    rule_id=rule_id,
                                    rule_name=rule_name,
                                    severity=severity,
                                    message=f"{rule_name} detected.",
                                    snippet=line_text.strip(),
                                    suggestion=suggestion,
                                )
                            )

        return violations
