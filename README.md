# `reviewer` (CLI) & GitHub MCP Server Integration

[![CI](https://github.com/ChrisMansourian/review-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/ChrisMansourian/review-cli/actions/workflows/ci.yml)

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

# SARIF 2.1.0 (GitHub code scanning); stdout is only the document
reviewer --format sarif > reviewer.sarif

# GitHub Actions workflow commands (::error/::warning/::notice) for PR annotations
reviewer --format github
```

SARIF notes: paths are repo-relative with forward slashes; each result carries a
`primaryLocationLineHash` fingerprint so GitHub dedupes across runs. Commit-message
violations have no file, so they are emitted without `locations` (the sha is in
`properties.commit`); in `github` output they omit `file`/`line`.

---

## Configuration

`reviewer` reads settings from the `[tool.reviewer]` table of `pyproject.toml` in the repository root (`--path`, default: the working directory). If that table is absent it falls back to a `.reviewer.toml` file in the same directory, which uses the same keys at the top level. Use `--config PATH` to load an explicit file (a file named `pyproject.toml` uses its `[tool.reviewer]` table; any other file is read as `.reviewer.toml`). With no config file, behaviour is unchanged.

```toml
[tool.reviewer]
disable = ["quality/narrating-comment", "style/*"]      # fnmatch globs on rule_id
ignore_paths = ["tests/fixtures/**", "migrations/**"]   # globs on repo-relative paths; ** spans directories

[tool.reviewer.severity]
"quality/god-function" = "INFO"                          # ERROR | WARNING | INFO

[tool.reviewer.thresholds]                               # values shown are the defaults
max_params = 4
max_nesting = 4
max_function_lines = 50
max_line_length = 120
elif_chain = 3
literal_repeat = 3
duplicate_lines = 3
```

`disable` and `severity` match the violation's rule ID (for example `quality/deep-nesting` or `commit/...`). Unknown keys and invalid values print a warning on stderr and are ignored. On Python 3.9/3.10 the `tomli` package is required to parse config; if it is missing, a warning is printed and defaults are used. The MCP server loads the same config from its `repo_path`.

## Suppressing findings

Inline directives (in any comment style):

| Directive | Effect |
| --- | --- |
| `reviewer:ignore` | Suppress every rule on that line. |
| `reviewer:ignore[quality/deep-nesting, security/*]` | Suppress only the listed rule IDs on that line (fnmatch globs allowed). |
| `reviewer:ignore-file` | Within the first 5 lines of a file: suppress every rule for the whole file. |
| `reviewer:ignore-file[style/*]` | Same, restricted to the listed rule IDs. |

Baseline: `reviewer --update-baseline` writes `.reviewer-baseline.json` at the repository root (commit it). It stores line-independent fingerprints (`sha1(rule_id, file path, whitespace-normalised snippet)`), so findings survive line shifts but reappear when the offending code changes. Later runs hide baselined findings, print `N baselined findings hidden` on stderr, and hidden findings do not affect the exit code. Use `--no-baseline` to see everything. Commit-message findings are never baselined.

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
| `quality/unnecessary-else-after-return` | **Unnecessary Else** | `WARNING` | Flags `else` blocks directly after `return`/`raise`/`throw`. |
| `quality/complex-if-else-chain` | **Complex If/Elif Chain** | `WARNING` | Flags 3+ `elif`/`else if` branches that should be a dispatch dict or `match`. |
| `quality/duplicated-code-pattern` | **Duplicated Code** | `WARNING` | Flags 3+ near-identical adjacent lines. |
| `quality/magic-literal-repetition` | **Magic Literal Repetition** | `INFO` | Flags the same literal repeated 3+ times. |
| `quality/redundant-boolean-return` | **Redundant Boolean Return** | `WARNING` | `if c: return True else: return False`, `True if c else False`, `c ? true : false`. |
| `quality/nested-ternary` | **Nested Ternary** | `WARNING` | Conditional expressions nested inside each other (Python, JS/TS, Java, C#, C/C++, PHP). |
| `quality/deep-nesting` | **Deep Nesting** | `WARNING` | Control flow nested 4+ levels; use guard clauses. |
| `quality/long-parameter-list` | **Long Parameter List** | `WARNING` | Functions with 5+ positional params (keyword-only and `self` excluded). |
| `quality/mutable-default-argument` | **Mutable Default Argument** | `ERROR` | Python `def f(x=[])` / `{}` / `set()` defaults. |
| `quality/bare-except` | **Bare Except** | `WARNING` | Python `except:` with no exception type. |
| `quality/swallowed-exception` | **Swallowed Exception** | `WARNING` | `except: pass`, empty `catch {}`, `.catch(() => {})`. |
| `quality/unreachable-code` | **Unreachable Code** | `WARNING` | Statements after an unconditional `return`/`raise`/`throw`/`break`/`continue`. |
| `quality/god-function` | **Oversized Function** | `WARNING` | Function bodies over 50 non-blank lines. |
| `quality/loose-equality` | **Loose Equality** | `WARNING` | JS/TS `==`/`!=` (except `== null`). |
| `quality/non-idiomatic-comparison` | **Non-Idiomatic Comparison** | `INFO` | Python `== None`, `== True`, `len(x) == 0`. |
| `quality/range-len-loop` | **range(len()) Loop** | `INFO` | Use `enumerate()` / `zip()`. |
| `quality/manual-accumulation-loop` | **Manual Accumulation Loop** | `INFO` | Loops that only `append`/`push`; use a comprehension or `.filter().map()`. |
| `quality/string-concatenation` | **String Concatenation** | `INFO` | `"a" + x + "b"`; use f-strings / template literals. |
| `quality/await-in-loop` | **Await in Loop** | `INFO` | Sequential `await` in a loop; consider `Promise.all` / `asyncio.gather`. |
| `quality/collapsible-if` | **Collapsible If** | `INFO` | Nested `if` that is the sole statement of its parent. |
| `quality/commented-out-code` | **Commented-Out Code** | `INFO` | Comment blocks that are code. |
| `quality/narrating-comment` | **Narrating Comment** | `INFO` | Comments that restate the next line (`# increment counter`). |
| `security/no-eval` | **No eval() Execution** | `ERROR` | Prevents dangerous dynamic evaluation (`eval`, `new Function`). |
| `security/subprocess-shell-true` | **Subprocess shell=True** | `ERROR` | Flags `subprocess.run(..., shell=True)` susceptible to command injection. |
| `security/sql-string-format` | **SQL String Formatting** | `ERROR` | `execute`/`query`/`raw` fed an f-string, `%`, `.format()` or `+` built SQL statement. |
| `security/unsafe-deserialization` | **Unsafe Deserialization** | `ERROR` | `pickle.load(s)`, `marshal.load(s)`, `yaml.load` without a `SafeLoader`. |
| `security/tls-verify-disabled` | **TLS Verify Disabled** | `ERROR` | `verify=False`, `rejectUnauthorized: false`, `InsecureSkipVerify: true`, `NODE_TLS_REJECT_UNAUTHORIZED=0`. |
| `security/inner-html` | **Raw HTML Injection** | `WARNING` | JS/TS `.innerHTML =`, `dangerouslySetInnerHTML`, `document.write(`. |
| `security/weak-hash` | **Weak Hash** | `WARNING` | `hashlib.md5/sha1` and `createHash('md5'/'sha1')` (skipped with `usedforsecurity=False`). |
| `quality/unexplained-suppression` | **Unexplained Suppression** | `WARNING` | `# type: ignore`, `# noqa`, `// @ts-ignore`, `// eslint-disable` with neither a rule code nor a reason. |
| `quality/ts-any` | **TypeScript any** | `INFO` | `: any`, `as any`, `<any>` in `.ts`/`.tsx`. |
| `style/mixed-indentation` | **Mixed Indentation** | `WARNING` | Detects lines mixing tabs and spaces. |
| `style/line-too-long` | **Line Length Limit** | `INFO` | Flags added lines exceeding 120 characters. |
| `git/commit-message-format` | **Clean & Clear Commits** | `WARNING` | Enforces short (<=72 chars), structured conventional commits telling what changed. Blocks vague commit messages. |

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
