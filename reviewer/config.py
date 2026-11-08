"""Configuration loading for reviewer (``[tool.reviewer]`` / ``.reviewer.toml``).

Rules are module-level singletons, so the active configuration is held in this
module: the CLI / MCP server call :func:`set_config` once per run and rules read
limits through :func:`get_config` at check time.
"""

import fnmatch
import os
import re
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Tuple

from reviewer.models import Severity

try:  # Python 3.11+
    import tomllib as _toml
except ImportError:  # pragma: no cover - depends on interpreter version
    try:
        import tomli as _toml
    except ImportError:
        _toml = None

CONFIG_FILENAMES = ("pyproject.toml", ".reviewer.toml")

_THRESHOLD_KEYS = (
    "max_params",
    "max_nesting",
    "max_function_lines",
    "max_line_length",
    "elif_chain",
    "literal_repeat",
    "duplicate_lines",
)
_TOP_LEVEL_KEYS = ("disable", "ignore_paths", "severity", "thresholds")


@dataclass(frozen=True)
class ReviewerConfig:
    """Effective settings; defaults reproduce the built-in behaviour."""
    disable: Tuple[str, ...] = ()
    ignore_paths: Tuple[str, ...] = ()
    severity: Dict[str, Severity] = field(default_factory=dict)
    max_params: int = 4
    max_nesting: int = 4
    max_function_lines: int = 50
    max_line_length: int = 120
    elif_chain: int = 3
    literal_repeat: int = 3
    duplicate_lines: int = 3

    def is_disabled(self, rule_id: str) -> bool:
        return any(fnmatch.fnmatchcase(rule_id, pat) for pat in self.disable)

    def is_path_ignored(self, file_path: str) -> bool:
        return path_matches(file_path, self.ignore_paths)


_active = ReviewerConfig()


def get_config() -> ReviewerConfig:
    return _active


def set_config(cfg: Optional[ReviewerConfig]) -> None:
    """Install the active config (``None`` resets to defaults)."""
    global _active
    _active = cfg if cfg is not None else ReviewerConfig()


def _glob_to_regex(pattern: str) -> "re.Pattern":
    out = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
            continue
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
            continue
        ch = pattern[i]
        if ch == "*":
            out.append("[^/]*")
        elif ch == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(ch))
        i += 1
    return re.compile("".join(out) + r"\Z")


def path_matches(file_path: str, patterns: Tuple[str, ...]) -> bool:
    """Match a repo-relative path against globs where ``**`` spans directories.

    A pattern with no ``/`` is also tried against the basename.
    """
    norm = file_path.replace("\\", "/")
    if norm.startswith("./"):
        norm = norm[2:]
    base = norm.rsplit("/", 1)[-1]
    for pat in patterns:
        pat = pat.replace("\\", "/")
        regex = _glob_to_regex(pat)
        if regex.match(norm) or ("/" not in pat and regex.match(base)):
            return True
    return False


def _str_list(value: Any, key: str, warnings: List[str]) -> Tuple[str, ...]:
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return tuple(value)
    warnings.append(f"config: '{key}' must be a list of strings; ignoring")
    return ()


def build_config(data: Dict[str, Any], warnings: List[str]) -> ReviewerConfig:
    """Validate a raw table into a ReviewerConfig, appending problems to warnings."""
    cfg = ReviewerConfig()
    for key in data:
        if key not in _TOP_LEVEL_KEYS:
            warnings.append(f"config: unknown key '{key}'")
    if "disable" in data:
        cfg = replace(cfg, disable=_str_list(data["disable"], "disable", warnings))
    if "ignore_paths" in data:
        cfg = replace(cfg, ignore_paths=_str_list(data["ignore_paths"], "ignore_paths", warnings))

    sev_table = data.get("severity", {})
    if isinstance(sev_table, dict):
        severities: Dict[str, Severity] = {}
        for rule_id, raw in sev_table.items():
            try:
                severities[rule_id] = Severity(str(raw).upper())
            except ValueError:
                warnings.append(f"config: invalid severity {raw!r} for '{rule_id}' (use ERROR, WARNING or INFO)")
        cfg = replace(cfg, severity=severities)
    else:
        warnings.append("config: 'severity' must be a table; ignoring")

    thresholds = data.get("thresholds", {})
    if isinstance(thresholds, dict):
        updates: Dict[str, int] = {}
        for key, raw in thresholds.items():
            if key not in _THRESHOLD_KEYS:
                warnings.append(f"config: unknown key 'thresholds.{key}'")
            elif isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
                warnings.append(f"config: 'thresholds.{key}' must be a positive integer; ignoring")
            else:
                updates[key] = raw
        cfg = replace(cfg, **updates)
    else:
        warnings.append("config: 'thresholds' must be a table; ignoring")
    return cfg


def _read_toml(path: str, warnings: List[str]) -> Optional[Dict[str, Any]]:
    if _toml is None:
        warnings.append(
            f"config: found {path} but no TOML parser is available "
            "(install 'tomli' on Python < 3.11); using defaults"
        )
        return None
    try:
        with open(path, "rb") as fh:
            return _toml.load(fh)
    except (OSError, ValueError) as exc:  # TOMLDecodeError subclasses ValueError
        warnings.append(f"config: could not read {path}: {exc}; using defaults")
        return None


def _table_for(path: str, doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if os.path.basename(path).lower() == "pyproject.toml":
        table = doc.get("tool", {}).get("reviewer")
        return table if isinstance(table, dict) else None
    return doc


def load_config(
    repo_dir: Optional[str] = None,
    explicit_path: Optional[str] = None,
) -> Tuple[ReviewerConfig, List[str]]:
    """Find and parse configuration. Returns (config, warnings); never raises."""
    warnings: List[str] = []
    root = repo_dir or os.getcwd()
    if explicit_path:
        candidates = [explicit_path]
    else:
        candidates = [os.path.join(root, name) for name in CONFIG_FILENAMES]
    for path in candidates:
        if not os.path.isfile(path):
            if explicit_path:
                warnings.append(f"config: file not found: {path}; using defaults")
            continue
        doc = _read_toml(path, warnings)
        if doc is None:
            return ReviewerConfig(), warnings
        table = _table_for(path, doc)
        if table is None:
            if explicit_path:
                warnings.append(f"config: no [tool.reviewer] table in {path}; using defaults")
            continue
        return build_config(table, warnings), warnings
    return ReviewerConfig(), warnings


def apply_config(
    repo_dir: Optional[str] = None,
    explicit_path: Optional[str] = None,
) -> List[str]:
    """Load config, make it active, and return any warnings."""
    cfg, warnings = load_config(repo_dir, explicit_path)
    set_config(cfg)
    return warnings
