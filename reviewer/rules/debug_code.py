"""Rule to flag leftover debug code and TODO comments (Anti-AI Guardrail)."""

import os
import re
from typing import List, Tuple
from reviewer.models import FileDiff, Violation, Severity
from reviewer.rules.base import BaseRule, RuleInfo, register_rule

DEBUG_PATTERNS: List[Tuple[str, str, re.Pattern, Severity, str]] = [
    # JavaScript / TypeScript
    (
        "quality/no-console-log",
        "Leftover console.log statement",
        re.compile(r"\bconsole\.(log|debug|info|trace|dir)\s*\("),
        Severity.WARNING,
        "Remove console logging statement before merging to maintain clean production logs.",
    ),
    (
        "quality/no-debugger",
        "Leftover debugger statement",
        re.compile(r"\bdebugger\s*;?"),
        Severity.ERROR,
        "Remove interactive debugger breakpoint statement.",
    ),
    # Python
    (
        "quality/no-python-print",
        "Leftover print() call in Python",
        re.compile(r"^\s*print\s*\(.*\)"),
        Severity.WARNING,
        "Replace print() with structured logger (e.g. logging.getLogger) or remove before merging.",
    ),
    (
        "quality/no-breakpoint",
        "Leftover breakpoint() or pdb call",
        re.compile(r"\bbreakpoint\s*\(|\bpdb\.set_trace\s*\(|\bimport\s+pdb\b"),
        Severity.ERROR,
        "Remove Python breakpoint before merging.",
    ),
    # PHP / Ruby / Go / Rust
    (
        "quality/no-var-dump",
        "Leftover debug dump call",
        re.compile(r"\b(var_dump|dd|print_r|binding\.pry)\s*(\(|;)"),
        Severity.ERROR,
        "Remove leftover debug dump statement.",
    ),
    (
        "quality/no-rust-dbg",
        "Leftover dbg!() macro in Rust",
        re.compile(r"\bdbg!\s*\("),
        Severity.WARNING,
        "Remove dbg!() macro call.",
    ),
    # Marker comments
    (
        "quality/no-todo-comments",
        "Unresolved TODO / FIXME / HACK comment",
        re.compile(r"(?i)(?://|#|/\*|\*)\s*(TODO|FIXME|HACK|XXX)\b\s*[:\-]?(.*)"),
        Severity.INFO,
        "Resolve this pending item or create a tracked issue/ticket instead of leaving inline TODOs.",
    ),
]


@register_rule
class NoDebugCodeRule(BaseRule):
    """Flags leftover debugging statements, breakpoints, and unresolved TODOs."""
    rule_id = "quality/no-debug-code"
    name = "No Debug Code & TODOs"
    description = (
        "Flags leftover console.log, debugger, print(), and TODO comments "
        "frequently left behind during rapid AI prototyping."
    )
    severity = Severity.WARNING

    def catalog(self) -> List[RuleInfo]:
        return [
            RuleInfo(rule_id, name, severity, name, suggestion)
            for rule_id, name, _pattern, severity, suggestion in DEBUG_PATTERNS
        ]

    def check(self, file_diff: FileDiff) -> List[Violation]:
        ext = os.path.splitext(file_diff.file_path)[1].lower()
        # Documentation and config files don't execute debug code
        if ext in [".md", ".txt", ".rst", ".json", ".yaml", ".yml", ".toml"]:
            return []

        violations: List[Violation] = []

        # Don't flag print() in test scripts or CLI entrypoints where print is intentional
        is_cli_or_script = "cli" in file_diff.file_path.lower() or "scripts" in file_diff.file_path.lower()

        for line_no, line_text in file_diff.added_lines:
            stripped = line_text.strip()

            # Allow if explicitly marked with an inline bypass directive
            if any(marker in line_text.lower() for marker in [
                "reviewer:allow-debug",
                "reviewer:ignore",
                "reviewer:allow",
                "noqa",
                "intentional",
            ]):
                continue

            for rule_id, rule_name, pattern, severity, suggestion in DEBUG_PATTERNS:
                # Skip python print check for non-python files or cli scripts
                if rule_id == "quality/no-python-print" and (ext != ".py" or is_cli_or_script):
                    continue
                # Skip console.log for non-js/ts files
                if rule_id in ("quality/no-console-log", "quality/no-debugger") and ext not in (
                    ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte"
                ):
                    continue
                # Skip rust dbg for non-rust files
                if rule_id == "quality/no-rust-dbg" and ext != ".rs":
                    continue
                # Skip var_dump for non-php/ruby files
                if rule_id == "quality/no-var-dump" and ext not in (".php", ".rb"):
                    continue

                match = pattern.search(line_text)
                if match:
                    # Allow tracked TODOs that reference an issue, PR, ticket, or URL
                    # e.g.: TODO(#123), TODO(JIRA-456), TODO: https://github.com/...
                    if rule_id == "quality/no-todo-comments":
                        comment_text = match.group(0)
                        if re.search(r"TODO\s*\([#A-Za-z0-9_\-]+\)|https?://", line_text, re.IGNORECASE):
                            continue

                    violations.append(
                        Violation(
                            file_path=file_diff.file_path,
                            line_number=line_no,
                            rule_id=rule_id,
                            rule_name=rule_name,
                            severity=severity,
                            message=f"{rule_name} detected in diff addition.",
                            snippet=stripped,
                            suggestion=suggestion,
                        )
                    )

        return violations
