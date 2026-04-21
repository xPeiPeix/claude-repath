"""Pre-flight check for processes holding resources in a project directory.

Before moving or rewiring a project, we scan running processes for any that
have a ``cwd`` inside the target path or any open file under it. On Windows
in particular these locks cause ``shutil.move`` to fail mid-migration with
``WinError 32``, leaving a half-migrated state; better to hard-refuse before
touching anything.

Uses ``psutil`` for cross-platform access. Results are best-effort: processes
inaccessible due to permissions or already-exited are silently skipped
rather than raising.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import psutil


@dataclass(frozen=True)
class LockEntry:
    """A single process holding a resource under the target path."""

    pid: int
    name: str
    reason: str


def find_locks_on_path(path: Path) -> list[LockEntry]:
    """Return processes with a ``cwd`` or open file under ``path``.

    Each process contributes at most one entry (the first reason found).
    Caller should display these to the user and either abort or proceed
    with ``--force`` depending on UX preference.

    Returns an empty list if ``path`` does not exist — there's nothing to
    lock, so nothing to report.
    """
    if not path.exists():
        return []
    try:
        target = path.resolve()
    except OSError:
        return []
    entries: list[LockEntry] = []
    for proc in psutil.process_iter(attrs=["pid", "name"]):
        entry = _inspect_process(proc, target)
        if entry is not None:
            entries.append(entry)
    return entries


def _inspect_process(proc: psutil.Process, target: Path) -> LockEntry | None:
    """Return a ``LockEntry`` if ``proc`` holds anything under ``target``."""
    try:
        info = proc.info
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None
    pid = info.get("pid")
    name = info.get("name") or "?"

    # 1) cwd check — the most common lock source on Windows (shell cd'd in)
    try:
        cwd = proc.cwd()
    except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
        cwd = None
    if cwd:
        try:
            cwd_resolved = Path(cwd).resolve()
        except OSError:
            cwd_resolved = None
        if cwd_resolved and _is_subpath(cwd_resolved, target):
            return LockEntry(pid=pid, name=name, reason=f"cwd={cwd}")

    # 2) open_files check — IDEs and editors
    try:
        open_files = proc.open_files() or []
    except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
        open_files = []
    for of in open_files:
        try:
            of_resolved = Path(of.path).resolve()
        except OSError:
            continue
        if _is_subpath(of_resolved, target):
            return LockEntry(pid=pid, name=name, reason=f"open_file={of.path}")

    return None


def _is_subpath(candidate: Path, root: Path) -> bool:
    """``True`` if ``candidate`` equals or lives under ``root``."""
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def format_lock_report(entries: list[LockEntry]) -> str:
    """Render lock entries as a multi-line string for CLI display."""
    if not entries:
        return ""
    lines = [f"  • PID {e.pid:<8} {e.name:<30} {e.reason}" for e in entries]
    return "\n".join(lines)
