# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/xPeiPeix/claude-repath/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/xPeiPeix/claude-repath/releases/tag/v0.1.0
