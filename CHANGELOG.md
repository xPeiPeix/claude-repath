# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.9.2] — 2026-04-27

### Fixed

- **Pre-flight lock scan no longer "looks hung" on Windows.** Users
  reported the TUI freezing for 10–60 seconds after pressing
  ``✅ Yes, proceed`` on busy machines. Root cause:
  ``find_locks_on_paths`` walked every running process serially and on
  Windows ``psutil.Process.open_files()`` does a per-handle type query
  with a defensive timeout — 200+ processes × ~100 handles each pushed
  the scan into "looks hung" range. The scan is now parallelized with
  ``ThreadPoolExecutor`` (``max_workers = min(32, cpu_count * 4)``);
  ``open_files()`` releases the GIL on every syscall so plain threads
  fan out cleanly. ``cli.py`` additionally prints a permanent
  ``● Pre-flight lock scan`` stage marker plus a ``console.status``
  spinner before the scan, so the user can see work is happening
  even when the scan still takes a moment.
- **Esc-at-name no longer stacks duplicate prompt rows.** In Step 2
  of the wizard, repeatedly pressing Esc at the project-name prompt
  to re-edit the parent left a growing column of finalized
  ``? New parent directory:`` / ``? New project name:`` rows in
  scrollback. ``prompt_new_path`` now calls a new
  ``_erase_prev_lines(2)`` helper before re-entering the loop so
  each iteration overwrites the prior attempt in place.

### Changed

