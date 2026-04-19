"""Unit tests for :mod:`claude_repath.encoder`."""

from __future__ import annotations

from pathlib import Path

from claude_repath.encoder import WORKTREE_INFIX, encode_path, find_worktree_folders


class TestEncodePath:
    def test_windows_path_backslash(self):
        assert encode_path(r"D:\dev_code\time-blocks") == "D--dev-code-time-blocks"

    def test_windows_path_forward_slash(self):
        assert encode_path("D:/dev_code/time-blocks") == "D--dev-code-time-blocks"

    def test_posix_path(self):
        assert encode_path("/home/user/project") == "-home-user-project"

    def test_case_preserved_uppercase(self):
        assert encode_path(r"D:\dev_code\Life\time-blocks") == "D--dev-code-Life-time-blocks"

    def test_case_preserved_lowercase(self):
        assert encode_path(r"D:\dev_code\life\time-blocks") == "D--dev-code-life-time-blocks"

    def test_underscore_becomes_hyphen(self):
        assert encode_path(r"D:\dev_code\foo") == "D--dev-code-foo"

    def test_existing_hyphens_preserved_as_hyphens(self):
        assert encode_path("time-blocks") == "time-blocks"

    def test_consecutive_non_alnum_not_collapsed(self):
        assert encode_path("//foo") == "--foo"
        assert encode_path(r"D:\\foo") == "D---foo"

    def test_worktree_path_encoding(self):
        assert (
            encode_path(r"D:\dev_code\time-blocks\.claude\worktrees\feat-x")
            == "D--dev-code-time-blocks--claude-worktrees-feat-x"
        )

    def test_worktree_infix_constant(self):
        # The WORKTREE_INFIX must match what encode_path produces for the
        # literal ``\.claude\worktrees\`` segment (including leading backslash).
        assert encode_path(r"\.claude\worktrees\x").startswith(WORKTREE_INFIX)

    def test_digits_preserved(self):
        assert encode_path("D:/proj3py2") == "D--proj3py2"

    def test_non_ascii_treated_as_non_alnum(self):
        # Chinese characters are outside [a-zA-Z0-9]; each becomes one hyphen.
        assert encode_path("ab项目cd") == "ab--cd"

    def test_path_object_accepted(self):
        assert encode_path(Path("/foo/bar")) == "-foo-bar"

    def test_empty_string(self):
        assert encode_path("") == ""

    def test_only_alnum(self):
        assert encode_path("abc123") == "abc123"


class TestFindWorktreeFolders:
    def test_finds_matching_worktrees_sorted(self, tmp_path: Path):
        projects = tmp_path / "projects"
        projects.mkdir()
        base = "D--dev-code-time-blocks"
        (projects / f"{base}{WORKTREE_INFIX}feat").mkdir()
        (projects / f"{base}{WORKTREE_INFIX}bugfix").mkdir()
        (projects / base).mkdir()  # the base project itself — must not match
        (projects / "D--other-project").mkdir()  # unrelated
        (projects / f"{base}-sibling").mkdir()  # prefix starts same but no worktree infix

        result = [p.name for p in find_worktree_folders(base, projects)]

        assert result == [
            f"{base}{WORKTREE_INFIX}bugfix",
            f"{base}{WORKTREE_INFIX}feat",
        ]

    def test_missing_projects_dir_returns_empty(self, tmp_path: Path):
        assert find_worktree_folders("D--anything", tmp_path / "nope") == []

    def test_no_matches_returns_empty(self, tmp_path: Path):
        projects = tmp_path / "projects"
        projects.mkdir()
        (projects / "D--other").mkdir()
        assert find_worktree_folders("D--foo", projects) == []

    def test_skips_regular_files(self, tmp_path: Path):
        projects = tmp_path / "projects"
        projects.mkdir()
        base = "D--foo"
        (projects / f"{base}{WORKTREE_INFIX}file").write_text("not a dir")
        (projects / f"{base}{WORKTREE_INFIX}dir").mkdir()

        result = [p.name for p in find_worktree_folders(base, projects)]

        assert result == [f"{base}{WORKTREE_INFIX}dir"]
