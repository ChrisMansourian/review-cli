"""Code quality / anti-AI-slop rule engine.

Flags patterns that a senior SWE would immediately refactor:
unnecessary else branches after returns, long if/elif chains that should
be dicts/match statements, repeated literals, and similar simplification
opportunities common in AI-generated code.
"""

import os
import re
from collections import Counter
from typing import List, Tuple

from reviewer.models import FileDiff, Violation, Severity
from reviewer.rules.base import BaseRule, register_rule

CODE_EXTENSIONS = {
    ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx",
    ".py", ".rb", ".go", ".rs", ".php", ".c", ".cpp", ".cs", ".java",
}

# Minimum chain length before flagging elif / else-if chains
_ELIF_CHAIN_THRESHOLD = 3
# Minimum occurrences of the same literal before flagging
_LITERAL_REPEAT_THRESHOLD = 3
# Minimum number of near-duplicate adjacent lines before flagging
_DUPLICATE_LINE_THRESHOLD = 3


def _is_bypass(line: str) -> bool:
    """Return True if the line carries an inline reviewer bypass directive."""
    lowered = line.lower()
    return any(m in lowered for m in ("reviewer:ignore", "reviewer:allow", "noqa"))


@register_rule
class CodeQualityRule(BaseRule):
    """Flags AI-slop patterns that a senior SWE would immediately refactor.

    Checks performed:
    - Unnecessary ``else`` / ``} else {`` immediately after a return/raise/throw.
    - Long ``if / elif / else-if`` chains (≥3 branches) that suggest a dict
      lookup or match/switch statement would be cleaner.
    - The same hardcoded string or numeric literal appearing ≥3 times across
      added lines (should be extracted to a named constant).
    - Three or more adjacent added lines that are nearly identical (duplicated
      logic block that should be abstracted into a function).
    """

    rule_id = "quality/code-quality"
    name = "Code Quality (Anti-AI-Slop)"
    description = (
        "Flags patterns common in AI-generated 'slop' code that a senior SWE "
        "would immediately refactor: unnecessary else branches after returns, "
        "long if/elif chains that should use dicts/match, repeated literals, "
        "and duplicated adjacent code blocks."
    )
    severity = Severity.WARNING

    # --- patterns -----------------------------------------------------------

    # Matches bare return/raise/throw/break/continue as the *only* statement
    # on the line (possibly with a value).
    _EARLY_EXIT_RE = re.compile(
        r"^\s*(return\b|raise\b|throw\b|break\b|continue\b)",
        re.IGNORECASE,
    )

    # Matches the opening of an else block: ``} else {``, ``} else:``,
    # ``else:``, ``else {``.
    _ELSE_OPEN_RE = re.compile(
        r"^\s*(\}\s*)?else\s*[\{:]",
        re.IGNORECASE,
    )

    # Matches ``elif …:`` (Python) or ``else if (…) {`` / ``} else if`` (C-style).
    _ELIF_RE = re.compile(
        r"^\s*(\}?\s*else\s+if\s*\(|elif\b)",
        re.IGNORECASE,
    )

    # Literals: quoted strings or bare numbers/floats.
    _LITERAL_RE = re.compile(
        r"(?:\"[^\"\\]*\"|'[^'\\]*'|`[^`\\]*`|\b\d+(?:\.\d+)?\b)"
    )

    # ---------------------------------------------------------------------------

    def check(self, file_diff: FileDiff) -> List[Violation]:
        ext = os.path.splitext(file_diff.file_path)[1].lower()
        if ext not in CODE_EXTENSIONS:
            return []

        violations: List[Violation] = []
        lines: List[Tuple[int, str]] = file_diff.added_lines

        violations.extend(self._check_unnecessary_else(lines, file_diff.file_path))
        violations.extend(self._check_elif_chains(lines, file_diff.file_path))
        violations.extend(self._check_magic_literals(lines, file_diff.file_path))
        violations.extend(self._check_duplicate_lines(lines, file_diff.file_path))

        return violations

    # --- individual checks --------------------------------------------------

    def _check_unnecessary_else(
        self,
        lines: List[Tuple[int, str]],
        path: str,
    ) -> List[Violation]:
        """Flag ``else`` blocks that immediately follow a return/raise/throw."""
        violations: List[Violation] = []
        texts = [t for _, t in lines]
        line_nos = [n for n, _ in lines]

        for i in range(1, len(texts)):
            prev = texts[i - 1].strip()
            curr = texts[i].strip()

            if _is_bypass(curr):
                continue

            # Previous line must end with an early exit
            if self._EARLY_EXIT_RE.match(prev) and self._ELSE_OPEN_RE.match(curr):
                violations.append(
                    Violation(
                        file_path=path,
                        line_number=line_nos[i],
                        rule_id="quality/unnecessary-else-after-return",
                        rule_name="Unnecessary Else After Return",
                        severity=Severity.WARNING,
                        message=(
                            "``else`` block is redundant after an unconditional "
                            "return/raise/throw. Remove the else and dedent the block."
                        ),
                        snippet=curr,
                        suggestion=(
                            "Replace ``if … return … else …`` with an early-return "
                            "guard: return inside the if, then fall through."
                        ),
                    )
                )

        return violations

    def _check_elif_chains(
        self,
        lines: List[Tuple[int, str]],
        path: str,
    ) -> List[Violation]:
        """Flag long elif/else-if chains suggesting a dict/match refactor.

        A chain is defined as a sequence of ``elif``/``else if`` branches
        within the same if-block. Non-elif lines between branches are
        permitted (they are the branch bodies); a plain ``if`` resets the
        chain.
        """
        violations: List[Violation] = []
        texts = [t for _, t in lines]
        line_nos = [n for n, _ in lines]

        # Match a fresh ``if`` (not elif / else if)
        _IF_START_RE = re.compile(r"^\s*if\s*[\(\s]", re.IGNORECASE)
        # Match a closing else without elif (chain terminator)
        _ELSE_ONLY_RE = re.compile(r"^\s*(\}\s*)?else\s*[\{:](?!\s*if\b)", re.IGNORECASE)

        def _flush(start_idx: int, length: int) -> None:
            if start_idx >= 0 and length >= _ELIF_CHAIN_THRESHOLD:
                violations.append(
                    Violation(
                        file_path=path,
                        line_number=line_nos[start_idx],
                        rule_id="quality/complex-if-else-chain",
                        rule_name="Complex If/Elif Chain",
                        severity=Severity.WARNING,
                        message=(
                            f"If/elif chain with {length} branches detected. "
                            "Consider refactoring to a dict lookup, match statement, "
                            "or polymorphism."
                        ),
                        snippet=texts[start_idx].strip(),
                        suggestion=(
                            "Replace long elif chains with a dispatch dict "
                            "``handlers = {key: fn}`` and ``handlers.get(key, default)()``, "
                            "or use Python 3.10+ ``match``."
                        ),
                    )
                )

        chain_start_idx: int = -1
        chain_len: int = 0

        for i, text in enumerate(texts):
            stripped = text.strip()

            if _is_bypass(text):
                _flush(chain_start_idx, chain_len)
                chain_start_idx = -1
                chain_len = 0
                continue

            if self._ELIF_RE.match(stripped):
                # Accumulate branch count; remember start of first elif
                if chain_len == 0:
                    chain_start_idx = i
                chain_len += 1
            elif _IF_START_RE.match(stripped):
                # New if-block: flush current chain and restart
                _flush(chain_start_idx, chain_len)
                chain_start_idx = -1
                chain_len = 0
            elif _ELSE_ONLY_RE.match(stripped):
                # Terminal else: flush and reset
                _flush(chain_start_idx, chain_len)
                chain_start_idx = -1
                chain_len = 0
            # else: branch body — keep accumulating

        _flush(chain_start_idx, chain_len)
        return violations

        return violations

    def _check_magic_literals(
        self,
        lines: List[Tuple[int, str]],
        path: str,
    ) -> List[Violation]:
        """Flag the same literal appearing ≥3 times across added lines."""
        violations: List[Violation] = []
        counts: Counter = Counter()
        first_occurrence: dict = {}

        # Literals to ignore: trivially common values
        _IGNORED_LITERALS = {"0", "1", "2", "-1", "", '""', "''", "``", "true", "false", "null", "none"}

        for line_no, line_text in lines:
            if _is_bypass(line_text):
                continue
            for match in self._LITERAL_RE.finditer(line_text):
                lit = match.group(0).lower()
                if lit in _IGNORED_LITERALS:
                    continue
                counts[lit] += 1
                if lit not in first_occurrence:
                    first_occurrence[lit] = line_no

        for lit, count in counts.items():
            if count >= _LITERAL_REPEAT_THRESHOLD:
                violations.append(
                    Violation(
                        file_path=path,
                        line_number=first_occurrence[lit],
                        rule_id="quality/magic-literal-repetition",
                        rule_name="Magic Literal Repetition",
                        severity=Severity.INFO,
                        message=(
                            f"Literal {lit!r} appears {count} times across added lines. "
                            "Extract to a named constant."
                        ),
                        snippet=lit,
                        suggestion=(
                            f"Define a module-level constant (e.g., ``MAX_RETRIES = {lit}``) "
                            "and reference it throughout."
                        ),
                    )
                )

        return violations

    def _check_duplicate_lines(
        self,
        lines: List[Tuple[int, str]],
        path: str,
    ) -> List[Violation]:
        """Flag 3+ adjacent near-identical added lines suggesting copy-paste."""
        violations: List[Violation] = []
        texts = [t for _, t in lines]
        line_nos = [n for n, _ in lines]

        def _normalise(s: str) -> str:
            """Collapse variable names but preserve string literals for diff."""
            stripped = s.strip()
            # Replace identifiers but keep quoted string content intact so
            # lines with different string arguments don't collide.
            return re.sub(r"\b[A-Z][A-Z0-9_]{3,}\b", "CONST", stripped)

        run_start = 0
        run_len = 1

        for i in range(1, len(texts)):
            if _is_bypass(texts[i]):
                run_start = i
                run_len = 1
                continue

            prev_norm = _normalise(texts[i - 1])
            curr_norm = _normalise(texts[i])

            # Ignore blank / trivially short lines from run counts
            if len(prev_norm.strip()) < 8 or len(curr_norm.strip()) < 8:  # noqa: magic-literal
                run_start = i
                run_len = 1
                continue

            if prev_norm == curr_norm:
                run_len += 1
            else:
                if run_len >= _DUPLICATE_LINE_THRESHOLD:
                    violations.append(
                        Violation(
                            file_path=path,
                            line_number=line_nos[run_start],
                            rule_id="quality/duplicated-code-pattern",
                            rule_name="Duplicated Code Pattern",
                            severity=Severity.WARNING,
                            message=(
                                f"{run_len} near-identical adjacent lines detected. "
                                "Abstract the repeated logic into a helper function."
                            ),
                            snippet=texts[run_start].strip(),
                            suggestion=(
                                "Extract the repeated pattern into a function and "
                                "call it with the varying arguments."
                            ),
                        )
                    )
                run_start = i
                run_len = 1

        # Flush trailing run
        if run_len >= _DUPLICATE_LINE_THRESHOLD:
            violations.append(
                Violation(
                    file_path=path,
                    line_number=line_nos[run_start],
                    rule_id="quality/duplicated-code-pattern",
                    rule_name="Duplicated Code Pattern",
                    severity=Severity.WARNING,
                    message=(
                        f"{run_len} near-identical adjacent lines detected. "
                        "Abstract the repeated logic into a helper function."
                    ),
                    snippet=texts[run_start].strip(),
                    suggestion=(
                        "Extract the repeated pattern into a function and "
                        "call it with the varying arguments."
                    ),
                )
            )

        return violations
