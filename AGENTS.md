# Repository Agent Rules & Guidelines

## Code Quality & Guardrails
- **Enforce Curly Braces:** Always use curly braces `{ ... }` on all `if`, `else`, `for`, and `while` control structures in languages that support them.
- **No Hardcoded Credentials:** Never hardcode secrets, tokens, or private keys.
- **Clean Production Code:** Do not commit temporary debug code (`console.log`, `debugger`, `print()`, untracked `TODO`). If strictly necessary (e.g., CLI utilities, intentional diagnostics, or tracked engineering backlog items), annotate with `// reviewer:allow-debug` (or `# noqa`) or use a tracked reference like `TODO(#123)`.
- **Short, Clean & Clear Commit Messages:** Write commit messages that are concise (<= 72 characters), structured, and explicitly state what was changed. Use the conventional commit standard: `<type>: <imperative description>` (e.g., `feat: add commit message linter rule` or `fix: resolve token parsing in git diff`). Never use vague messages like `update`, `fixed`, `wip`, or `changes`.
- **Local Reviewer CLI:** The local tool `reviewer` is configured to audit changes. When prompted to fix issues, consult `.reviewer/report.md`.
