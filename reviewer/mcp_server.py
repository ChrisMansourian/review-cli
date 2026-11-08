"""Model Context Protocol (MCP) server for Reviewer tools.

Exposes:
- review_security_vulnerabilities
- check_style_guide
- generate_pr_template
- review_diff
"""

import sys
import json
import os
from typing import Dict, Any, List, Optional
from reviewer.git_diff import get_git_diff, parse_unified_diff, get_recent_commits
from reviewer.rules.base import RuleRegistry
from reviewer.rules.secrets import SecretDetectionRule
from reviewer.rules.curly_braces import CurlyBracesRule
from reviewer.rules.debug_code import NoDebugCodeRule
from reviewer.rules.style import StyleGuideRule
from reviewer.models import ReviewReport, Severity
from reviewer.reporter import Reporter
from reviewer.pr_generator import generate_pr_payload

TOOLS = [
    {
        "name": "review_security_vulnerabilities",
        "description": (
            "Programmatically scans changed files/diffs for hardcoded secrets, "
            "API tokens, private keys, and security vulnerabilities."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Path to the repository root (defaults to current working directory)",
                },
                "base": {
                    "type": "string",
                    "description": "Base git branch or reference (e.g. origin/main)",
                },
                "staged": {
                    "type": "boolean",
                    "description": "Whether to only scan staged changes",
                },
            },
        },
    },
    {
        "name": "check_style_guide",
        "description": (
            "Executes syntax and style checks, enforcing curly braces on control structures, "
            "line length, indentation, and flagging leftover debug code/TODOs."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Path to the repository root (defaults to current working directory)",
                },
                "base": {
                    "type": "string",
                    "description": "Base git branch or reference",
                },
                "staged": {
                    "type": "boolean",
                    "description": "Whether to only scan staged changes",
                },
            },
        },
    },
    {
        "name": "generate_pr_template",
        "description": (
            "Analyzes git commits and diffs, drafts a formal Pull Request description, "
            "and prepares payload for GitHub create_pull_request tool."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Path to the repository root",
                },
                "base_branch": {
                    "type": "string",
                    "description": "Target base branch for PR (e.g. main)",
                },
            },
        },
    },
    {
        "name": "review_diff",
        "description": (
            "Runs full local code review pipeline (security, style, curly braces) "
            "and updates .reviewer/report.md."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string"},
                "strict": {"type": "boolean", "description": "Fails if any warnings exist"},
                "base": {"type": "string"},
                "staged": {"type": "boolean"},
            },
        },
    },
]


def handle_review_security(args: Dict[str, Any]) -> Dict[str, Any]:
    repo_path = args.get("repo_path") or os.getcwd()
    diff_text, base_ref, target_ref = get_git_diff(
        base=args.get("base"),
        staged=args.get("staged", False),
        repo_dir=repo_path,
    )
    file_diffs = parse_unified_diff(diff_text, repo_dir=repo_path)

    registry = RuleRegistry()
    registry.register(SecretDetectionRule())
    violations = registry.execute_all(file_diffs)

    report = ReviewReport(
        target_ref=target_ref,
        base_ref=base_ref,
        files_analyzed=len(file_diffs),
        lines_analyzed=sum(len(fd.added_lines) for fd in file_diffs),
        violations=violations,
    )

    reporter = Reporter()
    md = reporter.generate_markdown(report)
    return {
        "content": [{"type": "text", "text": md}],
        "isError": not report.passed,
    }


def handle_check_style(args: Dict[str, Any]) -> Dict[str, Any]:
    repo_path = args.get("repo_path") or os.getcwd()
    diff_text, base_ref, target_ref = get_git_diff(
        base=args.get("base"),
        staged=args.get("staged", False),
        repo_dir=repo_path,
    )
    file_diffs = parse_unified_diff(diff_text, repo_dir=repo_path)

    registry = RuleRegistry()
    registry.register(CurlyBracesRule())
    registry.register(NoDebugCodeRule())
    registry.register(StyleGuideRule())
    violations = registry.execute_all(file_diffs)

    report = ReviewReport(
        target_ref=target_ref,
        base_ref=base_ref,
        files_analyzed=len(file_diffs),
        lines_analyzed=sum(len(fd.added_lines) for fd in file_diffs),
        violations=violations,
    )

    reporter = Reporter()
    md = reporter.generate_markdown(report)
    return {
        "content": [{"type": "text", "text": md}],
        "isError": report.error_count > 0,
    }


