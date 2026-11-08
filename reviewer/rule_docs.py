"""Helpers behind ``reviewer rules`` and ``reviewer explain``."""

import difflib
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from reviewer.config import ReviewerConfig
from reviewer.rules.base import RuleInfo, RuleRegistry

SKILL_RELATIVE_PATH = os.path.join(".agents", "skills", "refactor", "SKILL.md")
_HEADING_RE = re.compile(r"^#{1,6}\s")


@dataclass(frozen=True)
class RuleRow:
    """A catalog entry plus the effect of the active config."""
    info: RuleInfo
    effective_severity: str
    overridden: bool
    disabled: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.info.rule_id,
            "name": self.info.name,
            "severity": self.effective_severity,
            "default_severity": self.info.severity.value,
            "overridden": self.overridden,
            "disabled": self.disabled,
            "description": self.info.description,
            "suggestion": self.info.suggestion,
        }


def build_rows(registry: RuleRegistry, cfg: ReviewerConfig) -> List[RuleRow]:
    rows: List[RuleRow] = []
    for info in registry.catalog():
        override = cfg.severity.get(info.rule_id)
        overridden = override is not None and override != info.severity
        effective = override.value if override is not None else info.severity.value
        rows.append(RuleRow(info, effective, overridden, cfg.is_disabled(info.rule_id)))
    return rows


def find_row(rows: List[RuleRow], rule_id: str) -> Optional[RuleRow]:
    for row in rows:
        if row.info.rule_id == rule_id:
            return row
    return None


def suggest_ids(rows: List[RuleRow], rule_id: str) -> List[str]:
    ids = [row.info.rule_id for row in rows]
    close = difflib.get_close_matches(rule_id, ids, n=3, cutoff=0.5)
    tail = [i for i in ids if i.endswith("/" + rule_id) and i not in close]
    return tail + close


def find_playbook(repo_dir: str, rule_id: str) -> Optional[Tuple[str, int]]:
    """Return (path, 1-based line) of the SKILL.md heading naming ``rule_id``."""
    path = os.path.join(repo_dir, SKILL_RELATIVE_PATH)
    if not os.path.isfile(path):
        return None
    needle = "`" + rule_id + "`"
    try:
        with open(path, encoding="utf-8") as fh:
            for number, line in enumerate(fh, start=1):
                if _HEADING_RE.match(line) and needle in line:
                    return path, number
    except OSError:
        return None
    return None
