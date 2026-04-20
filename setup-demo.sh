#!/bin/bash
# ============================================================================
# setup-demo.sh  —  reset a pristine Claude Code state for demo recording.
#
# Used by `demo.tape` (vhs) so the demo runs on any fresh Linux machine:
#   * CI runners
#   * a remote server used for rendering
#   * anyone clone-and-run reproducing the GIF
#
# Running this script wipes ~/.claude/, ~/.claude.json, and the mock project
# directory under /tmp. It does NOT touch anything else.
# ============================================================================

set -e

OLD_PATH="/tmp/workspace/time-blocks"
ENCODED="-tmp-workspace-time-blocks"

# ---- Reset ----
rm -rf "$HOME/.claude" "$HOME/.claude.json"
rm -rf /tmp/workspace /tmp/archive

# ---- Claude Code projects directory with a mock session.jsonl ----
mkdir -p "$HOME/.claude/projects/$ENCODED"
cat > "$HOME/.claude/projects/$ENCODED/session-demo.jsonl" <<EOF
{"type":"user","cwd":"$OLD_PATH","msg":"implementing feature X"}
{"type":"assistant","cwd":"$OLD_PATH","msg":"here is the implementation"}
{"type":"user","cwd":"$OLD_PATH","msg":"looks good, ship it"}
EOF

# ---- Global ~/.claude.json (next to ~/.claude/, not inside) ----
cat > "$HOME/.claude.json" <<EOF
{"projects":{"$OLD_PATH":{"mcpServers":{},"enabledMcpjsonServers":[]}}}
EOF

# ---- Physical project folder (required so `move` can mv it) ----
mkdir -p "$OLD_PATH"
echo "# time-blocks" > "$OLD_PATH/README.md"
echo "print('demo')" > "$OLD_PATH/main.py"

echo "[setup] mock state ready — demo project at $OLD_PATH"
