"""Tests for :mod:`claude_repath.platform_paths`."""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_repath import platform_paths


class TestDesktopLocalStorageCandidate:
    def test_windows_candidate(self, monkeypatch, tmp_path: Path):
        monkeypatch.setattr(platform_paths.sys, "platform", "win32")
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        candidate = platform_paths._desktop_local_storage_candidate()
        assert candidate == tmp_path / "claude" / "Local Storage" / "leveldb"

    def test_macos_candidate(self, monkeypatch):
        monkeypatch.setattr(platform_paths.sys, "platform", "darwin")
        candidate = platform_paths._desktop_local_storage_candidate()
        assert candidate is not None
        assert candidate.parts[-4:] == (
            "Application Support",
            "claude",
            "Local Storage",
            "leveldb",
        )

    def test_linux_candidate(self, monkeypatch):
        monkeypatch.setattr(platform_paths.sys, "platform", "linux")
        candidate = platform_paths._desktop_local_storage_candidate()
        assert candidate is not None
        assert candidate.parts[-4:] == (
            ".config",
            "claude",
            "Local Storage",
            "leveldb",
        )

    def test_windows_without_localappdata_falls_back(self, monkeypatch, tmp_path: Path):
        monkeypatch.setattr(platform_paths.sys, "platform", "win32")
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        # With no env var and no AppData/Local dir, result is None.
        monkeypatch.setattr(platform_paths.Path, "home", classmethod(lambda cls: tmp_path))
        candidate = platform_paths._desktop_local_storage_candidate()
        assert candidate is None


class TestDesktopLocalStorageDir:
    def test_returns_none_when_missing(self, monkeypatch, tmp_path: Path):
        monkeypatch.setattr(platform_paths.sys, "platform", "linux")
        monkeypatch.setattr(
            platform_paths.Path, "home", classmethod(lambda cls: tmp_path)
        )
        # .config/claude/... doesn't exist.
        assert platform_paths.desktop_local_storage_dir() is None

    def test_returns_path_when_present(self, monkeypatch, tmp_path: Path):
        monkeypatch.setattr(platform_paths.sys, "platform", "linux")
        monkeypatch.setattr(
            platform_paths.Path, "home", classmethod(lambda cls: tmp_path)
        )
        target = tmp_path / ".config" / "claude" / "Local Storage" / "leveldb"
        target.mkdir(parents=True)
        result = platform_paths.desktop_local_storage_dir()
        assert result == target


class TestPlatformLabel:
    @pytest.mark.parametrize(
        "plat,expected",
        [
            ("win32", "Windows"),
            ("cygwin", "Windows"),
            ("darwin", "macOS"),
            ("linux", "Linux"),
            ("linux2", "Linux"),
            ("freebsd", "freebsd"),
        ],
    )
    def test_label(self, monkeypatch, plat, expected):
        monkeypatch.setattr(platform_paths.sys, "platform", plat)
        assert platform_paths.platform_label() == expected
