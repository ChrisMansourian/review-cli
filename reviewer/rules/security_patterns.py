"""Security and suppression-hygiene rule pack.

Line-based heuristics over the added lines of a diff. Code patterns are matched
against a *masked* copy of each line in which string-literal contents and
trailing comments are blanked out, so a pattern that merely appears inside a
string or comment never fires. Rules that must inspect a string argument
(SQL text, ``createHash('md5')``) locate the call in the masked line and then
read the argument from the original text at the same offset.
"""

import os
import re
from typing import Callable, List, NamedTuple, Tuple

from reviewer.models import FileDiff, Severity, Violation
from reviewer.rules.base import BaseRule, register_rule
from reviewer.rules.code_quality import CODE_EXTENSIONS, _is_bypass
from reviewer.rules.refactor_patterns import (
    _HASH_COMMENT,
    _JS,
    _STRING_RE,
    _Hit,
    _Smell,
)

_TS = {".ts", ".tsx"}
_PY_EXT = ".py"
_CONFIG_EXTENSIONS = {".sh", ".env", ".yml", ".yaml"}

SQL_FORMAT = _Smell(
    "security/sql-string-format", "SQL Built With String Formatting", Severity.ERROR,
    "SQL statement is assembled with string formatting/concatenation, enabling SQL injection.",
    "Use a parameterised query and pass values separately: execute(sql, params).",
)
UNSAFE_DESERIALIZATION = _Smell(
    "security/unsafe-deserialization", "Unsafe Deserialization", Severity.ERROR,
    "Deserialising untrusted data with pickle/marshal/unsafe YAML can execute arbitrary code.",
    "Use json, or yaml.safe_load / Loader=yaml.SafeLoader for YAML.",
)
TLS_VERIFY_DISABLED = _Smell(
    "security/tls-verify-disabled", "TLS Verification Disabled", Severity.ERROR,
    "Certificate verification is turned off, allowing man-in-the-middle attacks.",
    "Keep verification on; trust a custom CA bundle instead of disabling checks.",
)
INNER_HTML = _Smell(
    "security/inner-html", "Raw HTML Injection", Severity.WARNING,
    "Writing raw HTML into the DOM opens cross-site scripting (XSS) risks.",
    "Use textContent / DOM APIs, or sanitise the HTML (e.g. DOMPurify) first.",
)
WEAK_HASH = _Smell(
    "security/weak-hash", "Weak Hash Algorithm", Severity.WARNING,
    "MD5/SHA-1 are cryptographically broken.",
    "Use SHA-256 or better, or pass usedforsecurity=False for non-security checksums.",
)
UNEXPLAINED_SUPPRESSION = _Smell(
    "quality/unexplained-suppression", "Unexplained Suppression", Severity.WARNING,
    "Lint/type suppression has neither a rule code nor a reason.",
    "Name the rule being suppressed (e.g. [attr-defined], E501) or add a short reason.",
)
TS_ANY = _Smell(
    "quality/ts-any", "TypeScript any", Severity.INFO,
    "Explicit ``any`` disables type checking.",
    "Use a concrete type, a generic, or ``unknown`` and narrow it.",
)

# --- regexes ----------------------------------------------------------------

_SQL_KEYWORD_RE = re.compile(
    r"\b(SELECT\b.*\bFROM|INSERT\s+INTO|UPDATE\b.*\bSET|DELETE\s+FROM)\b", re.IGNORECASE | re.DOTALL
)
_SQL_CALL_RE = re.compile(r"(?<!def )\b(?:execute|executemany|query|raw)\s*\(")
_FORMAT_AFTER_RE = re.compile(r"^\s*(?:%|\+|\.format\s*\()")
_FORMAT_BEFORE_RE = re.compile(r"\+\s*[A-Za-z]{0,2}$")
_BRACE_FIELD_RE = re.compile(r"\{[^}]+\}")

_PICKLE_RE = re.compile(r"\b(?:c?pickle|_pickle|marshal)\.loads?\s*\(")
_YAML_LOAD_RE = re.compile(r"\byaml\.load(?:_all)?\s*\(")
_SAFE_LOADER_RE = re.compile(r"Loader\s*=\s*(?:\w+\.)?(?:C?Safe|Base)Loader\b")

_VERIFY_FALSE_RE = re.compile(r"\bverify\s*=\s*False\b")
_REJECT_UNAUTH_RE = re.compile(r"\brejectUnauthorized\s*:\s*false\b")
_INSECURE_SKIP_RE = re.compile(r"\bInsecureSkipVerify\s*:\s*true\b")
_NODE_TLS_RE = re.compile(r"NODE_TLS_REJECT_UNAUTHORIZED[\"']?]?\s*[:=,]\s*[\"']?0\b")

_INNER_HTML_ASSIGN_RE = re.compile(r"\.innerHTML\s*\+?=(?!=)")
_EMPTY_RHS_RE = re.compile(r"^\s*(?:\"\"|''|``)\s*;?\s*$")
_DANGEROUS_HTML_RE = re.compile(r"\bdangerouslySetInnerHTML\b|\bdocument\.write(?:ln)?\s*\(")

