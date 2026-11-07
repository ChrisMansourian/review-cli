# Repository Agent Rules & Guidelines

## Code Quality & Guardrails
- **Enforce Curly Braces:** Always use curly braces `{ ... }` on all `if`, `else`, `for`, and `while` control structures in languages that support them.
- **No Hardcoded Credentials:** Never hardcode secrets, tokens, or private keys.
- **Clean Production Code:** Do not commit temporary debug code (`console.log`, `debugger`, `print()`, untracked `TODO`). If strictly necessary (e.g., CLI utilities, intentional diagnostics, or tracked engineering backlog items), annotate with `// reviewer:allow-debug` (or `# noqa`) or use a tracked reference like `TODO(#123)`.
- **Local Reviewer CLI:** The local tool `reviewer` is configured to audit changes. When prompted to fix issues, consult `.reviewer/report.md`.
