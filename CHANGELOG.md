# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.2] — 2026-04-21

### Added

- **Pre-flight warning for path-sensitive subdirectories.** `move` now
  scans the first level of the source path for directories that embed
  absolute paths at creation time and will not function at the new
  location until rebuilt. Currently detects:
  - Python virtual environments (`.venv/` or `venv/` containing
    `pyvenv.cfg`) — Windows `Scripts/*.exe` are trampoline binaries whose
    resource section hard-codes the absolute path to `python.exe`; Unix
    scripts use `#!/abs/path` shebangs. After a move, `pytest` / `ruff` /
    any console script silently invokes the *old* path's `python.exe` (if
    still on disk) and imports from the old venv's `site-packages`.
  - `node_modules/` — `.bin/*.cmd` shims and pnpm symlinks may contain
    absolute paths.
  Unlike the pre-flight lock check, this is a **non-blocking warning**:
  the move proceeds normally, but the user is told what they need to
  rebuild and which command to use (`uv sync` / `pip install -e .` /
  `npm ci` / etc.). claude-repath does not auto-rebuild — every package
  manager has its own command and auto-running any of them without user
  consent can clobber lockfiles, pull unexpected versions, or take a long
  time with no progress feedback.
- New module `env_warn.py` (`find_env_sensitive_subdirs`,
  `format_env_warn_report`) paralleling the `locks.py` layout.
- 12 new pytest cases in `test_env_warn.py` (160 total): venv detection
  with `pyvenv.cfg` sentinel, `node_modules` detection, false-positive
  rejection (venv-named folder without `pyvenv.cfg`), non-recursive
  behavior (nested venvs under `src/` not flagged), multi-entry
  aggregation.

### Changed

- README gains a new **"Known limitations"** section above Platform
  support, documenting the venv / `node_modules` rebuild requirement with
  a per-ecosystem command reference table.
- `skills/claude-repath/SKILL.md` Edge cases section updated so the
  Claude Code agent warns users about the rebuild step **before** they
  run `move`.

## [0.4.1] — 2026-04-21

### Fixed

- **Atomic physical move — no more half-migrated source directories.**
  `move_project_folder` used to call `shutil.move`, which on Windows
  silently downgrades to a non-atomic `copytree + rmtree` when `os.rename`
  fails (cross-device **or** `WinError 32` / `WinError 5` from a file
  lock). If the lock only fired mid-rmtree (e.g. Docker Desktop's daemon
  holding `.git/objects/<hash>`, AV scanners, Windows Search indexer), the
  copy had already completed — leaving the user with **both** a complete
  target and a half-deleted source. The v0.4 pre-flight lock check
  (`locks.py`) caught many cases pre-emptively but could never cover
  elevated processes, TOCTOU races, or transient AV locks. The rewrite:
  - Primary path is now a bare `os.rename` — atomic, same-volume only.
  - `EXDEV` (cross-volume) falls back to `robocopy /MOVE` on Windows
    (built-in retry on locks, ships with the OS) or `shutil.move` on Unix
    (cross-volume is safe there — no in-use semantics).
  - **Any other** `OSError` raises a new `PhysicalMoveError` with a
    clear recovery message pointing to `claude-repath rewire`, and the
    source directory is guaranteed 100% intact for retry.
- **`.claude-plugin/plugin.json` + `marketplace.json` bumped from 0.3.2
  to 0.4.1.** They had been stuck at 0.3.2 across the 0.3.2→0.4.0 jump.

### Changed

- **`--force` help text clarified.** The flag still bypasses pre-flight
  lock detection but **cannot** bypass OS-level runtime locks (elevated
  processes, AV scans, Windows Search indexer). The new atomic-rename
  behavior makes this limitation survivable — you retry rather than
  recover from a half-migration.

### Added

- 9 new pytest cases in `test_migrate.py` pinning the atomic-rename
  invariants (148 total): same-volume `os.rename` primary path,
  source-preserved-on-lock (the load-bearing safety invariant),
  `EXDEV`-triggers-fallback, robocopy argument shape / failure handling,
  Unix `shutil.move` fallback. These regression tests lock the
  non-atomic `copytree + rmtree` downgrade out permanently.

