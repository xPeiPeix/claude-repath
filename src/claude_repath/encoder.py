"""Path encoding for Claude Code's ``~/.claude/projects/<encoded>`` folders.

Claude Code derives each project's folder name by replacing every
non-alphanumeric character in the absolute path with a hyphen. Case is
preserved and no path normalization is performed — the input is treated
as a literal string.

Examples:
    D:\\dev_code\\time-blocks                        -> D--dev-code-time-blocks
    /home/user/project                               -> -home-user-project
    D:\\dev\\time-blocks\\.claude\\worktrees\\feat-x -> D--dev-time-blocks--claude-worktrees-feat-x
"""

from __future__ import annotations

import re
from pathlib import Path

_NON_ALNUM = re.compile(r"[^a-zA-Z0-9]")

WORKTREE_INFIX = "--claude-worktrees-"


def encode_path(path: str | Path) -> str:
    """Encode an absolute path into Claude Code's folder-name form.

    Non-alphanumeric characters are replaced with hyphens. Case is preserved.
    The input is not normalized — ``D:\\foo`` and ``D:/foo`` both yield
    ``D--foo`` only because ``\\`` and ``/`` are both non-alphanumeric.
    """
    return _NON_ALNUM.sub("-", str(path))


def find_worktree_folders(base_encoded: str, projects_dir: Path) -> list[Path]:
    """Return worktree-derived project folders for a given base project.

    A worktree folder has the form ``<base_encoded>--claude-worktrees-<name>``.
    The result is sorted by name; an empty list is returned if
    ``projects_dir`` doesn't exist.
    """
    if not projects_dir.is_dir():
        return []
    prefix = f"{base_encoded}{WORKTREE_INFIX}"
    return sorted(
        p for p in projects_dir.iterdir() if p.is_dir() and p.name.startswith(prefix)
    )