- **Cross-platform robustness for the new ANSI helper and parallel
  scan.** ``_erase_prev_lines`` writes to ``sys.stderr`` (matching
  ``questionary`` / ``prompt_toolkit``'s default output stream); on
  Windows it gates on ``WT_SESSION`` / ``TERM_PROGRAM`` / ``TERM`` env
  vars **or** an explicit ``GetConsoleMode`` check for the
  ``ENABLE_VIRTUAL_TERMINAL_PROCESSING`` bit, so legacy ``cmd.exe``
  without VT processing skips the emit instead of rendering literal
  ``?[F?[2K`` garbage. ``TERM=dumb`` / ``unknown`` is honored as an
  explicit opt-out. The parallel scan's worker now catches
  ``psutil.ZombieProcess`` (Linux/macOS) and ``OSError`` at every
  entry point of ``_inspect_process`` (including the leading
  ``proc.info`` access), so a single transient ``/proc`` read failure
  can't abort the whole batch via ``pool.map``. ``shutdown(wait=True,
  cancel_futures=True)`` keeps Ctrl+C latency bounded by the slowest
  in-flight ``open_files()`` call instead of the full process queue.

## [0.9.1] — 2026-04-24

### Changed

- **Step 2/3 confirmation merged.** The trailing "Confirm the new
  location?" action menu at the end of Step 2 was collapsed into Step
  3's Proceed menu — both menus confirmed the same decision (one over
  a path, one over the same path plus a plan-count breakdown), which
  felt like redundant friction. ``prompt_new_path`` now returns the
  composed path as soon as parent + name are filled (and the
  parent-creation confirm, when applicable), and Step 3's menu gains
  the displaced navigation options:

  ```
  Proceed with migration?
    ✅  Yes, proceed
    ✏️  Edit — re-enter path (Step 2)
    ⬅️  Back to project selection (Step 1)
    ❌  No, cancel
  ```

  ``Edit`` re-runs Step 2 keeping the picked project; ``Back to project
  selection`` rewinds all the way to Step 1; Esc on the menu is
  equivalent to ``Edit``. Four previously-needed tests for the removed
  Step 2 action menu were deleted; two new tests pin the Step 3 edit /
  back_to_pick navigation semantics.

### Added

- **Explicit stage markers during migration.** ``move_cmd`` now prints
  a permanent ``● Moving project folder`` / ``● Rewiring Claude Code
  state`` line before each phase in addition to the existing spinner.
  Rich's ``console.status`` spinner is live-redrawn and leaves no
  trace in the scrollback, so on larger moves (or in terminals that
  render spinner frames unreliably) the user saw a silent gap and
  suspected a hang. The ``●`` lines stay in the output both during
  and after execution, so "what phase am I in" is answerable at a
  glance.

### Fixed

- **Visual glue between Step 2 and Step 3 panels.** ``_step_banner``
  now emits a blank line before every step after the first, so the
  Step 3 ``Review & confirm`` Panel doesn't abut the tail of Step 2's
  path-preview / confirmation output. Step 1 keeps no leading blank
  because the REPATH splash already provides separation.

## [0.9.0] — 2026-04-24

### Added

- **Conflict marker for duplicate-cwd picker rows.** When two projects
  under ``~/.claude/projects/`` record the same ``cwd`` value (classic
  case: a WSL-launched session at ``/mnt/d/dev_code`` encodes as
  ``-mnt-d-dev-code/`` but its jsonl lines carry ``D:\dev_code\x`` from a
  later ``--add-dir`` / cwd switch, colliding with the native
  ``D--dev-code-x/`` folder), the Step-1 picker previously rendered two
  visually indistinguishable rows — the user couldn't tell which
  ``<encoded>/`` directory each one lived in. v0.9.0 now appends a
  dim-yellow ``⚠ from: <folder>`` suffix to colliding rows, keeping
  non-colliding rows untouched. Collision detection scopes to the
  currently-visible filter bucket, so a row visible in isolation stays
  clean.

  ``_choice_title`` gains an opt-in keyword-only ``conflict_folder``
  argument; ``pick_project`` builds the collision set from the filtered
  entries with a single ``Counter`` pass. Four new tests pin the
  backwards-compat shape, the suffix content/style, and the end-to-end
  collision + unique behaviors under ``pick_project``.

## [0.8.2] — 2026-04-24

### Fixed

- **Esc latency still ~1 s after v0.8.1 despite ``timeoutlen = 0``.**
  prompt_toolkit has *two* escape-timer knobs on ``Application``:
  - ``timeoutlen`` — gates multi-key bindings (e.g. ``Ctrl-X Ctrl-S``)
    waiting for the second key
  - ``ttimeoutlen`` — gates terminal-level escape-sequence detection
    (single Esc vs ``ESC [ A`` arrow keys)

  v0.8.1 zeroed only the first, leaving the single-Esc path pinned at
  the ~500 ms terminal timer. Debug instrumentation on a Windows
  PowerShell session confirmed this: ``timeoutlen`` was 0.0 as written,
  but the Esc handler still only fired ~1 s after the keystroke (time
  delta between ``about to call unsafe_ask`` and ``esc handler fired``
  in the trace). Setting ``ttimeoutlen = 0.01`` collapses the terminal
  timer too and Esc now fires on keydown. Users should notice the Back
  transition as effectively instant (~10 ms vs the old ~1 s).

## [0.8.1] — 2026-04-24

### Fixed

- **Esc response latency on single press.** v0.8.0 relied on `eager=True`
  in the prompt_toolkit KeyBinding to fire Esc immediately, but Esc is a
  *prefix key* (can introduce Alt-<key> combos) and the global
  `Application.timeoutlen` (default 500 ms) still gated the single-press
  handler behind a half-second wait. `_attach_esc_back` now collapses
  `timeoutlen` to `0.0` so Esc fires on keydown. Users saw a ~2 s delay
  before the Back-to-Step-1a transition; it's now instant.
- **``KeyError: ''`` at Step 1a when the filter prompt returned an empty
  string.** Some questionary + prompt_toolkit versions emit `''` (instead
  of raising) when the user hits Esc at a `select` prompt without the
  Esc handler wired. `_pick_status_filter` now routes through
  `_ask_with_back` so Esc consistently maps to :data:`_BACK`, and treats
  an empty-string return as cancel. Guards the downstream
  `buckets[filter_key]` lookup from crashing on a bogus key.
- **Step-2 banner stacking when the user cycled through "Edit".** The
  ``_step_banner`` + ``_help_bar`` calls were inside the Step-2 ``while``
  loop, so every Edit round re-printed the banner, stacking them vertically
  and confusing first-time users about which Step-2 prompt was "live".
  Moved both calls to run once on function entry; prompts, preview, and
  action menu still re-render per loop iteration as before.

### Changed

- `_pick_status_filter` return type semantics: previously returned
  ``None`` only on Ctrl+C; now also returns ``None`` on Esc and on any
  falsy value (e.g. ``""``). Equivalent behavior for callers that
  already guarded with ``if filter_key is None``.

## [0.8.0] — 2026-04-24

### Added

- **Esc = Back shortcut throughout the wizard.** Pressing Esc at any
  interactive prompt jumps back one step instead of being a no-op. The
  four hop-points:
  - Step 1b (project list) → **back to Step 1a (filter menu)** — lets
    you widen or switch category without Ctrl+C-ing the whole flow
  - Step 2 parent field → **back to Step 1** (re-pick project)
  - Step 2 name field → **back to the parent field** (retains parent,
    just re-enter name)
  - Step 2 / Step 3 action menus → **equivalent to choosing "Back"**
  The help bar in every step now shows `Esc back` so the shortcut is
  discoverable without reading docs.
- New module-level helpers in `claude_repath.tui`:
  - `_EscBackError` — custom exception raised from the Esc key binding
  - `_esc_back_kb()` — prompt_toolkit KeyBindings instance with an
    eager Escape handler (fires on the single keystroke, no 500 ms
    wait for Alt-<key> combos we don't use)
  - `_attach_esc_back(question)` — merges the Esc handler onto a
    questionary Question's existing bindings after construction
    (workaround for `questionary.path` / `text` passing their own
    `key_bindings` kwarg to PromptSession, which blocks the usual
    "add as a kwarg" path)
  - `_ask_with_back(question)` — runs the prompt's `unsafe_ask` and
    translates `_EscBackError` → :data:`_BACK`, KeyboardInterrupt →
    None, everything else propagates
- 8 new pytest cases in `test_tui.py` (200 total, up from 192):
  `_ask_with_back` exception-to-sentinel mapping (EscBackError / KI /
  normal value / propagation of unexpected exceptions), Esc at parent
  returns `_BACK`, Esc at name loops back to parent, Esc at Step 2
  action menu propagates, Esc at project list re-opens filter menu.

### Changed

- `pick_project` wraps Step 1a + Step 1b in a `while True` loop so
  Esc from the project list is a no-cost re-entry into the filter
  stage. The filter stage itself still only has Ctrl+C for cancel
  (it's the first step — nothing to go back to).
- `prompt_new_path` routes the parent / name inputs through
  `_ask_with_back` so Esc propagates as `_BACK` (parent) or loops
  the inner re-entry (name).
- `run_interactive_move` treats the Step-3 action menu's `_BACK`
  return (Esc pressed) the same as choosing the menu's "Back" item.
- Cross-platform: prompt_toolkit's Esc recognition is consistent
  across Windows / macOS / Linux; no platform-specific code needed.

## [0.7.0] — 2026-04-24

### Added

- **Step 1 status filter.** The interactive `move` picker now opens with a
  compact menu that buckets projects by status — 🟢 active / 🔴 orphan /
  ⚪ empty / ❓ unknown / 📋 all — each with a count. On machines with
  many projects (the common case once you've used Claude Code for a
  while), you can narrow the list to a single status before scrolling.
  The cursor defaults to `active`, the daily-use case. Empty buckets are
  hidden from the menu so users never see "empty (0)". New public helper
  `_group_by_status` centralizes the bucketing logic for test reuse.
- **Step 2 path preview + action menu.** After entering parent + name,
  the wizard shows a Source→Target panel so you can see exactly where
  the project will land before committing. A follow-up action menu
  offers four paths:
  - ✅ Continue — proceed to Step 3 (plan preview)
  - ✏️  Edit — re-enter parent / name (defaults preserve last inputs, so
    a typo in one field doesn't force re-typing the other)
  - ⬅️  Back — return to Step 1 to re-pick the project
  - ❌ Cancel — abort the whole flow
- **Step 3 back-to-Step-2 option.** The final "Proceed with migration?"
  prompt is now a three-way menu (proceed / back / cancel), so if the
  plan preview reveals an unexpected change count you can hop back to
  Step 2 and edit the target location without Ctrl+C-ing out and
  restarting from scratch.
- Sentinel constant `_BACK` (returned by step functions to signal the
  orchestrator to re-enter the previous step) and helper `_ask_action`
  (wraps `questionary.select` for the Step-2/Step-3 action menus).
- 11 new pytest cases in `test_tui.py` (192 total, up from 181):
  status-bucket classification (empty / four-status / missing keys),
  filter stage dispatch (all / one-bucket / cancel / empty-dir skip),
  Step-2 action menu branches (back / cancel / edit-then-confirm loop),
  Step-3 back navigation (re-prompts new path while keeping project),
  Step-2 back navigation (re-runs picker, retains flow state).

### Changed

- `pick_project` is now a two-stage flow (filter → project) instead of a
  single flat list. Pre-v0.7 callers that passed no arguments besides
  `projects_dir` are unaffected — the signature is unchanged, only the
  interactive behavior is richer.
- `prompt_new_path` return type widened to include `_BACK` alongside
  `str | None`. Type annotation is still `str | None` at the signature
  level (the sentinel is a string) but callers now check for the
  `_BACK` value before using the result as a path.
- `run_interactive_move` wraps the three steps in an outer `while`
  loop. Forward transitions advance by setting `old` / `new`; back
  transitions clear the later variable and re-enter the earlier step.
  Step 1 has no back option (it's the first step); Step 2 and Step 3
  each have one.

## [0.6.0] — 2026-04-24

### Changed

- **Pre-flight lock check is now project-scoped, not global.** Previously,
  `move` / `rewire` printed a red `⚠ WARNING` panel listing every
  running `claude.exe` / `claude` process on the machine, regardless of
  which project each Claude Code session was operating on. On a
  multi-project Windows box this surfaced 10+ unrelated PIDs as
  "possible interference" on every migration — pure noise, and the
  user was told to close them all before continuing. The check now
  asks a more precise question: *which processes actually hold
  resources relevant to **this** migration?* It scans two paths in one
  psutil pass:
  1. The source project folder — catches shells that have `cd`-ed in,
     IDEs / editors with open files (unchanged from v0.4).
  2. `~/.claude/projects/<encoded-source>/` — the per-project Claude
     Code state directory. Catches a Claude Code session actively
     writing `.jsonl` session files for *this* project, which was
     previously a blind spot: a session writing the source project's
     state could be stepped on mid-migration, and the old global
     `claude.exe` scan could not identify the guilty session.
  Unrelated Claude Code sessions (operating on *other* projects) are
  now correctly ignored. The lock panel lists every scanned path so
  the scope is transparent.

### Added

- **`find_locks_on_paths(paths: list[Path])`** public API in
  `claude_repath.locks` — multi-path aggregation of the single-path
  `find_locks_on_path`. One pass over `psutil.process_iter`; each
  process contributes at most one entry regardless of how many target
  paths hit; non-existent paths are silently skipped so callers can
  pass candidate lists without pre-filtering. `find_locks_on_path` is
  retained as a single-path convenience wrapper.
- 6 new pytest cases in `test_locks.py` (181 total, up from 178):
  empty-input short-circuit, all-paths-nonexistent short-circuit,
  mixed-existence tolerance (missing path skipped, real path still
  checked), cross-path hit aggregation, single-process dedup across
  multiple target paths, `find_locks_on_path` single-path wrapper
  delegation invariant.

### Removed

- **`detect_claude_processes()`** public function in
  `claude_repath.migrate` — the former global `tasklist` / `pgrep -af`
  scan that powered the noisy `⚠ WARNING` panel. Callers needing
  project-scoped process detection should use `find_locks_on_paths`
  instead, which reports *why* each process is a risk (cwd /
  open_file) rather than a bare PID list. `TestDetectClaudeProcesses`
  (3 cases) removed from `test_migrate.py`.
- **`_warn_running_claude()`** soft-warning helper in `cli.py` — the
  red `⚠ WARNING` panel itself. The targeted hard-check (pre-flight
  lock report) now covers every case the soft warning was meant to
  flag, with better signal and no false positives from unrelated
  Claude Code windows.

## [0.5.2] — 2026-04-22

### Fixed

- **`claude-repath --version` reported stale 0.5.0 on 0.5.1 install.**
  v0.5.1 synced three version-number locations (`pyproject.toml`,
  `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`) but
  missed a fourth: `src/claude_repath/__init__.py`'s `__version__`
  constant, which is what `typer`'s `--version` callback reads. Result:
  PyPI shipped 0.5.1 code, but `claude-repath --version` printed
  `0.5.0` — harmless but misleading. v0.5.2 bumps the fourth location.

### Changed

- **Release checklist expanded from three to four version-number
  locations.** `CLAUDE.md` + `.claude/rules/release.md` now both pin
  the complete four-file bump (adds `src/claude_repath/__init__.py`
  explicitly), with a copy-paste `grep` one-liner for post-bump
  verification. Lesson pinned at the bottom of the checklist so the
  next agent does not repeat v0.5.1's mistake.

## [0.5.1] — 2026-04-22

### Fixed

- **PyPI project page `demo.gif` broken image.** The README embedded
  the demo GIF with a relative path (`./demo.gif`), which GitHub
  auto-resolves to a raw URL but PyPI does not render — so the PyPI
  page showed a broken-image icon instead of the wizard demo.
  Replaced with the absolute
  `https://raw.githubusercontent.com/xPeiPeix/claude-repath/main/demo.gif`
  URL so the GIF renders identically on GitHub and PyPI. Note: PyPI
  does not retroactively re-render old versions' README, so fixing
  v0.5.0's already-published PyPI page requires publishing this
  patch release.

### Added

- **`npx skills add xPeiPeix/claude-repath` install path** documented
  in the "Install as a Claude Code plugin" section. Covers the
  [skills.sh](https://skills.sh/) open-standard ecosystem
  (`vercel-labs/skills` CLI), which discovers this repo's
  `skills/claude-repath/SKILL.md` automatically and symlinks it into
  any supported agent (Claude Code, Cursor, Codex, ~40 more) —
  complementing the existing `/plugin marketplace add` path for
  Claude Code-native installs.
- `CLAUDE.md` + `.claude/rules/release.md` — project-level AI
  behavior rules + a strict release checklist (three-file version bump
  sync, CHANGELOG link-table, README absolute-URL guard, `gh release
  create` requirement to trigger `publish.yml`, PyPI + skills.sh
  post-publish verification). Lessons learned from v0.5.0's PyPI
  demo-gif regression are pinned at the bottom of the checklist.

## [0.5.0] — 2026-04-22

### Added

- **TUI picker visual overhaul.** `claude-repath move` (no-args
  interactive mode) now opens with a grayscale `REPATH` ASCII splash
  banner (figlet `ansi_shadow` font, per-line truecolor gradient from
  `#f0f0f0` near-white down to `#404040` dark gray), gated on
  `sys.stderr.isatty()` so pytest capture and pipes stay silent. Step
  banners grow wizard icons — 📋 pick / 📍 locate / 🚀 confirm — to make
  the flow scannable at a glance.
- **Per-row status icons in the project picker**, rendered via
  questionary's FormattedText (prompt_toolkit per-segment styling):
  - 🟢 `active` — cwd resolved + folder exists + sessions ≥ 1 (green,
    bold if sessions ≥ 10)
  - 🔴 `orphan` — cwd resolved but the folder no longer exists on disk
    (bold red); the primary migration candidate and the key signal this
    release adds
  - ⚪ `empty` — cwd resolved + folder exists + 0 sessions (fully dimmed)
  - ❓ `unknown` — cwd unparseable from jsonl (yellow path, dim count)
- **Legend bar** below the keyboard help line so first-time users can
  decode the icons without guessing.
- **Orphan detection** in `discover_projects`: each resolved cwd gets a
  `Path(cwd).exists()` check, and the result is appended to the return
  tuple. Answers the "which projects *actually* need migrating?"
  question at a glance — previously every resolved row looked identical.
- **Sort-rank rework** — precedence is now
  `active > orphan > empty > unknown`. The user's daily-driver projects
  stay at the top of the list, orphans sit just below (visible but not
  crowding the head), empty shells and unparseable entries sink. Within
  each rank, entries remain sorted case-insensitively by cwd.
- New runtime dependency: `pyfiglet>=1.0` (banner generation).
- 18 new pytest cases (178 total): `_choice_title` dispatch across the
  four status branches, `_show_banner` TTY gating, `_gradient_hex` RGB
  interpolation + clamp behavior, orphan detection in `discover_projects`,
  rank-based sort precedence (active ahead of orphan regardless of
  folder-name alphabet).

### Changed

- `discover_projects` return tuple widens from `(folder, cwd, sessions)`
  to `(folder, cwd, sessions, cwd_exists)`. Internal consumer
  (`pick_project`) was updated in the same commit; any external caller
  unpacking the 3-tuple needs a trivial fix.
- `_choice_title` signature gains `cwd_exists: bool` so the title
  builder can dispatch the 🔴 orphan branch without doing filesystem IO
  inside a render function.

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

[Unreleased]: https://github.com/xPeiPeix/claude-repath/compare/v0.9.2...HEAD
[0.9.2]: https://github.com/xPeiPeix/claude-repath/compare/v0.9.1...v0.9.2
[0.9.1]: https://github.com/xPeiPeix/claude-repath/compare/v0.9.0...v0.9.1
[0.9.0]: https://github.com/xPeiPeix/claude-repath/compare/v0.8.2...v0.9.0
[0.8.2]: https://github.com/xPeiPeix/claude-repath/compare/v0.8.1...v0.8.2
[0.8.1]: https://github.com/xPeiPeix/claude-repath/compare/v0.8.0...v0.8.1
[0.8.0]: https://github.com/xPeiPeix/claude-repath/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/xPeiPeix/claude-repath/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/xPeiPeix/claude-repath/compare/v0.5.2...v0.6.0
[0.5.2]: https://github.com/xPeiPeix/claude-repath/compare/v0.5.1...v0.5.2
[0.5.1]: https://github.com/xPeiPeix/claude-repath/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/xPeiPeix/claude-repath/compare/v0.4.2...v0.5.0
[0.4.2]: https://github.com/xPeiPeix/claude-repath/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/xPeiPeix/claude-repath/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/xPeiPeix/claude-repath/compare/v0.3.2...v0.4.0
[0.3.2]: https://github.com/xPeiPeix/claude-repath/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/xPeiPeix/claude-repath/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/xPeiPeix/claude-repath/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/xPeiPeix/claude-repath/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/xPeiPeix/claude-repath/releases/tag/v0.1.0
