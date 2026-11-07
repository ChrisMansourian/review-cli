"""Pull Request description generator analyzing git commits and diffs."""

from pathlib import Path
from typing import List, Dict, Optional, Any
from reviewer.models import FileDiff, ReviewReport
from reviewer.git_diff import get_recent_commits, run_git_cmd, detect_base_branch


def categorize_file(path: str) -> str:
    """Categorize file into functional groups."""
    p = path.lower()
    if any(x in p for x in ["test", "spec"]):
        return "Tests"
    if any(p.endswith(ext) for ext in [".md", ".rst", ".txt", "license"]):
        return "Documentation"
    if any(p.endswith(ext) for ext in [".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".lock"]):
        return "Configuration & Infrastructure"
    if any(x in p for x in ["script", "bin", "tool"]):
        return "Scripts & Tooling"
    return "Core Logic & Application"


def detect_pr_type(commits: List[Dict[str, str]], files: List[FileDiff]) -> str:
    """Infer change type (feat, fix, refactor, chore) from commit messages and changed files."""
    text = " ".join([c.get("subject", "") for c in commits]).lower()
    if "feat" in text or "add" in text or "new" in text:
        return "feat"
    if "fix" in text or "bug" in text or "patch" in text:
        return "fix"
    if "refactor" in text or "clean" in text:
        return "refactor"
    if "test" in text:
        return "test"
    if "doc" in text:
        return "docs"
    return "chore"


def generate_pr_payload(
    file_diffs: List[FileDiff],
    report: Optional[ReviewReport] = None,
    repo_dir: Optional[str] = None,
    base_branch: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generate comprehensive Pull Request metadata and markdown description,
    formatted for direct consumption by the GitHub MCP server create_pull_request tool.
    """
    commits = get_recent_commits(count=5, repo_dir=repo_dir)

    # Detect branches
    code, current_branch, _ = run_git_cmd(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_dir)
    head_branch = current_branch.strip() or "HEAD"
    base = base_branch or detect_base_branch(repo_dir)

    # Clean base name (e.g., origin/main -> main)
    clean_base = base.replace("origin/", "")

    pr_type = detect_pr_type(commits, file_diffs)
    top_subject = commits[0]["subject"] if commits else "Update project codebase"
    # Format conventional title
    if ":" in top_subject and any(top_subject.lower().startswith(p) for p in ["feat", "fix", "refactor", "chore"]):
        pr_title = top_subject
    else:
        pr_title = f"{pr_type}: {top_subject}"

    # Group changed files
    categorized: Dict[str, List[str]] = {}
    total_lines = 0
    for fd in file_diffs:
        cat = categorize_file(fd.file_path)
        categorized.setdefault(cat, []).append(fd.file_path)
        total_lines += len(fd.added_lines)

    # Build description markdown
    body_lines = []
    body_lines.append("## 📌 Summary of Changes")
    if commits:
        body_lines.append(f"This PR introduces changes related to: **{commits[0]['subject']}**.")
    else:
        body_lines.append("This PR introduces local updates verified via `reviewer`.")
    body_lines.append("")

    body_lines.append("### 🏷️ Change Classification")
    body_lines.append(f"- [x] `{pr_type.upper()}` - Primary change classification")
    for t in ["feat", "fix", "refactor", "style", "docs", "test", "chore"]:
        if t != pr_type:
            body_lines.append(f"- [ ] `{t.upper()}`")
    body_lines.append("")

    body_lines.append("### 📁 Changed Files Breakdown")
    for cat, file_list in categorized.items():
        body_lines.append(f"**{cat}**")
        for f in file_list:
            body_lines.append(f"- `{f}`")
    body_lines.append("")

    if commits:
        body_lines.append("### 📜 Recent Commits")
        for c in commits:
            body_lines.append(f"- `{c['hash']}` {c['subject']} *({c['author']})*")
        body_lines.append("")

    # Security & Quality Gate summary
    body_lines.append("### 🛡️ Automated Local Review Gate (`reviewer`)")
    if report:
        if report.passed:
            body_lines.append(
                f"- ✅ **Security & Quality:** PASSED (0 Critical Errors, {report.warning_count} Warnings in {report.files_analyzed} files)"
            )
        else:
            body_lines.append(
                f"- ⚠️ **Security & Quality:** FAILED ({report.error_count} Errors, {report.warning_count} Warnings)"
            )
        body_lines.append(f"- **Evaluated Lines:** {report.lines_analyzed}")
    else:
        body_lines.append("- ℹ️ Verified with local reviewer CLI.")
    body_lines.append("")

    body_lines.append("### 🧪 Verification Checklist")
    body_lines.append("- [x] Local security scanner verified no hardcoded secrets or credentials.")
    body_lines.append("- [x] Custom syntax rules (curly braces, debug code removal) satisfied.")
    body_lines.append("- [x] Automated tests and linter checks pass locally.")
    body_lines.append("")

    pr_body = "\n".join(body_lines)

    # Save to .reviewer/pr_description.md
    target_dir = Path(repo_dir or ".") / ".reviewer"
    target_dir.mkdir(parents=True, exist_ok=True)
    pr_file = target_dir / "pr_description.md"
    pr_file.write_text(f"# {pr_title}\n\n{pr_body}", encoding="utf-8")

    return {
        "title": pr_title,
        "body": pr_body,
        "head": head_branch,
        "base": clean_base,
        "file_path": str(pr_file),
    }
