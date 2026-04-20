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

import questionary
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .layers.base import MigrationContext
from .migrate import PlanReport, plan_migration

_console = Console(stderr=True)
STEPS_TOTAL = 3


def discover_projects(projects_dir: Path) -> list[tuple[Path, str, int]]:
    """Return ``[(folder, resolved_cwd, session_count), ...]`` for top-level projects.

    Worktree-derived folders (``...--claude-worktrees-...``) are excluded
    because they're migrated automatically with their parent project.
    """
    if not projects_dir.is_dir():
        return []
    out: list[tuple[Path, str, int]] = []
    for sub in sorted(projects_dir.iterdir()):
        if not sub.is_dir():
            continue
        if "--claude-worktrees-" in sub.name:
            continue
        cwd = _extract_cwd_from_sessions(sub)
        if cwd is None:
            cwd = f"<unknown: {sub.name}>"
        sessions = sum(1 for _ in sub.glob("*.jsonl"))
        out.append((sub, cwd, sessions))
    return out


def _extract_cwd_from_sessions(project_dir: Path) -> str | None:
    """Read a representative cwd value from one of the project's jsonl files."""
    jsonls = sorted(project_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    for jsonl in jsonls:
        try:
            with jsonl.open("r", encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    cwd = _find_cwd(obj)
                    if cwd:
                        return cwd
                    break
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


def _step_banner(step: int, title: str, subtitle: str | None = None) -> None:
    body = f"[bold]{title}[/bold]"
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


def pick_project(projects_dir: Path) -> str | None:
    """Step 1/3: show project list, return chosen project's cwd or ``None``."""
    _step_banner(1, "Pick a project to migrate")
    entries = discover_projects(projects_dir)
    if not entries:
        _notify(f"No projects found under {projects_dir}")
        return None
    choices = [
        questionary.Choice(
            title=f"{cwd}  [{n} session{'s' if n != 1 else ''}]",
            value=cwd,
        )
        for _folder, cwd, n in entries
    ]
    _help_bar([("↑↓", "navigate"), ("Enter", "select"), ("Ctrl+C", "cancel")])
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