_HASHLIB_WEAK_RE = re.compile(r"\bhashlib\.(?:md5|sha1)\s*\(")
_NOT_FOR_SECURITY_RE = re.compile(r"usedforsecurity\s*=\s*False")
_CREATE_HASH_RE = re.compile(r"\bcreateHash\s*\(")
_WEAK_ALGO_ARG_RE = re.compile(r"^\s*['\"](?:md5|sha1)['\"]", re.IGNORECASE)

_TYPE_IGNORE_RE = re.compile(r"#\s*type:\s*ignore\b(?P<tail>.*)")
_NOQA_RE = re.compile(r"#\s*noqa\b(?P<tail>.*)", re.IGNORECASE)
_TS_IGNORE_RE = re.compile(r"(?://|/\*)\s*@ts-ignore\b(?P<tail>.*)")
_ESLINT_DISABLE_RE = re.compile(r"(?://|/\*)\s*eslint-disable(?:-next-line|-line)?\b(?P<tail>.*)")

_TS_ANY_RE = re.compile(r":\s*any\b|\bas\s+any\b|<any>")

_FILLER = " \t-—:;#*/,"
_LOOKAHEAD_LINES = 4

Line = Tuple[int, str]


class _Ctx(NamedTuple):
    """One added line plus its string/comment-masked form."""
    run: List[Line]
    idx: int
    text: str
    masked: str
    ext: str

    @property
    def line_no(self) -> int:
        return self.run[self.idx][0]

    @property
    def window(self) -> str:
        return _window(self.run, self.idx)


# --- helpers ----------------------------------------------------------------

def _blank_string(match: "re.Match") -> str:
    literal = match.group(0)
    return literal[0] + "x" * (len(literal) - 2) + literal[-1]


def _mask_strings(text: str) -> str:
    """Blank string contents (same length, quotes kept) so offsets stay aligned."""
    return _STRING_RE.sub(_blank_string, text)


def _comment_start(masked: str, ext: str) -> int:
    """Offset of the first comment marker in a string-masked line, or -1."""
    markers = ["#"] if ext in _HASH_COMMENT else ["//", "/*"]
    found = [masked.find(m) for m in markers if m in masked]
    return min(found) if found else -1


def _mask(text: str, ext: str) -> str:
    """String-masked line with any trailing comment removed."""
    masked = _mask_strings(text)
    cut = _comment_start(masked, ext)
    return masked if cut < 0 else masked[:cut]


def _has_reason(tail: str) -> bool:
    """True when text after a suppression directive is more than separators."""
    return bool(tail.replace("*/", "").strip(_FILLER))


def _window(run: List[Line], idx: int) -> str:
    """Text of a line plus the next few consecutively numbered lines."""
    parts = [run[idx][1]]
    for offset in range(1, _LOOKAHEAD_LINES + 1):
        nxt = idx + offset
        if nxt >= len(run) or run[nxt][0] != run[idx][0] + offset:
            break
        parts.append(run[nxt][1])
    return " ".join(parts)


def _contiguous(lines: List[Line]) -> List[List[Line]]:
    runs: List[List[Line]] = []
    for item in lines:
        if runs and item[0] == runs[-1][-1][0] + 1:
            runs[-1].append(item)
        else:
            runs.append([item])
    return runs


