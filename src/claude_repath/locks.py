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

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import psutil


@dataclass(frozen=True)
class LockEntry:
    """A single process holding a resource under the target path."""

    pid: int
    name: str
    reason: str


def find_locks_on_paths(paths: list[Path]) -> list[LockEntry]:
    """Return processes with a ``cwd`` or open file under ANY of ``paths``.

    A single process contributes at most one entry — the first hit wins,
    checked in this order: cwd, then open_files, then path-by-path within
    each category. Non-existent paths are silently skipped (nothing to lock
    there), so this is safe to call with an unfiltered list of candidate
    paths including the source project folder, its Claude state dir, etc.

    Returns an empty list if no input path exists. This is the underlying
    implementation; most callers pass one path and should use
    :func:`find_locks_on_path` for readability.
    """
    targets: list[Path] = []
    for p in paths:
        if not p.exists():
            continue
        try:
            targets.append(p.resolve())
        except OSError:
            continue
    if not targets:
        return []

    # Snapshot processes up-front, then fan out the per-process inspection to
    # a thread pool. Windows' ``psutil.Process.open_files()`` is expensive —
    # it enumerates every handle with a per-handle type-query and a defensive
    # timeout to avoid hanging on exotic kernel objects. Serially iterating
    # 200+ processes with that cost per process pushed the pre-flight check
    # into the "looks hung" range (10-60s). These calls release the GIL on
    # every syscall, so plain threads parallelize them cleanly.
    #
    # Each Process instance is accessed from exactly one worker thread via
    # ``pool.map`` — psutil.Process has per-instance mutable state (CPU time
    # caches, oneshot context, etc.) that isn't documented thread-safe for
    # concurrent same-object access. Refactors that share a Process across
    # threads (e.g. a shared work queue) must reintroduce that guarantee.
    procs = list(psutil.process_iter(attrs=["pid", "name"]))
    max_workers = min(32, (os.cpu_count() or 4) * 4)
    pool = ThreadPoolExecutor(max_workers=max_workers)

    def _scan_one(proc: psutil.Process) -> LockEntry | None:
        # Named (not lambda) so any unhandled exception inside _inspect_process
        # surfaces with a meaningful traceback frame instead of "<lambda>".
        return _inspect_process(proc, targets)

    try:
        results = list(pool.map(_scan_one, procs))
    finally:
        # ``cancel_futures`` drops queued-but-not-started work immediately on
        # Ctrl+C so we don't wait on the full ~200-process queue. In-flight
        # workers still drain their current ``open_files()`` syscall, so the
        # observed Ctrl+C lag is bounded by the slowest in-flight call
        # (~1-2s on Windows) × the number of running workers (max 32) — not
        # by the full process count.
        pool.shutdown(wait=True, cancel_futures=True)
    return [entry for entry in results if entry is not None]


def find_locks_on_path(path: Path) -> list[LockEntry]:
    """Return processes with a ``cwd`` or open file under ``path``.

    Single-path convenience wrapper over :func:`find_locks_on_paths` —
    kept for callers that only care about one target. Each process
    contributes at most one entry.
    """
    return find_locks_on_paths([path])


def _inspect_process(
    proc: psutil.Process, targets: list[Path]
) -> LockEntry | None:
    """Return a ``LockEntry`` if ``proc`` holds anything under any ``target``."""
    try:
        info = proc.info
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        # OSError mirrors the cwd / open_files clauses below — under heavy
        # ``/proc`` contention on Linux ``proc.info``'s oneshot lookup can
        # surface a transient OSError that would otherwise abort the entire
        # parallel scan via pool.map.
        return None
    pid = info.get("pid")
    name = info.get("name") or "?"

    # 1) cwd check — the most common lock source on Windows (shell cd'd in)
    try:
        cwd = proc.cwd()
    except (
        psutil.AccessDenied,
        psutil.NoSuchProcess,
        psutil.ZombieProcess,  # subclass of NoSuchProcess; explicit for clarity
        OSError,
    ):
        cwd = None
    if cwd:
        try:
            cwd_resolved = Path(cwd).resolve()
        except OSError:
            cwd_resolved = None
        if cwd_resolved:
            for target in targets:
                if _is_subpath(cwd_resolved, target):
                    return LockEntry(pid=pid, name=name, reason=f"cwd={cwd}")

    # 2) open_files check — IDEs and editors
    try:
        open_files = proc.open_files() or []
    except (
        psutil.AccessDenied,
        psutil.NoSuchProcess,
        psutil.ZombieProcess,  # subclass of NoSuchProcess; explicit for clarity
        OSError,
    ):
        open_files = []
    for of in open_files:
        try:
            of_resolved = Path(of.path).resolve()
        except OSError:
            continue
        for target in targets:
            if _is_subpath(of_resolved, target):
                return LockEntry(
                    pid=pid, name=name, reason=f"open_file={of.path}"
                )

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
