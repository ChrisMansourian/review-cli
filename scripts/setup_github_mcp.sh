#!/usr/bin/env bash
set -e

echo "=== [1/4] Checking Node.js Runtime ==="
if ! command -v node &> /dev/null; then
    echo "Error: Node.js is not installed. Please install Node.js 18+ to proceed."
    exit 1
fi
echo "Node.js detected: $(node -v)"

echo ""
echo "=== [2/4] Installing Official GitHub MCP Server ==="
npm install -g @modelcontextprotocol/server-github
echo "GitHub MCP server installed."

echo ""
echo "=== [3/4] Configuring GitHub Authentication ==="
TOKEN="${1:-$GITHUB_PERSONAL_ACCESS_TOKEN}"
if [ -z "$TOKEN" ]; then
    TOKEN="${GITHUB_TOKEN}"
fi

if [ -z "$TOKEN" ]; then
    echo "A GitHub Personal Access Token (PAT) with 'repo' scope is required."
    echo "Create one at: https://github.com/settings/tokens/new?scopes=repo"
    read -sp "Enter your GitHub Personal Access Token: " TOKEN
    echo ""
fi

if [ -n "$TOKEN" ]; then
    export GITHUB_PERSONAL_ACCESS_TOKEN="$TOKEN"
    echo "Exported GITHUB_PERSONAL_ACCESS_TOKEN in current session."
    echo "To make it permanent, add: export GITHUB_PERSONAL_ACCESS_TOKEN=\"$TOKEN\" to your ~/.bashrc or ~/.zshrc."
fi

echo ""
echo "=== [4/4] Registering with Antigravity / Gemini CLI ==="
NODE_PATH=$(which node)
SERVER_PATH=$(npm root -g)/@modelcontextprotocol/server-github/dist/index.js

if command -v agy &> /dev/null; then
    agy mcp remove github 2>/dev/null || true
    if [ -n "$TOKEN" ]; then
        agy mcp add --env "GITHUB_PERSONAL_ACCESS_TOKEN=$TOKEN" github "$NODE_PATH" "$SERVER_PATH"
    else
        agy mcp add github "$NODE_PATH" "$SERVER_PATH"
    fi
    echo "Registered with Antigravity CLI."
    agy mcp list
else
    echo "Configuring ~/.gemini/config/mcp_config.json manually..."
    CONFIG_DIR="$HOME/.gemini/config"
    mkdir -p "$CONFIG_DIR"
    cat > "$CONFIG_DIR/mcp_config.json" <<EOF
{
  "mcpServers": {
    "github": {
      "command": "$NODE_PATH",
      "args": ["$SERVER_PATH"],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "$TOKEN"
      }
    }
  }
}
EOF
    echo "Configuration written to $CONFIG_DIR/mcp_config.json."
fi

echo ""
echo "=== GitHub MCP Server Setup Complete! ==="
