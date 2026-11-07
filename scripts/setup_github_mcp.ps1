<#
.SYNOPSIS
    Installs, authenticates, and verifies the official GitHub MCP server in Antigravity / Gemini CLI.

.DESCRIPTION
    1. Verifies Node.js & npm runtimes.
    2. Installs @modelcontextprotocol/server-github globally.
    3. Configures GITHUB_PERSONAL_ACCESS_TOKEN in User environment and Antigravity mcp_config.
    4. Verifies connection to the GitHub MCP server.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$false)]
    [string]$Token
)

$ErrorActionPreference = "Stop"

Write-Host "`n=== [1/4] Checking Node.js Runtime ===" -ForegroundColor Cyan
try {
    $nodeVersion = & node --version
    Write-Host "Node.js detected: $nodeVersion" -ForegroundColor Green
} catch {
    Write-Host "Node.js not found in current PATH. Checking default install directory..." -ForegroundColor Yellow
    $defaultNode = "$env:LOCALAPPDATA\Programs\nodejs"
    if (Test-Path "$defaultNode\node.exe") {
        $env:Path = "$defaultNode;$env:Path"
        Write-Host "Found portable Node.js at $defaultNode" -ForegroundColor Green
    } else {
        Write-Error "Please install Node.js 18+ (or run via portable zip) to proceed."
        exit 1
    }
}

Write-Host "`n=== [2/4] Installing Official GitHub MCP Server ===" -ForegroundColor Cyan
& npm install -g @modelcontextprotocol/server-github
Write-Host "GitHub MCP server installed." -ForegroundColor Green

Write-Host "`n=== [3/4] Configuring GitHub Authentication ===" -ForegroundColor Cyan
if (-not $Token) {
    if ($env:GITHUB_PERSONAL_ACCESS_TOKEN) {
        $Token = $env:GITHUB_PERSONAL_ACCESS_TOKEN
        Write-Host "Using existing GITHUB_PERSONAL_ACCESS_TOKEN from environment." -ForegroundColor Green
    } elseif ($env:GITHUB_TOKEN) {
        $Token = $env:GITHUB_TOKEN
        Write-Host "Using existing GITHUB_TOKEN from environment." -ForegroundColor Green
    } else {
        Write-Host "A GitHub Personal Access Token (PAT) with 'repo' scope is required." -ForegroundColor Yellow
        Write-Host "Create one at: https://github.com/settings/tokens/new?scopes=repo" -ForegroundColor Gray
        $Token = Read-Host -Prompt "Enter your GitHub Personal Access Token"
    }
}

if ($Token) {
    # Set in User environment permanently
    [System.Environment]::SetEnvironmentVariable("GITHUB_PERSONAL_ACCESS_TOKEN", $Token, "User")
    $env:GITHUB_PERSONAL_ACCESS_TOKEN = $Token
    Write-Host "GITHUB_PERSONAL_ACCESS_TOKEN set permanently for User." -ForegroundColor Green
} else {
    Write-Host "WARNING: No token provided. GitHub API operations requiring authentication will fail." -ForegroundColor Yellow
}

Write-Host "`n=== [4/4] Registering with Antigravity CLI ===" -ForegroundColor Cyan
$agyCmd = Get-Command agy.exe -ErrorAction SilentlyContinue
if (-not $agyCmd) {
    $localAgy = "$env:LOCALAPPDATA\agy\bin\agy.exe"
    if (Test-Path $localAgy) {
        $agyExe = $localAgy
    }
} else {
    $agyExe = $agyCmd.Source
}

$nodePath = (Get-Command node.exe).Source
$serverScript = (Resolve-Path "$env:LOCALAPPDATA\Programs\nodejs\node_modules\@modelcontextprotocol\server-github\dist\index.js" -ErrorAction SilentlyContinue).Path

if (-not $serverScript) {
    $globalRoot = & npm root -g
    $serverScript = "$globalRoot\@modelcontextprotocol\server-github\dist\index.js"
}

if ($agyExe -and (Test-Path $agyExe)) {
    Write-Host "Configuring Antigravity MCP server via agy CLI..." -ForegroundColor Gray
    try {
        & $agyExe mcp remove github 2>$null
    } catch {}

    if ($Token) {
        & $agyExe mcp add --env "GITHUB_PERSONAL_ACCESS_TOKEN=$Token" github $nodePath $serverScript
    } else {
        & $agyExe mcp add github $nodePath $serverScript
    }
    Write-Host "Registered in Antigravity MCP config." -ForegroundColor Green
    & $agyExe mcp list
} else {
    Write-Host "Antigravity CLI (agy) not found in PATH. You can register manually in ~/.gemini/config/mcp_config.json:" -ForegroundColor Yellow
    Write-Host @"
{
  "mcpServers": {
    "github": {
      "command": "$nodePath",
      "args": ["$serverScript"],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "$Token"
      }
    }
  }
}
"@
}

Write-Host "`n=== Setup Complete! ===" -ForegroundColor Green
Write-Host "You can now ask your AI assistant to open Pull Requests, inspect issues, and interact with GitHub via MCP!" -ForegroundColor Cyan
