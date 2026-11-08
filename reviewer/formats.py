"""Machine-readable output formats: SARIF 2.1.0 and GitHub Actions commands."""

import hashlib
import json
from typing import Any, Dict, List, Tuple

from reviewer import __version__
from reviewer.models import ReviewReport, Severity, Violation

SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
INFORMATION_URI = "https://github.com/ChrisMansourian/review-cli"
COMMIT_PREFIX = "commit:"

_SARIF_LEVELS = {
    Severity.ERROR: "error",
    Severity.WARNING: "warning",
    Severity.INFO: "note",
}
_GITHUB_COMMANDS = {
    Severity.ERROR: "error",
    Severity.WARNING: "warning",
    Severity.INFO: "notice",
}


def _is_commit(violation: Violation) -> bool:
    return violation.file_path.startswith(COMMIT_PREFIX)


def normalize_uri(path: str) -> str:
    """Repo-relative URI: forward slashes, no leading './' or '/'."""
    uri = path.replace("\\", "/")
    while uri.startswith("./"):
        uri = uri[2:]
    return uri.lstrip("/")


def _fingerprint(violation: Violation) -> str:
    snippet = " ".join(violation.snippet.split())
    key = "\n".join([violation.rule_id, normalize_uri(violation.file_path), snippet])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _build_rules(violations: List[Violation]) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    rules: List[Dict[str, Any]] = []
    rule_index: Dict[str, int] = {}
    for v in violations:
        if v.rule_id in rule_index:
            continue
        rule_index[v.rule_id] = len(rules)
        rule: Dict[str, Any] = {
            "id": v.rule_id,
            "name": v.rule_name,
            "shortDescription": {"text": v.rule_name},
            "defaultConfiguration": {"level": _SARIF_LEVELS[v.severity]},
        }
        if v.suggestion:
            rule["help"] = {"text": v.suggestion}
        rules.append(rule)
    return rules, rule_index


def _build_result(v: Violation, index: int) -> Dict[str, Any]:
    text = v.message if not v.suggestion else "{} Suggestion: {}".format(v.message, v.suggestion)
    result: Dict[str, Any] = {
        "ruleId": v.rule_id,
        "ruleIndex": index,
        "level": _SARIF_LEVELS[v.severity],
        "message": {"text": text},
        "partialFingerprints": {"primaryLocationLineHash": _fingerprint(v)},
    }
    if _is_commit(v):
        result["properties"] = {"commit": v.file_path[len(COMMIT_PREFIX):]}
    else:
        result["locations"] = [
            {
                "physicalLocation": {
                    "artifactLocation": {"uri": normalize_uri(v.file_path)},
                    "region": {"startLine": max(1, int(v.line_number or 1))},
                }
            }
        ]
    return result


def generate_sarif(report: ReviewReport) -> Dict[str, Any]:
    """Build a SARIF 2.1.0 document.

    Commit-message violations (``commit:<sha>``) have no file, so they are
    emitted without ``locations`` (valid SARIF); the sha is kept in the
    result's ``properties.commit``.
    """
    rules, rule_index = _build_rules(report.violations)
    results = [_build_result(v, rule_index[v.rule_id]) for v in report.violations]
    driver = {
        "name": "reviewer",
        "informationUri": INFORMATION_URI,
        "version": __version__,
        "rules": rules,
    }
    return {
        "$schema": SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [{"tool": {"driver": driver}, "results": results}],
    }


def generate_sarif_json(report: ReviewReport) -> str:
    return json.dumps(generate_sarif(report), indent=2)


def _escape_data(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_property(value: str) -> str:
    return _escape_data(value).replace(":", "%3A").replace(",", "%2C")


def format_github_command(violation: Violation) -> str:
    """One GitHub Actions workflow command for a violation."""
    props = []
    if not _is_commit(violation):
        props.append("file=" + _escape_property(normalize_uri(violation.file_path)))
        props.append("line=" + _escape_property(str(max(1, int(violation.line_number or 1)))))
    props.append("title=" + _escape_property(violation.rule_id))
    return "::{} {}::{}".format(
        _GITHUB_COMMANDS[violation.severity], ",".join(props), _escape_data(violation.message)
    )


def generate_github(report: ReviewReport) -> str:
    return "\n".join(format_github_command(v) for v in report.violations)
