"""Tests for :mod:`claude_repath.env_warn` — path-sensitive subdir warnings.

Unlike ``locks.py`` which inspects running processes, this scan is purely
static: it just looks at directory names + a sentinel file to tell a real
Python venv from a folder that happens to share the name. These tests build
minimal on-disk fixtures and assert the classifier's outputs.
"""

from __future__ import annotations

from pathlib import Path

from claude_repath.env_warn import (
    EnvSensitiveEntry,
    find_env_sensitive_subdirs,
    format_env_warn_report,
)


class TestFindEnvSensitiveSubdirs:
    def test_empty_when_path_missing(self, tmp_path: Path):
        assert find_env_sensitive_subdirs(tmp_path / "nope") == []

    def test_empty_when_path_is_file(self, tmp_path: Path):
        f = tmp_path / "file.txt"
        f.write_text("", encoding="utf-8")
        assert find_env_sensitive_subdirs(f) == []

    def test_empty_when_no_sensitive_subdirs(self, tmp_path: Path):
        (tmp_path / "src").mkdir()
        (tmp_path / "docs").mkdir()
        (tmp_path / "README.md").write_text("", encoding="utf-8")
        assert find_env_sensitive_subdirs(tmp_path) == []

    def test_detects_dotvenv_with_pyvenv_cfg(self, tmp_path: Path):
        venv = tmp_path / ".venv"
        venv.mkdir()
        (venv / "pyvenv.cfg").write_text("home = /x", encoding="utf-8")
        result = find_env_sensitive_subdirs(tmp_path)
        assert len(result) == 1
        assert result[0].kind == "Python venv"
        assert result[0].path == venv
        assert "python.exe" in result[0].reason or "uv sync" in result[0].reason

    def test_detects_plain_venv_with_pyvenv_cfg(self, tmp_path: Path):
        venv = tmp_path / "venv"
        venv.mkdir()
        (venv / "pyvenv.cfg").write_text("home = /x", encoding="utf-8")
        result = find_env_sensitive_subdirs(tmp_path)
        assert len(result) == 1
        assert result[0].path.name == "venv"

    def test_skips_venv_name_without_pyvenv_cfg(self, tmp_path: Path):
        """A ``.venv/`` folder lacking ``pyvenv.cfg`` is not a real venv — do
        not flag. This prevents false positives on unrelated folders sharing
        the name (e.g. someone's ``venv/`` containing requirement snippets).
        """
        venv = tmp_path / ".venv"
        venv.mkdir()
        (venv / "notes.md").write_text("placeholder", encoding="utf-8")
        assert find_env_sensitive_subdirs(tmp_path) == []

    def test_detects_node_modules(self, tmp_path: Path):
        nm = tmp_path / "node_modules"
        nm.mkdir()
        # No sentinel required — name is unique enough.
        result = find_env_sensitive_subdirs(tmp_path)
        assert len(result) == 1
        assert result[0].kind == "Node modules"
        assert result[0].path == nm

    def test_detects_multiple_entries(self, tmp_path: Path):
        venv = tmp_path / ".venv"
        venv.mkdir()
        (venv / "pyvenv.cfg").write_text("home = /x", encoding="utf-8")
        (tmp_path / "node_modules").mkdir()
        result = find_env_sensitive_subdirs(tmp_path)
        kinds = sorted(e.kind for e in result)
        assert kinds == ["Node modules", "Python venv"]

    def test_does_not_recurse_into_nested(self, tmp_path: Path):
        """Only the first level is scanned — nested venvs under ``src/`` are
        intentionally out of scope (monorepo case)."""
        nested = tmp_path / "src" / "sub" / ".venv"
        nested.mkdir(parents=True)
        (nested / "pyvenv.cfg").write_text("home = /x", encoding="utf-8")
        assert find_env_sensitive_subdirs(tmp_path) == []

    def test_ignores_file_named_venv(self, tmp_path: Path):
        """A regular file named ``.venv`` (weird but possible) must not match."""
        f = tmp_path / ".venv"
        f.write_text("", encoding="utf-8")
        assert find_env_sensitive_subdirs(tmp_path) == []


class TestFormatEnvWarnReport:
    def test_empty_list_returns_empty_string(self):
        assert format_env_warn_report([]) == ""

    def test_renders_each_entry(self, tmp_path: Path):
        venv = tmp_path / ".venv"
        nm = tmp_path / "node_modules"
        entries = [
            EnvSensitiveEntry(
                path=venv, kind="Python venv", reason="rebuild with uv sync"
            ),
            EnvSensitiveEntry(
                path=nm, kind="Node modules", reason="rebuild with npm ci"
            ),
        ]
        out = format_env_warn_report(entries)
        assert ".venv" in out
        assert "Python venv" in out
        assert "uv sync" in out
        assert "node_modules" in out
        assert "Node modules" in out
        assert "npm ci" in out
