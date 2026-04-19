"""Tests for :mod:`claude_repath.layers.worktrees_json`."""

from __future__ import annotations

import json
from pathlib import Path

from claude_repath.backup import start_backup
from claude_repath.layers import worktrees_json
from claude_repath.layers.base import MigrationContext


def _ctx(claude_home: Path) -> MigrationContext:
    return MigrationContext(
        old_path=r"D:\dev_code\time-blocks",
        new_path=r"D:\dev_code\Life\time-blocks",
        claude_home=claude_home,
    )


class TestPlan:
    def test_missing_file(self, tmp_path: Path):
        claude_home = tmp_path / ".claude"
        claude_home.mkdir()
        plan = worktrees_json.plan(_ctx(claude_home))
        assert any("skip" in line for line in plan)

    def test_paths_to_rewrite(self, tmp_path: Path):
        claude_home = tmp_path / ".claude"
        claude_home.mkdir()
        (claude_home / "git-worktrees.json").write_text(
            json.dumps({"entries": [{"path": r"D:\dev_code\time-blocks\wt1"}]}),
            encoding="utf-8",
        )
        plan = worktrees_json.plan(_ctx(claude_home))
        assert any("rewrite" in line for line in plan)


class TestApply:
    def test_rewrites_paths_recursively(self, tmp_path: Path):
        claude_home = tmp_path / ".claude"
        claude_home.mkdir()
        original = {
            "entries": [
                {"path": r"D:\dev_code\time-blocks", "name": "main"},
                {"path": r"D:\dev_code\time-blocks\.claude\worktrees\feat"},
                {"path": r"D:\dev_code\unrelated"},
            ],
            "top_level_path": r"D:\dev_code\time-blocks\deep\file",
        }
        target = claude_home / "git-worktrees.json"
        target.write_text(json.dumps(original), encoding="utf-8")
        session = start_backup(tmp_path / "backups")

        changes = worktrees_json.apply(_ctx(claude_home), session)

        assert len(changes) == 1
        new = json.loads(target.read_text())
        assert new["entries"][0]["path"] == r"D:\dev_code\Life\time-blocks"
        assert (
            new["entries"][1]["path"]
            == r"D:\dev_code\Life\time-blocks\.claude\worktrees\feat"
        )
        assert new["entries"][2]["path"] == r"D:\dev_code\unrelated"
        assert new["top_level_path"] == r"D:\dev_code\Life\time-blocks\deep\file"

    def test_missing_file_returns_empty(self, tmp_path: Path):
        claude_home = tmp_path / ".claude"
        claude_home.mkdir()
        session = start_backup(tmp_path / "backups")
        assert worktrees_json.apply(_ctx(claude_home), session) == []

    def test_noop_when_no_matches(self, tmp_path: Path):
        claude_home = tmp_path / ".claude"
        claude_home.mkdir()
        (claude_home / "git-worktrees.json").write_text(
            json.dumps({"entries": [{"path": r"D:\unrelated"}]}),
            encoding="utf-8",
        )
        session = start_backup(tmp_path / "backups")
        assert worktrees_json.apply(_ctx(claude_home), session) == []
