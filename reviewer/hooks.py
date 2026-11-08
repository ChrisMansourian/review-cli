"""Git pre-commit hook installation for ``reviewer install-hook``."""

import os
import subprocess
from typing import List

import click

HOOK_MARKER = "# reviewer-managed-hook"
HOOK_NAME = "pre-commit"
BACKUP_NAME = "pre-commit.bak"

HOOK_SCRIPT = f"""#!/bin/sh
{HOOK_MARKER}: installed by `reviewer install-hook`; remove with `reviewer install-hook --uninstall`.
if command -v reviewer >/dev/null 2>&1; then
    exec reviewer --staged
fi
if command -v python3 >/dev/null 2>&1; then
    exec python3 -m reviewer.cli --staged
fi
exec python -m reviewer.cli --staged
"""


def resolve_hooks_dir(start_dir: str) -> str:
    """Hooks directory for the repo containing ``start_dir`` (honours worktrees and core.hooksPath)."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--git-path", "hooks"],
            cwd=start_dir, capture_output=True, text=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise click.ClickException(f"not inside a git repository: {start_dir}") from exc
    return os.path.normpath(os.path.join(start_dir, proc.stdout.strip()))


def _is_reviewer_hook(path: str) -> bool:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return HOOK_MARKER in fh.read()
    except OSError:
        return False


def _write_hook(path: str) -> None:
    # Binary write keeps LF endings so `sh` parses the script on Windows too.
    with open(path, "wb") as fh:
        fh.write(HOOK_SCRIPT.encode("utf-8"))
    os.chmod(path, 0o755)


def install_hook(start_dir: str, force: bool = False) -> List[str]:
    """Write the pre-commit hook; returns status messages."""
    hooks_dir = resolve_hooks_dir(start_dir)
    hook_path = os.path.join(hooks_dir, HOOK_NAME)
    messages: List[str] = []
    if os.path.exists(hook_path):
        if not force:
            raise click.ClickException(
                f"{hook_path} already exists; use --force to replace it (a backup is kept)."
            )
        backup = os.path.join(hooks_dir, BACKUP_NAME)
        os.replace(hook_path, backup)
        messages.append(f"Backed up existing hook to {backup}")
    os.makedirs(hooks_dir, exist_ok=True)
    _write_hook(hook_path)
    messages.append(f"Installed pre-commit hook at {hook_path}")
    return messages


def uninstall_hook(start_dir: str) -> List[str]:
    """Remove the hook if reviewer wrote it; returns status messages."""
    hook_path = os.path.join(resolve_hooks_dir(start_dir), HOOK_NAME)
    if not os.path.exists(hook_path):
        return [f"No pre-commit hook at {hook_path}; nothing to remove"]
    if not _is_reviewer_hook(hook_path):
        raise click.ClickException(f"{hook_path} was not installed by reviewer; leaving it untouched.")
    os.remove(hook_path)
    return [f"Removed pre-commit hook {hook_path}"]
