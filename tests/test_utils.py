"""Tests for :mod:`claude_repath.utils`."""

from __future__ import annotations

from claude_repath.utils import patch_string_fields, rewrite_path_value


class TestRewritePathValue:
    def test_exact_match(self):
        assert rewrite_path_value(
            r"D:\dev_code\time-blocks",
            r"D:\dev_code\time-blocks",
            r"D:\dev_code\Life\time-blocks",
        ) == (r"D:\dev_code\Life\time-blocks", True)

    def test_prefix_match_backslash(self):
        assert rewrite_path_value(
            r"D:\dev_code\time-blocks\.claude\worktrees\feat",
            r"D:\dev_code\time-blocks",
            r"D:\dev_code\Life\time-blocks",
        ) == (r"D:\dev_code\Life\time-blocks\.claude\worktrees\feat", True)

    def test_prefix_match_forward_slash(self):
        assert rewrite_path_value(
            "/home/user/proj/sub",
            "/home/user/proj",
            "/new/place/proj",
        ) == ("/new/place/proj/sub", True)

    def test_no_match(self):
        assert rewrite_path_value("unrelated", r"D:\a", r"D:\b") == ("unrelated", False)

    def test_similar_prefix_is_not_match(self):
        # "D:\\dev_code\\time-blocks-chronospect" must NOT match prefix of
        # "D:\\dev_code\\time-blocks" because the next char is "-" not a separator.
        assert rewrite_path_value(
            r"D:\dev_code\time-blocks-chronospect",
            r"D:\dev_code\time-blocks",
            r"D:\dev_code\Life\time-blocks",
        ) == (r"D:\dev_code\time-blocks-chronospect", False)

    def test_empty_old_path_edge_case(self):
        # Not a real case but shouldn't crash. An empty old_path doesn't match
        # "anything" exactly, and "anything".startswith("\\") is False, so
        # no change is made.
        val, changed = rewrite_path_value("anything", "", "REPLACED")
        assert changed is False

    def test_forward_slash_value_with_backslash_input(self):
        # User supplies backslash form; value in file uses forward slashes
        # (this is the real ~/.claude.json case).
        assert rewrite_path_value(
            "D:/dev_code/time-blocks",
            r"D:\dev_code\time-blocks",
            r"D:\dev_code\Life\time-blocks",
        ) == ("D:/dev_code/Life/time-blocks", True)

    def test_forward_slash_prefix_preserves_style(self):
        assert rewrite_path_value(
            "D:/dev_code/time-blocks/sub/file.py",
            r"D:\dev_code\time-blocks",
            r"D:\dev_code\Life\time-blocks",
        ) == ("D:/dev_code/Life/time-blocks/sub/file.py", True)

    def test_backslash_value_with_forward_slash_input(self):
        assert rewrite_path_value(
            r"D:\dev_code\time-blocks\sub",
            "D:/dev_code/time-blocks",
            "D:/dev_code/Life/time-blocks",
        ) == (r"D:\dev_code\Life\time-blocks\sub", True)

    def test_similar_prefix_still_not_match_with_style_variants(self):
        # Even with separator tolerance, "-chronospect" is not "sep + more".
        assert rewrite_path_value(
            "D:/dev_code/time-blocks-chronospect",
            r"D:\dev_code\time-blocks",
            r"D:\dev_code\Life\time-blocks",
        ) == ("D:/dev_code/time-blocks-chronospect", False)


class TestPatchStringFields:
    def test_patches_named_field_only(self):
        obj = {"cwd": r"D:\a", "other": r"D:\a"}
        changed = patch_string_fields(obj, r"D:\a", r"D:\b", frozenset({"cwd"}))
        assert changed
        assert obj == {"cwd": r"D:\b", "other": r"D:\a"}

    def test_patches_all_strings_when_fields_none(self):
        obj = {"cwd": r"D:\a", "other": r"D:\a"}
        changed = patch_string_fields(obj, r"D:\a", r"D:\b", field_names=None)
        assert changed
        assert obj == {"cwd": r"D:\b", "other": r"D:\b"}

    def test_recurses_into_nested_dict(self):
        obj = {"meta": {"cwd": r"D:\a"}}
        changed = patch_string_fields(obj, r"D:\a", r"D:\b", frozenset({"cwd"}))
        assert changed
        assert obj == {"meta": {"cwd": r"D:\b"}}

    def test_recurses_into_list(self):
        obj = {"items": [{"cwd": r"D:\a"}, {"cwd": r"D:\other"}]}
        changed = patch_string_fields(obj, r"D:\a", r"D:\b", frozenset({"cwd"}))
        assert changed
        assert obj["items"][0]["cwd"] == r"D:\b"
        assert obj["items"][1]["cwd"] == r"D:\other"

    def test_no_change_returns_false(self):
        obj = {"cwd": "unrelated"}
        changed = patch_string_fields(obj, r"D:\a", r"D:\b", frozenset({"cwd"}))
        assert not changed
        assert obj == {"cwd": "unrelated"}

    def test_list_of_strings_when_fields_none(self):
        obj = [r"D:\a", "other", r"D:\a\sub"]
        changed = patch_string_fields(obj, r"D:\a", r"D:\b", field_names=None)
        assert changed
        assert obj == [r"D:\b", "other", r"D:\b\sub"]
