"""Refactor-pattern rule engine.

Complements ``code_quality`` with structural smells a senior engineer would
refactor on sight: boolean-returning if/else, nested ternaries, deep nesting,
long parameter lists, swallowed exceptions, unreachable code, commented-out
code, narrating comments, oversized functions, and non-idiomatic constructs.

All checks are line-based heuristics over the added lines of a diff. Checks
that reason about blocks only look inside contiguous runs of added lines so
that unrelated hunks are never stitched together.
"""

import os
import re
from dataclasses import dataclass, replace
from typing import Callable, Dict, Iterator, List, Optional, Set, Tuple

from reviewer.models import FileDiff, Severity, Violation
from reviewer.config import get_config
from reviewer.rules.base import BaseRule, register_rule
from reviewer.rules.code_quality import CODE_EXTENSIONS, _is_bypass

Line = Tuple[int, str]

_PY = {".py"}
_JS = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}
_HASH_COMMENT = {".py", ".rb"}
_TERNARY_LANGS = _JS | {".java", ".cs", ".c", ".cpp", ".php"}
_CONCAT_LANGS = _PY | _JS | {".java", ".cs", ".rb"}

# Thresholds (max params, nesting depth, function lines) come from the active
# config (see reviewer.config); defaults live in ReviewerConfig.
# How many lines a multi-line signature may span before we give up.
_SIGNATURE_LOOKAHEAD = 15
# Narrating comments longer than this are assumed to carry real intent.
_MAX_NARRATION_WORDS = 6


@dataclass(frozen=True)
class _Smell:
    rule_id: str
    name: str
    severity: Severity
    message: str
    suggestion: str


# (smell, line_number, snippet)
_Hit = Tuple[_Smell, int, str]


