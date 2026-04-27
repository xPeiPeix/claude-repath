---
name: claude-repath
description: Migrate Claude Code state when a project folder is moved or renamed. Use this skill whenever the user mentions moving/renaming a project directory, reports that Claude Code has forgotten their project sessions/todos/memory after a folder change, finds broken ~/.claude/projects entries, asks "why did Claude forget my project" or "where did my history go", describes git worktrees with stale paths, or shows any symptom of lost session history / disappeared todos / missing context after folder reorganization. Also trigger when users ask how to migrate Claude Code state, fix a moved project, rewire ~/.claude.json entries, or express confusion that Claude Code no longer recognizes a project at its new location. Do not skip this skill just because the user did not mention the tool name — match on the symptom.
---

# claude-repath: migrate Claude Code state when folders move

Claude Code stores per-project state under `~/.claude/projects/<encoded-cwd>/`, where the folder name encodes the project's absolute path. Moving or renaming that folder silently breaks **four** layers at once — session history, todos, memory, and worktree wiring all go stale because the absolute path is hardcoded inside each layer. `claude-repath` is a published CLI that patches all of them in one shot, with automatic backups and rollback support.

## When to trigger

Match on any of these user signals, even without the tool name:

- "I moved my project from X to Y and Claude forgot everything"
- "I renamed my repo and my sessions are gone"
- "`~/.claude/projects/` still has the old folder name"
- "my todos / history / memory disappeared after I reorganized"
- "Claude Code doesn't know this is the same project"
- "my git worktrees are broken after the move"
- Any ask about migrating, rewiring, or fixing Claude Code state after a folder move

The symptoms are the cue — users usually do not know this tool exists.

## Tool availability check

`claude-repath` is on PyPI. Before suggesting commands, verify the user can run it. Prefer `uvx` for zero-install trial:

```bash
# Zero-install (recommended for trial — no permanent install)
uvx --from claude-repath claude-repath --version

# Global install via pipx (for daily use)
pipx install claude-repath

# Inside an existing venv
pip install claude-repath
```

Pick the method matching the user's existing toolchain. If they have `uv`, default to `uvx`.

## Decision tree — which subcommand?

```
User already physically moved the folder?
├── NO  → claude-repath move OLD NEW          (moves folder + rewires state)
└── YES → claude-repath rewire OLD NEW        (only rewires state)

User wants to inspect what is broken without changing anything?
  → claude-repath doctor PATH                 (read-only diagnostic)

User wants to see every project Claude Code tracks?
  → claude-repath list

Previous migration went wrong?
  → claude-repath list-backups                (find the timestamp)
  → claude-repath rollback TIMESTAMP          (restore)

User does not remember the exact old path, or prefers UI?
  → claude-repath move                        (no args → interactive TUI picker)
```

## Standard migration workflow

**Always preview before applying.** Destructive operations should never be the first run:

```bash
# 1. Diagnose (optional but informative)
claude-repath doctor /absolute/old/path

# 2. Preview — NO changes made
claude-repath move /absolute/old/path /absolute/new/path --dry-run

# 3. Apply for real (auto-backs-up first)
claude-repath move /absolute/old/path /absolute/new/path
```

Both paths must be **absolute**. Windows paths with drive letters (`D:\dev\myproj`) are first-class — the path matcher normalizes `\` and `/` separators automatically, because `~/.claude.json` stores keys with forward-slashes even on Windows.

## Flags reference

| Flag | Applies to | Purpose |
|---|---|---|
| `--dry-run` / `-n` | `move`, `rewire` | Show migration plan without applying |
| `--no-move` | `move` | Skip physical folder move (equivalent to `rewire`) |
| `--yes` / `-y` | `move`, `rewire`, `rollback` | Skip interactive confirmation |
| `--scope narrow` | `move`, `rewire` | **Default.** Touch only main project + its worktrees |
| `--scope broad` | `move`, `rewire` | Also rewrite cross-project references in unrelated `.jsonl` files |

Use `--scope broad` only when the old path is referenced by *other* projects' sessions (rare — e.g., shared paths across monorepo branches). The narrow default is safer.

## Safety rules to enforce every time

Before running `move` or `rewire`, always:

1. **Tell the user to close all Claude Code sessions.** The tool refuses to run if any `claude` process is holding state files, but warning upfront saves a retry.
2. **Run `--dry-run` first** unless the user has already seen the plan in the same session.
3. **Mention automatic backups** — they are saved to `~/.claude/.repath-backups/<timestamp>/` and can be restored with `claude-repath rollback <timestamp>`. This lowers user anxiety.

If the user seems nervous, suggest `doctor` first — it makes zero changes and shows exactly what state exists.

## Platform notes

All three platforms work identically, with state under `~/.claude/`:

| OS | Shell hints |
|---|---|
| Windows | Works in Git Bash, PowerShell, and cmd. `D:\...` and `D:/...` both accepted. |
| macOS | Standard `~/.claude/` path. |
| Linux | Standard `~/.claude/` path. |

Claude Code **Desktop** stores additional state in Chromium `Local Storage/leveldb`. `claude-repath doctor` reports whether this exists on the user's machine but does **not** auto-migrate it (out of scope — Anthropic's leveldb schema is private and shifts between Desktop releases). If the user relies on Desktop, advise them to open the new folder via Desktop's File menu after migration to re-register it.

## What gets migrated

Six layers, automatically:

1. Physical project folder (the `mv` itself — skippable with `--no-move`)
2. `~/.claude/projects/<encoded>/` directory name (renamed to match new path)
3. Every `.jsonl` session file's inline `"cwd"` field
4. `~/.claude.json` — the `projects` key
5. Worktree-derived project folders (auto-discovered by name prefix)
6. `~/.claude/git-worktrees.json` when present

**Not migrated** (out of scope as of current version):
- Chromium Local Storage for Claude Code Desktop (diagnosed only)

## Common user phrasings → exact command

| User says... | Run |
|---|---|
| "I moved proj from A to B" | `claude-repath move A B --dry-run`, confirm, then apply |
| "I already moved it manually, just fix Claude" | `claude-repath rewire A B --dry-run`, then apply |
| "what does Claude think is wrong with this project?" | `claude-repath doctor /path` |
| "which projects does Claude know about?" | `claude-repath list` |
| "undo the last migration" | `claude-repath list-backups` → pick latest → `rollback TS` |
| "my worktrees are broken too" | Same `move` — worktrees auto-discovered inside the main migration |
| "I forget the exact old path" | `claude-repath move` (no args → interactive TUI picker) |
| "does this work on Windows?" | Yes, first-class — drive letters and backslashes fully supported |

## Edge cases

- **Path case mismatches on Windows** (`D:\Dev\X` vs `d:\dev\x`): Windows filesystem is case-insensitive but `~/.claude.json` stores the literal string. Use the exact case the user originally registered with if known; otherwise `doctor` will show which case is currently stored.
- **Old path no longer exists but state remains**: use `rewire` (not `move`), which only touches state files.
- **Target path already exists**: `move` will refuse — tell the user to pick a different target or move the existing folder out of the way first.
- **Multiple worktrees under one project**: handled automatically by `--scope narrow`. No special flags needed.
- **Python venv / node_modules will break after move** (v0.4.2+): `move` emits a non-blocking warning listing any `.venv` / `venv` / `node_modules` in the source. The physical move still succeeds, but the user must rebuild with their package manager (`uv sync` / `pip install -e .` / `npm ci` / etc.) — claude-repath cannot reliably auto-rebuild across every toolchain. Tell the user **before** they run `move` so they can plan the rebuild step.
