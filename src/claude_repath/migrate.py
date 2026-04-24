"""Migration orchestrator — coordinates all layers in order."""

from __future__ import annotations

import errno
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .backup import BackupSession
from .layers import global_json, jsonl_cwd, projects_dir, worktrees_json
from .layers.base import MigrationContext


class PhysicalMoveError(RuntimeError):
    """Raised when the physical folder move fails at the OS level.

    The caller is expected to surface ``args[0]`` (actionable message with
    recovery guidance) to the user. The source directory is guaranteed to be
    left intact when this is raised — no half-migrated state.
    """

#: Ordered list of migration layers. Order matters:
#: 1. Rename physical projects/ dirs before rewriting their contents
#: 2. Rewrite jsonl cwd fields inside the (now-renamed) dirs
#: 3. Rewrite global ~/.claude.json
#: 4. Rewrite git-worktrees.json
LAYERS: list[tuple[str, object]] = [
    ("projects_dir", projects_dir),
    ("jsonl_cwd", jsonl_cwd),
    ("global_json", global_json),
    ("worktrees_json", worktrees_json),
]


@dataclass
class PlanReport:
    """Result of a dry-run plan across all layers."""

    entries: list[tuple[str, list[str]]]

    @property
    def total_actions(self) -> int:
        return sum(
            1
            for _, lines in self.entries
            for line in lines
            if not line.startswith(("[skip]", "[noop]"))
        )


@dataclass
class ApplyReport:
    """Result of a full migration apply across all layers."""

    entries: list[tuple[str, list[str]]]
    backup_root: Path
    timestamp: str
    moved_folder: bool = False

    @property
    def total_changes(self) -> int:
        return sum(len(changes) for _, changes in self.entries)


def plan_migration(ctx: MigrationContext) -> PlanReport:
    """Dry-run every layer; no mutations."""
    entries = [(name, module.plan(ctx)) for name, module in LAYERS]
    return PlanReport(entries=entries)


def apply_migration(ctx: MigrationContext, session: BackupSession) -> ApplyReport:
    """Execute every layer in order, recording changes into ``session``."""
    entries: list[tuple[str, list[str]]] = []
    for name, module in LAYERS:
        changes = module.apply(ctx, session)
        if changes:
            entries.append((name, changes))
    return ApplyReport(
        entries=entries, backup_root=session.root, timestamp=session.timestamp
    )


def move_project_folder(old_path: str, new_path: str) -> None:
    """Physically move the project directory from ``old_path`` to ``new_path``.

    Uses ``os.rename`` — an atomic same-volume rename — as the primary path.
    On ``EXDEV`` (cross-volume link) we fall back to a copy-and-delete
    sequence (``robocopy /MOVE`` on Windows, ``shutil.move`` on Unix), which
    is the only way to relocate across drives.

    On **any other** ``OSError`` (e.g. Windows ``WinError 5`` / ``32`` from a
    file lock, permission denied), we raise ``PhysicalMoveError`` instead of
    downgrading to ``copytree + rmtree``. The key safety property: the source
    directory is left completely intact, so the user can close the locking
    process and retry — no half-migrated state.

    Parent directories of ``new_path`` are created automatically.

    Raises:
        FileNotFoundError: ``old_path`` does not exist.
        FileExistsError: ``new_path`` already exists.
        PhysicalMoveError: OS-level failure during the move (wraps the
            underlying ``OSError`` with actionable recovery guidance).
    """
    old = Path(old_path)
    new = Path(new_path)
    if not old.exists():
        raise FileNotFoundError(f"{old} does not exist — nothing to move")
    if new.exists():
        raise FileExistsError(f"{new} already exists — refusing to overwrite")
    new.parent.mkdir(parents=True, exist_ok=True)

    try:
        os.rename(str(old), str(new))
        return
    except OSError as exc:
        if exc.errno == errno.EXDEV:
            _cross_volume_move(old, new)
            return
        # Anything else — lock, permission, etc. — bubble up with guidance.
        # Crucially, we do NOT fall back to copytree+rmtree here, because that
        # path is non-atomic and can leave the source directory half-deleted
        # if rmtree hits a lock mid-delete (the original shutil.move failure
        # mode this function was rewritten to prevent).
        filename = exc.filename or old
        reason = exc.strerror or str(exc)
        raise PhysicalMoveError(
            f"Physical move failed: {reason} (file: {filename}).\n"
            f"Source directory left intact at {old}.\n"
            f"Close any process holding a file under the path and retry, "
            f"or move the folder manually and then run:\n"
            f"  claude-repath rewire {old} {new}"
        ) from exc


def _cross_volume_move(old: Path, new: Path) -> None:
    """Copy-then-delete fallback for ``EXDEV``. Only reachable on cross-drive moves.

    On Windows we prefer ``robocopy /MOVE`` — it ships with Windows, has
    built-in retry on transient locks, and copes with long paths better than
    Python's ``shutil``. Exit codes 0-7 are success (bitfield of
    files-copied / files-skipped / files-mismatched etc.); ``>= 8`` is
    failure.

    On Unix, cross-volume moves don't suffer the same in-use-lock semantics,
    so ``shutil.move`` is safe and matches the pre-rewrite behavior.
    """
    if sys.platform.startswith("win"):
        result = subprocess.run(
            [
                "robocopy",
                str(old),
                str(new),
                "/MOVE",
                "/E",
                "/NFL",
                "/NDL",
                "/NJH",
                "/NJS",
                "/NP",
                "/R:2",
                "/W:1",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode >= 8:
            raise PhysicalMoveError(
                f"Cross-volume move failed (robocopy exit code "
                f"{result.returncode}).\n"
                f"Source directory at {old} may be partially moved — "
                f"inspect before retrying.\n"
                f"robocopy stderr: {(result.stderr or result.stdout).strip()}"
            )
    else:
        shutil.move(str(old), str(new))

