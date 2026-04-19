"""Interactive TUI for picking projects to migrate (questionary-based).

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
            # Fall back: show encoded name so user can still pick & edit.
            cwd = f"<unknown: {sub.name}>"
        sessions = sum(1 for _ in sub.glob("*.jsonl"))
        out.append((sub, cwd, sessions))
    return out


def _extract_cwd_from_sessions(project_dir: Path) -> str | None:
    """Read a representative cwd value from one of the project's jsonl files.

    Tries newest files first so renamed paths aren't resurrected. Returns
    ``None`` if no readable cwd was found.
    """
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


def pick_project(projects_dir: Path) -> str | None:
    """Interactive: show project list, return chosen project's cwd or ``None``."""
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
    return questionary.select(
        "Which project do you want to relocate?",
        choices=choices,
    ).ask()


def prompt_new_path(default: str = "") -> str | None:
    """Ask for the new absolute path; returns None if cancelled."""
    return questionary.text(
        "New absolute path:",
        default=default,
    ).ask()


def confirm(message: str, default: bool = False) -> bool:
    answer = questionary.confirm(message, default=default).ask()
    return bool(answer)


def run_interactive_move(projects_dir: Path) -> tuple[str, str] | None:
    """Full interactive flow: pick old project, enter new path, confirm.

    Returns ``(old_path, new_path)`` or ``None`` if the user cancels anywhere.
    """
    old = pick_project(projects_dir)
    if not old:
        return None
    new = prompt_new_path(default=old)
    if not new:
        return None
    if new == old:
        _notify("New path is identical to old — nothing to migrate.")
        return None
    if not confirm(f"Migrate\n  {old}\n→ {new}\n?", default=True):
        return None
    return old, new
