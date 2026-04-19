"""Tests for :mod:`claude_repath.layers.projects_dir`."""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_repath.backup import start_backup
from claude_repath.layers import projects_dir
from claude_repath.layers.base import MigrationContext


@pytest.fixture
def fake_claude(tmp_path: Path):
    """Build a fake ~/.claude tree with a main project and two worktrees."""
    claude_home = tmp_path / "claude"
    projects = claude_home / "projects"
    projects.mkdir(parents=True)

    old_enc = "D--dev-code-time-blocks"
    (projects / old_enc).mkdir()
    (projects / old_enc / "session1.jsonl").write_text("{}")
    (projects / f"{old_enc}--claude-worktrees-feat").mkdir()
    (projects / f"{old_enc}--claude-worktrees-bugfix").mkdir()
    # Unrelated project that must not be touched.
    (projects / "D--dev-code-other").mkdir()

    return claude_home


def _make_ctx(claude_home: Path) -> MigrationContext:
    return MigrationContext(
        old_path=r"D:\dev_code\time-blocks",
        new_path=r"D:\dev_code\Life\time-blocks",
        claude_home=claude_home,
    )


class TestPlan:
    def test_lists_main_and_worktrees(self, fake_claude: Path):
        plan = projects_dir.plan(_make_ctx(fake_claude))
        # Should mention both rename (main) and two worktrees.
        text = "\n".join(plan)
        assert "D--dev-code-time-blocks/ -> projects/D--dev-code-Life-time-blocks/" in text
        assert "worktrees-feat" in text
        assert "worktrees-bugfix" in text
        # Unrelated project should not appear.
        assert "D--dev-code-other" not in text

    def test_conflict_when_target_exists(self, fake_claude: Path):
        ctx = _make_ctx(fake_claude)
        (fake_claude / "projects" / "D--dev-code-Life-time-blocks").mkdir()
        plan = projects_dir.plan(ctx)
        assert any("conflict" in line for line in plan)

    def test_missing_projects_dir(self, tmp_path: Path):
        ctx = MigrationContext(
            old_path=r"D:\a",
            new_path=r"D:\b",
            claude_home=tmp_path / "nope",
        )
        plan = projects_dir.plan(ctx)
        assert any("skip" in line for line in plan)


class TestApply:
    def test_renames_main_and_worktrees(self, tmp_path: Path, fake_claude: Path):
        ctx = _make_ctx(fake_claude)
        session = start_backup(tmp_path / "backups")

        changes = projects_dir.apply(ctx, session)

        projects = fake_claude / "projects"
        assert not (projects / "D--dev-code-time-blocks").exists()
        assert (projects / "D--dev-code-Life-time-blocks").exists()
        assert (projects / "D--dev-code-Life-time-blocks" / "session1.jsonl").exists()
        assert (projects / "D--dev-code-Life-time-blocks--claude-worktrees-feat").exists()
        assert (projects / "D--dev-code-Life-time-blocks--claude-worktrees-bugfix").exists()
        # Unrelated untouched.
        assert (projects / "D--dev-code-other").exists()
        assert len(changes) == 3  # main + 2 worktrees

    def test_conflict_raises(self, tmp_path: Path, fake_claude: Path):
        ctx = _make_ctx(fake_claude)
        (fake_claude / "projects" / "D--dev-code-Life-time-blocks").mkdir()
        session = start_backup(tmp_path / "backups")

        with pytest.raises(FileExistsError):
            projects_dir.apply(ctx, session)

    def test_noop_when_encoding_unchanged(self, tmp_path: Path, fake_claude: Path):
        # Old == new path → encoding unchanged → no-op.
        ctx = MigrationContext(
            old_path=r"D:\dev_code\time-blocks",
            new_path=r"D:\dev_code\time-blocks",
            claude_home=fake_claude,
        )
        session = start_backup(tmp_path / "backups")
        changes = projects_dir.apply(ctx, session)
        assert changes == []
