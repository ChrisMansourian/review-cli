"""Git context analysis and diff parser."""

import os
import re
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple, Dict
from reviewer.config import get_config
from reviewer.models import FileDiff

# Files and extensions to ignore by default to preserve tokens and focus on reviewable code
IGNORED_PATTERNS = [
    r"\.reviewer(/|\\).*",
    r".*\.lock$",
    r"package-lock\.json$",
    r"yarn\.lock$",
    r"pnpm-lock\.yaml$",
    r"poetry\.lock$",
    r"Pipfile\.lock$",
    r"Cargo\.lock$",
    r"go\.sum$",
    r".*\.min\.(js|css)$",
    r".*\.svg$",
    r".*\.png$",
    r".*\.jpg$",
    r".*\.ico$",
    r".*\.map$",
]


def run_git_cmd(args: List[str], cwd: Optional[str] = None) -> Tuple[int, str, str]:
    """Execute a git command and return (exit_code, stdout, stderr)."""
    try:
        proc = subprocess.run(
            ["git"] + args,
            cwd=cwd or os.getcwd(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError:
        return 127, "", "git executable not found in PATH"
    except Exception as e:
        return 1, "", str(e)


def detect_base_branch(repo_dir: Optional[str] = None) -> str:
    """Detect appropriate base branch (origin/main, origin/master, main, master)."""
    code, stdout, _ = run_git_cmd(["rev-parse", "--abbrev-ref", "origin/HEAD"], cwd=repo_dir)
    if code == 0 and stdout.strip():
        return stdout.strip()

    # Try common branch names in order
    candidates = ["origin/main", "origin/master", "main", "master"]
    for candidate in candidates:
        code, _, _ = run_git_cmd(["rev-parse", "--verify", candidate], cwd=repo_dir)
        if code == 0:
            return candidate

    return "HEAD"


def is_ignored_file(file_path: str) -> bool:
    """Check if file should be excluded from review analysis."""
    norm_path = file_path.replace("\\", "/")
    for pattern in IGNORED_PATTERNS:
        if re.search(pattern, norm_path, re.IGNORECASE):
            return True
    return False


def get_git_diff(
    base: Optional[str] = None,
    target: Optional[str] = None,
    staged: bool = False,
    repo_dir: Optional[str] = None,
) -> Tuple[str, str, str]:
    """
    Generate git diff string based on targets or working directory.
    Returns (diff_output, base_ref, target_ref).
    """
    # 1. Staged diff requested
    if staged:
        code, out, err = run_git_cmd(["diff", "--cached"], cwd=repo_dir)
        return out, "HEAD", "STAGED"

    # 2. Explicit base and target provided
    if base and target:
        code, out, err = run_git_cmd(["diff", f"{base}...{target}"], cwd=repo_dir)
        return out, base, target

    # 3. Explicit base provided, target is HEAD / working tree
    if base:
        code, out, err = run_git_cmd(["diff", base], cwd=repo_dir)
        return out, base, "WORKING_TREE"

    # 4. Check for uncommitted working tree changes first (staged + unstaged)
    code, status_out, _ = run_git_cmd(["status", "--porcelain"], cwd=repo_dir)
    if status_out.strip():
        # Working tree has changes: review diff against HEAD (both staged and unstaged)
        code, out, _ = run_git_cmd(["diff", "HEAD"], cwd=repo_dir)
        if not out.strip():
            # If no commit exists yet (initial repo), fallback to staged diff
            code, out, _ = run_git_cmd(["diff", "--cached"], cwd=repo_dir)
        return out, "HEAD", "WORKING_TREE"

    # 5. No dirty working tree: diff current branch against detected base branch
    detected_base = detect_base_branch(repo_dir)
    code, current_branch, _ = run_git_cmd(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_dir)
    current_ref = current_branch.strip() or "HEAD"

    if detected_base != current_ref and detected_base != "HEAD":
        code, out, _ = run_git_cmd(["diff", f"{detected_base}...{current_ref}"], cwd=repo_dir)
        return out, detected_base, current_ref

    # 6. Fallback: diff against parent commit HEAD~1
    code, out, _ = run_git_cmd(["diff", "HEAD~1...HEAD"], cwd=repo_dir)
    if code == 0 and out.strip():
        return out, "HEAD~1", "HEAD"

    # 7. Last fallback: empty diff
    return "", detected_base, current_ref


def parse_unified_diff(diff_text: str, repo_dir: Optional[str] = None) -> List[FileDiff]:
    """
    Parse a unified diff output into structured FileDiff objects containing
    added/modified lines with accurate file line numbers.
    """
    if not diff_text or not diff_text.strip():
        return []

    file_diffs: List[FileDiff] = []
    current_file: Optional[FileDiff] = None
    current_new_line = 0

    # Match diff headers: diff --git a/path b/path
    diff_header_re = re.compile(r"^diff --git a/(.*?) b/(.*?)$")
    hunk_header_re = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

    for line in diff_text.splitlines():
        # New file diff start
        header_match = diff_header_re.match(line)
        if header_match:
            if current_file:
                file_diffs.append(current_file)

            old_file_path = header_match.group(1)
            new_file_path = header_match.group(2)

            current_file = FileDiff(
                file_path=new_file_path,
                old_path=old_file_path,
                status="modified",
                added_lines=[],
            )
            continue

        if not current_file:
            continue

        # Detect new file / deleted file modes
        if line.startswith("new file mode"):
            current_file.status = "added"
            continue
        elif line.startswith("deleted file mode"):
            current_file.status = "deleted"
            continue

        # Hunk header: @@ -old_start,old_count +new_start,new_count @@
        hunk_match = hunk_header_re.match(line)
        if hunk_match:
            current_new_line = int(hunk_match.group(1))
            continue

        # Added line
        if line.startswith("+") and not line.startswith("+++"):
            added_content = line[1:]
            current_file.added_lines.append((current_new_line, added_content))
            current_new_line += 1
        # Context line (unchanged)
        elif line.startswith(" "):
            current_new_line += 1
        # Removed lines do not advance the new file line counter
        elif line.startswith("-") and not line.startswith("---"):
            pass

    if current_file:
        file_diffs.append(current_file)

    # Filter out ignored files and deleted files
    valid_diffs = []
    base_path = Path(repo_dir or os.getcwd())

    for fd in file_diffs:
        if fd.status == "deleted":
            continue
        if is_ignored_file(fd.file_path) or get_config().is_path_ignored(fd.file_path):
            continue

        # Attempt to read full file content for context when needed by multi-line checks
        full_path = base_path / fd.file_path
        if full_path.is_file():
            try:
                fd.full_content = full_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                fd.full_content = None

        valid_diffs.append(fd)

    return valid_diffs


def get_recent_commits(count: int = 5, repo_dir: Optional[str] = None) -> List[Dict[str, str]]:
    """Get recent commit hashes, subjects, and authors for PR generation."""
    code, out, _ = run_git_cmd(
        ["log", f"-n{count}", "--pretty=format:%h%x09%an%x09%s%x09%b%x1e"],
        cwd=repo_dir,
    )
    if code != 0 or not out.strip():
        return []

    commits = []
    records = out.strip().split("\x1e")
    for rec in records:
        parts = rec.strip().split("\t")
        if len(parts) >= 3:
            commits.append({
                "hash": parts[0].strip(),
                "author": parts[1].strip(),
                "subject": parts[2].strip(),
                "body": parts[3].strip() if len(parts) > 3 else "",
            })
    return commits
