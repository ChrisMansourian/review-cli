"""Inline suppression directives (``reviewer:ignore`` / ``reviewer:ignore-file``)."""

import fnmatch
import re
from typing import Dict, List, Optional

from reviewer.models import FileDiff, Violation

# ``None`` means "suppress every rule"; a list restricts to those ID globs.
Directive = Optional[List[str]]

_LINE_RE = re.compile(r"reviewer:ignore(?![\w-])(?:\[([^\]]*)\])?", re.IGNORECASE)
_FILE_RE = re.compile(r"reviewer:ignore-file(?![\w-])(?:\[([^\]]*)\])?", re.IGNORECASE)
FILE_DIRECTIVE_WINDOW = 5


def _parse_ids(raw: Optional[str]) -> Directive:
    if raw is None:
        return None
    return [part.strip() for part in raw.split(",") if part.strip()]


def parse_line_directives(text: str) -> List[Directive]:
    """Return every ``reviewer:ignore[...]`` directive found on one line."""
    return [_parse_ids(m.group(1)) for m in _LINE_RE.finditer(text)]


def parse_file_directives(lines: List[str]) -> List[Directive]:
    """Return ``reviewer:ignore-file`` directives from the first few lines."""
    found: List[Directive] = []
    for text in lines[:FILE_DIRECTIVE_WINDOW]:
        for m in _FILE_RE.finditer(text):
            found.append(_parse_ids(m.group(1)))
    return found


def _matches(directives: List[Directive], rule_id: str) -> bool:
    for ids in directives:
        if ids is None:
            return True
        if any(fnmatch.fnmatchcase(rule_id, pattern) for pattern in ids):
            return True
    return False


def filter_suppressed(violations: List[Violation], file_diff: FileDiff) -> List[Violation]:
    """Drop violations on ``file_diff`` silenced by inline directives."""
    if file_diff.full_content is not None:
        head = file_diff.full_content.splitlines()
    else:
        head = [text for _, text in file_diff.added_lines]
    file_directives = parse_file_directives(head)
    line_text: Dict[int, str] = dict(file_diff.added_lines)

    kept: List[Violation] = []
    for violation in violations:
        if violation.file_path != file_diff.file_path:
            kept.append(violation)
            continue
        if _matches(file_directives, violation.rule_id):
            continue
        directives = parse_line_directives(line_text.get(violation.line_number, ""))
        if _matches(directives, violation.rule_id):
            continue
        kept.append(violation)
    return kept