BOOLEAN_RETURN = _Smell(
    "quality/redundant-boolean-return", "Redundant Boolean Return", Severity.WARNING,
    "Branch returns a boolean literal that just mirrors its condition.",
    "Return the condition directly: ``return cond`` / ``flag = x > 0``.",
)
NESTED_TERNARY = _Smell(
    "quality/nested-ternary", "Nested Ternary", Severity.WARNING,
    "Nested conditional expression is hard to read.",
    "Use an if/elif chain, early returns, or a lookup table.",
)
DEEP_NESTING = _Smell(
    "quality/deep-nesting", "Deeply Nested Control Flow", Severity.WARNING,
    "Control flow is nested too deeply.",
    "Invert conditions into guard clauses that return early, or extract the inner block.",
)
LONG_PARAMS = _Smell(
    "quality/long-parameter-list", "Long Parameter List", Severity.WARNING,
    "Function takes too many positional parameters.",
    "Group related values into an options object / dataclass, or make extras keyword-only.",
)
MUTABLE_DEFAULT = _Smell(
    "quality/mutable-default-argument", "Mutable Default Argument", Severity.ERROR,
    "Mutable default argument is shared across every call.",
    "Default to ``None`` and create the list/dict inside the function.",
)
BARE_EXCEPT = _Smell(
    "quality/bare-except", "Bare Except", Severity.WARNING,
    "Bare ``except:`` also catches KeyboardInterrupt and SystemExit.",
    "Catch the specific exception types you expect.",
)
SWALLOWED_EXCEPTION = _Smell(
    "quality/swallowed-exception", "Swallowed Exception", Severity.WARNING,
    "Exception is caught and silently discarded.",
    "Handle it, log it, or re-raise. If ignoring is intentional, say why in a comment.",
)
NON_IDIOMATIC_COMPARISON = _Smell(
    "quality/non-idiomatic-comparison", "Non-Idiomatic Comparison", Severity.INFO,
    "Comparison against None/True/False/len() is not idiomatic Python.",
    "Use ``is None`` / ``is not None``, or plain truthiness (``if items:``).",
)
LOOSE_EQUALITY = _Smell(
    "quality/loose-equality", "Loose Equality", Severity.WARNING,
    "``==`` / ``!=`` perform type coercion.",
    "Use ``===`` / ``!==`` (``== null`` is the only accepted exception).",
)
RANGE_LEN_LOOP = _Smell(
    "quality/range-len-loop", "range(len()) Loop", Severity.INFO,
    "Index-based loop over ``range(len(...))``.",
    "Iterate directly, or use ``enumerate()`` / ``zip()`` when you need the index.",
)
MANUAL_ACCUMULATION = _Smell(
    "quality/manual-accumulation-loop", "Manual Accumulation Loop", Severity.INFO,
    "Loop only builds a list with append/push.",
    "Use a list comprehension (Python) or ``.filter().map()`` (JS/TS).",
)
STRING_CONCAT = _Smell(
    "quality/string-concatenation", "String Concatenation", Severity.INFO,
    "String built by concatenating literals and values.",
    "Use an f-string / template literal / format call.",
)
AWAIT_IN_LOOP = _Smell(
    "quality/await-in-loop", "Await Inside Loop", Severity.INFO,
    "``await`` inside a loop runs iterations sequentially.",
    "If iterations are independent, use ``Promise.all`` / ``asyncio.gather``.",
)
UNREACHABLE_CODE = _Smell(
    "quality/unreachable-code", "Unreachable Code", Severity.WARNING,
    "Statement follows an unconditional return/raise/throw/break/continue.",
    "Delete the dead code, or move it before the exit.",
)
COLLAPSIBLE_IF = _Smell(
    "quality/collapsible-if", "Collapsible Nested If", Severity.INFO,
    "Nested ``if`` is the only statement in its parent ``if``.",
    "Merge the conditions: ``if a and b:`` / ``if (a && b)``.",
)
COMMENTED_OUT_CODE = _Smell(
    "quality/commented-out-code", "Commented-Out Code", Severity.INFO,
    "Block of commented-out code.",
    "Delete it. Version control keeps the history.",
)
NARRATING_COMMENT = _Smell(
    "quality/narrating-comment", "Narrating Comment", Severity.INFO,
    "Comment restates what the next line already says.",
    "Delete it, or replace it with *why* the code does this.",
)
GOD_FUNCTION = _Smell(
    "quality/god-function", "Oversized Function", Severity.WARNING,
    "Function body is too long.",
    "Split it by responsibility so the top-level function reads like a table of contents.",
)


# --- shared regexes ---------------------------------------------------------

_STRING_RE = re.compile(r"\"(?:[^\"\\\n]|\\.)*\"|'(?:[^'\\\n]|\\.)*'|`(?:[^`\\\n]|\\.)*`")
_EXIT_RE = re.compile(r"^(return|raise|throw|break|continue)\b")
_IF_RE = re.compile(r"^if\b")
_RETURN_BOOL_RE = re.compile(r"^return\s+(true|false)\s*;?\s*\}?$", re.IGNORECASE)
_ELSE_LINE_RE = re.compile(r"^\}?\s*(else\s*[:{]?)?$")
_CLOSE_ONLY_RE = re.compile(r"^[}\])]+;?$")

_BLOCK_OPENER_RE = re.compile(
    r"^(\}\s*)?(if|elif|else|for|foreach|while|switch|try|except|catch|finally|with|unless)\b"
    r"|^async\s+(for|with)\b"
)

