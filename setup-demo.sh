#!/bin/bash
# ============================================================================
# setup-demo.sh  —  reset a pristine Claude Code state for demo recording.
#
# Used by `demo.tape` (vhs) so the demo runs on any fresh Linux machine:
#   * CI runners
#   * a remote server used for rendering
#   * anyone clone-and-run reproducing the GIF
#
# v0.5: we now seed projects in 3 states so the Step-1 picker shows off the
# new icon palette (🟢 active / 🔴 orphan / ❓ unknown — ⚪ empty is a rare
# edge case that's hard to construct reliably):
#   * active  — folder exists + jsonl with valid cwd + sessions ≥ 1
#   * orphan  — jsonl references a cwd whose folder is gone (primary demo
#               signal for the "I moved/deleted my project" use case)
#   * unknown — project-state directory exists but has no jsonl at all, so
#               discover_projects can't extract a cwd
#
# Running this script wipes ~/.claude/, ~/.claude.json, and the mock project
# directories under /tmp. It does NOT touch anything else.
# ============================================================================

set -e

OLD_PATH="/tmp/workspace/time-blocks"

# ---- Reset ----
rm -rf "$HOME/.claude" "$HOME/.claude.json"
rm -rf /tmp/workspace /tmp/archive /tmp/ghost_projects

mkdir -p "$HOME/.claude/projects"

write_session() {
  # write_session <cwd> <encoded-folder-name> [msg]
  local cwd="$1"
  local enc="$2"
  local msg="${3:-demo session}"
  mkdir -p "$HOME/.claude/projects/$enc"
  cat > "$HOME/.claude/projects/$enc/session-demo.jsonl" <<EOF
{"type":"user","cwd":"$cwd","msg":"$msg"}
{"type":"assistant","cwd":"$cwd","msg":"acknowledged"}
EOF
}

# ---- 🟢 active — folder exists, one session recorded ----
write_session "$OLD_PATH" "-tmp-workspace-time-blocks" "implementing feature X"
mkdir -p "$OLD_PATH"
echo "# time-blocks" > "$OLD_PATH/README.md"
echo "print('demo')" > "$OLD_PATH/main.py"

# ---- 🔴 orphan × 2 — cwd resolves but folder is gone ----
write_session "/tmp/ghost_projects/moved-away-last-month" \
              "-tmp-ghost_projects-moved-away-last-month" \
              "legacy prototype"
write_session "/tmp/ghost_projects/deleted-repo" \
              "-tmp-ghost_projects-deleted-repo" \
              "old workspace"

# ---- ❓ unknown — project-state dir exists but no jsonl inside ----
mkdir -p "$HOME/.claude/projects/-tmp-retired-scratch"

# ---- Global ~/.claude.json lists the resolved projects ----
cat > "$HOME/.claude.json" <<'EOF'
{
  "projects": {
    "/tmp/workspace/time-blocks": {"mcpServers": {}, "enabledMcpjsonServers": []},
    "/tmp/ghost_projects/moved-away-last-month": {"mcpServers": {}, "enabledMcpjsonServers": []},
    "/tmp/ghost_projects/deleted-repo": {"mcpServers": {}, "enabledMcpjsonServers": []}
  }
}
EOF

echo "[setup] mock state ready:"
echo "  active  → $OLD_PATH"
echo "  orphan  → /tmp/ghost_projects/moved-away-last-month (missing)"
echo "  orphan  → /tmp/ghost_projects/deleted-repo (missing)"
echo "  unknown → -tmp-retired-scratch (no jsonl)"
