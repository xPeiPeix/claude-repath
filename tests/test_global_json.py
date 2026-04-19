"""Tests for :mod:`claude_repath.layers.global_json`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claude_repath.backup import start_backup
from claude_repath.layers import global_json
from claude_repath.layers.base import MigrationContext


@pytest.fixture
def fake_home(tmp_path: Path):
    claude_home = tmp_path / ".claude"
    claude_home.mkdir()
    global_json_path = tmp_path / ".claude.json"
    data = {
        "theme": "dark",
        "projects": {
            r"D:\dev_code\time-blocks": {"lastUsed": 123},
            r"D:\dev_code\time-blocks\.claude\worktrees\feat": {"lastUsed": 124},
            r"D:\dev_code\other": {"lastUsed": 99},
        },
        "someOtherAbsolutePath": r"D:\dev_code\time-blocks",
    }
    global_json_path.write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )
    return claude_home


def _ctx(claude_home: Path) -> MigrationContext:
    return MigrationContext(
        old_path=r"D:\dev_code\time-blocks",
        new_path=r"D:\dev_code\Life\time-blocks",
        claude_home=claude_home,
    )


class TestPlan:
    def test_lists_rekeys_and_rewrites(self, fake_home: Path):
        plan = global_json.plan(_ctx(fake_home))
        text = "\n".join(plan)
        # Main project key rename.
        assert r"D:\dev_code\time-blocks" in text
        assert r"D:\dev_code\Life\time-blocks" in text
        # Worktree subpath rename.
        assert "worktrees" in text or "subpath" in text or "rekey" in text

    def test_missing_file_skip(self, tmp_path: Path):
        ctx = MigrationContext(
            old_path=r"D:\a", new_path=r"D:\b", claude_home=tmp_path / ".claude"
        )
        plan = global_json.plan(ctx)
        assert any("skip" in line for line in plan)


class TestApply:
    def test_rekeys_matching_project_entries(self, tmp_path: Path, fake_home: Path):
        ctx = _ctx(fake_home)
        session = start_backup(tmp_path / "backups")

        changes = global_json.apply(ctx, session)

        data = json.loads((fake_home.parent / ".claude.json").read_text())
        projects = data["projects"]

        # Main project key renamed.
        assert r"D:\dev_code\Life\time-blocks" in projects
        assert r"D:\dev_code\time-blocks" not in projects
        # Worktree subpath renamed.
        assert (
            r"D:\dev_code\Life\time-blocks\.claude\worktrees\feat" in projects
        )
        # Unrelated untouched.
        assert r"D:\dev_code\other" in projects
        # Nested string rewritten too.
        assert data["someOtherAbsolutePath"] == r"D:\dev_code\Life\time-blocks"

        assert len(changes) >= 2

    def test_no_changes_returns_empty(self, tmp_path: Path):
        claude_home = tmp_path / ".claude"
        claude_home.mkdir()
        (tmp_path / ".claude.json").write_text(
            json.dumps({"projects": {r"D:\other": {}}}), encoding="utf-8"
        )
        ctx = _ctx(claude_home)
        session = start_backup(tmp_path / "backups")

        assert global_json.apply(ctx, session) == []

    def test_collision_raises(self, tmp_path: Path):
        claude_home = tmp_path / ".claude"
        claude_home.mkdir()
        (tmp_path / ".claude.json").write_text(
            json.dumps(
                {
                    "projects": {
                        r"D:\dev_code\time-blocks": {"a": 1},
                        r"D:\dev_code\Life\time-blocks": {"b": 2},  # target exists!
                    }
                }
            ),
            encoding="utf-8",
        )
        ctx = _ctx(claude_home)
        session = start_backup(tmp_path / "backups")

        with pytest.raises(ValueError, match="[Cc]ollision"):
            global_json.apply(ctx, session)
