"""Base classes and registry for reviewer custom rules."""

from abc import ABC, abstractmethod
from dataclasses import replace
from typing import List, Dict, Optional, Type
from reviewer.config import ReviewerConfig, get_config
from reviewer.models import FileDiff, Violation, Severity


class BaseRule(ABC):
    """Abstract base class for all reviewer rules."""
    rule_id: str = "base-rule"
    name: str = "Base Rule"
    description: str = "Base rule description"
    severity: Severity = Severity.WARNING

    @abstractmethod
    def check(self, file_diff: FileDiff) -> List[Violation]:
        """Inspect changed lines in file_diff and return any detected violations."""
        pass

    def check_commits(self, commits: List[Dict[str, str]]) -> List[Violation]:
        """Optionally check git commits for quality, clarity, and formatting."""
        return []


class RuleRegistry:
    """Manages available and active rules."""

    def __init__(self):
        self._rules: Dict[str, BaseRule] = {}

    def register(self, rule: BaseRule) -> None:
        self._rules[rule.rule_id] = rule

    def get_all(self) -> List[BaseRule]:
        return list(self._rules.values())

    def get_by_id(self, rule_id: str) -> BaseRule:
        return self._rules.get(rule_id)

    def execute_all(
        self,
        file_diffs: List[FileDiff],
        commits: List[Dict[str, str]] = None,
        config: Optional[ReviewerConfig] = None,
    ) -> List[Violation]:
        """Run all registered rules against changed files and commits.

        ``disable`` and ``severity`` overrides from ``config`` (default: the
        active config) are applied to the resulting violations by rule_id.
        """
        cfg = config if config is not None else get_config()
        all_violations: List[Violation] = []
        for file_diff in file_diffs:
            for rule in self._rules.values():
                violations = rule.check(file_diff)
                all_violations.extend(violations)

        if commits:
            for rule in self._rules.values():
                commit_violations = rule.check_commits(commits)
                all_violations.extend(commit_violations)

        return self._apply_config(all_violations, cfg)

    @staticmethod
    def _apply_config(violations: List[Violation], cfg: ReviewerConfig) -> List[Violation]:
        result: List[Violation] = []
        for violation in violations:
            if cfg.is_disabled(violation.rule_id):
                continue
            override = cfg.severity.get(violation.rule_id)
            if override is not None and override != violation.severity:
                violation = replace(violation, severity=override)
            result.append(violation)
        return result


# Global default registry
default_registry = RuleRegistry()


def register_rule(rule_cls: Type[BaseRule]) -> Type[BaseRule]:
    """Decorator to register a rule class in the default registry."""
    instance = rule_cls()
    default_registry.register(instance)
    return rule_cls
