"""Tests for :mod:`claude_repath.locks` — pre-flight lock detection.

Uses monkeypatched ``psutil.process_iter`` returning fake Process-like
objects; no real processes are inspected. ``open_files()`` entries use a
minimal namedtuple-style shim matching psutil's ``sopen`` ``popenfile``
fields.
"""

from __future__ import annotations

from typing import NamedTuple

import psutil
import pytest

from claude_repath.locks import (
    LockEntry,
    _is_subpath,
    find_locks_on_path,
    format_lock_report,
)


class _FakeOpenFile(NamedTuple):
    path: str
    fd: int = -1


class _FakeProc:
    """Minimal stand-in for ``psutil.Process`` that supports info/cwd/open_files."""

    def __init__(
        self,
        pid: int,
        name: str = "fake",
        cwd: str | None = None,
        open_files: list[_FakeOpenFile] | None = None,
        cwd_raises: type[Exception] | None = None,
        open_files_raises: type[Exception] | None = None,
    ):
        self.info = {"pid": pid, "name": name}
        self._cwd = cwd
        self._open_files = open_files or []
        self._cwd_raises = cwd_raises
        self._open_files_raises = open_files_raises

    def cwd(self) -> str | None:
        if self._cwd_raises:
            raise self._cwd_raises(pid=self.info["pid"])
        return self._cwd

    def open_files(self) -> list[_FakeOpenFile]:
        if self._open_files_raises:
            raise self._open_files_raises(pid=self.info["pid"])
        return self._open_files


@pytest.fixture
def patch_process_iter(monkeypatch):
    """Return a setter that replaces ``psutil.process_iter`` with a fixed list."""

    def _set(procs: list[_FakeProc]) -> None:
        monkeypatch.setattr(
            psutil, "process_iter", lambda **_kw: iter(procs)
        )

    return _set


class TestIsSubpath:
    def test_exact_match(self, tmp_path):
        assert _is_subpath(tmp_path, tmp_path) is True

    def test_direct_child(self, tmp_path):
        child = tmp_path / "a"
        child.mkdir()
        assert _is_subpath(child, tmp_path) is True

    def test_nested_grandchild(self, tmp_path):
        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)
        assert _is_subpath(nested, tmp_path) is True

    def test_sibling_is_not_subpath(self, tmp_path):
        other = tmp_path.parent / "sibling-that-doesnt-exist"
        assert _is_subpath(other, tmp_path) is False

    def test_parent_is_not_subpath(self, tmp_path):
        child = tmp_path / "a"
        child.mkdir()
        assert _is_subpath(tmp_path, child) is False


class TestFindLocksOnPath:
    def test_empty_when_path_does_not_exist(self, tmp_path, patch_process_iter):
        patch_process_iter([_FakeProc(pid=1, cwd=str(tmp_path))])
        nonexistent = tmp_path / "nope"
        assert find_locks_on_path(nonexistent) == []

    def test_detects_cwd_inside_target(self, tmp_path, patch_process_iter):
        target = tmp_path / "proj"
        target.mkdir()
        inside = target / "sub"
        inside.mkdir()
        patch_process_iter(
            [_FakeProc(pid=1234, name="bash.exe", cwd=str(inside))]
        )
        result = find_locks_on_path(target)
        assert len(result) == 1
        assert result[0].pid == 1234
        assert result[0].name == "bash.exe"
        assert "cwd=" in result[0].reason

    def test_detects_open_file_inside_target(self, tmp_path, patch_process_iter):
        target = tmp_path / "proj"
        target.mkdir()
        locked_file = target / "main.py"
        locked_file.write_text("x = 1")
        patch_process_iter(
            [
                _FakeProc(
                    pid=5678,
                    name="code.exe",
                    cwd=None,
                    open_files=[_FakeOpenFile(path=str(locked_file))],
                )
            ]
        )
        result = find_locks_on_path(target)
        assert len(result) == 1
        assert result[0].pid == 5678
        assert "open_file=" in result[0].reason

    def test_skips_unrelated_processes(self, tmp_path, patch_process_iter):
        target = tmp_path / "proj"
        target.mkdir()
        other = tmp_path / "elsewhere"
        other.mkdir()
        patch_process_iter([_FakeProc(pid=1, cwd=str(other))])
        assert find_locks_on_path(target) == []

    def test_skips_access_denied_cwd(self, tmp_path, patch_process_iter):
        target = tmp_path / "proj"
        target.mkdir()
        # Process raises AccessDenied on cwd() but has no open_files — skip.
        patch_process_iter(
            [_FakeProc(pid=1, cwd_raises=psutil.AccessDenied, open_files=[])]
        )
        assert find_locks_on_path(target) == []

    def test_skips_no_such_process(self, tmp_path, patch_process_iter):
        target = tmp_path / "proj"
        target.mkdir()
        patch_process_iter(
            [_FakeProc(pid=1, cwd_raises=psutil.NoSuchProcess, open_files=[])]
        )
        assert find_locks_on_path(target) == []

    def test_one_entry_per_process_even_with_multiple_reasons(
        self, tmp_path, patch_process_iter
    ):
        """A process with both cwd and open_file inside target reports once."""
        target = tmp_path / "proj"
        target.mkdir()
        f = target / "main.py"
        f.write_text("")
        patch_process_iter(
            [
                _FakeProc(
                    pid=42,
                    name="ide",
                    cwd=str(target),
                    open_files=[_FakeOpenFile(path=str(f))],
                )
            ]
        )
        result = find_locks_on_path(target)
        assert len(result) == 1
        # cwd is checked before open_files, so cwd wins as the reported reason.
        assert result[0].reason.startswith("cwd=")


class TestFormatLockReport:
    def test_empty_list_returns_empty_string(self):
        assert format_lock_report([]) == ""

    def test_renders_entries_with_pid_name_reason(self):
        entries = [
            LockEntry(pid=123, name="bash", reason="cwd=/x"),
            LockEntry(pid=456, name="code.exe", reason="open_file=/x/main.py"),
        ]
        out = format_lock_report(entries)
        assert "123" in out
        assert "bash" in out
        assert "cwd=/x" in out
        assert "456" in out
        assert "code.exe" in out
        assert "open_file=/x/main.py" in out
