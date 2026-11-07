# Reviewer Quality & Guardrail Rules

When working in this codebase:

1. **Local-First Code Review Protocol:**
   - Always adhere to findings generated in `.reviewer/report.md`.
   - When asked to fix flagged issues, parse `.reviewer/report.md` for exact file lines and recommended fixes.

2. **Syntax Guardrails (Anti-AI-Mistakes):**
   - **Enforce Curly Braces:** Never write single-line `if`, `else`, `for`, or `while` statements without explicit curly braces `{ ... }` in languages that support them (JavaScript, TypeScript, C/C++, Java, Go, C#, Rust, PHP).
   - **No Hardcoded Secrets:** Never hardcode credentials, tokens, AWS keys, GitHub tokens, or connection strings with passwords in code files. Always read from environment variables.
   - **No Leftover Debug Code:** Do not commit temporary debug statements (`console.log`, `debugger;`, `print()`, `breakpoint()`, or untracked `TODO` comments). When strictly necessary (e.g. intentional CLI console outputs, scripts, or tracked engineering backlog items), annotate with `// reviewer:allow-debug` / `# noqa` or link to a tracked ticket (e.g., `TODO(#123)`).
   - **Short, Clean & Clear Commit Messages:** Every commit message must be short, clean, and specifically tell what was changed. Use conventional format: `<type>: <clear imperative description>` (subject line <= 72 chars). Banned vague messages: `update`, `fixed`, `wip`, `temp`, `changes`.

3. **Pull Request Preparation:**
   - Before requesting a PR, verify clean status with `reviewer --strict`.
   - Draft descriptions using `reviewer --pr` and publish via the GitHub MCP server.
