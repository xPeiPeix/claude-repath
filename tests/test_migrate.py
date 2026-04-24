"""End-to-end tests for the migration orchestrator."""

from __future__ import annotations

import errno
import json
import os
import sys
from pathlib import Path

import pytest

from claude_repath.backup import rollback, start_backup
from claude_repath.layers.base import MigrationContext
from claude_repath.migrate import (
    PhysicalMoveError,
    apply_migration,
    move_project_folder,
    plan_migration,
)


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


class TestMoveProjectFolder:
    """Regression tests for the ``os.rename``-first physical move.

    The v0.4.1 rewrite replaced ``shutil.move`` (which silently downgrades to
    ``copytree + rmtree`` on Windows cross-device or lock failures, leaving a
    half-migrated state) with an atomic ``os.rename`` + explicit ``EXDEV``
    fallback. These tests pin the new guarantees:

    * Same-volume happy path uses ``os.rename`` directly.
    * Non-``EXDEV`` ``OSError`` (simulated lock) raises ``PhysicalMoveError``
      with the source directory 100% intact — **no** copy-delete downgrade.
    * ``EXDEV`` triggers the cross-volume fallback (``robocopy`` on Windows,
      ``shutil.move`` on Unix).
    * Pre-existing refusal semantics (``FileNotFoundError`` /
      ``FileExistsError``) are preserved.
    """

    def test_same_volume_uses_os_rename(self, tmp_path: Path, monkeypatch):
        src = tmp_path / "src"
        src.mkdir()
        (src / "file.txt").write_text("hi", encoding="utf-8")
        dst = tmp_path / "dst"

        calls: list[tuple[str, str]] = []
        original_rename = os.rename

        def spy_rename(a, b):
            calls.append((str(a), str(b)))
            return original_rename(a, b)

        monkeypatch.setattr(os, "rename", spy_rename)

        move_project_folder(str(src), str(dst))

        assert calls == [(str(src), str(dst))]
        assert dst.is_dir()
        assert (dst / "file.txt").read_text(encoding="utf-8") == "hi"
        assert not src.exists()

    def test_non_exdev_oserror_preserves_source_and_raises(
        self, tmp_path: Path, monkeypatch
    ):
        """The load-bearing invariant: on a simulated Windows lock failure
        (``errno != EXDEV``), the source directory must be left intact and
        the target must NOT exist. No ``copytree + rmtree`` downgrade — that
        is exactly the non-atomic path we rewrote to eliminate.
        """
        src = tmp_path / "src"
        src.mkdir()
        critical = src / "critical.txt"
        critical.write_text("must-survive", encoding="utf-8")
        dst = tmp_path / "dst"

        def fake_rename(a, b):
            raise PermissionError(
                errno.EACCES, "The process cannot access the file", str(critical)
            )

        monkeypatch.setattr(os, "rename", fake_rename)

        with pytest.raises(PhysicalMoveError) as excinfo:
            move_project_folder(str(src), str(dst))

        msg = str(excinfo.value)
        assert "Source directory left intact" in msg
        assert "claude-repath rewire" in msg
        # Critical safety: source must be 100% intact, target must not exist.
        assert src.is_dir()
        assert critical.read_text(encoding="utf-8") == "must-survive"
        assert not dst.exists()

    def test_exdev_triggers_cross_volume_fallback(
        self, tmp_path: Path, monkeypatch
    ):
        src = tmp_path / "src"
        src.mkdir()
        (src / "f.txt").write_text("x", encoding="utf-8")
        dst = tmp_path / "dst"

        def fake_rename(a, b):
            raise OSError(errno.EXDEV, "Invalid cross-device link")

        monkeypatch.setattr(os, "rename", fake_rename)

        fallback_calls: list[tuple[Path, Path]] = []

        def spy_fallback(old: Path, new: Path):
            fallback_calls.append((old, new))
            # Perform a minimal same-directory "move" so dst exists at the end.
            import shutil

            shutil.copytree(str(old), str(new))
            shutil.rmtree(str(old))

        monkeypatch.setattr(
            "claude_repath.migrate._cross_volume_move", spy_fallback
        )

        move_project_folder(str(src), str(dst))

        assert len(fallback_calls) == 1
        assert fallback_calls[0] == (Path(str(src)), Path(str(dst)))
        assert dst.is_dir()
        assert not src.exists()

    def test_raises_filenotfound_when_source_missing(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            move_project_folder(
                str(tmp_path / "nope"), str(tmp_path / "dst")
            )

    def test_raises_fileexists_when_target_exists(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        dst = tmp_path / "dst"
        dst.mkdir()
        with pytest.raises(FileExistsError):
            move_project_folder(str(src), str(dst))

    def test_creates_missing_parent_dir_of_target(
        self, tmp_path: Path, monkeypatch
    ):
        src = tmp_path / "src"
        src.mkdir()
        (src / "f.txt").write_text("y", encoding="utf-8")
        # Deep path whose parent does not yet exist.
        dst = tmp_path / "a" / "b" / "c" / "dst"

        move_project_folder(str(src), str(dst))

        assert dst.is_dir()
        assert (dst / "f.txt").read_text(encoding="utf-8") == "y"


class TestCrossVolumeFallback:
    """Directly exercise ``_cross_volume_move``'s platform branches.

    These tests mock the underlying move primitive (``subprocess.run`` for
    Windows / ``shutil.move`` for Unix) so they run cross-platform.
    """

    def test_windows_uses_robocopy_with_move_flag(
        self, tmp_path: Path, monkeypatch
    ):
        from claude_repath import migrate

        monkeypatch.setattr(sys, "platform", "win32")
        captured: dict = {}

        class _Result:
            returncode = 1  # robocopy "files copied" success
            stdout = ""
            stderr = ""

        def fake_run(cmd, **_kwargs):
            captured["cmd"] = cmd
            return _Result()

        monkeypatch.setattr(migrate.subprocess, "run", fake_run)

        migrate._cross_volume_move(tmp_path / "old", tmp_path / "new")

        cmd = captured["cmd"]
        assert cmd[0] == "robocopy"
        assert "/MOVE" in cmd
        assert "/E" in cmd
        assert str(tmp_path / "old") in cmd
        assert str(tmp_path / "new") in cmd

    def test_windows_robocopy_failure_raises_physical_move_error(
        self, tmp_path: Path, monkeypatch
    ):
        from claude_repath import migrate

        monkeypatch.setattr(sys, "platform", "win32")

        class _Result:
            returncode = 16  # robocopy "serious error"
            stdout = ""
            stderr = "access denied"

        monkeypatch.setattr(
            migrate.subprocess, "run", lambda *_a, **_k: _Result()
        )

        with pytest.raises(PhysicalMoveError, match="robocopy exit code 16"):
            migrate._cross_volume_move(tmp_path / "old", tmp_path / "new")

    def test_unix_uses_shutil_move(self, tmp_path: Path, monkeypatch):
        from claude_repath import migrate

        monkeypatch.setattr(sys, "platform", "linux")
        calls: list[tuple[str, str]] = []

        def spy_move(a, b):
            calls.append((a, b))

        monkeypatch.setattr(migrate.shutil, "move", spy_move)

        migrate._cross_volume_move(tmp_path / "old", tmp_path / "new")

        assert calls == [(str(tmp_path / "old"), str(tmp_path / "new"))]


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
