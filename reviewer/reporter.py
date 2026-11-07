"""Reporter module for console output and local state storage."""

import json
from pathlib import Path
from typing import Optional, Tuple
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from reviewer.models import ReviewReport, Severity, Violation


class Reporter:
    """Handles Rich terminal formatting and persistence to .reviewer/report.md & .reviewer/report.json."""

    def __init__(self, console: Optional[Console] = None):
        self.console = console or Console()

    def print_terminal_summary(self, report: ReviewReport) -> None:
        """Render beautiful colored terminal output with summary table."""
        self.console.print()

        # Header title
        title = Text("🔍 Reviewer - Local Code Review & Security Scanner", style="bold cyan")
        self.console.print(Panel(title, border_style="cyan"))

        # Context details
        self.console.print(
            f"[dim]Diff Target:[/dim] [bold]{report.target_ref}[/bold] "
            f"[dim]| Base:[/dim] [bold]{report.base_ref}[/bold] "
            f"[dim]| Files:[/dim] [bold]{report.files_analyzed}[/bold] "
            f"[dim]| Lines Added/Modified:[/dim] [bold]{report.lines_analyzed}[/bold]"
        )
        self.console.print()

        if not report.violations:
            self.console.print(
                Panel(
                    "[bold green]✔ All checks passed! No security vulnerabilities or rule violations detected.[/bold green]",
                    border_style="green",
                )
            )
            return

        # Violations Table
        table = Table(title="Detected Violations", show_header=True, header_style="bold magenta")
        table.add_column("Severity", justify="center", width=10)
        table.add_column("File", style="cyan", no_wrap=False)
        table.add_column("Line", justify="right", width=6)
        table.add_column("Rule", style="dim", width=22)
        table.add_column("Details & Snippet", style="white")

        for v in report.violations:
            if v.severity == Severity.ERROR:
                sev_text = Text("ERROR", style="bold white on red")
            elif v.severity == Severity.WARNING:
                sev_text = Text("WARN", style="bold black on yellow")
            else:
                sev_text = Text("INFO", style="bold white on blue")

            details = f"[bold]{v.message}[/bold]"
            if v.snippet:
                details += f"\n[dim]`{v.snippet[:90]}`[/dim]"
            if v.suggestion:
                details += f"\n[italic green]💡 {v.suggestion}[/italic green]"

            table.add_row(
                sev_text,
                v.file_path,
                str(v.line_number),
                v.rule_id,
                details,
            )

        self.console.print(table)
        self.console.print()

        # Summary footer panel
        status_color = "red" if not report.passed else "yellow" if report.warning_count > 0 else "green"
        status_word = "FAILED" if not report.passed else "PASSED WITH WARNINGS" if report.warning_count > 0 else "PASSED"

        summary_text = (
            f"Status: [bold {status_color}]{status_word}[/bold {status_color}]  |  "
            f"Errors: [bold red]{report.error_count}[/bold red]  |  "
            f"Warnings: [bold yellow]{report.warning_count}[/bold yellow]  |  "
            f"Info: [bold blue]{report.info_count}[/bold blue]"
        )
        if report.strict:
            summary_text += "  |  [bold magenta](Strict Mode Active)[/bold magenta]"

        self.console.print(Panel(summary_text, border_style=status_color))

    def save_reports(self, report: ReviewReport, base_dir: Optional[str] = None) -> Tuple[Path, Path]:
        """Save report to .reviewer/report.md and .reviewer/report.json."""
        target_dir = Path(base_dir or ".") / ".reviewer"
        target_dir.mkdir(parents=True, exist_ok=True)

        md_path = target_dir / "report.md"
        json_path = target_dir / "report.json"

        # Generate markdown report
        md_content = self.generate_markdown(report)
        md_path.write_text(md_content, encoding="utf-8")

        # Save JSON
        json_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")

        return md_path, json_path

    def generate_markdown(self, report: ReviewReport) -> str:
        """Construct structured markdown report designed for easy AI consumption."""
        lines = []
        lines.append("# Code Review & Security Analysis Report")
        lines.append("")
        lines.append("> **Note for AI Assistant:** This report was generated locally by the `reviewer` CLI.")
        lines.append("> Use the file paths, line numbers, and actionable suggestions below to resolve each issue.")
        lines.append("")
        lines.append("## Executive Summary")
        lines.append(f"- **Scan Status:** `{'PASSED' if report.passed else 'FAILED'}`")
        lines.append(f"- **Mode:** `{'Strict' if report.strict else 'Standard'}`")
        lines.append(f"- **Diff Target:** `{report.target_ref}` (against base `{report.base_ref}`)")
        lines.append(f"- **Files Changed:** `{report.files_analyzed}`")
        lines.append(f"- **Lines Evaluated:** `{report.lines_analyzed}`")
        lines.append(f"- **Critical Errors:** `{report.error_count}`")
        lines.append(f"- **Warnings:** `{report.warning_count}`")
        lines.append(f"- **Advisory Items:** `{report.info_count}`")
        lines.append(f"- **Timestamp:** `{report.timestamp}`")
        lines.append("")

        if not report.violations:
            lines.append("### Result")
            lines.append("✅ **Clean diff:** No security vulnerabilities, syntax errors, or debug leftovers detected.")
            return "\n".join(lines)

        # Categorize violations
        errors = [v for v in report.violations if v.severity == Severity.ERROR]
        warnings = [v for v in report.violations if v.severity == Severity.WARNING]
        infos = [v for v in report.violations if v.severity == Severity.INFO]

        if errors:
            lines.append("## 🚨 Critical Violations (Errors)")
            lines.append("These issues must be resolved before merging or creating a Pull Request:")
            lines.append("")
            for idx, v in enumerate(errors, 1):
                lines.append(f"### {idx}. [{v.rule_id}] {v.file_path}:{v.line_number}")
                lines.append(f"- **Issue:** {v.message}")
                if v.snippet:
                    lines.append(f"- **Code Snippet:** `{v.snippet}`")
                if v.suggestion:
                    lines.append(f"- **Recommended Fix:** {v.suggestion}")
                lines.append("")

        if warnings:
            lines.append("## ⚠️ Warnings")
            lines.append("Review and fix these potential style or quality concerns:")
            lines.append("")
            for idx, v in enumerate(warnings, 1):
                lines.append(f"### {idx}. [{v.rule_id}] {v.file_path}:{v.line_number}")
                lines.append(f"- **Issue:** {v.message}")
                if v.snippet:
                    lines.append(f"- **Code Snippet:** `{v.snippet}`")
                if v.suggestion:
                    lines.append(f"- **Recommended Fix:** {v.suggestion}")
                lines.append("")

        if infos:
            lines.append("## ℹ️ Advisory & Style Items")
            for idx, v in enumerate(infos, 1):
                lines.append(f"- **{v.file_path}:{v.line_number}** (`{v.rule_id}`): {v.message}")
                if v.suggestion:
                    lines.append(f"  *Tip:* {v.suggestion}")
            lines.append("")

        lines.append("## 🤖 Recommended AI Remediation Plan")
        lines.append("1. **Open and inspect** each referenced file at the exact line number.")
        lines.append("2. **Apply the fixes** indicated in the 'Recommended Fix' bullets.")
        lines.append("3. **Re-run** `reviewer` locally to verify 0 remaining violations.")
        lines.append("")

        return "\n".join(lines)
