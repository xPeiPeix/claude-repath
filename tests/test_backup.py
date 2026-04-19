"""Tests for :mod:`claude_repath.backup`."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from claude_repath.backup import list_backups, rollback, start_backup


class TestSave:
    def test_save_file(self, tmp_path: Path):
        src = tmp_path / "conf.json"
        src.write_text('{"v": 1}')

        session = start_backup(tmp_path / "backups")
        dest = session.save(src)

        assert dest is not None
        assert dest.exists()
        assert dest.read_text() == '{"v": 1}'

    def test_save_directory(self, tmp_path: Path):
        src = tmp_path / "proj"
        src.mkdir()
        (src / "a.txt").write_text("a")
        (src / "b.txt").write_text("b")

        session = start_backup(tmp_path / "backups")
        dest = session.save(src)

        assert dest is not None
        assert dest.is_dir()
        assert (dest / "a.txt").read_text() == "a"
        assert (dest / "b.txt").read_text() == "b"

    def test_save_missing_source_records_none(self, tmp_path: Path):
        missing = tmp_path / "ghost.txt"
        session = start_backup(tmp_path / "backups")
        result = session.save(missing)

        assert result is None
        data = json.loads(session.manifest_path.read_text())
        assert len(data["entries"]) == 1
        assert data["entries"][0]["backup"] is None
        assert data["entries"][0]["original"] == str(missing)

    def test_manifest_written_incrementally(self, tmp_path: Path):
        backup_root = tmp_path / "backups"
        f1 = tmp_path / "f1.txt"
        f1.write_text("1")
        f2 = tmp_path / "f2.txt"
        f2.write_text("2")

        session = start_backup(backup_root)
        session.save(f1)
        data = json.loads(session.manifest_path.read_text())
        assert len(data["entries"]) == 1

        session.save(f2)
        data = json.loads(session.manifest_path.read_text())
        assert len(data["entries"]) == 2


class TestRollback:
    def test_rollback_restores_file_content(self, tmp_path: Path):
        src = tmp_path / "conf.json"
        src.write_text('{"v": 1}')
        backup_root = tmp_path / "backups"

        session = start_backup(backup_root)
        session.save(src)
        src.write_text('{"v": 2}')  # mutate after backup

        restored = rollback(session.timestamp, backup_root)

        assert restored == 1
        assert src.read_text() == '{"v": 1}'

    def test_rollback_restores_directory_and_removes_additions(self, tmp_path: Path):
        src = tmp_path / "proj"
        src.mkdir()
        (src / "file.txt").write_text("hello")
        backup_root = tmp_path / "backups"

        session = start_backup(backup_root)
        session.save(src)

        shutil.rmtree(src)
        src.mkdir()
        (src / "other.txt").write_text("different")

        rollback(session.timestamp, backup_root)

        assert (src / "file.txt").read_text() == "hello"
        assert not (src / "other.txt").exists()

    def test_rollback_removes_item_that_was_missing_at_backup(self, tmp_path: Path):
        path = tmp_path / "ghost.txt"
        backup_root = tmp_path / "backups"

        session = start_backup(backup_root)
        session.save(path)  # path doesn't exist yet
        path.write_text("appeared later")

        rollback(session.timestamp, backup_root)

        assert not path.exists()

    def test_rollback_missing_timestamp_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            rollback("not-a-real-ts", tmp_path / "backups")


class TestListBackups:
    def test_returns_newest_first(self, tmp_path: Path):
        backup_root = tmp_path / "backups"
        s1 = start_backup(backup_root)
        s2 = start_backup(backup_root)
        s3 = start_backup(backup_root)

        assert len({s1.timestamp, s2.timestamp, s3.timestamp}) == 3

        result = list_backups(backup_root)
        names = [r[0] for r in result]
        assert names == sorted(names, reverse=True)
        assert len(names) == 3

    def test_empty_when_no_backups(self, tmp_path: Path):
        assert list_backups(tmp_path / "nope") == []

    def test_ignores_dirs_without_manifest(self, tmp_path: Path):
        backup_root = tmp_path / "backups"
        backup_root.mkdir()
        (backup_root / "orphan").mkdir()

        assert list_backups(backup_root) == []