def handle_generate_pr(args: Dict[str, Any]) -> Dict[str, Any]:
    repo_path = args.get("repo_path") or os.getcwd()
    diff_text, base_ref, target_ref = get_git_diff(repo_dir=repo_path)
    file_diffs = parse_unified_diff(diff_text, repo_dir=repo_path)

    pr_payload = generate_pr_payload(
        file_diffs=file_diffs,
        repo_dir=repo_path,
        base_branch=args.get("base_branch"),
    )

    text_resp = (
        f"### PR Title\n{pr_payload['title']}\n\n"
        f"### Target Base\n`{pr_payload['base']}` (Head: `{pr_payload['head']}`)\n\n"
        f"### Description\n{pr_payload['body']}\n\n"
        f"> Saved locally to `{pr_payload['file_path']}`. Ready for submission via GitHub MCP `create_pull_request`."
    )
    return {
        "content": [{"type": "text", "text": text_resp}],
        "isError": False,
    }


def handle_review_diff(args: Dict[str, Any]) -> Dict[str, Any]:
    repo_path = args.get("repo_path") or os.getcwd()
    strict = args.get("strict", False)
    diff_text, base_ref, target_ref = get_git_diff(
        base=args.get("base"),
        staged=args.get("staged", False),
        repo_dir=repo_path,
    )
    file_diffs = parse_unified_diff(diff_text, repo_dir=repo_path)

    from reviewer.rules import default_registry
    commits = get_recent_commits(count=5, repo_dir=repo_path)
    violations = default_registry.execute_all(file_diffs, commits=commits)

    report = ReviewReport(
        target_ref=target_ref,
        base_ref=base_ref,
        files_analyzed=len(file_diffs),
        lines_analyzed=sum(len(fd.added_lines) for fd in file_diffs),
        violations=violations,
        strict=strict,
    )

    reporter = Reporter()
    md_file, json_file = reporter.save_reports(report, base_dir=repo_path)
    md = reporter.generate_markdown(report)

    return {
        "content": [
            {
                "type": "text",
                "text": f"{md}\n\n*Persisted to `{md_file}` and `{json_file}`.*",
            }
        ],
        "isError": not report.passed,
    }


def _result(req_id: Any, result: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _unknown_tool(name: Any) -> Dict[str, Any]:
    return {
        "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
        "isError": True,
    }


def _handle_initialize(req_id: Any, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return _result(
        req_id,
        {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "reviewer-mcp-server", "version": "1.0.0"},
        },
    )


def _handle_initialized(req_id: Any, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return None


def _handle_tools_list(req_id: Any, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return _result(req_id, {"tools": TOOLS})


def _handle_tools_call(req_id: Any, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    tool_name = params.get("name")
    tool_args = params.get("arguments", {})
    if not isinstance(tool_args, dict):
        tool_args = {}
    handler = _TOOL_HANDLERS.get(tool_name) if isinstance(tool_name, str) else None
    if handler is None:
        return _result(req_id, _unknown_tool(tool_name))
    return _result(req_id, handler(tool_args))


_TOOL_HANDLERS = {
    "review_security_vulnerabilities": handle_review_security,
    "check_style_guide": handle_check_style,
    "generate_pr_template": handle_generate_pr,
    "review_diff": handle_review_diff,
}

_METHOD_HANDLERS = {
    "initialize": _handle_initialize,
    "notifications/initialized": _handle_initialized,
    "tools/list": _handle_tools_list,
    "tools/call": _handle_tools_call,
}


def handle_request(request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Process one JSON-RPC request; return the response, or None for notifications."""
    if not isinstance(request, dict):
        return None
    req_id = request.get("id")
    method = request.get("method")
    params = request.get("params", {})
    if not isinstance(params, dict):
        params = {}

    handler = _METHOD_HANDLERS.get(method) if isinstance(method, str) else None
    if handler is None:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }
    return handler(req_id, params)


def main():
    """Stdio JSON-RPC server loop."""
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue

        resp = handle_request(req)
        if resp is None:
            continue
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()


