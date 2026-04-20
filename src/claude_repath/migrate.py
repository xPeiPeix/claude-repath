"""Migration orchestrator — coordinates all layers in order."""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .backup import BackupSession
from .layers import global_json, jsonl_cwd, projects_dir, worktrees_json
from .layers.base import MigrationContext

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

    Parent directories of ``new_path`` are created automatically. Raises
    ``FileNotFoundError`` / ``FileExistsError`` on conflicts.
    """
    old = Path(old_path)
    new = Path(new_path)
    if not old.exists():
        raise FileNotFoundError(f"{old} does not exist — nothing to move")
    if new.exists():
        raise FileExistsError(f"{new} already exists — refusing to overwrite")
    new.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(old), str(new))


def detect_claude_processes() -> list[int]:
    """Return PIDs of running Claude Code CLI processes. Best-effort.

    Excludes this tool's own process — ``pgrep -f claude`` would otherwise
    match any command line containing "claude", including ``claude-repath``
    itself, producing a misleading "running claude detected" warning.

    Returns an empty list on systems where the check can't run, rather than
    raising — this is a soft safety check, not a hard gate.
    """
    if sys.platform.startswith("win"):
        cmd = ["tasklist", "/fi", "imagename eq claude.exe", "/fo", "csv", "/nh"]
    else:
        cmd = ["pgrep", "-af", "claude"]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=5, check=False
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    pids: list[int] = []
    if sys.platform.startswith("win"):
        for line in result.stdout.splitlines():
            parts = [p.strip('"') for p in line.split(",")]
            if len(parts) >= 2 and parts[0].lower().startswith("claude"):
                try:
                    pids.append(int(parts[1]))
                except ValueError:
                    pass
    else:
        # pgrep -af emits "PID full-cmdline"; filter out lines whose cmdline
        # clearly belongs to this tool (or uv-tool/pipx wrappers for it).
        for line in result.stdout.splitlines():
            pid_str, _, cmdline = line.partition(" ")
            if "claude-repath" in cmdline:
                continue
            try:
                pids.append(int(pid_str))
            except ValueError:
                pass
    return pids
