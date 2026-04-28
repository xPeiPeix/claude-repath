# =============================================================================
# claude-repath v1.0.0 — TUI wizard demo (Linux render)
#
# Tool:      https://github.com/charmbracelet/vhs
# Reqs:      vhs 0.11+, ttyd 1.7+, ffmpeg 4+, claude-repath (via pipx/pip --user)
# Regen:     bash setup-demo.sh && vhs demo.tape
# Outputs:   demo.gif (README embed) + demo.mp4 (social / blog)
#
# Why Linux-shaped paths? vhs runs best on Linux (Windows has no native ttyd).
# The CLI itself supports Windows paths first-class — see README for examples.
#
# v1.0.0 highlights on display (move wizard — core use case):
#   * grayscale REPATH ASCII banner at splash
#   * wizard-step icons (📋 / 📍 / 🚀)
#   * Step-1a status-filter menu (active / orphan / empty / unknown / all)
#   * 4-state picker with 🟢 / 🔴 / ⚪ / ❓ icons + legend bar
#   * single-confirmation flow: Step 2 returns straight to Step 3's
#     Proceed menu (no more double "Confirm the new location?" prompt)
#   * explicit stage markers during migration: "● Moving project folder",
#     "● Rewiring Claude Code state" — replaces the silent-spinner look
#
# v1.0.0 also ships interactive pickers for `rollback` / `doctor` and
# `--install-completion` — not shown here to keep the splash demo tight;
# see README "Other commands" for those flows.
# =============================================================================

Output demo.gif
Output demo.mp4

# ---- Visuals ---------------------------------------------------------------
Set FontSize 14
Set Width 1280
Set Height 720
Set Padding 20
Set Theme "Dracula"
Set TypingSpeed 55ms
Set CursorBlink true
Set WindowBar Colorful
Set WindowBarSize 40

# ---- Fresh mock state (hidden setup) ---------------------------------------
Hide
Type 'export PATH="$HOME/.local/bin:$PATH"'
Enter
Type "bash setup-demo.sh"
Enter
Sleep 1500ms
Type "clear"
Enter
Show

# ---- Intro comment ---------------------------------------------------------
Type "# claude-repath v1.0 — relocate Claude Code projects without losing state"
Sleep 2s
Ctrl+U

# ---- Launch the interactive wizard -----------------------------------------
Type "claude-repath move"
Enter
# Give viewers time to read the REPATH banner + legend
Sleep 4s

# ---- Step 1a: status filter (default cursor lands on "active") -------------
Sleep 1s
Enter
Sleep 1500ms

# ---- Step 1b: pick project (default highlight = top active entry) ----------
Enter
Sleep 2s

# ---- Step 2: parent directory ----------------------------------------------
# Ctrl+U wipes questionary's pre-filled default, otherwise Type appends.
Ctrl+U
Type "/tmp/archive/"
Sleep 800ms
Enter

# ---- Step 2: project name (accept default) ---------------------------------
Sleep 600ms
Enter

# ---- Prompt: "Parent doesn't exist — create on apply?" (default Y) ---------
Sleep 600ms
Enter

# ---- Step 3: Migration Preview (let viewers read the per-layer counts) -----
# No separate "Confirm the new location?" menu in v1.0 — name input flows
# straight into Step 3. The Proceed menu cursor defaults to "Yes, proceed".
Sleep 5s
Enter

# ---- Watch stage markers ("● Moving..." / "● Rewiring...") + summary -------
Sleep 5s

# ---- Outro -----------------------------------------------------------------
Type "# Done — folder moved, ~/.claude/projects/ renamed, session jsonls rewired"
Sleep 3s
