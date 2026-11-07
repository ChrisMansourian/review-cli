---
name: reviewer
description: >-
  Use this skill to run local-first code reviews, inspect git diffs, scan for security
  vulnerabilities (hardcoded keys/secrets), enforce custom syntax guardrails (curly braces, no debug statements),
  and generate formal Pull Request descriptions for GitHub submission.
---

# Reviewer: Local-First Code Review & Guardrail Skill

The `reviewer` CLI is a local-first developer tool that minimizes AI context overhead by inspecting only changed git lines, scanning for security vulnerabilities and AI anti-patterns, and persisting results to `.reviewer/report.md`.

## Workflow & Commands

### 1. Running Local Reviews
When the user requests a code review or syntax/security scan:
```bash
# Default review against base branch or working tree changes
reviewer

# Strict mode: fail on any warning or style violation
reviewer --strict

# Review only staged changes
reviewer --staged

# Generate Pull Request template alongside review
reviewer --pr
```

### 2. Reading and Remediating Issues
When commanded by the user (e.g., `[PROMPT: Read .reviewer/report.md and fix the flagged issues]`):
1. **Read `.reviewer/report.md`** to inspect the categorized list of errors and warnings.
2. For each flagged violation:
   - Locate the exact file and line number.
   - For **`syntax/curly-braces-required`**: Ensure all single-line `if`, `else`, `for`, and `while` statements are enclosed in curly braces `{ ... }`.
   - For **`security/hardcoded-secrets`**: Remove the secret and replace with environment variable access (`os.environ.get(...)`, `process.env....`).
   - For **`quality/no-debug-code`**: Delete leftover `console.log`, `print()`, `debugger;`, or resolve `TODO` comments.
   - For **`style/formatting`**: Adjust indentation and line lengths.
3. Re-run `reviewer` to ensure 0 errors remain.

### 3. Creating Pull Requests via GitHub MCP
1. Run `reviewer --pr` to generate the PR draft at `.reviewer/pr_description.md`.
2. Review the generated title and body.
3. Call the GitHub MCP server tool `create_pull_request` with:
   - `owner`: Repository owner
   - `repo`: Repository name
   - `title`: PR title from `.reviewer/pr_description.md`
   - `body`: PR description from `.reviewer/pr_description.md`
   - `head`: Feature branch name
   - `base`: Target branch (e.g., `main`)
