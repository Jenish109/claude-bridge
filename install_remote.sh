#!/bin/bash
# Run on the Mac you want to control. Installs bridge_daemon.py as a launchd
# agent bound to this Mac's Tailscale IP, then prints the URL + token to use
# on the controlling Mac.
#
#   ./install_remote.sh [--root ~/Projects ...] [--permission-mode acceptEdits] [--allow-bypass]
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.claude-bridge.daemon"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PORT="${BRIDGE_PORT:-8765}"

TS=$(command -v tailscale || echo /Applications/Tailscale.app/Contents/MacOS/Tailscale)
[ -x "$TS" ] || { echo "Tailscale not found. Install it from https://tailscale.com/download and sign in." >&2; exit 1; }
TS_IP=$("$TS" ip -4 | head -1)
[ -n "$TS_IP" ] || { echo "Tailscale has no IPv4 address; is it connected?" >&2; exit 1; }

CLAUDE=$(command -v claude || true)
[ -n "$CLAUDE" ] || { echo "claude not on PATH; install Claude Code and log in first." >&2; exit 1; }
PY=$(command -v python3)

args=("$PY" "$DIR/bridge_daemon.py" --host "$TS_IP" --port "$PORT" --claude-bin "$CLAUDE" "$@")

{
  echo '<?xml version="1.0" encoding="UTF-8"?>'
  echo '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">'
  echo '<plist version="1.0"><dict>'
  echo "  <key>Label</key><string>$LABEL</string>"
  echo '  <key>ProgramArguments</key><array>'
  for a in "${args[@]}"; do echo "    <string>${a/#\~/$HOME}</string>"; done
  echo '  </array>'
  echo "  <key>EnvironmentVariables</key><dict><key>PATH</key><string>$(dirname "$CLAUDE"):/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string></dict>"
  echo '  <key>RunAtLoad</key><true/>'
  echo '  <key>KeepAlive</key><true/>'
  echo '  <key>ThrottleInterval</key><integer>15</integer>'
  echo "  <key>StandardErrorPath</key><string>$HOME/.claude-bridge/daemon.log</string>"
  echo '</dict></plist>'
} > "$PLIST"

mkdir -p "$HOME/.claude-bridge"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
sleep 2

echo "Bridge running. On the controlling Mac, run:"
echo
echo "  claude mcp add claude-bridge --scope user \\"
echo "    -e BRIDGE_URL=http://$TS_IP:$PORT -e BRIDGE_TOKEN=$(cat "$HOME/.claude-bridge/token") \\"
echo "    -- uv run -q --script /path/to/claude-bridge/bridge_mcp.py"
echo
echo "Logs: ~/.claude-bridge/daemon.log   Stop: launchctl bootout gui/$(id -u)/$LABEL"
