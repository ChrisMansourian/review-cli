"""Data models for reviewer CLI."""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple, Dict, Any
from datetime import datetime, timezone


class Severity(str, Enum):
    """Violation severity levels."""
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


@dataclass
class Violation:
    """Represents a rule violation detected in code."""
    file_path: str
    line_number: int
    rule_id: str
    rule_name: str
    severity: Severity
    message: str
    snippet: str = ""
    suggestion: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "line_number": self.line_number,
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "severity": self.severity.value,
            "message": self.message,
            "snippet": self.snippet,
            "suggestion": self.suggestion,
        }


@dataclass
class FileDiff:
    """Represents git changes for a single file."""
    file_path: str
    old_path: Optional[str] = None
    status: str = "modified"  # added, modified, deleted, renamed
    added_lines: List[Tuple[int, str]] = field(default_factory=list)  # (line_no, line_content)
    full_content: Optional[str] = None


@dataclass
class ReviewReport:
    """Consolidated review report."""
    target_ref: str
    base_ref: str
    files_analyzed: int
    lines_analyzed: int
    violations: List[Violation] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    strict: bool = False

    @property
    def error_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == Severity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == Severity.WARNING)

    @property
    def info_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == Severity.INFO)

    @property
    def passed(self) -> bool:
        if self.strict:
            return len(self.violations) == 0
        return self.error_count == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "target_ref": self.target_ref,
            "base_ref": self.base_ref,
            "files_analyzed": self.files_analyzed,
            "lines_analyzed": self.lines_analyzed,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "strict": self.strict,
            "passed": self.passed,
            "violations": [v.to_dict() for v in self.violations],
        }
