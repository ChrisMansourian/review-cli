"""CLI entrypoint for reviewer developer tool."""

import json
import sys
import os
from pathlib import Path
import click
from rich.console import Console

from reviewer.git_diff import get_git_diff, parse_unified_diff, get_recent_commits
from reviewer.rules import default_registry
from reviewer.models import ReviewReport
from reviewer.reporter import Reporter
from reviewer.pr_generator import generate_pr_payload



def _make_streams_safe() -> None:
    """Prevent UnicodeEncodeError on consoles that cannot encode emoji (e.g. cp1252)."""
    for stream in (sys.stdout, sys.stderr):
        encoding = getattr(stream, "encoding", None) or "ascii"
        try:
            "🔍✔".encode(encoding)
        except (UnicodeEncodeError, LookupError):
            reconfigure = getattr(stream, "reconfigure", None)
            if reconfigure is not None:
                reconfigure(errors="replace")


@click.command(context_settings=dict(help_option_names=["-h", "--help"]))
@click.option(
    "--strict",
    is_flag=True,
    default=False,
    help="Strict mode: Exit with code 1 on ANY rule violation (including warnings).",
)
@click.option(
    "--pr",
    is_flag=True,
    default=False,
    help="Generate Pull Request description template based on diff & commits.",
)
@click.option(
    "--staged",
    is_flag=True,
    default=False,
    help="Inspect staged git changes only (git diff --cached).",
)
@click.option(
    "--base",
    default=None,
    help="Base git reference/branch to compare against (e.g. origin/main, main).",
)
@click.option(
    "--target",
    default=None,
    help="Target git reference/branch (defaults to current HEAD or working directory).",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json", "markdown"], case_sensitive=False),
    default="table",
    help="Terminal output format.",
)
@click.option(
    "--path",
    "repo_path",
    default=None,
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    help="Repository directory path (defaults to current working directory).",
)
def main(
    strict: bool,
    pr: bool,
    staged: bool,
    base: str,
    target: str,
    output_format: str,
    repo_path: str,
):
    """
    Reviewer: Local-first developer tool for git diff inspection,
    security scanning, custom syntax enforcement, and PR generation.
    """
    _make_streams_safe()
    console = Console()
    status_console = Console(stderr=True)
    work_dir = repo_path or os.getcwd()

    # Task 1: Git Context Analysis
    diff_text, base_ref, target_ref = get_git_diff(
        base=base,
        target=target,
        staged=staged,
        repo_dir=work_dir,
    )

    file_diffs = parse_unified_diff(diff_text, repo_dir=work_dir)
    total_added_lines = sum(len(fd.added_lines) for fd in file_diffs)
    commits = get_recent_commits(count=5, repo_dir=work_dir)

    # Task 2: Local Security & Rule Enforcement Engine
    violations = default_registry.execute_all(file_diffs, commits=commits)

    # Compile report
    report = ReviewReport(
        target_ref=target_ref,
        base_ref=base_ref,
        files_analyzed=len(file_diffs),
        lines_analyzed=total_added_lines,
        violations=violations,
        strict=strict,
    )

    # Task 3: Feedback Output & State Storage
    reporter = Reporter(console=console)
    md_file, json_file = reporter.save_reports(report, base_dir=work_dir)

    # Terminal rendering
    if output_format == "json":
        click.echo(json.dumps(report.to_dict(), indent=2))
    elif output_format == "markdown":
        click.echo(reporter.generate_markdown(report))
    else:
        reporter.print_terminal_summary(report)

    status_console.print(f"[dim]Saved reports to:[/dim] [cyan]{md_file}[/cyan] [dim]and[/dim] [cyan]{json_file}[/cyan]")

    # PR Description generation if requested
    if pr:
        pr_console = console if output_format == "table" else status_console
        pr_console.print()
        pr_console.print("[bold magenta]📝 Generating Pull Request Description...[/bold magenta]")
        pr_payload = generate_pr_payload(
            file_diffs=file_diffs,
            report=report,
            repo_dir=work_dir,
            base_branch=base,
        )
        pr_console.print(f"[green]✔ PR template generated at:[/green] [bold cyan]{pr_payload['file_path']}[/bold cyan]")
        pr_console.print(f"[dim]PR Title:[/dim] [bold]{pr_payload['title']}[/bold]")
        pr_console.print(
            f"[dim]Ready for GitHub MCP server `create_pull_request` "
            f"(head: {pr_payload['head']} -> base: {pr_payload['base']})[/dim]"
        )

    # Exit code determination
    if not report.passed:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
