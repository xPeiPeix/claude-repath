# claude-repath

[![PyPI version](https://img.shields.io/pypi/v/claude-repath.svg)](https://pypi.org/project/claude-repath/)
[![Python versions](https://img.shields.io/pypi/pyversions/claude-repath.svg)](https://pypi.org/project/claude-repath/)
[![CI](https://github.com/xPeiPeix/claude-repath/actions/workflows/ci.yml/badge.svg)](https://github.com/xPeiPeix/claude-repath/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> Rewire Claude Code's local state when your project folder moves.

![claude-repath wizard demo](https://raw.githubusercontent.com/xPeiPeix/claude-repath/main/demo.gif)

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

## Install

Pick whichever matches your workflow — they're all equivalent:

| Method | Command | When to use |
|---|---|---|
| **uvx** (zero-install) | `uvx --from claude-repath claude-repath <subcommand>` | Try or use without installing — `uv` caches it transparently |
| **pipx** (global CLI) | `pipx install claude-repath` | Daily use, isolated from system Python |
| **pip** (in a venv) | `pip install claude-repath` | Already inside a project venv |

> 💡 **First time?** Run `uvx --from claude-repath claude-repath --version` — no commitment, just see if it works on your box. Upgrade later with `uvx --refresh …`.

---

## Install as a Claude Code plugin (optional)

In addition to the CLI, this repo ships a Claude Code plugin so your AI assistant can recognize symptoms — "I moved my project and Claude forgot everything", "sessions gone after rename", "~/.claude/projects has the old folder name" — and suggest `claude-repath` automatically, without you having to remember the tool's name.

From inside Claude Code:

```text
/plugin marketplace add xPeiPeix/claude-repath
/plugin install claude-repath@claude-repath-marketplace
```

Or, from any terminal (uses the open [skills.sh](https://skills.sh/) ecosystem — Claude Code, Cursor, Codex, and [~40 more agents](https://github.com/vercel-labs/skills#available-agents)):

```bash
npx skills add xPeiPeix/claude-repath
```

The plugin only ships a skill (a ~200-line guidance document). It does **not** bundle the CLI — you still install that via `uvx`/`pipx`/`pip` above, or let the skill guide Claude to run it via `uvx` on first use.

---

## Quick start

```bash
# INTERACTIVE mode — pick from a list, no path typing needed
claude-repath move

# Explicit mode — preview changes first (ALWAYS recommended)
claude-repath move D:\dev_code\time-blocks D:\dev_code\Life\time-blocks --dry-run

# Actually perform the migration (auto-backs-up first)
claude-repath move D:\dev_code\time-blocks D:\dev_code\Life\time-blocks

# Broader scan — also rewrite cross-project references (use with care)
claude-repath move <old> <new> --scope broad

# Override pre-flight lock check (still bounded by OS-level runtime locks
# — see --force note in Safety section). v0.4.1+ uses atomic os.rename, so
# a runtime lock now fails loudly with the source directory intact; previously
# shutil.move could half-succeed on Windows.
claude-repath move <old> <new> --force

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

Legend: **✅** fully handled · **⚠️** physically moved but needs manual rebuild · **🔍** diagnosed but not migrated

| # | Layer | Status |
|---|---|:---:|
| 1 | Physical project folder (`mv`) | ✅ |
| 2 | `~/.claude/projects/<encoded>/` directory name | ✅ |
| 3 | `.jsonl` session files — inline `"cwd"` fields | ✅ |
| 4 | `~/.claude.json` — `projects` key | ✅ |
| 5 | Worktree-derived project folders (auto-discovered) | ✅ |
| 6 | `~/.claude/git-worktrees.json` (if present) | ✅ |
| 7 | Python `.venv/` / `venv/` — rebuild after move ([why & how](#known-limitations)) | ⚠️ |
| 8 | `node_modules/` — rebuild after move ([why & how](#known-limitations)) | ⚠️ |
| 9 | Chromium `Local Storage/leveldb` entries (Desktop app) | 🔍 |

> ⚠️ rows: `move` physically relocates these directories, but their internal binaries/shims embed absolute paths and stop working until you rebuild with the original package manager. `claude-repath` detects them pre-flight and prints a non-blocking warning — see [Known limitations](#known-limitations) for the exact rebuild commands.

---

## Safety

- **Pre-flight lock check** (v0.4+): scans every running process via `psutil` for any that have a `cwd` inside the target directory or a file open under it, and **hard-refuses** the migration with exit code 1 if any are found. Reports PID, process name, and specific lock reason (shell `cd`, IDE, editor, etc.). Overridable with `--force` / `-f`.
- **Atomic physical move** (v0.4.1+): even when the pre-flight check misses a lock (elevated processes invisible to `psutil`, TOCTOU races, transient AV-scanner or Windows-Search-indexer locks), the physical folder move uses a bare `os.rename` instead of `shutil.move` — no silent `copytree + rmtree` downgrade. Result: on `WinError 32` / `5` the move fails loudly with exit code 1 and the source directory is **guaranteed intact** for retry; the previous half-migration failure mode (target complete, source half-deleted) is now impossible. Cross-volume moves fall back to `robocopy /MOVE` (Windows) or `shutil.move` (Unix).
- **Dry-run by default logic**: destructive commands require either `--dry-run` preview first or explicit confirmation. Dry-run also previews the pre-flight lock report without blocking.
- **Auto-backup**: every mutation is snapshotted to `~/.claude/.repath-backups/<timestamp>/`.
- **Running-Claude warning**: soft heads-up if any `claude` CLI process is detected holding state files (complements the hard pre-flight check above).
- **Rollback**: `claude-repath rollback <timestamp>` restores a previous snapshot.

---

## Known limitations

Some directories inside a project embed **absolute paths** at creation time,
and no amount of careful copying fixes that — they must be rebuilt after the
move. `claude-repath move` detects the most common offenders and prints a
warning (non-blocking) so you know what to rebuild:

| Directory | Why it breaks | How to rebuild |
|---|---|---|
| Python `.venv/` / `venv/` | Windows `Scripts/*.exe` trampolines hard-code the path to `python.exe`; Unix scripts use `#!/abs/path` shebangs | `uv sync` / `pip install -e .` / `poetry install` — whichever your project uses |
| `node_modules/` | `.bin/*.cmd` shims (Windows) and pnpm symlinks may contain absolute paths | `npm ci` / `pnpm install` / `yarn install` |

`claude-repath` **does not** run the rebuild for you — every package manager
has its own command and auto-running any of them without your consent can
clobber lockfiles, pull unexpected versions, or take a long time with no
progress feedback. The warning tells you what needs attention; you run the
right command.

Other directories with similar issues (`target/` for Rust debug builds,
`vendor/bundle/` for Ruby Bundler, etc.) are currently **not** detected —
flag them via a GitHub issue if you hit problems.

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

`claude-repath doctor` reports whether this directory exists on your machine but does **not** migrate it automatically — Desktop's Chromium leveldb format is intentionally out of scope (the schema is private to Anthropic and shifts between Desktop releases, so any auto-migration would be brittle to maintain). If you use Desktop exclusively and move a project, the Desktop UI's "recent projects" list may show a stale path. Remedy: open the new folder via Desktop's File menu to re-register it.

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
├── tui.py              # wizard picker + project discovery
├── locks.py            # pre-flight psutil lock detection (v0.4+)
├── encoder.py          # path → folder-name encoding
├── backup.py           # manifest-based backup & LIFO rollback
├── platform_paths.py   # per-OS Desktop state paths (Win/macOS/Linux)
├── utils.py            # shared path rewrite helpers
└── layers/
    ├── projects_dir.py    # ~/.claude/projects/<encoded>/ renaming
    ├── jsonl_cwd.py       # .jsonl cwd field rewriting
    ├── global_json.py     # ~/.claude.json projects key
    └── worktrees_json.py  # ~/.claude/git-worktrees.json
```

---

## Roadmap

- **v1.0.0 (current)** — **Interactive pickers for `rollback` / `doctor` + shell-completion auto-install.** Both commands previously hard-required a positional argument (`rollback <timestamp>` meant copy-pasting an encoded folder name from `list-backups`; `doctor <path>` required typing the absolute project path). v1.0.0 makes the argument optional and a no-args invocation launches a TUI picker matching `move`'s v0.3.0 wizard style. `rollback`'s picker lists every backup directory under `~/.claude/.repath-backups/` newest-first, each annotated with a humanized date (`2026-04-27 15:30:12`) parsed from the `YYYYMMDD-HHMMSS` directory name plus the manifest's entry count (or `[unreadable]` for corrupted manifests so one bad backup never aborts the picker). `doctor`'s picker reuses `pick_project` (status filter → orphan detection → conflict markers) but suppresses the `Step 1/3` wizard banner and filters out `<unknown: ...>` placeholder rows so the synthetic string never reaches `MigrationContext` as if it were a real path. `add_completion=True` flipped on the typer app exposes `claude-repath --install-completion` (auto-detects bash / zsh / fish / PowerShell and writes the script into the appropriate rc file) and `--show-completion` (dumps the script to stdout for manual inspection). `pick_project` gains keyword-only `wizard_step` / `title` / `prompt` / `exclude_unknown` parameters so non-wizard callers opt out of the step banner without forking the picker. `_read_manifest_entry_count` hardens against three previously-unhandled corruption modes: non-dict JSON root (`json.loads("[]")` returns a list, `data.get("entries")` was raising `AttributeError`), missing `entries` key, and non-UTF-8 bytes (`Path.read_text(encoding="utf-8")` raises `UnicodeDecodeError`, a `ValueError` subclass not in the original `(OSError, JSONDecodeError)` tuple). New `tests/test_cli.py` adds 8 typer-CliRunner smoke tests pinning the `Argument(None, ...)` change against future regressions — particularly the v0.5.1 "PyPI code right but `--version` wrong" footgun, now caught by `test_version_matches_init`.
- **v0.9.2** — **Pre-flight lock scan no longer "looks hung" on Windows.** `find_locks_on_paths` parallelizes the per-process inspection via `ThreadPoolExecutor` (`max_workers = min(32, cpu_count * 4)`); psutil's `proc.cwd()` / `proc.open_files()` release the GIL on every syscall so plain threads fan out cleanly, compressing 200+ processes × per-handle type-query latency from "10–60 s perceived hang" into single-digit seconds. `cli.py` additionally emits a permanent `● Pre-flight lock scan` stage marker plus a `console.status` spinner before the scan so the phase is visible in scrollback (matching v0.9.1's `● Moving project folder` / `● Rewiring Claude Code state` markers). `_inspect_process` now catches `psutil.ZombieProcess` (Linux/macOS unreaped children) and `OSError` at every entry point, including the leading `proc.info` access — a single transient `/proc` read failure no longer aborts the whole batch via `pool.map`. `pool.shutdown(wait=True, cancel_futures=True)` keeps Ctrl+C latency bounded by the slowest in-flight `open_files()` call instead of the full process queue. Step 2's Esc-at-name now calls a new `_erase_prev_lines(2)` helper before re-entering the parent prompt, so repeated Esc cycles overwrite the prior questionary transcript rows in place instead of stacking a growing column. The helper writes to `sys.stderr` (matching prompt_toolkit's default) and on Windows gates emission on `WT_SESSION` / `TERM_PROGRAM` / `TERM` env-var hints **or** an explicit `GetConsoleMode` check for the `ENABLE_VIRTUAL_TERMINAL_PROCESSING` bit — legacy `cmd.exe` without VT processing is silently skipped instead of rendering literal `?[F?[2K` garbage. `TERM=dumb` / `unknown` honored as opt-out.
- **v0.9.1** — **Single-confirmation migration flow.** Step 2's trailing "Confirm the new location?" action menu was collapsed into Step 3's Proceed menu — both previously confirmed the same decision (one over a path, one over the same path plus a plan-count breakdown), which felt like redundant friction. `prompt_new_path` now returns as soon as parent + name are filled (plus the parent-creation confirm when the parent is missing), and the Step 3 menu absorbs the displaced navigation: **✅ Yes, proceed / ✏️ Edit — re-enter path (Step 2) / ⬅️ Back to project selection (Step 1) / ❌ No, cancel**. Also adds **explicit stage markers during migration** (`● Moving project folder` / `● Rewiring Claude Code state` printed before each phase) — Rich's `console.status` spinner is live-redrawn and leaves no scrollback trace, so on larger moves users saw a silent gap and suspected a hang. The `●` lines stay visible both during and after execution. `_step_banner` gains a leading blank line for steps > 1 so the Step 3 Panel doesn't abut the tail of Step 2's path-preview output.
- **v0.9.0** — Interactive picker now disambiguates **duplicate-`cwd` rows**. When two project folders under `~/.claude/projects/` record the same `cwd` value (classic case: a WSL-launched session at `/mnt/d/dev_code` encodes as `-mnt-d-dev-code/` but its `.jsonl` entries carry `D:\dev_code\x` from a later `--add-dir` / cwd switch, colliding with the native `D--dev-code-x/` folder), previously-identical picker rows now gain a dim-yellow `⚠ from: <folder>` suffix so you can tell which `~/.claude/projects/<encoded>/` each row lives in. Collision detection scopes to the currently-visible filter bucket — a row visible in isolation stays clean.
- **v0.8.2** — Esc still took ~1 s despite v0.8.1 zeroing `timeoutlen`. Root cause: prompt_toolkit has **two** escape-timers on `Application`; v0.8.1 only lowered `timeoutlen` (multi-key binding wait) but left `ttimeoutlen` (terminal escape-sequence detection) at the 500 ms default, and the single-Esc path actually hits the latter. Setting `ttimeoutlen = 0.01` too makes Esc fire on keydown (~10 ms). Localized via temporary debug instrumentation (`CLAUDE_REPATH_DEBUG=1` hook), removed post-fix.
- **v0.8.1** — Hotfix pass over v0.8.0: Esc now fires faster (was stuck behind prompt_toolkit's 500 ms escape-timeout despite the `eager=True` binding — needed to zero out `Application.timeoutlen` too); crash at Step 1a when the filter prompt returned an empty string (`KeyError: ''`) fixed by routing it through the same `_ask_with_back` translator; Step-2 banner no longer stacks vertically every time the user cycles through the Edit option (moved the `_step_banner` + `_help_bar` calls out of the inner while loop).
- **v0.8.0** — **Esc = Back shortcut** throughout the wizard. Esc at Step 1b's project list returns to the status filter. Esc at Step 2's parent input jumps to Step 1; Esc at the name input loops back to parent (retaining it). Esc at any action menu is equivalent to choosing its "Back" item. Cross-platform — prompt_toolkit's Escape recognition works identically on Windows / macOS / Linux. The help bar in every step now shows `Esc back` for discoverability.
- **v0.7.0** — Interactive wizard gains **status filter + bidirectional navigation**. Step 1 now opens with a status-bucket menu (🟢 active / 🔴 orphan / ⚪ empty / ❓ unknown / 📋 all, each with counts), so machines with dozens of projects don't force you to paginate through everything to find one. Step 2 adds a live Source→Target path preview plus an action menu — Continue / ✏️ Edit (re-enter with defaults retained) / ⬅️ Back to Step 1 / ❌ Cancel. Step 3 similarly gains a Back option so you can hop back to Step 2 if the plan preview reveals a surprise, instead of Ctrl+C-ing out and restarting. Cursor defaults to `active` for daily-use flow.
- **v0.6.0** — Pre-flight lock check is now project-scoped instead of global. Previously every migration panel-warned on every `claude.exe` running on the box (10+ unrelated PIDs on multi-project machines, all noise). The check now scans the source project folder **plus** `~/.claude/projects/<encoded-source>/` — catching only Claude Code sessions actually operating on *this* project, and closing a prior blind spot where a session actively writing the source project's `.jsonl` state could be stepped on mid-migration. Unrelated Claude Code windows are correctly ignored. New public API `find_locks_on_paths(paths)` in `claude_repath.locks`; the old global `detect_claude_processes()` and `_warn_running_claude()` soft-warning are removed.
- **v0.5.0** — Interactive TUI picker visual overhaul: grayscale `REPATH` ASCII splash banner (figlet `ansi_shadow`, per-line `#f0f0f0` → `#404040` truecolor gradient), wizard-step icons (📋 pick / 📍 locate / 🚀 confirm), and per-row project-status icons with colored session counts. New **🔴 orphan detection** surfaces projects whose resolved `cwd` no longer exists on disk — the primary migration candidate — so you can see at a glance which projects actually need `claude-repath`. Sort precedence `active > orphan > empty > unknown` keeps daily-driver projects at the top, orphans visible just below. New dependency: `pyfiglet>=1.0`.
- **v0.4.2** — Pre-flight warning for path-sensitive subdirectories (`.venv` / `venv` with `pyvenv.cfg`, `node_modules`). Non-blocking heads-up before `move`: lists what will need rebuilding at the new location and the per-ecosystem rebuild command, but does not auto-rebuild (auto-running random package managers is risky). New `env_warn.py` module, new Known limitations section in the README, SKILL.md Edge cases entry so the Claude Code agent can warn users before they run `move`.
- **v0.4.1** — Atomic `os.rename` replaces `shutil.move` for the physical folder move; `EXDEV` cross-volume fallback uses `robocopy /MOVE` on Windows. Eliminates the Windows half-migration failure mode (source half-deleted + target complete) that the v0.4 pre-flight check could only prevent, not recover from. New `PhysicalMoveError` with actionable recovery message. `--force` help text clarifies it cannot bypass OS-level runtime locks.
- **v0.4** — Pre-flight lock check (psutil-based scan of running processes for `cwd`/`open_files` under the target path, hard-refusing unless `--force` is passed); Claude Code plugin distribution (installable as a single-plugin marketplace, ships a skill that lets Claude recognize rename symptoms and recommend the tool automatically); TUI picker sorts `<unknown>` and zero-session projects to the bottom.
- **v0.3** — Wizard-style TUI with three-step flow (pick / locate / preview), two-stage path input (parent directory + project name) with Tab-completion, per-layer change counts in a Rich preview panel, and a live spinner during apply.
- **v0.2** — Interactive TUI picker, `--scope narrow|broad` flag, Desktop Local Storage diagnostic, cross-platform path handling (Win/macOS/Linux).

---

## License

MIT
