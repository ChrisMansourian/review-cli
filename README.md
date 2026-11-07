# `reviewer` (CLI) & GitHub MCP Server Integration

> **Local-first developer tool for git diff inspection, automated security scanning, custom syntax guardrails, and GitHub Pull Request automation.**

---

## 🌟 Overview

Modern AI coding assistants are extraordinarily productive, but frequently repeat subtle mistakes:
- Omitting curly braces `{}` on single-line control statements (`if (x) return y;`), violating strict codebase style guides.
- Accidentally inserting or committing hardcoded API keys, tokens, or connection strings.
- Leaving behind leftover `console.log`, `debugger`, `print()`, or unaddressed `TODO` comments.
- Flooding the AI context window with entire files rather than focusing on git diff hunks.

**`reviewer`** operates **purposely local-first** to minimize context overhead. It inspects only changed lines in git diffs, executes security & syntax scanners, outputs clean summaries to the terminal, persists reports to `.reviewer/report.md`, and prepares automated Pull Requests via the **GitHub Model Context Protocol (MCP)** server.

---

## 🚀 Quick Start & Installation

### 1. Prerequisites
- **Python 3.9+**
- **Node.js 18+** (for the GitHub MCP server)
- **Git 2.20+**

### 2. Install `reviewer` Locally
From the repository root:

```bash
# Install in editable mode
python -m pip install -e .

# Verify installation
reviewer --help
```

On Windows, you can also directly invoke `.\bin\reviewer.bat`.

---

## ⚙️ Phase 0: GitHub MCP Server Setup & Authentication

The CLI integrates directly with the official GitHub MCP server (`@modelcontextprotocol/server-github`) so AI assistants can programmatically inspect repos, check branches, and create Pull Requests.

### Automated Setup

Run the automated setup script for your operating system:

#### Windows (PowerShell):
```powershell
.\scripts\setup_github_mcp.ps1
```
*(Optionally pass your token directly: `.\scripts\setup_github_mcp.ps1 -Token "ghp_yourTokenHere"`)*

#### macOS / Linux:
```bash
chmod +x ./scripts/setup_github_mcp.sh
./scripts/setup_github_mcp.sh
```

#### Cross-Platform Python:
```bash
python ./scripts/setup_github_mcp.py
```

### Manual Configuration
If you prefer manual configuration, create or edit your global MCP configuration file:

**Location:** `~/.gemini/config/mcp_config.json`

```json
{
  "mcpServers": {
    "github": {
      "command": "node",
      "args": [
        "<PATH_TO_NODE_MODULES>/@modelcontextprotocol/server-github/dist/index.js"
      ],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "<YOUR_GITHUB_PAT_TOKEN>"
      }
    }
  }
}
```

> [!IMPORTANT]
> The GitHub Personal Access Token requires the **`repo`** scope (Full control of private repositories) to create Pull Requests, query branch status, and commit updates.

---

## 🛠️ CLI Usage & Flags

`reviewer` automatically discovers modified files, staged changes, or branch differences:

### 1. Standard Review
Inspects working tree changes or diffs against base branch (`origin/main`, `origin/master`, or `main`):
```bash
reviewer
```

### 2. Strict Mode
Fails with exit code `1` if **any** rule violations or warnings are detected:
```bash
reviewer --strict
```

### 3. Generate Pull Request Description
Analyzes git diff additions and recent commit logs to draft a comprehensive Pull Request description ready for GitHub submission:
```bash
reviewer --pr
```

### 4. Review Staged Changes Only
```bash
reviewer --staged
```

### 5. Compare Against Specific Base Branch
```bash
reviewer --base origin/develop --target HEAD
```

### 6. Output Formats
```bash
# Pretty terminal table with colors (default)
reviewer --format table

# Machine-readable JSON
reviewer --format json

# Markdown representation
reviewer --format markdown
```

---

## 🛡️ Built-in Custom Rules (The "Anti-AI-Mistake" Guardrails)

