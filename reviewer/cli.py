"""CLI entrypoint for reviewer developer tool."""

import json
import sys
import os
from typing import Any, Dict, List
import click
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from reviewer.baseline import apply_baseline, load_baseline, write_baseline
from reviewer.config import apply_config, get_config
from reviewer.git_diff import get_git_diff, parse_unified_diff, get_recent_commits
from reviewer.rules import default_registry
from reviewer.models import ReviewReport
from reviewer.reporter import Reporter
from reviewer.formats import generate_github, generate_sarif_json
from reviewer.pr_generator import generate_pr_payload
from reviewer.rule_docs import RuleRow, build_rows, find_playbook, find_row, suggest_ids

_CONTEXT = dict(help_option_names=["-h", "--help"])
_DEFAULT_COMMAND = "review"


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


class _ReviewDefaultGroup(click.Group):
    """Group that runs the ``review`` command when no subcommand is named.

    ``reviewer --staged`` therefore keeps working exactly as before the CLI
    gained subcommands; only ``-h/--help`` and known subcommand names are
    handled by the group itself.
    """

    def parse_args(self, ctx: click.Context, args: List[str]) -> List[str]:
        first = args[0] if args else None
        if first is None or (first not in self.commands and first not in ctx.help_option_names):
            args = [_DEFAULT_COMMAND] + list(args)
        return super().parse_args(ctx, args)


@click.group(
    cls=_ReviewDefaultGroup,
    context_settings=_CONTEXT,
    help=(
        "Reviewer: Local-first developer tool for git diff inspection, "
        "security scanning, custom syntax enforcement, and PR generation.\n\n"
        "Run with no subcommand (or with review options such as --staged or "
        "--base) to review a diff; see 'reviewer review --help' for those options."
    ),
)
def main() -> None:
    """Dispatch to a subcommand; ``review`` is the default."""


def _review_options(func):
    """Attach the review options (shared by ``review`` and the default route)."""
    options = [
        click.option("--config", "config_path", default=None, type=click.Path(dir_okay=False),
                     help="Explicit config file (pyproject.toml: [tool.reviewer]; else .reviewer.toml style)."),
        click.option("--strict", is_flag=True, default=False,
                     help="Strict mode: Exit with code 1 on ANY rule violation (including warnings)."),
        click.option("--pr", is_flag=True, default=False,
                     help="Generate Pull Request description template based on diff & commits."),
        click.option("--staged", is_flag=True, default=False,
                     help="Inspect staged git changes only (git diff --cached)."),
        click.option("--base", default=None,
                     help="Base git reference/branch to compare against (e.g. origin/main, main)."),
        click.option("--target", default=None,
                     help="Target git reference/branch (defaults to current HEAD or working directory)."),
        click.option("--format", "output_format", default="table",
                     type=click.Choice(["table", "json", "markdown", "sarif", "github"], case_sensitive=False),
                     help="Terminal output format."),
        click.option("--path", "repo_path", default=None,
                     type=click.Path(exists=True, file_okay=False, dir_okay=True),
                     help="Repository directory path (defaults to current working directory)."),
        click.option("--update-baseline", is_flag=True, default=False,
                     help="Write current findings to .reviewer-baseline.json so later runs hide them."),
        click.option("--no-baseline", is_flag=True, default=False,
                     help="Ignore .reviewer-baseline.json and report every finding."),
    ]
    for option in reversed(options):
        func = option(func)
    return func


def _collect_report(opts: Dict[str, Any], work_dir: str):
    """Diff, run every rule, apply the baseline. Returns (report, file_diffs, baselined)."""
    diff_text, base_ref, target_ref = get_git_diff(
        base=opts["base"],
        target=opts["target"],
        staged=opts["staged"],
        repo_dir=work_dir,
    )
    file_diffs = parse_unified_diff(diff_text, repo_dir=work_dir)
    commits = get_recent_commits(count=5, repo_dir=work_dir)
    violations = default_registry.execute_all(file_diffs, commits=commits)

    baselined_count = 0
    if not opts["no_baseline"] and not opts["update_baseline"]:
        violations, baselined_count = apply_baseline(violations, load_baseline(work_dir))

    report = ReviewReport(
        target_ref=target_ref,
        base_ref=base_ref,
        files_analyzed=len(file_diffs),
        lines_analyzed=sum(len(fd.added_lines) for fd in file_diffs),
        violations=violations,
        strict=opts["strict"],
    )
    return report, file_diffs, baselined_count


def _render_report(report: ReviewReport, reporter: Reporter, output_format: str) -> None:
    if output_format == "json":
        click.echo(json.dumps(report.to_dict(), indent=2))
    elif output_format == "markdown":
        click.echo(reporter.generate_markdown(report))
    elif output_format == "sarif":
        click.echo(generate_sarif_json(report))
    elif output_format == "github":
        github_output = generate_github(report)
        if github_output:
            click.echo(github_output)
    else:
        reporter.print_terminal_summary(report)


def _emit_pr(pr_console: Console, file_diffs, report: ReviewReport, *, work_dir: str, base) -> None:
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