## [0.4.0] — 2026-04-21

### Added

- **Claude Code plugin distribution.** This repo is now a single-plugin
  marketplace — users can install via
  `/plugin marketplace add xPeiPeix/claude-repath` +
  `/plugin install claude-repath@claude-repath-marketplace`. The plugin
  bundles a skill (`skills/claude-repath/SKILL.md`) that teaches Claude
  Code to recognize symptoms like "sessions gone after rename" and
  recommend `claude-repath` without the user knowing the tool's name.
- `.claude-plugin/marketplace.json` and `.claude-plugin/plugin.json`
  manifests at the repo root, following the single-plugin marketplace
  pattern (same model as `cndoit18/deepwiki`).
- **Pre-flight lock check** — `move` / `rewire` now scan running processes
  for `cwd` or open-file handles inside the target path and **hard-refuse**
  to start if any are found (unless `--force` / `-f` is passed). Previously,
  a shell `cd`-ed into the project directory or an IDE holding it open
  would make `shutil.move` fail mid-migration with `WinError 32`, leaving a
  half-migrated state. Now the check runs before any mutation and reports
  PID + process name + specific lock reason. Dry-run mode shows the same
  report informationally without blocking. Uses `psutil` for cross-platform
  process inspection.
- New runtime dependency: `psutil>=5.9` (pre-flight lock check).

### Changed

- **TUI `move` picker: `<unknown>` and 0-session projects sink to the
  bottom.** Projects whose cwd can't be resolved from their `.jsonl` files
  (typically empty-shell directories with zero sessions) used to interleave
  alphabetically with real projects by encoded folder name, making the real
  projects harder to find. They now sort **after** all resolved entries,
  and within the resolved group 0-session entries come after non-empty
  ones. Sort key: `(unknown?, zero_sessions?, cwd_lowercased)`.

## [0.3.2] — 2026-04-21

### Fixed

- **Interactive `move` picker now resolves real paths for all projects**,
  not just the lucky few. `_extract_cwd_from_sessions` previously read
  only the **first** JSON line of each `.jsonl` and then `break`-ed;
  real Claude Code sessions put `cwd` on the first user/assistant
  message (line 1+), while line 0 is session metadata
  (`type` / `permissionMode` / `sessionId`) with no `cwd` field. Result:
  the vast majority of projects showed up as `<unknown: D--dev-code-...>`
  and couldn't be selected without typing the full path. Fix: scan up
  to `_MAX_LINES_PER_JSONL` (50) lines per file before moving on.

### Added

- 3 new pytest cases in `test_tui.py` covering the real-world jsonl
  layout (metadata line first, cwd on line 2+), the bounded-scan
  fallback, and multiple metadata lines preceding cwd — plugging the
  testing blind spot that let the original bug ship (122 total).

## [0.3.1] — 2026-04-21

### Fixed

- `detect_claude_processes` (the soft check that warns when a Claude Code
  session is running) no longer flags `claude-repath` **itself** as a
  running claude process. The POSIX path used `pgrep -f claude`, which
  matched any command line containing the substring "claude" — including
  this tool's own PID — producing a spurious red `⚠ WARNING` at every
  apply. Fix: switch to `pgrep -af` (cmdline included) and skip entries
  whose cmdline contains "claude-repath".

### Added