_SIGNATURE_RES: Dict[str, List[re.Pattern]] = {
    "py": [re.compile(r"^\s*(?:async\s+)?def\s+\w+\s*\(")],
    "js": [
        re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*\w*\s*(?:<[^>]*>)?\s*\("),
        re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+\w+\s*(?::[^=]+)?=\s*(?:async\s*)?\("),
    ],
    "go": [re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?\w+\s*(?:\[[^\]]*\])?\s*\(")],
    "rs": [re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:const\s+)?fn\s+\w+\s*(?:<[^>]*>)?\s*\(")],
    "php": [re.compile(r"^\s*(?:(?:public|private|protected|static|final|abstract)\s+)*function\s+&?\w+\s*\(")],
    "rb": [re.compile(r"^\s*def\s+(?:self\.)?\w+[?!]?\s*\(")],
}
_EXT_TO_SIG = {".py": "py", ".go": "go", ".rs": "rs", ".php": "php", ".rb": "rb"}
_EXT_TO_SIG.update({ext: "js" for ext in _JS})

_IGNORED_PARAMS = {"self", "cls", "&self", "&mut self", "mut self", "/", "this"}
_MUTABLE_DEFAULT_RE = re.compile(r"=\s*(\[|\{|(?:set|list|dict|defaultdict)\(\))")

_NARRATION_STOPWORDS = {
    "a", "an", "the", "to", "of", "for", "and", "or", "in", "on", "at", "by", "with", "from",
    "into", "this", "that", "it", "is", "be", "we", "our", "new", "now", "here", "then", "if",
    "value", "values", "variable", "variables", "function", "method", "call", "set", "get",
    "return", "create", "make", "initialize", "initialise", "init", "define", "declare",
    "check", "import", "module", "modules", "library", "libraries", "dependency",
    "dependencies", "loop", "through", "over", "each", "all", "add", "update", "increment",
    "decrement", "result", "list", "dict", "array", "object", "instance", "store", "save",
    "assign", "use", "using", "print", "log", "start", "end", "do", "run", "handle",
}
# Comments carrying intent, directives or caveats are never "narration".
_INTENT_MARKERS = re.compile(
    r"\b(why|because|since|so that|note|hack|workaround|todo|fixme|xxx|warning|important"
    r"|must|never|always|avoid|otherwise|unless|until|ensure|keep|see)\b"
    r"|https?://|[:=]\s*\w|^!|type:|pylint|eslint|prettier|noqa|reviewer",
    re.IGNORECASE,
)

_PY_CODE_COMMENT_RE = re.compile(
    r"^(import\s+\w|from\s+[\w.]+\s+import\s|def\s+\w+\(|class\s+\w+[(:]|print\(|return\s+\S.*[()\[\]]"
    r"|(?:if|elif|for|while|with)\s.+:\s*$|else:\s*$|[\w.\[\]'\"]+\s*(?:=|\+=|-=)\s*\S"
    r"|[\w.]+\(.*\)\s*$)"
)
_C_CODE_COMMENT_RE = re.compile(
    r"^((?:const|let|var)\s+\w+\s*=|import\s.+;|export\s|function\s+\w+\s*\(|return\b.*;\s*$"
    r"|(?:if|for|while|switch)\s*\(.*\)\s*\{?\s*$|[\w.\[\]]+\s*(?:=|\+=|-=)\s*.+;\s*$"
    r"|[\w.]+\(.*\);\s*$|\}\s*(?:else\s*\{)?\s*$)"
)
_DOC_COMMENT_HINTS = re.compile(r"e\.g\.|i\.e\.|example|usage|>>>|\$ |reviewer:|noqa|type:", re.IGNORECASE)


# --- helpers ----------------------------------------------------------------

def _indent(text: str) -> int:
    expanded = text.expandtabs(4)
    return len(expanded) - len(expanded.lstrip())


def _strip_strings(text: str) -> str:
    return _STRING_RE.sub('""', text)


def _contiguous_runs(lines: List[Line]) -> Iterator[List[Line]]:
    """Yield runs of consecutive line numbers (one run per hunk region)."""
    run: List[Line] = []
    for line_no, text in lines:
        if run and line_no != run[-1][0] + 1:
            yield run
            run = []
        run.append((line_no, text))
    if run:
        yield run


def _comment_body(text: str, ext: str) -> Optional[str]:
    """Return the comment text if the line is a whole-line comment."""
    stripped = text.strip()
    if (ext in _HASH_COMMENT or ext == ".php") and stripped.startswith("#"):
        return stripped.lstrip("#").strip()
    if ext not in _HASH_COMMENT and stripped.startswith("//"):
        return stripped.lstrip("/").strip()
    return None


def _code_part(text: str, ext: str) -> str:
    """Strip string literals and trailing comments from a code line."""
    code = _strip_strings(text)
    marker = "#" if ext in _HASH_COMMENT else "//"
    cut = code.find(marker)
    return code if cut < 0 else code[:cut]


def _next_nonblank(run: List[Line], start: int) -> int:
    """Index of the first non-blank line at or after ``start`` (or len(run))."""
    idx = start
    while idx < len(run) and not run[idx][1].strip():
        idx += 1
    return idx


def _block_end(run: List[Line], start: int, indent: int) -> int:
    """Index just past the block whose body is indented deeper than ``indent``."""
    idx = start
    while idx < len(run):
        text = run[idx][1]
        if text.strip() and _indent(text) <= indent:
            break
        idx += 1
    return idx


def _split_top_level(params: str) -> List[str]:
    """Split a parameter list on commas that are not nested in brackets."""
    parts: List[str] = []
    depth = 0
    current = []
    for char in params:
        if char in "([{<":
            depth += 1
        elif char in ")]}>":
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    parts.append("".join(current).strip())
    return [p for p in parts if p]


def _collect_params(run: List[Line], idx: int, paren_at: int) -> Optional[str]:
    """Return the text between the signature's parens, spanning lines if needed."""
    window = " ".join(_strip_strings(t) for _, t in run[idx:idx + _SIGNATURE_LOOKAHEAD])
    text = window[paren_at + 1:]
    depth = 1
    for pos, char in enumerate(text):
        depth += {"(": 1, ")": -1}.get(char, 0)
        if depth == 0:
            return text[:pos]
    return None


def _positional_params(params: str) -> List[str]:
    positional: List[str] = []
    for param in _split_top_level(params):
        if param == "*" or param.startswith("*") and not param.startswith("**"):
            break
        if param.startswith("**") or param in _IGNORED_PARAMS:
            continue
        positional.append(param)
    return positional


def _identifier_words(code: str) -> Set[str]:
    words: Set[str] = set()
    for ident in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", code):
        spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", ident)
        for word in re.split(r"[_\s]+", spaced):
            if word:
                words.add(word.lower().rstrip("s"))
    return words


@register_rule
class RefactorPatternsRule(BaseRule):
    """Flags structural smells that call for a well-known refactoring."""

    rule_id = "quality/refactor-patterns"
    name = "Refactor Patterns"
    description = (
        "Flags structural smells with a standard refactoring: redundant boolean "
        "returns, nested ternaries, deep nesting, long parameter lists, swallowed "
        "exceptions, unreachable or commented-out code, narrating comments, "
        "oversized functions, and non-idiomatic loops/comparisons."
    )
    severity = Severity.WARNING

    def check(self, file_diff: FileDiff) -> List[Violation]:
        ext = os.path.splitext(file_diff.file_path)[1].lower()
        if ext not in CODE_EXTENSIONS:
            return []

        checks: List[Callable[[List[Line], str], List[_Hit]]] = [
            self._check_boolean_return,
            self._check_nested_ternary,
            self._check_deep_nesting,
            self._check_signatures,
            self._check_exceptions,
            self._check_comparisons,
            self._check_loops,
            self._check_string_concat,
            self._check_unreachable,
            self._check_collapsible_if,
            self._check_comments,
            self._check_god_function,
        ]

        hits: List[_Hit] = []
        for run in _contiguous_runs(file_diff.added_lines):
            for check in checks:
                hits.extend(check(run, ext))

        return [
            Violation(
                file_path=file_diff.file_path,
                line_number=line_no,
                rule_id=smell.rule_id,
                rule_name=smell.name,
                severity=smell.severity,
                message=smell.message,
                snippet=snippet.strip(),
                suggestion=smell.suggestion,
            )
            for smell, line_no, snippet in hits
        ]

    # --- checks -------------------------------------------------------------

    def _check_boolean_return(self, run: List[Line], ext: str) -> List[_Hit]:
        hits: List[_Hit] = []
        stripped = [t.strip() for _, t in run]
        for i, text in enumerate(stripped):
            if _is_bypass(run[i][1]):
                continue
            code = _strip_strings(text)
            if re.search(r"\b(True\s+if\b.+\belse\s+False|False\s+if\b.+\belse\s+True)\b", code) or \
                    re.search(r"\?\s*(true\s*:\s*false|false\s*:\s*true)\b", code):
                hits.append((BOOLEAN_RETURN, run[i][0], text))
                continue
            inline = re.findall(r"\breturn\s+(true|false)\b", code, re.IGNORECASE)
            if _IF_RE.match(code) and len(inline) == 2 and inline[0].lower() != inline[1].lower():
                hits.append((BOOLEAN_RETURN, run[i][0], text))
                continue
            first = _RETURN_BOOL_RE.match(text)
            if not first or i == 0 or not _IF_RE.match(stripped[i - 1]):
                continue
            # Skip at most two connector lines (``}``, ``else:``, ``} else {``).
            j = i + 1
            while j < len(stripped) and j <= i + 2 and _ELSE_LINE_RE.match(stripped[j]):
                j += 1
            if j >= len(stripped):
                continue
            second = _RETURN_BOOL_RE.match(stripped[j])
            # The second return must be the else-branch or the direct fall-through,
            # not a return after an enclosing loop ends.
            second_indent = _indent(run[j][1])
            aligned = second_indent in (_indent(run[i][1]), _indent(run[i - 1][1]))
            if second and aligned and second.group(1).lower() != first.group(1).lower():
                hits.append((BOOLEAN_RETURN, run[i - 1][0], stripped[i - 1]))
        return hits

    def _check_nested_ternary(self, run: List[Line], ext: str) -> List[_Hit]:
        hits: List[_Hit] = []
        for line_no, text in run:
            if _is_bypass(text) or _comment_body(text, ext) is not None:
                continue
            code = _code_part(text, ext).strip()
            if ext in _PY:
                if re.match(r"(el)?if\b|while\b", code):
                    continue
                if len(re.findall(r"\bif\b[^\n]*?\belse\b", code)) >= 2:
                    hits.append((NESTED_TERNARY, line_no, text))
            elif ext in _TERNARY_LANGS:
                if re.search(r"[(=,]\s*/[^/*]", code):
                    continue  # likely a regex literal
                scrubbed = re.sub(r"\?\?=?|\?\.|\?\s*[:),]|\w\?\s+\w+\s*[=;,)]", "", code)
                if scrubbed.count("?") >= 2 and scrubbed.count(":") >= 2:
                    hits.append((NESTED_TERNARY, line_no, text))
        return hits

    def _check_deep_nesting(self, run: List[Line], ext: str) -> List[_Hit]:
        hits: List[_Hit] = []
        max_nesting = get_config().max_nesting
        stack: List[int] = []
        flagged = False
        for line_no, text in run:
            stripped = text.strip()
            if not stripped or _comment_body(text, ext) is not None:
                continue
            indent = _indent(text)
            while stack and stack[-1] >= indent:
                stack.pop()
            if not stack:
                flagged = False
            if _BLOCK_OPENER_RE.match(stripped):
                stack.append(indent)
                if len(stack) >= max_nesting and not flagged and not _is_bypass(text):
                    smell = replace(DEEP_NESTING, message=f"Control flow is nested {max_nesting}+ levels deep.")
                    hits.append((smell, line_no, text))
                    flagged = True
        return hits

    def _check_signatures(self, run: List[Line], ext: str) -> List[_Hit]:
        hits: List[_Hit] = []
        patterns = _SIGNATURE_RES.get(_EXT_TO_SIG.get(ext, ""), [])
        max_params = get_config().max_params
        for i, (line_no, text) in enumerate(run):
            if _is_bypass(text):
                continue
            match = next((m for m in (p.match(_strip_strings(text)) for p in patterns) if m), None)
            if not match:
                continue
            params = _collect_params(run, i, match.end() - 1)
            if params is None:
                continue
            positional = _positional_params(params)
            if len(positional) > max_params:
                smell = replace(
                    LONG_PARAMS,
                    message=f"Function takes {len(positional)} positional parameters (max {max_params}).",
                )
                hits.append((smell, line_no, text))
            if ext in _PY and any(_MUTABLE_DEFAULT_RE.search(p) for p in _split_top_level(params)):
                hits.append((MUTABLE_DEFAULT, line_no, text))
        return hits

    def _check_exceptions(self, run: List[Line], ext: str) -> List[_Hit]:
        hits: List[_Hit] = []
        for i, (line_no, text) in enumerate(run):
            if _is_bypass(text):
                continue
            code = _code_part(text, ext).strip()
            nxt = _next_nonblank(run, i + 1)
            next_stripped = run[nxt][1].strip() if nxt < len(run) else ""
            if ext in _PY:
                if re.match(r"except\s*:", code):
                    hits.append((BARE_EXCEPT, line_no, text))
                inline_pass = re.match(r"except\b[^:]*:\s*(pass|\.\.\.)\s*$", code)
                if inline_pass or re.match(r"except\b[^:]*:\s*$", code) and next_stripped in ("pass", "..."):
                    hits.append((SWALLOWED_EXCEPTION, line_no, text))
            elif ext != ".rb":
                if re.search(r"\bcatch\s*(\([^)]*\))?\s*\{\s*\}", code) or \
                        re.search(r"\.catch\(\s*(\(\s*\w*\s*\)|\w+)\s*=>\s*(\{\s*\}|null|undefined)\s*\)", code) or \
                        re.search(r"\bcatch\s*(\([^)]*\))?\s*\{\s*$", code) and next_stripped.startswith("}"):
                    hits.append((SWALLOWED_EXCEPTION, line_no, text))
        return hits

    def _check_comparisons(self, run: List[Line], ext: str) -> List[_Hit]:
        hits: List[_Hit] = []
        for line_no, text in run:
            if _is_bypass(text) or _comment_body(text, ext) is not None:
                continue
            code = _code_part(text, ext)
            if ext in _PY and re.search(
                r"[=!]=\s*(None|True|False)\b|\b(None|True|False)\s*[=!]=|\blen\([^()]*\)\s*(==|!=|>)\s*0\b",
                code,
            ):
                hits.append((NON_IDIOMATIC_COMPARISON, line_no, text))
            elif ext in _JS and re.search(r"(?<![=!<>])(==|!=)(?!=)(?!\s*null\b)", code):
                hits.append((LOOSE_EQUALITY, line_no, text))
        return hits

    def _check_loops(self, run: List[Line], ext: str) -> List[_Hit]:
        hits: List[_Hit] = []
        for i, (line_no, text) in enumerate(run):
            if _is_bypass(text):
                continue
            code = _code_part(text, ext).strip()
            if ext in _PY and re.match(r"for\s+\w+\s+in\s+range\(\s*len\(", code):
                hits.append((RANGE_LEN_LOOP, line_no, text))
            if ext in _PY | _JS:
                hit = self._await_in_loop(run, i, ext) or self._manual_accumulation(run, i, ext)
                if hit:
                    hits.append(hit)
        return hits

    def _await_in_loop(self, run: List[Line], i: int, ext: str) -> Optional[_Hit]:
        code = _code_part(run[i][1], ext).strip()
        loop_re = r"(for|while)\b(?!\s+await)" if ext in _PY else r"(for|while)\s*\("
        if not re.match(loop_re, code):
            return None
        end = _block_end(run, i + 1, _indent(run[i][1]))
        for line_no, text in run[i + 1:end]:
            body = _code_part(text, ext)
            if re.search(r"\bawait\b", body) and not re.search(r"Promise\.all|gather\(", body):
                return (AWAIT_IN_LOOP, line_no, text)
        return None

    def _manual_accumulation(self, run: List[Line], i: int, ext: str) -> Optional[_Hit]:
        init_re = (
            r"^(\w+)\s*(?::[^=]+)?=\s*\[\]\s*$" if ext in _PY
            else r"^(?:const|let|var)\s+(\w+)\s*(?::[^=]+)?=\s*\[\]\s*;?$"
        )
        init = re.match(init_re, _code_part(run[i][1], ext).strip())
        if not init:
            return None
        name = init.group(1)
        loop_idx = _next_nonblank(run, i + 1)
        if loop_idx >= len(run):
            return None
        loop_code = _code_part(run[loop_idx][1], ext).strip()
        if not re.match(r"for\b", loop_code) or _indent(run[loop_idx][1]) != _indent(run[i][1]):
            return None
        end = _block_end(run, loop_idx + 1, _indent(run[loop_idx][1]))
        if end == len(run) and ext in _PY:
            return None  # loop body may continue past the visible hunk
        body = [_code_part(t, ext).strip() for _, t in run[loop_idx + 1:end]]
        body = [b for b in body if b and not _CLOSE_ONLY_RE.match(b)]
        append_re = rf"^{re.escape(name)}\.(append|push)\("
        appends = [b for b in body if re.match(append_re, b)]
        others = [b for b in body if not re.match(append_re, b)]
        if len(appends) == 1 and all(re.match(r"if\b", b) for b in others) and len(others) <= 1:
            return (MANUAL_ACCUMULATION, run[i][0], run[i][1])
        return None

    def _check_string_concat(self, run: List[Line], ext: str) -> List[_Hit]:
        if ext not in _CONCAT_LANGS:
            return []
        hits: List[_Hit] = []
        literal_then_value = re.compile(r"(\"[^\"\n]*\"|'[^'\n]*')\s*\+\s*[A-Za-z_(]")
        value_then_literal = re.compile(r"[\w)\]]\s*\+\s*(\"|')")
        for line_no, text in run:
            if _is_bypass(text) or _comment_body(text, ext) is not None:
                continue
            joins = len(literal_then_value.findall(text)) + len(value_then_literal.findall(text))
            if joins >= 2:
                hits.append((STRING_CONCAT, line_no, text))
        return hits

    def _check_unreachable(self, run: List[Line], ext: str) -> List[_Hit]:
        hits: List[_Hit] = []
        allowed_after = re.compile(
            r"^([}\])]|else\b|elif\b|except\b|catch\b|finally\b|case\b|default\b|when\b|end\b"
            r"|rescue\b|ensure\b|#|//|/\*|\*|@|def\b|class\b|func\b|fn\b|function\b)"
        )
        for i, (_, text) in enumerate(run):
            code = _code_part(text, ext).strip()
            if not _EXIT_RE.match(code) or re.search(r"\s(if|unless)\s", code):
                continue
            if code.endswith(("(", "[", "{", ",", "\\", "+", "&&", "||", "and", "or")):
                continue
            if code.count("(") != code.count(")") or code.count("[") != code.count("]"):
                continue
            nxt = _next_nonblank(run, i + 1)
            if nxt >= len(run):
                continue
            next_no, next_text = run[nxt]
            if _indent(next_text) != _indent(text) or _is_bypass(next_text):
                continue
            if not allowed_after.match(next_text.strip()):
                hits.append((UNREACHABLE_CODE, next_no, next_text))
        return hits

    def _check_collapsible_if(self, run: List[Line], ext: str) -> List[_Hit]:
        hits: List[_Hit] = []
        braced = ext not in _PY
        for i, ((outer_no, outer), (_, inner)) in enumerate(zip(run, run[1:])):
            outer_code = _code_part(outer, ext).strip()
            inner_code = _code_part(inner, ext).strip()
            opener = r"if\s*\(.*\)\s*\{$" if braced else r"if\b.*:$"
            if not (re.match(opener, outer_code) and re.match(opener, inner_code)):
                continue
            if _indent(inner) <= _indent(outer) or _is_bypass(outer):
                continue
            end = _block_end(run, i + 2, _indent(inner))
            if braced:
                tail = [_code_part(t, ext).strip() for _, t in run[end:end + 3]]
                ok = len(tail) >= 2 and tail[0] == "}" and tail[1] == "}" and \
                    (len(tail) < 3 or not tail[2].startswith("else"))
                ok = ok and _indent(run[end][1]) == _indent(inner) and _indent(run[end + 1][1]) == _indent(outer)
            else:
                nxt = _next_nonblank(run, end)
                ok = nxt < len(run) and _indent(run[nxt][1]) <= _indent(outer) and \
                    not re.match(r"(else|elif)\b", run[nxt][1].strip())
            if ok:
                hits.append((COLLAPSIBLE_IF, outer_no, outer))
        return hits

    def _check_comments(self, run: List[Line], ext: str) -> List[_Hit]:
        hits: List[_Hit] = []
        code_re = _PY_CODE_COMMENT_RE if ext in _HASH_COMMENT else _C_CODE_COMMENT_RE
        in_code_block = False
        for i, (line_no, text) in enumerate(run):
            body = _comment_body(text, ext)
            if body is None or _is_bypass(text):
                in_code_block = False
                continue
            looks_like_code = bool(code_re.match(body)) and not _DOC_COMMENT_HINTS.search(body)
            if looks_like_code:
                if not in_code_block:
                    hits.append((COMMENTED_OUT_CODE, line_no, text))
                in_code_block = True
                continue
            in_code_block = False
            # Only single-line comments can be narration; skip multi-line comment blocks.
            prev_is_comment = i > 0 and _comment_body(run[i - 1][1], ext) is not None
            if prev_is_comment:
                continue
            if i + 1 < len(run) and self._is_narration(body, run[i + 1][1], ext):
                hits.append((NARRATING_COMMENT, line_no, text))
        return hits

    @staticmethod
    def _is_narration(comment: str, next_line: str, ext: str) -> bool:
        if not next_line.strip() or _comment_body(next_line, ext) is not None:
            return False
        if _INTENT_MARKERS.search(comment):
            return False
        words = re.findall(r"[a-z]+", comment.lower())
        if not words or len(words) > _MAX_NARRATION_WORDS:
            return False
        code_words = _identifier_words(_code_part(next_line, ext))
        content = {w.rstrip("s") for w in words if w not in _NARRATION_STOPWORDS}
        return bool(code_words) and content <= code_words

    def _check_god_function(self, run: List[Line], ext: str) -> List[_Hit]:
        hits: List[_Hit] = []
        patterns = _SIGNATURE_RES.get(_EXT_TO_SIG.get(ext, ""), [])
        max_lines = get_config().max_function_lines
        for i, (line_no, text) in enumerate(run):
            code = _strip_strings(text)
            if _is_bypass(text) or not any(p.match(code) for p in patterns):
                continue
            if ext in _PY or ext == ".rb":
                end = _block_end(run, i + 1, _indent(text))
                body = sum(1 for _, t in run[i + 1:end] if t.strip())
            else:
                body = self._braced_body_length(run, i, ext)
            if body > max_lines:
                smell = replace(
                    GOD_FUNCTION,
                    message=f"Function body is {body} lines (max {max_lines}).",
                )
                hits.append((smell, line_no, text))
        return hits

    @staticmethod
    def _braced_body_length(run: List[Line], start: int, ext: str) -> int:
        depth = 0
        opened = False
        count = 0
        for _, text in run[start:]:
            code = _code_part(text, ext)
            depth += code.count("{") - code.count("}")
            if "{" in code:
                opened = True
            if opened and text.strip():
                count += 1
            if opened and depth <= 0:
                break
        return max(count - 2, 0)
