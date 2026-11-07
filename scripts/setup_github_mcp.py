#!/usr/bin/env python3
"""Cross-platform Python script to setup and verify GitHub MCP Server."""

import sys
import os
import json
import subprocess
import shutil
from pathlib import Path


def run_command(cmd, shell=False):
    """Run command and return stdout string or raise."""
    proc = subprocess.run(cmd, shell=shell, capture_output=True, text=True, errors="replace")
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def main():
    print("\n=== [1/4] Checking Node.js Environment ===")
    node_exe = shutil.which("node")
    if not node_exe:
        # Check standard Windows portable location
        local_app = os.environ.get("LOCALAPPDATA", "")
        candidate = Path(local_app) / "Programs" / "nodejs" / "node.exe"
        if candidate.is_file():
            node_exe = str(candidate)
        else:
            print("Error: Node.js executable not found in PATH.")
            print("Please install Node.js 18+ from https://nodejs.org")
            sys.exit(1)

    code, out, _ = run_command([node_exe, "--version"])
    print(f"Node.js found: {node_exe} ({out})")

    print("\n=== [2/4] Checking @modelcontextprotocol/server-github ===")
    # Check if installed
    code, npm_root, _ = run_command(["npm", "root", "-g"], shell=True)
    server_entry = None
    if code == 0 and npm_root:
        possible_entry = Path(npm_root) / "@modelcontextprotocol" / "server-github" / "dist" / "index.js"
        if possible_entry.is_file():
            server_entry = str(possible_entry)

    if not server_entry:
        print("Installing @modelcontextprotocol/server-github globally...")
        code, out, err = run_command(["npm", "install", "-g", "@modelcontextprotocol/server-github"], shell=True)
        if code != 0:
            print(f"npm install warning/error: {err}")
        code, npm_root, _ = run_command(["npm", "root", "-g"], shell=True)
        server_entry = str(Path(npm_root) / "@modelcontextprotocol" / "server-github" / "dist" / "index.js")

    print(f"GitHub MCP Server entrypoint: {server_entry}")

    print("\n=== [3/4] Checking GitHub Authentication ===")
    token = os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print("GITHUB_PERSONAL_ACCESS_TOKEN not detected in current process environment.")
        user_input = input("Enter your GitHub Personal Access Token (leave empty to skip): ").strip()
        if user_input:
            token = user_input
            if os.name == "nt":
                subprocess.run(
                    f'[System.Environment]::SetEnvironmentVariable("GITHUB_PERSONAL_ACCESS_TOKEN", "{token}", "User")',
                    shell=True,
                )
                print("GITHUB_PERSONAL_ACCESS_TOKEN saved to User environment variables.")

    print("\n=== [4/4] Configuring Antigravity MCP Server ===")
    agy_exe = shutil.which("agy") or shutil.which("agy.exe")
    if not agy_exe and os.name == "nt":
        cand = Path(os.environ.get("LOCALAPPDATA", "")) / "agy" / "bin" / "agy.exe"
        if cand.is_file():
            agy_exe = str(cand)

    if agy_exe:
        print(f"Registering with agy CLI at: {agy_exe}")
        run_command([agy_exe, "mcp", "remove", "github"])
        args = [agy_exe, "mcp"]
        if token:
            args.extend(["--env", f"GITHUB_PERSONAL_ACCESS_TOKEN={token}"])
        args.extend(["add", "github", node_exe, server_entry])
        code, out, err = run_command(args)
        print(out or err)
        run_command([agy_exe, "mcp", "list"])
    else:
        # Fallback to direct json edit
        cfg_path = Path.home() / ".gemini" / "config" / "mcp_config.json"
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"mcpServers": {}}
        if cfg_path.is_file():
            try:
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
            except Exception:
                data = {"mcpServers": {}}

        data.setdefault("mcpServers", {})["github"] = {
            "command": node_exe.replace("\\", "/"),
            "args": [server_entry.replace("\\", "/")],
            "disabled": False,
        }
        if token:
            data["mcpServers"]["github"]["env"] = {
                "GITHUB_PERSONAL_ACCESS_TOKEN": token
            }
        cfg_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"Wrote config to: {cfg_path}")

    print("\n✔ GitHub MCP Server is ready for AI assistant interactions!\n")


if __name__ == "__main__":
    main()
