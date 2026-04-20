# =============================================================================
# claude-repath v0.3 — TUI wizard demo (Linux render)
#
# Tool:      https://github.com/charmbracelet/vhs
# Reqs:      vhs 0.11+, ttyd 1.7+, ffmpeg 4+, claude-repath (via `uv tool install`)
# Regen:     bash setup-demo.sh && vhs demo.tape
# Outputs:   demo.gif (README embed) + demo.mp4 (social / blog)
#
# Why Linux-shaped paths? vhs runs best on Linux (Windows has no native ttyd).
# The CLI itself supports Windows paths first-class — see README for examples.
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
Type "# claude-repath — relocate Claude Code projects without losing state"
Sleep 2s
Ctrl+U

# ---- Launch the interactive wizard -----------------------------------------
Type "claude-repath move"
Enter
Sleep 2500ms

# ---- Step 1/3: pick project (only one in the mock state) -------------------
Enter
Sleep 2s

# ---- Step 2/3: parent directory --------------------------------------------
# Ctrl+U wipes questionary's pre-filled default, otherwise Type appends.
Ctrl+U
Type "/tmp/archive/"
Sleep 800ms
Enter

# ---- Step 2/3: project name (default accepts) ------------------------------
Sleep 600ms
Enter

# ---- Prompt: "Parent doesn't exist — create on apply?" (default Y) ---------
Sleep 600ms
Enter

# ---- Step 3/3: preview panel (let viewers read) ----------------------------
Sleep 4500ms

# ---- Confirm & watch spinner + success panel -------------------------------
Type "y"
Sleep 4s

# ---- Outro -----------------------------------------------------------------
Type "# Done — folder moved, ~/.claude/projects/ renamed, session jsonls rewired"
Sleep 3s