| Rule ID | Name | Severity | Description |
| :--- | :--- | :---: | :--- |
| `syntax/curly-braces-required` | **Enforce Curly Braces** | `ERROR` | Flags single-line `if`/`else`/`for`/`while` statements missing `{}` in JS, TS, Java, C++, C#, Go, Rust, and PHP. |
| `security/aws-access-key` | **AWS Access Key** | `ERROR` | Scans diff additions for exposed AWS Access Key IDs (`AKIA...`). Automatically redacts in logs. |
| `security/github-token` | **GitHub Token** | `ERROR` | Detects hardcoded GitHub personal access tokens (`ghp_...`, `github_pat_...`). |
| `security/private-key` | **Private Key** | `ERROR` | Flags committed RSA/EC/OPENSSH/PGP private keys. |
| `security/connection-string-credential` | **Connection String Password** | `ERROR` | Flags database connection URLs containing embedded user credentials (`postgres://user:pass@host`). |
| `quality/no-console-log` | **No console.log** | `WARNING` | Detects leftover `console.log` statements in JS/TS diffs (allow with `// reviewer:allow-debug`). |
| `quality/no-debugger` | **No Debugger** | `ERROR` | Flags interactive `debugger;` breakpoints left in the diff. |
| `quality/no-python-print` | **No print() in Python** | `WARNING` | Flags leftover `print()` in core logic (exempts CLI tools and scripts). |
| `quality/no-todo-comments` | **No Unresolved TODOs** | `INFO` | Flags untracked `TODO`/`FIXME` comments (exempts tracked items like `TODO(#123)`). |
| `security/no-eval` | **No eval() Execution** | `ERROR` | Prevents dangerous dynamic evaluation (`eval`, `new Function`). |
| `security/subprocess-shell-true` | **Subprocess shell=True** | `ERROR` | Flags `subprocess.run(..., shell=True)` susceptible to command injection. |
| `style/mixed-indentation` | **Mixed Indentation** | `WARNING` | Detects lines mixing tabs and spaces. |
| `style/line-too-long` | **Line Length Limit** | `INFO` | Flags added lines exceeding 120 characters. |

---

## 🤖 AI Assistant & MCP Integration Layer

### Exposing Tools via MCP Server
`reviewer` includes a native JSON-RPC Model Context Protocol (MCP) server located at `reviewer/mcp_server.py`.

It can be registered with any MCP client (such as Google Antigravity, Claude Desktop, Cursor, or Cline):

```bash
reviewer-mcp
```

### Available MCP Tools:

1. **`review_security_vulnerabilities`**
   - **Parameters:** `repo_path` (string, optional), `base` (string, optional), `staged` (boolean, optional)
   - **Behavior:** Scans git diff additions strictly for hardcoded secrets, API tokens, and private keys.

2. **`check_style_guide`**
   - **Parameters:** `repo_path` (string, optional), `base` (string, optional), `staged` (boolean, optional)
   - **Behavior:** Executes custom syntax guardrails (curly braces enforcement, debug code detection, style compliance).

3. **`generate_pr_template`**
   - **Parameters:** `repo_path` (string, optional), `base_branch` (string, optional)
   - **Behavior:** Analyzes commits and diff hunks, producing a structured title and description payload compatible with the GitHub MCP server's `create_pull_request` tool.

4. **`review_diff`**
   - **Parameters:** `repo_path` (string, optional), `strict` (boolean, optional), `base` (string, optional), `staged` (boolean, optional)
   - **Behavior:** Runs the entire pipeline and persists state to `.reviewer/report.md` and `.reviewer/report.json`.

---

## 💬 Agent Interaction Patterns

When working with an AI assistant in your project, use these explicit prompts:

### 1. Fix Flagged Issues
> `[PROMPT: Read .reviewer/report.md and fix the flagged issues]`
The AI will open `.reviewer/report.md`, review the exact line numbers and suggestions, fix each violation, and re-run `reviewer`.

### 2. Verify Changes Before Commit
> `[PROMPT: Run reviewer --staged and check if there are any remaining security or syntax violations]`

### 3. Open a Pull Request Automatically
> `[PROMPT: Run reviewer --pr, review .reviewer/pr_description.md, and open a pull request against main using the GitHub MCP server]`

---

## 🧪 Testing

Run the comprehensive unit test suite:

```bash
python -m unittest discover tests
```

Tests cover:
- Control statement curly brace detection across multiple languages.
- AWS, GitHub, and database secret pattern recognition with snippet redaction.
- Debug statement and TODO comment flagging.
- Unified diff parsing and file filtering.
- PR metadata and change categorization generation.

---

## 📄 License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
