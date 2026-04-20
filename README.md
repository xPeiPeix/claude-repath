# claude-repath

> Rewire Claude Code's local state when your project folder moves.

When you move or rename a project directory, Claude Code loses track of its sessions, memory, todos, and worktrees — because the absolute path is hardcoded in **four** different places. `claude-repath` patches all of them in one shot.

---

## Why this exists

Claude Code stores per-project state under `~/.claude/projects/<encoded-cwd>/`, where the folder name is derived from the project's absolute path. Moving the project folder breaks:

1. `~/.claude/projects/<encoded>/` — the encoded folder name no longer matches
2. `~/.claude/projects/<encoded>/*.jsonl` — each session file has `"cwd"` hardcoded inside
3. `~/.claude.json` — the `projects` key is indexed by absolute path
4. Git worktree sub-projects — each has its own encoded folder AND internal `cwd` fields

Anthropic has no official migration command (as of 2026-04), and existing community tools cover at most 6 of the needed layers. `claude-repath` aims to handle **all of them**, with special care for Windows paths and worktrees.

---

## Quick start

```bash
# Install
pip install claude-repath

# Or run without installing (requires uv)
uvx --from claude-repath claude-repath --help

# INTERACTIVE mode — pick from a list, no path typing needed
claude-repath move

# Explicit mode — preview changes first (ALWAYS recommended)
claude-repath move D:\dev_code\time-blocks D:\dev_code\Life\time-blocks --dry-run

# Actually perform the migration (auto-backs-up first)
claude-repath move D:\dev_code\time-blocks D:\dev_code\Life\time-blocks

# Broader scan — also rewrite cross-project references (use with care)
claude-repath move <old> <new> --scope broad

# If you already moved the folder manually, just rewire state
claude-repath rewire D:\dev_code\time-blocks D:\dev_code\Life\time-blocks

# Health check a project's Claude Code state
claude-repath doctor D:\dev_code\time-blocks

# List all projects Claude Code knows about
claude-repath list

# Roll back a previous migration
claude-repath rollback 20260419-155331
```

---

## What gets migrated

| # | Layer | Handled |
|---|---|:---:|
| 1 | Physical project folder (`mv`) | ✅ |
| 2 | `~/.claude/projects/<encoded>/` directory name | ✅ |
| 3 | `.jsonl` session files — inline `"cwd"` fields | ✅ |
| 4 | `~/.claude.json` — `projects` key | ✅ |
| 5 | Worktree-derived project folders (auto-discovered) | ✅ |
| 6 | `~/.claude/git-worktrees.json` (if present) | ✅ |
| 7 | Chromium `Local Storage/leveldb` entries (Desktop app) | ⏳ v0.3+ backlog |

---

## Safety

- **Dry-run by default logic**: destructive commands require either `--dry-run` preview first or explicit confirmation
- **Auto-backup**: every mutation is snapshotted to `~/.claude/.repath-backups/<timestamp>/`
- **Process guard**: refuses to run if any `claude` process is holding the state files
- **Rollback**: `claude-repath rollback <timestamp>` restores a previous snapshot

---

## Platform support

| OS | CLI state (`~/.claude/`) | Desktop state (`Local Storage/leveldb`) |
|---|:---:|:---:|
| **Windows** 11 (Git Bash / PowerShell / cmd) | ✅ auto-migrated | 🔍 diagnosed |
| **macOS** | ✅ auto-migrated | 🔍 diagnosed |
| **Linux** | ✅ auto-migrated | 🔍 diagnosed |

Windows paths with drive letters (`D:\...`) and backslashes are first-class — they were the primary motivation for writing this tool. The path matcher accepts both `\` and `/` separators and automatically aligns with `~/.claude.json`'s forward-slash-stored keys.

### About Claude Code **Desktop**

Claude Code Desktop stores additional session state in Chromium's Local Storage LevelDB:
- Windows: `%LOCALAPPDATA%\claude\Local Storage\leveldb\`
- macOS: `~/Library/Application Support/claude/Local Storage/leveldb/`
- Linux: `~/.config/claude/Local Storage/leveldb/`

`claude-repath doctor` reports whether this directory exists on your machine but does **not** migrate it automatically — see [Roadmap](#roadmap) for planned v0.3+ support. If you use Desktop exclusively and move a project, the Desktop UI's "recent projects" list may show a stale path. Remedy: open the new folder via Desktop's File menu to re-register it.

---

## Comparison to existing tools

At the time of writing (April 2026) there is **no official** Anthropic
migration command. A handful of community tools exist — `claude-repath`
is designed to close their gaps:

| Tool | Layers covered | Windows | Worktrees | `~/.claude.json` | Separator tolerance |
|---|:---:|:---:|:---:|:---:|:---:|
| arak-git/claude-code-project-mover-py | 6 | ✅ | partial | ✅ | partial |
| justinstimatze/claude-mv | 9 | ❌ | ❌ | ✅ | ❌ |
| lovstudio/cc-mv (npm) | 4 | ? | ❌ | ❌ | ❌ |
| skydiver/claude-code-project-mover | 2 | ❌ | ❌ | ❌ | ❌ |
| **claude-repath** | **6 + rollback** | ✅ | ✅ auto | ✅ | ✅ both |

---

## Development

```bash
# Clone & enter
git clone https://github.com/xPeiPeix/claude-repath.git
cd claude-repath

# Install with uv (creates .venv, installs typer + dev deps)
uv sync --all-groups

# Run tests
uv run pytest

# Lint
uv run ruff check

# Run CLI locally
uv run claude-repath --help
```

Layout:

```
src/claude_repath/
├── cli.py              # typer app (move/rewire/doctor/list/rollback)
├── migrate.py          # orchestrator
├── encoder.py          # path → folder-name encoding
├── backup.py           # manifest-based backup & LIFO rollback
├── utils.py            # shared path rewrite helpers
└── layers/
    ├── projects_dir.py    # ~/.claude/projects/<encoded>/ renaming
    ├── jsonl_cwd.py       # .jsonl cwd field rewriting
    ├── global_json.py     # ~/.claude.json projects key
    └── worktrees_json.py  # ~/.claude/git-worktrees.json
```

---

## Roadmap

- **v0.2 (current)** — Interactive TUI picker, `--scope narrow|broad` flag, Desktop Local Storage diagnostic, cross-platform path handling (Win/macOS/Linux)
- **v0.3+ (backlog)** — Chromium `Local Storage/leveldb` auto-migration for Claude Code Desktop users (requires closing Desktop first + `plyvel-ci` bindings + META-protobuf maintenance); interactive TUI variants for `rollback` / `doctor`; shell-completion auto-install (typer's built-in)

---

## License

MIT