- **Demo assets committed**: `demo.gif` (219 KB) + `demo.mp4` (183 KB),
  rendered end-to-end with [vhs](https://github.com/charmbracelet/vhs).
  README now embeds the GIF right under the tagline so first-time visitors
  see the wizard in action before reading a single word of prose.
- **Reproducible demo pipeline**: `demo.tape` + `setup-demo.sh` check
  into the repo. On any clean Linux box (including CI runners),
  `bash setup-demo.sh && vhs demo.tape` rebuilds `demo.gif` + `demo.mp4`
  from scratch. The setup script resets and mocks a minimal Claude state
  at `/tmp/workspace/time-blocks`, so running it is idempotent and never
  touches a user's real data.
- 3 new pytest cases covering the pgrep filter (119 total).

## [0.3.0] — 2026-04-20

### Added

- **Wizard-style TUI** — `claude-repath move` now walks through three
  clearly-labelled steps (pick project / new location / confirm) with
  Rich-rendered banners and inline help bars instead of a flat prompt list.
- **Two-stage path input** — new location entered as `parent directory`
  (with filesystem Tab-completion) + `project name` (defaults to original
  name, Enter to accept). Covers the two most common migration shapes:
  rehoming under a new parent, and in-place renames.
- **Step 3 preview panel** — before the final confirmation, a compact
  summary panel shows the exact Before → After paths plus per-layer
  change counts (folder, projects dir, jsonl cwd rewrites, worktrees,
  global.json key) and the backup location.
- **In-migration spinner** — `rich.status` shows live progress while
  `apply_migration` runs, replacing the previous silent pause.

### Changed

- Parent-directory auto-create is no longer silent: if the typed parent
  doesn't exist, the TUI explicitly confirms "create this directory?"
  before proceeding.

## [0.2.0] — 2026-04-19

### Added

- **`--scope narrow|broad`** flag on `move` / `rewire`. Default `narrow` scans
  only the main project and its worktrees (safe); `broad` scans every project
  directory and rewrites cross-project path references.
- **Interactive TUI picker** powered by `questionary`: running
  `claude-repath move` with no arguments lists known projects (real cwd
  extracted from each project's session `.jsonl`), prompts for the new path,
  and confirms. No need to remember encoded folder names.
- **Desktop Local Storage diagnostic** in `doctor`: reports whether Claude
  Code Desktop's Chromium `leveldb/` directory is present on the current OS
  (Win/macOS/Linux). Read-only — auto-migration deferred to v0.3+ backlog.
- **Cross-platform `platform_paths` module**: resolves the Desktop data
  directory for Windows / macOS / Linux (and `cygwin`).
- 35 new pytest cases (107 total) covering scope filtering, TUI interaction
  flow, and platform path detection.

### Changed

- `doctor`'s `~/.claude.json projects key` check now tolerates path-separator
  differences — a user-supplied `D:\foo` now matches stored `D:/foo`.

## [0.1.0] — 2026-04-19

### Added

- Initial release — first open-source tool that handles all 6 path-bound
  Claude Code state layers in a single command.
- CLI commands:
  - `move <old> <new>` — physical folder move + full state rewire
  - `rewire <old> <new>` — state-only (folder already moved manually)
  - `doctor <path>` — health check for a project's Claude state
  - `list` — every project Claude Code has state for
  - `rollback <timestamp>` — restore a previous migration's snapshot
  - `list-backups` — enumerate available backups
- Migration layers (in execution order):
  1. `~/.claude/projects/<encoded>/` folder renaming (incl. worktree auto-discovery)
  2. `.jsonl` session file `cwd` field rewriting (tolerant of both `\\` and `/`)
  3. `~/.claude.json` `projects` key migration
  4. `~/.claude/git-worktrees.json` path updates
- Safety features:
  - `--dry-run` preview
  - Manifest-based automatic backup to `~/.claude/.repath-backups/<ts>/`
  - LIFO rollback — correctly undoes nested rename + write effects
  - Soft-check for running `claude` processes
  - Interactive confirmation unless `-y/--yes` passed
- 72 unit + end-to-end pytest cases covering Windows backslash paths,
  forward-slash paths, mixed-style tolerance, worktree discovery, and
  full-round-trip rollback.

[Unreleased]: https://github.com/xPeiPeix/claude-repath/compare/v0.4.2...HEAD
[0.4.2]: https://github.com/xPeiPeix/claude-repath/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/xPeiPeix/claude-repath/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/xPeiPeix/claude-repath/compare/v0.3.2...v0.4.0
[0.3.2]: https://github.com/xPeiPeix/claude-repath/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/xPeiPeix/claude-repath/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/xPeiPeix/claude-repath/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/xPeiPeix/claude-repath/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/xPeiPeix/claude-repath/releases/tag/v0.1.0
