"""Security and Secret Detection Scanner (Anti-AI Guardrail)."""

import re
from typing import List, Tuple
from reviewer.models import FileDiff, Violation, Severity
from reviewer.rules.base import BaseRule, RuleInfo, register_rule

# Comprehensive secret regex signatures
SECRET_PATTERNS: List[Tuple[str, str, re.Pattern, Severity]] = [
    (
        "security/aws-access-key",
        "AWS Access Key ID Detected",
        re.compile(r"\b(AKIA[0-9A-Z]{16})\b"),
        Severity.ERROR,
    ),
    (
        "security/aws-secret-key",
        "AWS Secret Access Key Detected",
        re.compile(r"(?i)aws_secret_access_key\s*[:=]\s*['\"][A-Za-z0-9/+=]{40}['\"]"),
        Severity.ERROR,
    ),
    (
        "security/github-token",
        "GitHub Personal Access Token Detected",
        re.compile(r"\b(gh[pousr]_[A-Za-z0-9_]{36,255}|github_pat_[A-Za-z0-9_]{82})\b"),
        Severity.ERROR,
    ),
    (
        "security/private-key",
        "Private Cryptographic Key Detected",
        re.compile(r"-----BEGIN (RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----"),
        Severity.ERROR,
    ),
    (
        "security/connection-string-credential",
        "Hardcoded Database/Service Connection String with Password",
        re.compile(r"(?i)\b(postgres|postgresql|mysql|mongodb|redis|amqp|mssql):\/\/[^\s:]+:[^\s@]+@[^\s\/:]+"),
        Severity.ERROR,
    ),
    (
        "security/slack-token",
        "Slack Bot/User Token Detected",
        re.compile(r"\b(xox[baprs]-[0-9a-zA-Z]{10,48})\b"),
        Severity.ERROR,
    ),
    (
        "security/jwt-token",
        "Hardcoded JSON Web Token (JWT) Detected",
        re.compile(r"\beyJ[A-Za-z0-9-_]{10,}\.eyJ[A-Za-z0-9-_]{10,}\.[A-Za-z0-9-_]{10,}\b"),
        Severity.WARNING,
    ),
    (
        "security/generic-secret",
        "Potential Hardcoded API Key or Secret",
        re.compile(
            r"(?i)\b(api_key|apikey|secret_key|client_secret|auth_token)"
            r"\s*[:=]\s*['\"][a-zA-Z0-9_\-\.\/+=]{20,}['\"]"
        ),
        Severity.WARNING,
    ),
]


def redact_secret(text: str) -> str:
    """Mask secret characters for safe reporting."""
    if len(text) <= 8:
        return "****"
    return f"{text[:4]}...{text[-4:]}"


@register_rule
class SecretDetectionRule(BaseRule):
    """Scans diff additions for exposed credentials, API keys, and connection strings."""
    rule_id = "security/hardcoded-secrets"
    name = "Secret Detection Scanner"
    description = (
        "Detects hardcoded secrets, API tokens, private keys, and credentials "
        "accidentally committed or generated in diffs."
    )
    severity = Severity.ERROR

    def catalog(self) -> List[RuleInfo]:
        suggestion = "Store the secret in an environment variable or a secret manager, and rotate it."
        return [
            RuleInfo(rule_id, name, severity, f"{name}. Secrets must never be committed.", suggestion)
            for rule_id, name, _pattern, severity in SECRET_PATTERNS
        ]

    def check(self, file_diff: FileDiff) -> List[Violation]:
        # Exclude mock test data files or examples if explicitly named
        path_lower = file_diff.file_path.lower()
        if "test" in path_lower and ("mock" in path_lower or "fixture" in path_lower):
            # Still scan, but downgrade severity if desired; keep full scan for safety
            pass

        violations: List[Violation] = []

        for line_no, line_text in file_diff.added_lines:
            # Check for inline ignore directives
            if any(marker in line_text.lower() for marker in [
                "reviewer:ignore",
                "reviewer:allow",
                "reviewer:allow-secret",
                "noqa",
            ]):
                continue

            for rule_id, rule_name, pattern, severity in SECRET_PATTERNS:
                match = pattern.search(line_text)
                if match:
                    matched_str = match.group(0)
                    # Exclude obvious documentation templates like <YOUR_KEY>, YOUR_KEY_HERE, xxx, user:pass
                    if any(p in matched_str.lower() for p in [
                        "placeholder", "<your_", "your_key", "xxxx", "user:pass", "supersecret123"
                    ]):
                        continue

                    safe_snippet = line_text.replace(matched_str, redact_secret(matched_str)).strip()
                    violations.append(
                        Violation(
                            file_path=file_diff.file_path,
                            line_number=line_no,
                            rule_id=rule_id,
                            rule_name=rule_name,
                            severity=severity,
                            message=f"{rule_name}. Secrets must never be committed to source code.",
                            snippet=safe_snippet,
                            suggestion="Store secret in environment variables or a secure secret manager (e.g., .env or Vault).",
                        )
                    )

        return violations