@main.command("review", context_settings=_CONTEXT)
@_review_options
def review(**opts):
    """
    Review a git diff: security scanning, custom syntax enforcement, PR generation.

    This is the default command: `reviewer --staged` equals `reviewer review --staged`.
    """
    _make_streams_safe()
    console = Console()
    status_console = Console(stderr=True)
    work_dir = opts["repo_path"] or os.getcwd()

    for warning in apply_config(work_dir, opts["config_path"]):
        status_console.print(f"[yellow]warning:[/yellow] {escape(warning)}", highlight=False)

    report, file_diffs, baselined_count = _collect_report(opts, work_dir)

    reporter = Reporter(console=console)
    md_file, json_file = reporter.save_reports(report, base_dir=work_dir)
    _render_report(report, reporter, opts["output_format"])

    status_console.print(f"[dim]Saved reports to:[/dim] [cyan]{md_file}[/cyan] [dim]and[/dim] [cyan]{json_file}[/cyan]")
    if baselined_count:
        status_console.print(f"[dim]{baselined_count} baselined findings hidden[/dim]")
    if opts["update_baseline"]:
        baseline_file = write_baseline(work_dir, report.violations)
        status_console.print(f"[dim]Wrote baseline to:[/dim] [cyan]{escape(baseline_file)}[/cyan]")

    if opts["pr"]:
        pr_console = console if opts["output_format"] == "table" else status_console
        _emit_pr(pr_console, file_diffs, report, work_dir=work_dir, base=opts["base"])

    sys.exit(0 if report.passed else 1)


# --- reviewer rules / reviewer explain ---------------------------------------

_SEVERITY_STYLE = {"ERROR": "red", "WARNING": "yellow", "INFO": "cyan"}


def _load_rows(repo_path, config_path) -> List[RuleRow]:
    work_dir = repo_path or os.getcwd()
    for warning in apply_config(work_dir, config_path):
        click.echo(f"warning: {warning}", err=True)
    return build_rows(default_registry, get_config())


def _severity_cell(row: RuleRow) -> str:
    if row.disabled:
        return "[dim]disabled[/dim]"
    style = _SEVERITY_STYLE.get(row.effective_severity, "white")
    marker = " *" if row.overridden else ""
    return f"[{style}]{row.effective_severity}{marker}[/{style}]"


def _print_rules_table(rows: List[RuleRow]) -> None:
    table = Table(show_header=True, header_style="bold")
    table.add_column("ID", no_wrap=True)
    table.add_column("Severity", no_wrap=True)
    table.add_column("Name")
    for row in rows:
        table.add_row(escape(row.info.rule_id), _severity_cell(row), escape(row.info.name))
    Console(highlight=False).print(table)
    if any(row.overridden for row in rows):
        click.echo("* severity overridden by config", err=True)


_PATH_OPTION = click.option(
    "--path", "repo_path", default=None,
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    help="Repository directory path (defaults to current working directory).",
)
_CONFIG_OPTION = click.option(
    "--config", "config_path", default=None, type=click.Path(dir_okay=False),
    help="Explicit config file.",
)


@main.command("rules", context_settings=_CONTEXT)
@click.option("--format", "output_format", default="table",
              type=click.Choice(["table", "json"], case_sensitive=False), help="Output format.")
@_PATH_OPTION
@_CONFIG_OPTION
def rules_command(output_format, repo_path, config_path):
    """List every rule ID with its effective severity (config overrides applied)."""
    _make_streams_safe()
    rows = _load_rows(repo_path, config_path)
    if output_format.lower() == "json":
        click.echo(json.dumps([row.to_dict() for row in rows], indent=2))
    else:
        _print_rules_table(rows)


def _explain_lines(row: RuleRow, playbook) -> List[str]:
    severity = row.effective_severity
    if row.overridden:
        severity += f" (config override; default {row.info.severity.value})"
    lines = [
        f"{row.info.rule_id}",
        f"Name:        {row.info.name}",
        f"Severity:    {severity}",
    ]
    if row.disabled:
        lines.append("Status:      disabled by config")
    lines.append(f"Description: {row.info.description}")
    if row.info.suggestion:
        lines.append(f"Suggestion:  {row.info.suggestion}")
    if playbook is not None:
        lines.append(f"Playbook:    {playbook[0]}:{playbook[1]}")
    return lines


@main.command("explain", context_settings=_CONTEXT)
@click.argument("rule_id")
@_PATH_OPTION
@_CONFIG_OPTION
def explain_command(rule_id, repo_path, config_path):
    """Explain one rule: severity, description, suggestion and refactor playbook."""
    _make_streams_safe()
    rows = _load_rows(repo_path, config_path)
    row = find_row(rows, rule_id)
    if row is None:
        message = f"unknown rule ID '{rule_id}'."
        close = suggest_ids(rows, rule_id)
        if close:
            message += " Did you mean: " + ", ".join(close) + "?"
        raise click.ClickException(message + " Run 'reviewer rules' to list all rules.")
    playbook = find_playbook(repo_path or os.getcwd(), rule_id)
    click.echo("\n".join(_explain_lines(row, playbook)))


if __name__ == "__main__":
    main()
