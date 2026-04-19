"""Tests for :mod:`claude_repath.tui` (pure/offline functions only).

The interactive questionary parts are not tested here — they require a TTY.
"""

from __future__ import annotations

import json
from pathlib import Path

from claude_repath.tui import _extract_cwd_from_sessions, _find_cwd, discover_projects


class TestFindCwd:
    def test_top_level_cwd(self):
        assert _find_cwd({"cwd": "D:/foo", "other": 1}) == "D:/foo"

    def test_nested_cwd(self):
        obj = {"meta": {"session": {"cwd": "D:/nested"}}}
        assert _find_cwd(obj) == "D:/nested"

    def test_in_list(self):
        obj = [{"cwd": "D:/in/list"}]
        assert _find_cwd(obj) == "D:/in/list"

    def test_no_cwd_returns_none(self):
        assert _find_cwd({"other": "x"}) is None

    def test_empty_cwd_treated_as_missing(self):
        assert _find_cwd({"cwd": ""}) is None

    def test_max_depth_limit(self):
        # Ensure we don't recurse infinitely on deeply nested structures.
        obj = {"a": {"b": {"c": {"d": {"e": {"cwd": "deep"}}}}}}
        # Default max_depth=3, so cwd buried 5 levels deep won't be found.
        assert _find_cwd(obj) is None

    def test_non_string_cwd_rejected(self):
        assert _find_cwd({"cwd": 123}) is None


class TestExtractCwdFromSessions:
    def test_reads_cwd_from_first_jsonl_line(self, tmp_path: Path):
        proj = tmp_path / "p"
        proj.mkdir()
        (proj / "s.jsonl").write_text(
            json.dumps({"cwd": r"D:\real\path", "msg": "hi"}) + "\n",
            encoding="utf-8",
        )
        assert _extract_cwd_from_sessions(proj) == r"D:\real\path"

    def test_skips_blank_lines(self, tmp_path: Path):
        proj = tmp_path / "p"
        proj.mkdir()
        (proj / "s.jsonl").write_text(
            "\n\n" + json.dumps({"cwd": "X"}) + "\n", encoding="utf-8"
        )
        assert _extract_cwd_from_sessions(proj) == "X"

    def test_tries_newest_file_first(self, tmp_path: Path):
        proj = tmp_path / "p"
        proj.mkdir()
        older = proj / "older.jsonl"
        older.write_text(json.dumps({"cwd": "old_cwd"}) + "\n", encoding="utf-8")
        newer = proj / "newer.jsonl"
        newer.write_text(json.dumps({"cwd": "new_cwd"}) + "\n", encoding="utf-8")
        # Set mtimes explicitly: newer.jsonl > older.jsonl.
        import os
        os.utime(older, (1000, 1000))
        os.utime(newer, (2000, 2000))

        assert _extract_cwd_from_sessions(proj) == "new_cwd"

    def test_no_jsonls_returns_none(self, tmp_path: Path):
        proj = tmp_path / "p"
        proj.mkdir()
        assert _extract_cwd_from_sessions(proj) is None

    def test_malformed_json_falls_through(self, tmp_path: Path):
        proj = tmp_path / "p"
        proj.mkdir()
        (proj / "broken.jsonl").write_text("{not-json\n", encoding="utf-8")
        (proj / "good.jsonl").write_text(
            json.dumps({"cwd": "G"}) + "\n", encoding="utf-8"
        )
        # Both files read; good.jsonl provides cwd eventually (order by mtime).
        result = _extract_cwd_from_sessions(proj)
        assert result == "G"


class TestDiscoverProjects:
    def test_lists_top_level_projects_skipping_worktrees(self, tmp_path: Path):
        projects = tmp_path / "projects"
        projects.mkdir()
        # Main project with a session.
        main = projects / "D--dev-code-x"
        main.mkdir()
        (main / "s.jsonl").write_text(
            json.dumps({"cwd": r"D:\dev_code\x"}) + "\n", encoding="utf-8"
        )
        # Worktree sub-project (should be filtered out).
        wt = projects / "D--dev-code-x--claude-worktrees-feat"
        wt.mkdir()
        (wt / "s.jsonl").write_text(
            json.dumps({"cwd": r"D:\dev_code\x\.claude\worktrees\feat"}) + "\n",
            encoding="utf-8",
        )
        # Another top-level project with no jsonl (edge case: show unknown).
        empty = projects / "D--dev-code-empty"
        empty.mkdir()

        result = discover_projects(projects)

        names = {folder.name for folder, _cwd, _n in result}
        assert "D--dev-code-x" in names
        assert "D--dev-code-x--claude-worktrees-feat" not in names
        assert "D--dev-code-empty" in names

        # The x project should have the real cwd extracted.
        cwds = {folder.name: cwd for folder, cwd, _n in result}
        assert cwds["D--dev-code-x"] == r"D:\dev_code\x"
        assert cwds["D--dev-code-empty"].startswith("<unknown")

    def test_missing_projects_dir(self, tmp_path: Path):
        assert discover_projects(tmp_path / "nope") == []

    def test_session_count_correct(self, tmp_path: Path):
        projects = tmp_path / "projects"
        projects.mkdir()
        main = projects / "D--x"
        main.mkdir()
        for i in range(3):
            (main / f"s{i}.jsonl").write_text(
                json.dumps({"cwd": "X"}) + "\n", encoding="utf-8"
            )
        result = discover_projects(projects)
        assert len(result) == 1
        _folder, _cwd, n = result[0]
        assert n == 3
