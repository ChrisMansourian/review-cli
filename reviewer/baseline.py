"""Baseline of accepted findings, keyed by line-independent fingerprints."""

import hashlib
import json
import os
from typing import Dict, List, Tuple

from reviewer.models import Violation

BASELINE_FILENAME = ".reviewer-baseline.json"
BASELINE_VERSION = 1


def fingerprint(violation: Violation) -> str:
    """sha1(rule_id, posix file path, whitespace-normalised snippet); no line numbers."""
    path = violation.file_path.replace("\\", "/")
    snippet = " ".join(violation.snippet.split())
    raw = "\0".join([violation.rule_id, path, snippet])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _is_baselinable(violation: Violation) -> bool:
    return not violation.file_path.startswith("commit:")


def baseline_path(repo_dir: str) -> str:
    return os.path.join(repo_dir, BASELINE_FILENAME)


def load_baseline(repo_dir: str) -> Dict[str, dict]:
    """Return stored fingerprints, or an empty dict if missing or unreadable."""
    try:
        with open(baseline_path(repo_dir), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        fingerprints = data.get("fingerprints", {})
        return fingerprints if isinstance(fingerprints, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def write_baseline(repo_dir: str, violations: List[Violation]) -> str:
    entries = {
        fingerprint(v): {"rule_id": v.rule_id, "file_path": v.file_path.replace("\\", "/")}
        for v in violations
        if _is_baselinable(v)
    }
    payload = {"version": BASELINE_VERSION, "fingerprints": entries}
    path = baseline_path(repo_dir)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return path


def apply_baseline(
    violations: List[Violation], known: Dict[str, dict]
) -> Tuple[List[Violation], int]:
    """Split out baselined violations; returns (remaining, hidden_count)."""
    remaining: List[Violation] = []
    hidden = 0
    for violation in violations:
        if _is_baselinable(violation) and fingerprint(violation) in known:
            hidden += 1
        else:
            remaining.append(violation)
    return remaining, hidden
