"""Interactive TUI for picking projects to migrate (questionary + rich).

v0.3 presents a three-step wizard:
    Step 1/3  Pick a project
    Step 2/3  Choose the new location (two-stage: parent + name)
    Step 3/3  Review preview & confirm

Because Claude Code's folder-name encoding is lossy (every non-alphanumeric
character collapses to ``-``), we can't deterministically reverse an encoded
folder name back to its absolute path. Instead we extract the authoritative
``cwd`` value from the project's own session ``.jsonl`` files — that's the
real absolute path the project was opened at, captured at runtime.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pyfiglet
import questionary
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import __version__
from .backup import MANIFEST_NAME, list_backups
from .layers.base import MigrationContext
from .migrate import PlanReport, plan_migration

_console = Console(stderr=True)
STEPS_TOTAL = 3

# Claude Code jsonl files start with a session-metadata line
# (type/permissionMode/sessionId) with no cwd; cwd appears on the first
# user/assistant message line. 50 is a defensive upper bound — in practice
# cwd is on line 2-3.
_MAX_LINES_PER_JSONL = 50

# Wizard-step icons — clipboard (pick) → pin (locate) → rocket (go).
_STEP_ICONS = {1: "📋", 2: "📍", 3: "🚀"}

# Project-status icons for the Step-1 menu. Emoji are self-colored so the
# legend and list stay readable on both light and dark terminal themes.
_ICON_ACTIVE = "🟢"
_ICON_ORPHAN = "🔴"
_ICON_EMPTY = "⚪"
_ICON_UNKNOWN = "❓"

# Navigation sentinel returned by step functions to request "go back one
# step" — distinct from ``None``, which still means "cancel the whole flow".
_BACK = "__back__"


class _EscBackError(Exception):
    """Raised from a prompt key binding when the user presses Esc.

    Caught by :func:`_ask_with_back` and translated into the :data:`_BACK`
    sentinel so step functions treat Esc as a keyboard shortcut for their
    menu's "Back" option — cross-platform by way of prompt_toolkit's
    Esc-key recognition.
    """


def _esc_back_kb():
    """``KeyBindings`` that raise :class:`_EscBackError` on a single Esc press.

    ``eager=True`` bypasses prompt_toolkit's escape-timeout (500 ms default
    wait for a possible Alt-<key> combo). The TUI doesn't use any Alt-<key>
    shortcuts, so the trade is: instant Esc response for losing Alt combos.
    """
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys

    kb = KeyBindings()

    @kb.add(Keys.Escape, eager=True)
    def _on_escape(event):
        event.app.exit(exception=_EscBackError())

    return kb


def _attach_esc_back(question):
    """Merge an Esc-binds-to-_EscBackError handler onto ``question``'s existing bindings.

    Why not ``questionary.xxx(key_bindings=_esc_back_kb())``: ``questionary.path``
    and ``questionary.text`` already pass their own ``key_bindings`` arg into
    ``PromptSession(...)``, so adding another via the user-facing kwargs
    raises ``TypeError: multiple values for keyword argument 'key_bindings'``.
    Instead we reach into the constructed Question, fetch its Application's
    ``key_bindings``, and merge our Esc handler on top.

    Stubs in tests (non-Question objects) are silently left untouched — the
    function returns the original ``question`` in both cases so callers can
    chain it into ``_ask_with_back``.
    """
    from prompt_toolkit.key_binding import merge_key_bindings

    app = getattr(question, "application", None)
    if app is None:
        return question  # test stub without a real prompt_toolkit Application
    existing = app.key_bindings
    app.key_bindings = merge_key_bindings([existing, _esc_back_kb()])
    # Collapse prompt_toolkit's escape-timeout so a single Esc press fires
    # immediately instead of waiting ~500 ms. Two separate timers to
    # zero-out: ``timeoutlen`` gates multi-key bindings (e.g. Ctrl-X Ctrl-S)
    # waiting for a second key; ``ttimeoutlen`` gates terminal-level
    # escape-sequence detection (Esc alone vs Esc-[-A arrow keys). The
    # v0.8.1 fix only lowered ``timeoutlen``, leaving the user with a
    # ~1 s Esc latency driven by the terminal-timer. Setting ``ttimeoutlen``
    # to 0.01 s collapses that path too. Cost: we can't synthesize
    # Alt-<key> combos, which this TUI doesn't use.
    try:
        app.timeoutlen = 0.0
    except AttributeError:
        pass  # older prompt_toolkit without the attribute — still usable
    try:
        app.ttimeoutlen = 0.01
    except AttributeError:
        pass
    return question


def _ask_with_back(question):
    """Run a questionary prompt; translate Esc → :data:`_BACK`, Ctrl+C → ``None``.

    Automatically attaches the Esc handler via :func:`_attach_esc_back` so
    callers don't need to remember to wire it themselves. Uses ``unsafe_ask``
    rather than ``ask`` so questionary's default ``KeyboardInterrupt``
    swallowing doesn't hide :class:`_EscBackError` alongside it.
    """
    _attach_esc_back(question)
    try:
        return question.unsafe_ask()
    except _EscBackError:
        return _BACK
    except KeyboardInterrupt:
        return None

# Status keys (in display order for the Step-1a filter menu), paired with
# the rank numbers emitted by ``_status_rank``. Centralized so the filter
# menu / bucket dict / icon lookup share one source of truth.
_STATUS_KEYS = ("active", "orphan", "empty", "unknown")
_STATUS_RANK_MAP = {0: "active", 1: "orphan", 2: "empty", 3: "unknown"}
_STATUS_ICON_MAP = {
    "active": _ICON_ACTIVE,
    "orphan": _ICON_ORPHAN,
    "empty": _ICON_EMPTY,
    "unknown": _ICON_UNKNOWN,
}


def discover_projects(projects_dir: Path) -> list[tuple[Path, str, int, bool]]:
    """Return ``[(folder, resolved_cwd, session_count, cwd_exists), ...]``.

    ``cwd_exists`` checks whether the resolved cwd still points at a real
    directory on disk. Combined with ``session_count``, this classifies each
    row into one of four visual states the picker renders:

    =========  ============================================================
    rank 0  🟢 active — cwd resolved, folder exists, sessions ≥ 1 (top)
    rank 1  🔴 orphan — cwd resolved but folder gone (migration candidate)
    rank 2  ⚪ empty  — cwd resolved, folder exists, sessions = 0
    rank 3  ❓ unknown — cwd unparseable from jsonl
    =========  ============================================================

    Worktree-derived folders (``...--claude-worktrees-...``) are excluded
    because they're migrated automatically with their parent project.

    For unresolved (``<unknown: ...>``) entries the ``cwd_exists`` flag is
    irrelevant to sorting — we keep it ``True`` so ``unknown`` never falls
    through the orphan branch in ``_choice_title``.
    """
    if not projects_dir.is_dir():
        return []
    out: list[tuple[Path, str, int, bool]] = []
    for sub in sorted(projects_dir.iterdir()):
        if not sub.is_dir():
            continue
        if "--claude-worktrees-" in sub.name:
            continue
        cwd = _extract_cwd_from_sessions(sub)
        if cwd is None:
            cwd = f"<unknown: {sub.name}>"
            cwd_exists = True  # placeholder — skip orphan rank
        else:
            try:
                cwd_exists = Path(cwd).exists()
            except OSError:
                # Exotic path strings (long UNCs, reserved devices) can raise
                # on ``.exists()``; treat as still-present rather than orphan
                # to avoid false-positive migration nags.
                cwd_exists = True
        sessions = sum(1 for _ in sub.glob("*.jsonl"))
        out.append((sub, cwd, sessions, cwd_exists))
    out.sort(key=lambda t: (_status_rank(t[1], t[2], t[3]), t[1].lower()))
    return out


def _status_rank(cwd: str, sessions: int, cwd_exists: bool) -> int:
    """Sort priority: active < orphan < empty < unknown (lower = higher in list).

    Active projects float to the top since they're what the user actually
    works in day-to-day; orphans are a secondary migration candidate and
    sit just below so they're still visible without drowning the list head.
    """
    if cwd.startswith("<unknown"):
        return 3
    if not cwd_exists:
        return 1  # orphan
    if sessions == 0:
        return 2  # empty
    return 0  # active


def _group_by_status(
    entries: list[tuple[Path, str, int, bool]],
) -> dict[str, list[tuple[Path, str, int, bool]]]:
    """Bucket ``discover_projects`` output by visible status.

    All four keys are always present (empty list when a bucket has no
    entries) so callers don't need to handle ``KeyError``.
    """
    buckets: dict[str, list[tuple[Path, str, int, bool]]] = {
        k: [] for k in _STATUS_KEYS
    }
    for entry in entries:
        _folder, cwd, sessions, cwd_exists = entry
        rank = _status_rank(cwd, sessions, cwd_exists)
        buckets[_STATUS_RANK_MAP[rank]].append(entry)
    return buckets


def _pick_status_filter(
    buckets: dict[str, list[tuple[Path, str, int, bool]]],
) -> str | None:
    """Step 1a: ask which status bucket to show (or ``all``) before listing.

    Returns the chosen key (``"all"`` / ``"active"`` / ``"orphan"`` /
    ``"empty"`` / ``"unknown"``), or ``None`` when the user cancels.

    The initial cursor lands on ``"active"`` when that bucket is non-empty
    — the common "find the project I work in daily" case. Empty buckets
    are hidden from the menu so users never see "empty (0)".
    """
    total = sum(len(v) for v in buckets.values())
    choices: list[questionary.Choice] = [
        questionary.Choice(title=f"📋  all  ({total})", value="all"),
    ]
    for key in _STATUS_KEYS:
        count = len(buckets[key])
        if count == 0:
            continue
        choices.append(
            questionary.Choice(
                title=f"{_STATUS_ICON_MAP[key]}  {key}  ({count})", value=key
            )
        )

    default_value = "active" if buckets["active"] else "all"
    default_choice = next(
        (c for c in choices if c.value == default_value), choices[0]
    )
    question = questionary.select(
        "Filter by status:",
        choices=choices,
        default=default_choice,
    )
    result = _ask_with_back(question)
    # Step 1a has no previous step, so Esc / empty-submit / Ctrl+C all
    # collapse to "cancel". Also guards against an odd empty-string return
    # some questionary versions emit on Esc, which would otherwise crash
    # with KeyError when used as a bucket key downstream.
    if result == _BACK or not result:
        return None
    return result


def _ask_action(prompt: str, choices: list[tuple[str, str]]) -> str | None:
    """Present a ``(label, value)`` action menu and return the chosen value.

    Wraps ``questionary.select`` with Esc-aware key bindings. Returns:
        * A value from ``choices`` → user made a pick
        * :data:`_BACK` → user pressed Esc (equivalent to the menu's Back item)
        * ``None`` → user pressed Ctrl+C

    Callers that already have a dedicated "back" choice in ``choices``
    should treat the returned value and :data:`_BACK` identically.
    """
    qs_choices = [questionary.Choice(title=t, value=v) for t, v in choices]
    question = questionary.select(prompt, choices=qs_choices)
    return _ask_with_back(question)


def _extract_cwd_from_sessions(project_dir: Path) -> str | None:
    """Read a representative cwd value from one of the project's jsonl files.

    Real Claude Code sessions put cwd on the first user/assistant message,
    not the opening session-metadata line — so we scan up to
    ``_MAX_LINES_PER_JSONL`` lines per file before moving on.
    """
    jsonls = sorted(project_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    for jsonl in jsonls:
        try:
            with jsonl.open("r", encoding="utf-8") as fh:
                for i, line in enumerate(fh):
                    if i >= _MAX_LINES_PER_JSONL:
                        break
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    cwd = _find_cwd(obj)
                    if cwd:
                        return cwd
        except OSError:
            continue
    return None


def _find_cwd(obj: object, max_depth: int = 3) -> str | None:
    """Recursively search ``obj`` for a string-valued ``cwd`` field."""
    if max_depth < 0:
        return None
    if isinstance(obj, dict):
        cwd = obj.get("cwd")
        if isinstance(cwd, str) and cwd:
            return cwd
        for v in obj.values():
            found = _find_cwd(v, max_depth - 1)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_cwd(item, max_depth - 1)
            if found:
                return found
    return None


def _notify(message: str) -> None:
    """Emit a status message that works in both TTY and non-TTY contexts."""
    print(message, file=sys.stderr)


# Win32 console mode flag — bit 0x0004 enables interpretation of ANSI escape
# sequences on the attached console handle. Win10 1903+ enables it by default
# for new conhost windows; older Windows doesn't.
_ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
_STD_ERROR_HANDLE = -12


def _windows_stderr_vt_enabled() -> bool:
    """Check whether stderr's Windows console handle has VT processing on.

    Returns ``False`` on any failure (closed handle, not a real console,
    ``GetConsoleMode`` rejection) so callers treat "unknown" as "unsafe to
    emit raw ANSI." Pseudo-terminals like mintty / Git Bash don't route
    through the conhost API at all, so this returns ``False`` for them —
    the env-var fast-path in :func:`_erase_prev_lines` covers that case
    separately.
    """
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(_STD_ERROR_HANDLE)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(mode.value & _ENABLE_VIRTUAL_TERMINAL_PROCESSING)
    except (OSError, AttributeError, ImportError):
        return False


def _erase_prev_lines(n: int) -> None:
    """Erase the last ``n`` printed lines (cursor-up + erase-to-EOL).

    Questionary finalizes each prompt with a persistent transcript row
    (``? New parent directory: D:\\dev_code``). That's useful on the forward
    path but stacks up visually when the user reverses direction — pressing
    Esc at the name prompt would otherwise leave every prior attempt sitting
    in scrollback (parent + name × N). Emitting this sequence before the next
    loop iteration lets questionary's next prompt overwrite the same rows
    in place.

    Writes to **stderr**, not stdout: questionary / prompt_toolkit route
    their prompt UI to stderr by default (``create_output()`` picks stderr
    when it's a TTY), so the cursor-up targets the same rows questionary
    just advanced. Writing to stdout would corrupt the spinner / stage
    markers whenever stderr is redirected (``... 2>log.txt``), leaving the
    stdout stream's last bytes silently eaten by the escape codes.

    Silent when stderr isn't a TTY (tests, pipes) — bare ANSI control bytes
    leaking into captured output would pollute test assertions and piped
    logs. On Windows, additionally gates on VT processing being enabled
    for the stderr console handle (or a known modern terminal via
    ``WT_SESSION`` / ``TERM_PROGRAM`` / ``TERM``) — legacy ``cmd.exe``
    reports ``isatty() == True`` but renders raw ANSI as literal
    ``?[F?[2K`` garbage.
    """
    if not sys.stderr.isatty():
        return
    if sys.platform == "win32":
        # Order matters: env-var hints are checked first because mintty /
        # Git Bash pseudo-terminals don't route through conhost — their
        # ``GetConsoleMode`` returns 0 (failure) and ``_windows_stderr_vt_
        # enabled()`` reports False even though they render ANSI fine.
        # ``TERM`` rejects ``dumb`` / ``unknown`` explicitly so a user who
        # opted out of ANSI rendering doesn't see literal ``?[F?[2K``.
        term = os.environ.get("TERM")
        modern_terminal = (
            os.environ.get("WT_SESSION")
            or os.environ.get("TERM_PROGRAM")
            or (term and term not in ("dumb", "unknown"))
        )
        if not modern_terminal and not _windows_stderr_vt_enabled():
            return
    for _ in range(n):
        sys.stderr.write("\x1b[F\x1b[2K")
    sys.stderr.flush()


# Banner gradient: top-to-bottom white → dark gray. Produces a clean
# monochrome 3D-lit look that reads as sculpted block type (like skills.sh).
# Rich has no native gradient, so we interpolate RGB per line and emit each
# with a truecolor hex style. Modern terminals (Windows Terminal / iTerm2 /
# GNOME Terminal / Warp) render truecolor fine.
_BANNER_GRADIENT_START = (0xF0, 0xF0, 0xF0)  # near-white
_BANNER_GRADIENT_END = (0x40, 0x40, 0x40)  # dark gray


def _gradient_hex(t: float) -> str:
    """Linear-interpolate banner gradient at parameter ``t`` ∈ [0, 1]."""
    t = max(0.0, min(1.0, t))
    r = round(_BANNER_GRADIENT_START[0] + (_BANNER_GRADIENT_END[0] - _BANNER_GRADIENT_START[0]) * t)
    g = round(_BANNER_GRADIENT_START[1] + (_BANNER_GRADIENT_END[1] - _BANNER_GRADIENT_START[1]) * t)
    b = round(_BANNER_GRADIENT_START[2] + (_BANNER_GRADIENT_END[2] - _BANNER_GRADIENT_START[2]) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def _show_banner() -> None:
    """Render the REPATH splash on TUI entry.

    Skipped when stderr isn't a TTY (pytest capture, pipes) — the ASCII art
    is ~7×50 chars and would bloat non-interactive logs. Uses the
    ``ansi_shadow`` figlet font with a per-line cyan→pink truecolor gradient.
    """
    if not sys.stderr.isatty():
        return
    art = pyfiglet.figlet_format("REPATH", font="ansi_shadow").rstrip("\n")
    lines = art.split("\n")
    steps = max(1, len(lines) - 1)
    for i, line in enumerate(lines):
        _console.print(line, style=f"bold {_gradient_hex(i / steps)}", highlight=False)
    _console.print(
        f"[dim]Rewire Claude Code state when your project folder moves  "
        f"[cyan]v{__version__}[/cyan][/dim]"
    )
    _console.print()


def _step_banner(step: int, title: str, subtitle: str | None = None) -> None:
    # Blank line before every banner after Step 1 so consecutive panels
    # (e.g. the tail of Step 2's path-preview flowing into Step 3's
    # Review & confirm header) don't glue together. Step 1 already has
    # the REPATH splash above it, so the extra gap would look odd there.
    if step > 1:
        _console.print()
    icon = _STEP_ICONS.get(step, "")
    heading = f"{icon}  {title}" if icon else title
    body = f"[bold]{heading}[/bold]"
    if subtitle:
        body += f"\n[dim]{subtitle}[/dim]"
    _console.print(
        Panel(
            body,
            title=f"[cyan]Step {step}/{STEPS_TOTAL}[/cyan]",
            border_style="cyan",
            expand=False,
        )
    )


def _help_bar(keys: list[tuple[str, str]]) -> None:
    parts = [f"[bold cyan]{k}[/bold cyan] {d}" for k, d in keys]
    _console.print("   " + "   ".join(parts), style="dim")


def _legend_bar() -> None:
    """Render a short legend explaining the status icons used in the picker."""
    _console.print(
        f"   {_ICON_ACTIVE} [green]active[/green]"
        f"   {_ICON_ORPHAN} [red]orphan[/red]"
        f"   {_ICON_EMPTY} [dim]empty[/dim]"
        f"   {_ICON_UNKNOWN} [yellow]unknown[/yellow]"
    )


def _choice_title(
    cwd: str,
    sessions: int,
    cwd_exists: bool,
    *,
    conflict_folder: str | None = None,
) -> list[tuple[str, str]]:
    """Build a prompt_toolkit FormattedText title for one picker entry.

    Returns a list of ``(style, text)`` tuples. ``style`` uses prompt_toolkit
    syntax (``fg:ansigreen``, ``fg:ansibrightblack bold``, ...), not rich
    markup — questionary passes the list straight to prompt_toolkit.

    Dispatch (unknown wins over orphan so unparseable rows stay ❓, not 🔴):
        * ``<unknown: ...>`` placeholder → ❓ yellow cwd, dim count
        * resolved cwd + folder missing   → 🔴 red cwd + bold red count
        * resolved cwd + 0 sessions       → ⚪ fully dimmed row
        * resolved cwd + sessions ≥ 1     → 🟢 + green count (bold if ≥ 10)

    When ``conflict_folder`` is provided, a dim-yellow ``⚠ from: <folder>``
    segment is appended. ``pick_project`` sets this only for entries whose
    cwd value collides with another row in the same filtered view — usually
    one project folder name encodes the cwd (e.g. ``D--dev-code-x``) while
    another was recorded under a different startup cwd (e.g. ``-mnt-d-...``
    from a WSL-launched session). Two rows showing the same path is
    otherwise indistinguishable; the suffix tells the user which
    ``~/.claude/projects/<folder>/`` directory each one lives in.
    """
    is_unknown = cwd.startswith("<unknown")
    if is_unknown:
        icon = _ICON_UNKNOWN
        cwd_style = "fg:ansiyellow"
        session_style = "fg:ansibrightblack"
    elif not cwd_exists:
        icon = _ICON_ORPHAN
        cwd_style = "fg:ansired"
        session_style = "fg:ansired bold"
    elif sessions == 0:
        icon = _ICON_EMPTY
        cwd_style = "fg:ansibrightblack"
        session_style = "fg:ansibrightblack"
    else:
        icon = _ICON_ACTIVE
        cwd_style = ""
        session_style = "fg:ansigreen bold" if sessions >= 10 else "fg:ansigreen"

    session_label = f"{sessions} session{'s' if sessions != 1 else ''}"
    segments: list[tuple[str, str]] = [
        ("", f"{icon}  "),
        (cwd_style, cwd),
        ("", "  ["),
        (session_style, session_label),
        ("", "]"),
    ]
    if conflict_folder is not None:
        segments.append(("fg:ansiyellow", f"  ⚠ from: {conflict_folder}"))
    return segments


def pick_project(
    projects_dir: Path,
    *,
    wizard_step: int | None = 1,
    title: str = "Pick a project to migrate",
    prompt: str = "Which project do you want to relocate?",
    exclude_unknown: bool = False,
) -> str | None:
    """Two-stage pick — select a status bucket, then a project.

    Step 1a shows a compact menu counting each status bucket
    (active / orphan / empty / unknown / all). The cursor defaults to
    ``active`` when non-empty, the common daily-use case. Step 1b then
    lists only projects from the chosen bucket, so users with hundreds of
    projects don't have to page through everything to find one type.

    Pressing Esc inside Step 1b jumps back to Step 1a — useful when the
    user realizes they picked the wrong status bucket and wants to widen
    or switch categories without Ctrl+C-ing out of the flow.

    ``wizard_step`` controls the optional Rich step-banner header.
    Passing ``None`` (used by ``doctor`` and other one-shot flows that
    aren't multi-step wizards) suppresses the banner; ``move``'s wizard
    still defaults to step 1. ``title`` lets non-move callers retitle the
    prompt without forking the picker.

    ``exclude_unknown`` filters out ``<unknown: ...>`` placeholder rows
    (rows whose cwd could not be parsed from any session ``.jsonl``).
    ``move`` keeps them visible by default so users can spot encoded
    folders that lost their cwd; ``doctor`` sets this to ``True`` because
    feeding the placeholder string back into ``MigrationContext`` as if
    it were a real path produces nonsensical diagnostics.

    Returns the selected project's cwd, or ``None`` on cancel.
    """
    if wizard_step is not None:
        _step_banner(wizard_step, title)
    entries = discover_projects(projects_dir)
    if exclude_unknown:
        entries = [e for e in entries if not e[1].startswith("<unknown")]
    if not entries:
        _notify(f"No projects found under {projects_dir}")
        return None

    buckets = _group_by_status(entries)
    _help_bar([("↑↓", "navigate"), ("Enter", "select"), ("Ctrl+C", "cancel")])
    _legend_bar()

    while True:
        filter_key = _pick_status_filter(buckets)
        if filter_key is None:
            return None

        filtered = entries if filter_key == "all" else buckets[filter_key]
        if not filtered:
            _notify(f"No '{filter_key}' projects to pick.")
            continue

        # Flag cwd collisions within the currently-visible bucket so the
        # user can tell which ``~/.claude/projects/<folder>/`` each row
        # came from. Happens when the same logical directory was launched
        # from two different startup cwds (classic case: a WSL session
        # with ``/mnt/d/...`` alongside a native ``D:\...`` one).
        cwd_counts: dict[str, int] = {}
        for _f, cwd, _n, _e in filtered:
            cwd_counts[cwd] = cwd_counts.get(cwd, 0) + 1
        duplicated_cwds = {k for k, v in cwd_counts.items() if v > 1}

        choices = [
            questionary.Choice(
                title=_choice_title(
                    cwd,
                    n,
                    exists,
                    conflict_folder=folder.name if cwd in duplicated_cwds else None,
                ),
                value=cwd,
            )
            for folder, cwd, n, exists in filtered
        ]
        _help_bar(
            [
                ("↑↓", "navigate"),
                ("Enter", "select"),
                ("Esc", "back to filter"),
                ("Ctrl+C", "cancel"),
            ]
        )
        result = _ask_with_back(
            questionary.select(
                prompt,
                choices=choices,
            )
        )
        if result == _BACK:
            continue  # re-open the filter menu
        return result


def prompt_new_path(old_path: str) -> str | None:
    """Step 2: collect the new location, returning an absolute path.

    Returns one of three things:
        * Normalized absolute path string → caller proceeds to Step 3
        * ``None`` → user cancelled the whole flow
        * :data:`_BACK` → user asked to go back to Step 1 (re-pick project)

    The path goes straight to Step 3 once both fields are filled — prior
    versions inserted an extra "Confirm the new location?" action menu
    between Step 2 and the Migration Preview, which double-prompted the
    same decision (the Step 3 preview already offers a Yes/Edit/Back
    selector over the *same* path). v0.9.1 collapses the two into one.

    Esc bindings:
        * Esc at the parent field → return :data:`_BACK` (jumps to Step 1)
        * Esc at the name field   → loop back to re-enter parent (inner)

    The parent-does-not-exist confirm is kept inline here (not deferred
    to Step 3), so an obviously-typo parent is caught at the moment of
    entry rather than after building a full migration plan.
    """
    old = Path(old_path)
    current_parent = str(old.parent)
    current_name = old.name

    _step_banner(
        2,
        "Choose the new location",
        subtitle=f"Moving from:  {old_path}",
    )
    _help_bar(
        [
            ("Tab", "complete"),
            ("Enter", "next"),
            ("Esc", "back"),
            ("Ctrl+C", "cancel"),
        ]
    )

    while True:
        parent_input = _ask_with_back(
            questionary.path(
                "New parent directory:",
                default=current_parent,
                only_directories=True,
            )
        )
        if parent_input == _BACK:
            return _BACK  # Esc at parent → jump to Step 1
        if parent_input is None or not parent_input.strip():
            return None
        current_parent = parent_input.strip()

        name_input = _ask_with_back(
            questionary.text(
                "New project name:",
                default=current_name,
            )
        )
        if name_input == _BACK:
            # Erase the two questionary transcript rows ("parent:" answer +
            # "name:" prompt) before re-entering the loop so the next
            # iteration re-renders in place instead of stacking a growing
            # history of prior attempts.
            _erase_prev_lines(2)
            continue  # Esc at name → re-enter parent (inner loop)
        if name_input is None or not name_input.strip():
            return None
        current_name = name_input.strip()

        parent = Path(current_parent).expanduser()
        new_path_abs = parent / current_name

        _print_path_preview(old_path, str(new_path_abs))

        if not parent.exists():
            create = questionary.confirm(
                f"Parent directory does not exist:\n  {parent}\n"
                "Create it on apply?",
                default=True,
            ).ask()
            if not create:
                # Declining creation is an implicit cancel — Step 3's
                # Edit option is the path to "try a different parent"
                # without leaving the flow.
                return None
        return str(new_path_abs)


def confirm(message: str, default: bool = False) -> bool:
    answer = questionary.confirm(message, default=default).ask()
    return bool(answer)


def _print_path_preview(old: str, new: str) -> None:
    """Render a compact Source→Target panel during Step 2.

    Mirrors the layout of :func:`_print_preview` but without per-layer
    plan counts — the Step-2 user just needs to confirm the path math
    (parent + name) before we actually build a plan in Step 3.
    """
    body = (
        f"[dim]Source:[/dim]  [cyan]{old}[/cyan]\n"
        f"[dim]Target:[/dim]  [bold cyan]{new}[/bold cyan]"
    )
    _console.print(
        Panel(
            body,
            title="[bold]Path preview[/bold]",
            border_style="dim",
            expand=False,
        )
    )


def _print_preview(old: str, new: str, plan: PlanReport) -> None:
    """Render migration preview panel with per-layer change counts."""
    table = Table(show_header=False, show_lines=False, padding=(0, 1), box=None)
    table.add_column("Field", style="cyan", no_wrap=True)
    table.add_column("Value")

    table.add_row("From", old)
    table.add_row("To", new)
    table.add_row("", "")

    for name, lines in plan.entries:
        real = [ln for ln in lines if not ln.startswith(("[skip]", "[noop]"))]
        if not real:
            table.add_row(name, "[dim]no changes[/dim]")
        else:
            table.add_row(name, f"{len(real)} action(s)")

    _console.print(
        Panel(
            table,
            title="[bold]Migration Preview[/bold]",
            subtitle=f"[dim]total: {plan.total_actions} actions[/dim]",
            border_style="cyan",
            expand=False,
        )
    )


def run_interactive_move(
    projects_dir: Path,
    scope: str = "narrow",
) -> tuple[str, str] | None:
    """Full interactive flow with bidirectional navigation between steps.

    Forward: Step 1 (pick) → Step 2 (new location) → Step 3 (plan & confirm).
    Backward: Step 3 action menu offers Edit (re-run Step 2) and
    Back-to-project-selection (re-run Step 1); Esc at Step 2 parent input
    jumps straight to Step 1. Confirmation happens **once**, at Step 3,
    where the user can also see the concrete per-layer action counts —
    the Step 2 "Confirm the new location?" menu was collapsed in v0.9.1
    because it double-prompted the same decision.

    Returns ``(old_path, new_path)`` on final confirm, or ``None`` when the
    user cancels anywhere.
    """
    _show_banner()

    old: str | None = None
    new: str | None = None

    while True:
        if old is None:
            old = pick_project(projects_dir)
            if old is None:
                return None

        if new is None:
            result = prompt_new_path(old)
            if result is None:
                return None
            if result == _BACK:
                old = None
                continue
            if result == old:
                _notify("New path is identical to old — nothing to migrate.")
                return None
            new = result

        _step_banner(3, "Review & confirm")
        ctx = MigrationContext(old_path=old, new_path=new, scope=scope)
        try:
            plan = plan_migration(ctx)
        except Exception as exc:
            _notify(f"Planning failed: {exc}")
            return None
        _print_preview(old, new, plan)
        _help_bar(
            [
                ("↑↓", "navigate"),
                ("Enter", "select"),
                ("Esc", "back"),
                ("Ctrl+C", "cancel"),
            ]
        )

        action = _ask_action(
            "Proceed with migration?",
            [
                ("✅  Yes, proceed", "proceed"),
                ("✏️  Edit — re-enter path (Step 2)", "edit"),
                ("⬅️  Back to project selection (Step 1)", "back_to_pick"),
                ("❌  No, cancel", "cancel"),
            ],
        )

        if action is None or action == "cancel":
            return None
        if action == "edit" or action == _BACK:
            # Edit and Esc both rewind to Step 2, keeping the picked project.
            new = None
            continue
        if action == "back_to_pick":
            # Full rewind — re-enter Step 1 and discard the new-path too.
            old = None
            new = None
            continue
        # action == "proceed"
        return old, new


def _solo_banner(title: str, subtitle: str | None = None, icon: str = "") -> None:
    """Print a one-shot banner panel without ``Step X/N`` framing.

    Used for non-wizard flows (``doctor`` / ``rollback``) where the
    multi-step header would be misleading. Mirrors :func:`_step_banner`'s
    visual language (cyan-bordered Rich Panel) so wizard and one-shot
    flows feel like the same product, just without the step number.
    """
    heading = f"{icon}  {title}" if icon else title
    body = f"[bold]{heading}[/bold]"
    if subtitle:
        body += f"\n[dim]{subtitle}[/dim]"
    _console.print(Panel(body, border_style="cyan", expand=False))


def _humanize_backup_ts(ts: str) -> str:
    """Render a backup timestamp as a human-readable date.

    Backup directories are named ``time.strftime("%Y%m%d-%H%M%S")`` by
    :func:`backup.start_backup`, with an optional ``-N`` suffix when two
    backups land in the same wall-clock second. The canonical
    ``YYYYMMDD-HHMMSS`` prefix becomes ``YYYY-MM-DD HH:MM:SS``;
    collision suffixes append as ``(#N)``. Anything that fails to match
    the expected shape (externally-created dir, future-format change) is
    returned verbatim so the picker still surfaces it.
    """
    parts = ts.split("-")
    if len(parts) >= 2 and len(parts[0]) == 8 and len(parts[1]) == 6:
        try:
            dt = datetime.strptime(f"{parts[0]}{parts[1]}", "%Y%m%d%H%M%S")
            base = dt.strftime("%Y-%m-%d %H:%M:%S")
            extras = parts[2:]
            if extras:
                return f"{base} (#{'-'.join(extras)})"
            return base
        except ValueError:
            pass
    return ts


def _read_manifest_entry_count(backup_dir: Path) -> int | None:
    """Return entry count from a backup manifest, or ``None`` on parse failure.

    All failure modes (manifest missing, non-UTF-8 bytes, malformed JSON,
    root not a JSON object, ``entries`` not a list) collapse to ``None``
    so the picker renders ``[unreadable]`` instead of crashing on a
    corrupted backup directory. The ``isinstance(data, dict)`` guard
    matters: ``json.loads`` accepts ``[]``, ``"string"``, and bare numbers
    as valid root types, and a bare ``data.get("entries")`` would raise
    ``AttributeError`` on those — aborting the entire rollback picker
    because of one bad backup. ``UnicodeDecodeError`` is a ``ValueError``
    subclass (not ``OSError``), so it must be listed explicitly.
    """
    manifest = backup_dir / MANIFEST_NAME
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    entries = data.get("entries")
    if not isinstance(entries, list):
        return None
    return len(entries)


def run_interactive_rollback(root: Path | None = None) -> str | None:
    """One-shot picker over available migration backups.

    Lists every directory under ``~/.claude/.repath-backups/`` newest-first
    (per :func:`backup.list_backups`), each annotated with a humanized
    date plus the manifest's entry count so users can tell apart a no-op
    stub from a real multi-layer migration. Returns the chosen timestamp
    string (the same value :func:`backup.rollback` accepts), or ``None``
    on cancel.

    Single-step flow — Esc and Ctrl+C both mean cancel because there is
    no previous step to rewind to.
    """
    backups = list_backups(root)
    if not backups:
        _notify("No backups found. (Run a `move` or `rewire` first.)")
        return None

    _show_banner()
    _solo_banner("Pick a backup to roll back to", icon="↩️")
    _help_bar([("↑↓", "navigate"), ("Enter", "select"), ("Ctrl+C", "cancel")])

    choices: list[questionary.Choice] = []
    for ts, path in backups:
        readable = _humanize_backup_ts(ts)
        n_entries = _read_manifest_entry_count(path)
        if n_entries is None:
            count_label = "[unreadable]"
        else:
            count_label = f"{n_entries} item{'s' if n_entries != 1 else ''}"
        title = f"📦  {readable}  [{count_label}]"
        choices.append(questionary.Choice(title=title, value=ts))

    result = _ask_with_back(
        questionary.select("Which backup?", choices=choices)
    )
    if result == _BACK or not result:
        return None
    return result


def run_interactive_doctor(projects_dir: Path) -> str | None:
    """One-shot project picker for ``doctor``.

    Reuses :func:`pick_project` but suppresses its ``Step 1/3`` wizard
    banner — doctor is a one-shot diagnostic, not a multi-step flow,
    so the wizard chrome would be misleading. A solo banner plus a
    retitled menu prompt keep the doctor context obvious.
    """
    _show_banner()
    _solo_banner("Pick a project to diagnose", icon="🩺")
    return pick_project(
        projects_dir,
        wizard_step=None,
        prompt="Which project do you want to diagnose?",
        exclude_unknown=True,
    )
