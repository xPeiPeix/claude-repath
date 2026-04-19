"""End-to-end tests for the migration orchestrator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claude_repath.backup import rollback, start_backup
from claude_repath.layers.base import MigrationContext
from claude_repath.migrate import apply_migration, plan_migration


@pytest.fixture
def fake_home(tmp_path: Path):
    """Construct a complete fake ~/.claude layout for e2e testing."""
    claude_home = tmp_path / ".claude"
    projects = claude_home / "projects"
    projects.mkdir(parents=True)

    # Main project folder with one session.
    main = projects / "D--test-old"
    main.mkdir()
    (main / "s1.jsonl").write_text(
        json.dumps({"type": "user", "cwd": r"D:\test\old", "msg": "hi"}) + "\n"
        + json.dumps({"type": "user", "cwd": r"D:\test\old\sub\file.py"}) + "\n",
        encoding="utf-8",
    )

    # Worktree folder.
    wt = projects / "D--test-old--claude-worktrees-feat"
    wt.mkdir()
    (wt / "s2.jsonl").write_text(
        json.dumps(
            {"cwd": r"D:\test\old\.claude\worktrees\feat"}
        )
        + "\n",
        encoding="utf-8",
    )

    # Unrelated project.
    other = projects / "D--other"
    other.mkdir()
    (other / "s.jsonl").write_text(
        json.dumps({"cwd": r"D:\other"}) + "\n", encoding="utf-8"
    )

    # Global ~/.claude.json (note: forward slashes, like the real one)
    (tmp_path / ".claude.json").write_text(
        json.dumps(
            {
                "theme": "dark",
                "projects": {
                    "D:/test/old": {"lastUsed": 100},
                    "D:/test/old/.claude/worktrees/feat": {"lastUsed": 101},
                    "D:/other": {"lastUsed": 50},
                },
            }
        ),
        encoding="utf-8",
    )

    # git-worktrees.json (optional).
    (claude_home / "git-worktrees.json").write_text(
        json.dumps({"entries": [{"path": r"D:\test\old\.claude\worktrees\feat"}]}),
        encoding="utf-8",
    )

    return claude_home


def _ctx(claude_home: Path) -> MigrationContext:
    return MigrationContext(
        old_path=r"D:\test\old",
        new_path=r"D:\test\new",
        claude_home=claude_home,
    )


class TestPlan:
    def test_plan_covers_all_layers(self, fake_home: Path):
        report = plan_migration(_ctx(fake_home))
        names = [name for name, _ in report.entries]
        assert names == ["projects_dir", "jsonl_cwd", "global_json", "worktrees_json"]
        assert report.total_actions > 0


class TestApplyEndToEnd:
    def test_full_migration(self, tmp_path: Path, fake_home: Path):
        ctx = _ctx(fake_home)
        session = start_backup(tmp_path / "backups")

        report = apply_migration(ctx, session)

        projects = fake_home / "projects"

        # Layer 2: projects dirs renamed
        assert (projects / "D--test-new").is_dir()
        assert not (projects / "D--test-old").exists()
        assert (projects / "D--test-new--claude-worktrees-feat").is_dir()
        assert (projects / "D--other").is_dir()  # unrelated untouched

        # Layer 3: jsonl cwd fields rewritten
        new_s1 = (projects / "D--test-new" / "s1.jsonl").read_text()
        lines = [json.loads(ln) for ln in new_s1.strip().split("\n")]
        assert lines[0]["cwd"] == r"D:\test\new"
        assert lines[1]["cwd"] == r"D:\test\new\sub\file.py"

        wt_s = (projects / "D--test-new--claude-worktrees-feat" / "s2.jsonl").read_text()
        assert json.loads(wt_s.strip())["cwd"] == r"D:\test\new\.claude\worktrees\feat"

        # Unrelated project is untouched
        other_s = (projects / "D--other" / "s.jsonl").read_text()
        assert json.loads(other_s.strip())["cwd"] == r"D:\other"

        # Layer 4: global json rekeyed (forward-slash style preserved)
        gj = json.loads((fake_home.parent / ".claude.json").read_text())
        assert "D:/test/new" in gj["projects"]
        assert "D:/test/old" not in gj["projects"]
        assert "D:/test/new/.claude/worktrees/feat" in gj["projects"]
        assert "D:/other" in gj["projects"]  # unrelated untouched

        # Layer 5: git-worktrees.json updated
        wt_json = json.loads((fake_home / "git-worktrees.json").read_text())
        assert wt_json["entries"][0]["path"] == r"D:\test\new\.claude\worktrees\feat"

        assert report.total_changes > 0


class TestRollbackE2E:
    def test_rollback_restores_everything(self, tmp_path: Path, fake_home: Path):
        # Snapshot original state first.
        main_before = (fake_home / "projects" / "D--test-old" / "s1.jsonl").read_text()
        gj_before = (fake_home.parent / ".claude.json").read_text()

        ctx = _ctx(fake_home)
        session = start_backup(tmp_path / "backups")
        apply_migration(ctx, session)

        # Roll back.
        rollback(session.timestamp, tmp_path / "backups")

        # Original state restored.
        assert (fake_home / "projects" / "D--test-old" / "s1.jsonl").read_text() == main_before
        assert (fake_home.parent / ".claude.json").read_text() == gj_before
        # The new-encoded folder should be gone (since L2 saved old, and rollback recreates it).
        assert not (fake_home / "projects" / "D--test-new").exists()
