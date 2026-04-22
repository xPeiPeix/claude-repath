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
import sys
from pathlib import Path

import pyfiglet
import questionary
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import __version__
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


def _choice_title(cwd: str, sessions: int, cwd_exists: bool) -> list[tuple[str, str]]:
    """Build a prompt_toolkit FormattedText title for one picker entry.

    Returns a list of ``(style, text)`` tuples. ``style`` uses prompt_toolkit
    syntax (``fg:ansigreen``, ``fg:ansibrightblack bold``, ...), not rich
    markup — questionary passes the list straight to prompt_toolkit.

    Dispatch (unknown wins over orphan so unparseable rows stay ❓, not 🔴):
        * ``<unknown: ...>`` placeholder → ❓ yellow cwd, dim count
        * resolved cwd + folder missing   → 🔴 red cwd + bold red count
        * resolved cwd + 0 sessions       → ⚪ fully dimmed row
        * resolved cwd + sessions ≥ 1     → 🟢 + green count (bold if ≥ 10)
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
    return [
        ("", f"{icon}  "),
        (cwd_style, cwd),
        ("", "  ["),
        (session_style, session_label),
        ("", "]"),
    ]


def pick_project(projects_dir: Path) -> str | None:
    """Step 1/3: show project list, return chosen project's cwd or ``None``."""
    _step_banner(1, "Pick a project to migrate")
    entries = discover_projects(projects_dir)
    if not entries:
        _notify(f"No projects found under {projects_dir}")
        return None
    choices = [
        questionary.Choice(title=_choice_title(cwd, n, exists), value=cwd)
        for _folder, cwd, n, exists in entries
    ]
    _help_bar([("↑↓", "navigate"), ("Enter", "select"), ("Ctrl+C", "cancel")])
    _legend_bar()
    return questionary.select(
        "Which project do you want to relocate?",
        choices=choices,
    ).ask()


def prompt_new_path(old_path: str) -> str | None:
    """Step 2/3: two-stage input — parent directory + project name.

    Returns a normalized absolute path as a string, or ``None`` if cancelled.
    Path normalization (separators, ~ expansion) is done via ``pathlib.Path``;
    the resulting string uses the host OS's native separator.
    """
    _step_banner(
        2,
        "Choose the new location",
        subtitle=f"Moving from:  {old_path}",
    )
    _help_bar([("Tab", "complete"), ("Enter", "next"), ("Ctrl+C", "cancel")])

    old = Path(old_path)
    default_parent = str(old.parent)
    default_name = old.name

    parent_input = questionary.path(
        "New parent directory:",
        default=default_parent,
        only_directories=True,
    ).ask()
    if parent_input is None or not parent_input.strip():
        return None

    parent = Path(parent_input).expanduser()

    name_input = questionary.text(
        "New project name:",
        default=default_name,
    ).ask()
    if name_input is None or not name_input.strip():
        return None
    name = name_input.strip()

    new_path_abs = parent / name

    if not parent.exists():
        create = questionary.confirm(
            f"Parent directory does not exist:\n  {parent}\nCreate it on apply?",
            default=True,
        ).ask()
        if not create:
            return None

    return str(new_path_abs)


def confirm(message: str, default: bool = False) -> bool:
    answer = questionary.confirm(message, default=default).ask()
    return bool(answer)


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
    """Full interactive flow: pick project → choose location → preview → confirm.

    Returns ``(old_path, new_path)`` when the user confirms, or ``None`` if
    they cancel anywhere. The preview in Step 3 calls ``plan_migration``
    internally, so ``cli.py`` should skip re-printing the plan for TUI
    sessions.
    """
    _show_banner()
    old = pick_project(projects_dir)
    if not old:
        return None

    new = prompt_new_path(old)
    if not new:
        return None
    if new == old:
        _notify("New path is identical to old — nothing to migrate.")
        return None

    _step_banner(3, "Review & confirm")
    ctx = MigrationContext(old_path=old, new_path=new, scope=scope)
    try:
        plan = plan_migration(ctx)
    except Exception as exc:
        _notify(f"Planning failed: {exc}")
        return None
    _print_preview(old, new, plan)
    _help_bar([("Y", "proceed"), ("N", "cancel")])

    if not confirm("Proceed with migration?", default=True):
        return None
    return old, new
