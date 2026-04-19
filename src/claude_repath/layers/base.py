"""Shared context and path utilities for migration layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class MigrationContext:
    """Parameters passed to every layer's ``plan`` / ``apply`` function.

    ``claude_home`` defaults to ``~/.claude`` but is overridable for tests.
    """

    old_path: str
    new_path: str
    claude_home: Path = field(default_factory=lambda: Path.home() / ".claude")

    @property
    def projects_dir(self) -> Path:
        return self.claude_home / "projects"

    @property
    def global_json_path(self) -> Path:
        """``~/.claude.json`` — lives *next to* ``~/.claude/``, not inside it."""
        return self.claude_home.parent / ".claude.json"

    @property
    def worktrees_json_path(self) -> Path:
        return self.claude_home / "git-worktrees.json"
