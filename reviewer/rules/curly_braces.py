"""Rule to enforce curly braces on control flow statements (Anti-AI Guardrail)."""

import os
import re
from typing import List
from reviewer.models import FileDiff, Violation, Severity
from reviewer.rules.base import BaseRule, RuleInfo, register_rule

CURLY_SUPPORTED_EXTENSIONS = {
    ".js", ".jsx", ".mjs", ".cjs",
    ".ts", ".tsx",
    ".java", ".c", ".cpp", ".cc", ".cxx", ".h", ".hpp",
    ".cs", ".php", ".swift", ".kt", ".dart", ".rs", ".go"
}

# Regex to detect single-line control structures missing opening brace
# Matches: if (...) stmt; | else stmt; | for (...) stmt; | while (...) stmt;
SINGLE_LINE_PATTERN = re.compile(
    r"^\s*(?:else\s+)?(?:if|for|while)\s*\([^)]*\)\s*(?!\{)(?!\s*$).+;?\s*$",
    re.MULTILINE
)

# Pattern for trailing else missing brace on same line: else stmt; (and not 'else if')
ELSE_SINGLE_LINE_PATTERN = re.compile(
    r"^\s*else\s+(?!if\b)(?!\{)\s*.+;?\s*$",
    re.MULTILINE
)


@register_rule
class CurlyBracesRule(BaseRule):
    """Enforces explicit curly braces on single-line or unbraced control flow statements."""
    rule_id = "syntax/curly-braces-required"
    name = "Enforce Curly Braces"
    description = (
        "AI models frequently omit curly braces on single-line if/else/for statements, "
        "introducing indentation bugs and style violations. Explicit braces are required."
    )
    severity = Severity.ERROR

    def catalog(self) -> List[RuleInfo]:
        return [RuleInfo(
            self.rule_id, self.name, self.severity, self.description,
            "Wrap the statement body in curly braces: if (...) { ... }",
        )]

    def check(self, file_diff: FileDiff) -> List[Violation]:
        ext = os.path.splitext(file_diff.file_path)[1].lower()
        if ext not in CURLY_SUPPORTED_EXTENSIONS:
            return []

        violations: List[Violation] = []
        added_lines_map = {line_no: text for line_no, text in file_diff.added_lines}

        for idx, (line_no, line_text) in enumerate(file_diff.added_lines):
            stripped = line_text.strip()
            # Ignore comments
            if stripped.startswith("//") or stripped.startswith("/*") or stripped.startswith("*"):
                continue

            # Case 1: Single line 'if (cond) action;'
            if SINGLE_LINE_PATTERN.match(line_text):
                # Ensure it's not ending with a block or continuation
                if not stripped.endswith("{"):
                    violations.append(
                        Violation(
                            file_path=file_diff.file_path,
                            line_number=line_no,
                            rule_id=self.rule_id,
                            rule_name=self.name,
                            severity=self.severity,
                            message="Single-line control statement missing required curly braces '{ }'.",
                            snippet=line_text.strip(),
                            suggestion=f"Wrap statement body in curly braces: if (...) {{\n    ...\n}}",
                        )
                    )
                    continue

            # Case 2: Single line 'else action;'
            if ELSE_SINGLE_LINE_PATTERN.match(line_text):
                if not stripped.endswith("{"):
                    violations.append(
                        Violation(
                            file_path=file_diff.file_path,
                            line_number=line_no,
                            rule_id=self.rule_id,
                            rule_name=self.name,
                            severity=self.severity,
                            message="'else' branch missing required curly braces '{ }'.",
                            snippet=line_text.strip(),
                            suggestion="Wrap statement body in curly braces: else {\n    ...\n}",
                        )
                    )
                    continue

            # Case 3: 'if (cond)' on one line, and the next line is the body without braces
            if re.match(r"^\s*(?:else\s+)?(?:if|for|while)\s*\([^)]*\)\s*$", line_text):
                # Check next line in diff or file
                next_line_no = line_no + 1
                if next_line_no in added_lines_map:
                    next_text = added_lines_map[next_line_no].strip()
                    if next_text and not next_text.startswith("{"):
                        violations.append(
                            Violation(
                                file_path=file_diff.file_path,
                                line_number=line_no,
                                rule_id=self.rule_id,
                                rule_name=self.name,
                                severity=self.severity,
                                message="Control flow statement body is not wrapped in curly braces '{ }'.",
                                snippet=f"{line_text.strip()} -> {next_text}",
                                suggestion="Add curly braces '{ }' around the subordinate block.",
                            )
                        )

        return violations