@register_rule
class SecurityPatternsRule(BaseRule):
    """Flags injection, deserialization, TLS, XSS and weak-hash risks plus bare suppressions."""

    rule_id = "security/patterns"
    name = "Security & Suppression Patterns"
    description = (
        "SQL built by string formatting, unsafe deserialization, disabled TLS "
        "verification, raw HTML injection, weak hashes, unexplained lint/type "
        "suppressions and explicit TypeScript any."
    )
    severity = Severity.ERROR

    def check(self, file_diff: FileDiff) -> List[Violation]:
        ext = os.path.splitext(file_diff.file_path)[1].lower()
        if ext not in CODE_EXTENSIONS and ext not in _CONFIG_EXTENSIONS:
            return []

        checks: List[Callable[..., List[_Hit]]] = [
            self._check_sql,
            self._check_deserialization,
            self._check_tls,
            self._check_html,
            self._check_weak_hash,
            self._check_suppression,
            self._check_ts_any,
        ]
        hits: List[_Hit] = []
        for run in _contiguous(file_diff.added_lines):
            for idx, (_, text) in enumerate(run):
                masked = _mask(text, ext)
                for check in checks:
                    hits.extend(check(_Ctx(run, idx, text, masked, ext)))
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

    # -- security -------------------------------------------------------------

    def _check_sql(self, ctx: _Ctx) -> List[_Hit]:
        text, masked, ext = ctx.text, ctx.masked, ctx.ext
        if _is_bypass(text):
            return []
        for call in _SQL_CALL_RE.finditer(masked):
            if self._formats_sql(text[call.end():len(masked)]):
                return [(SQL_FORMAT, ctx.line_no, text)]
        return []

    @staticmethod
    def _formats_sql(args: str) -> bool:
        """True when a SQL-looking literal in ``args`` is interpolated or concatenated."""
        for lit in _STRING_RE.finditer(args):
            body = lit.group(0)
            if not _SQL_KEYWORD_RE.search(body):
                continue
            prefix = args[max(0, lit.start() - 2):lit.start()].lower()
            is_f_string = body[0] != "`" and "f" in prefix and bool(_BRACE_FIELD_RE.search(body))
            is_template = body[0] == "`" and "${" in body
            formatted_after = bool(_FORMAT_AFTER_RE.match(args[lit.end():]))
            concat_before = bool(_FORMAT_BEFORE_RE.search(args[:lit.start()]))
            if is_f_string or is_template or formatted_after or concat_before:
                return True
        return False

    def _check_deserialization(self, ctx: _Ctx) -> List[_Hit]:
        text, masked, ext = ctx.text, ctx.masked, ctx.ext
        if ext != _PY_EXT or _is_bypass(text):
            return []
        if _PICKLE_RE.search(masked):
            return [(UNSAFE_DESERIALIZATION, ctx.line_no, text)]
        if _YAML_LOAD_RE.search(masked) and not _SAFE_LOADER_RE.search(ctx.window):
            return [(UNSAFE_DESERIALIZATION, ctx.line_no, text)]
        return []

    def _check_tls(self, ctx: _Ctx) -> List[_Hit]:
        text, masked, ext = ctx.text, ctx.masked, ctx.ext
        if _is_bypass(text):
            return []
        disabled = (
            (ext == _PY_EXT and _VERIFY_FALSE_RE.search(masked))
            or (ext in _JS and _REJECT_UNAUTH_RE.search(masked))
            or (ext == ".go" and _INSECURE_SKIP_RE.search(masked))
            # The env var name is usually inside a string, so match the raw text.
            or _NODE_TLS_RE.search(text[:len(masked)])
        )
        return [(TLS_VERIFY_DISABLED, ctx.line_no, text)] if disabled else []

    def _check_html(self, ctx: _Ctx) -> List[_Hit]:
        text, masked, ext = ctx.text, ctx.masked, ctx.ext
        if ext not in _JS or _is_bypass(text):
            return []
        assign = _INNER_HTML_ASSIGN_RE.search(masked)
        if assign and not _EMPTY_RHS_RE.match(text[assign.end():len(masked)]):
            return [(INNER_HTML, ctx.line_no, text)]
        if _DANGEROUS_HTML_RE.search(masked):
            return [(INNER_HTML, ctx.line_no, text)]
        return []

    def _check_weak_hash(self, ctx: _Ctx) -> List[_Hit]:
        text, masked, ext = ctx.text, ctx.masked, ctx.ext
        if _is_bypass(text):
            return []
        hit = [(WEAK_HASH, ctx.line_no, text)]
        if ext == _PY_EXT and _HASHLIB_WEAK_RE.search(masked):
            return [] if _NOT_FOR_SECURITY_RE.search(ctx.window) else hit
        if ext in _JS:
            for call in _CREATE_HASH_RE.finditer(masked):
                if _WEAK_ALGO_ARG_RE.match(text[call.end():len(masked)]):
                    return hit
        return []

    # -- suppression hygiene --------------------------------------------------

    def _check_suppression(self, ctx: _Ctx) -> List[_Hit]:
        text, ext = ctx.text, ctx.ext
        lowered = text.lower()
        if "reviewer:ignore" in lowered or "reviewer:allow" in lowered:
            return []
        cut = _comment_start(_mask_strings(text), ext)
        if cut < 0:
            return []
        comment = text[cut:]
        if ext == _PY_EXT and self._bare_python_suppression(comment):
            return [(UNEXPLAINED_SUPPRESSION, ctx.line_no, text)]
        if ext in _JS:
            for regex in (_TS_IGNORE_RE, _ESLINT_DISABLE_RE):
                match = regex.search(comment)
                if match and not _has_reason(match.group("tail")):
                    return [(UNEXPLAINED_SUPPRESSION, ctx.line_no, text)]
        return []

    @staticmethod
    def _bare_python_suppression(comment: str) -> bool:
        ignore = _TYPE_IGNORE_RE.search(comment)
        if ignore:
            tail = ignore.group("tail")
            if not tail.lstrip().startswith("[") and not _has_reason(tail):
                return True
        noqa = _NOQA_RE.search(comment)
        if noqa:
            tail = noqa.group("tail")
            # ``# noqa: CODE`` carries a code; ``# noqa reason...`` carries a reason.
            if not tail.lstrip().startswith(":") and not _has_reason(tail):
                return True
        return False

    # -- typescript -----------------------------------------------------------

    def _check_ts_any(self, ctx: _Ctx) -> List[_Hit]:
        text, masked, ext = ctx.text, ctx.masked, ctx.ext
        if ext not in _TS or _is_bypass(text):
            return []
        if _TS_ANY_RE.search(masked):
            return [(TS_ANY, ctx.line_no, text)]
        return []
