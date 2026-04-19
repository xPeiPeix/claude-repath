"""Tests for :mod:`claude_repath.layers.jsonl_cwd`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claude_repath.backup import start_backup
from claude_repath.layers import jsonl_cwd
from claude_repath.layers.base import MigrationContext


@pytest.fixture
def fake_claude(tmp_path: Path):
    claude_home = tmp_path / "claude"
    projects = claude_home / "projects"
    main = projects / "D--dev-code-time-blocks"
    main.mkdir(parents=True)

    # A session with two relevant lines + one unrelated line + a blank line + one invalid.
    s1 = main / "session1.jsonl"
    lines = [
        json.dumps({"type": "user", "cwd": r"D:\dev_code\time-blocks", "msg": "hi"}),
        json.dumps({"type": "tool", "cwd": r"D:\dev_code\time-blocks\sub\file.py"}),
        json.dumps({"type": "user", "cwd": r"D:\dev_code\other", "msg": "untouched"}),
        "",
        "{not-json",
    ]
    s1.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Worktree folder with its own jsonl.
    wt = projects / "D--dev-code-time-blocks--claude-worktrees-feat"
    wt.mkdir()
    (wt / "session2.jsonl").write_text(
        json.dumps(
            {
                "type": "user",
                "cwd": r"D:\dev_code\time-blocks\.claude\worktrees\feat",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    # Totally unrelated project.
    other = projects / "D--dev-code-other"
    other.mkdir()
    (other / "s.jsonl").write_text(
        json.dumps({"cwd": r"D:\dev_code\other"}) + "\n", encoding="utf-8"
    )

    return claude_home


def _ctx(claude_home: Path) -> MigrationContext:
    return MigrationContext(
        old_path=r"D:\dev_code\time-blocks",
        new_path=r"D:\dev_code\Life\time-blocks",
        claude_home=claude_home,
    )


class TestRewriteContent:
    def test_exact_and_prefix_matches(self):
        content = (
            json.dumps({"cwd": r"D:\a"})
            + "\n"
            + json.dumps({"cwd": r"D:\a\sub"})
            + "\n"
            + json.dumps({"cwd": r"D:\b"})
            + "\n"
        )
        new_content, count = jsonl_cwd._rewrite_content(content, r"D:\a", r"D:\c")
        assert count == 2
        lines = [json.loads(ln) for ln in new_content.strip().split("\n")]
        assert lines[0]["cwd"] == r"D:\c"
        assert lines[1]["cwd"] == r"D:\c\sub"
        assert lines[2]["cwd"] == r"D:\b"

    def test_preserves_invalid_json_lines(self):
        content = json.dumps({"cwd": r"D:\a"}) + "\n" + "not-json-line\n"
        new_content, count = jsonl_cwd._rewrite_content(content, r"D:\a", r"D:\c")
        assert count == 1
        assert "not-json-line" in new_content

    def test_preserves_blank_lines(self):
        content = "\n" + json.dumps({"cwd": r"D:\a"}) + "\n\n"
        new_content, count = jsonl_cwd._rewrite_content(content, r"D:\a", r"D:\c")
        assert count == 1
        assert new_content.startswith("\n")

    def test_trailing_newline_preserved(self):
        content = json.dumps({"cwd": r"D:\a"}) + "\n"
        new_content, _ = jsonl_cwd._rewrite_content(content, r"D:\a", r"D:\c")
        assert new_content.endswith("\n")

    def test_no_trailing_newline_preserved(self):
        content = json.dumps({"cwd": r"D:\a"})
        new_content, _ = jsonl_cwd._rewrite_content(content, r"D:\a", r"D:\c")
        assert not new_content.endswith("\n")


class TestApply:
    def test_patches_main_and_worktree_jsonl(self, tmp_path: Path, fake_claude: Path):
        ctx = _ctx(fake_claude)
        session = start_backup(tmp_path / "backups")

        changes = jsonl_cwd.apply(ctx, session)

        # 2 files changed (main session1, worktree session2). Unrelated untouched.
        assert len(changes) == 2

        main_s = (
            fake_claude / "projects" / "D--dev-code-time-blocks" / "session1.jsonl"
        ).read_text(encoding="utf-8")
        lines = [ln for ln in main_s.split("\n") if ln.strip() and ln.strip() != "{not-json"]
        parsed = [json.loads(ln) for ln in lines]
        assert parsed[0]["cwd"] == r"D:\dev_code\Life\time-blocks"
        assert parsed[1]["cwd"] == r"D:\dev_code\Life\time-blocks\sub\file.py"
        assert parsed[2]["cwd"] == r"D:\dev_code\other"  # unrelated line intact
        assert "{not-json" in main_s  # invalid line preserved verbatim

        wt_s = (
            fake_claude
            / "projects"
            / "D--dev-code-time-blocks--claude-worktrees-feat"
            / "session2.jsonl"
        ).read_text(encoding="utf-8")
        wt_parsed = json.loads(wt_s.strip())
        assert wt_parsed["cwd"] == r"D:\dev_code\Life\time-blocks\.claude\worktrees\feat"

        other_s = (
            fake_claude / "projects" / "D--dev-code-other" / "s.jsonl"
        ).read_text(encoding="utf-8")
        other_parsed = json.loads(other_s.strip())
        assert other_parsed["cwd"] == r"D:\dev_code\other"
        assert "Life" not in other_s

    def test_missing_projects_dir_returns_empty(self, tmp_path: Path):
        ctx = MigrationContext(
            old_path=r"D:\a",
            new_path=r"D:\b",
            claude_home=tmp_path / "nope",
        )
        session = start_backup(tmp_path / "backups")
        assert jsonl_cwd.apply(ctx, session) == []
