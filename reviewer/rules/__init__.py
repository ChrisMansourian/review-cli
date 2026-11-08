"""Reviewer rules package."""

from reviewer.rules.base import BaseRule, RuleRegistry, default_registry, register_rule
from reviewer.rules.curly_braces import CurlyBracesRule
from reviewer.rules.secrets import SecretDetectionRule
from reviewer.rules.debug_code import NoDebugCodeRule
from reviewer.rules.style import StyleGuideRule
from reviewer.rules.commit_message import CommitMessageRule
from reviewer.rules.code_quality import CodeQualityRule
from reviewer.rules.refactor_patterns import RefactorPatternsRule
from reviewer.rules.security_patterns import SecurityPatternsRule

__all__ = [
    "BaseRule",
    "RuleRegistry",
    "default_registry",
    "register_rule",
    "CurlyBracesRule",
    "SecretDetectionRule",
    "NoDebugCodeRule",
    "StyleGuideRule",
    "CommitMessageRule",
    "CodeQualityRule",
    "RefactorPatternsRule",
    "SecurityPatternsRule",
]
