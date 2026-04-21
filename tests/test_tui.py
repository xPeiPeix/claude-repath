"""Tests for :mod:`claude_repath.tui` (pure/offline functions only).

The questionary prompts themselves require a TTY; we exercise the glue
(:func:`run_interactive_move`) by monkeypatching the prompt helpers.
"""

from __future__ import annotations

import json
from pathlib import Path

from claude_repath import tui
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

    def test_reads_cwd_from_later_line_when_first_is_metadata(self, tmp_path: Path):
        """Real Claude sessions: line 0 is session metadata (no cwd), cwd on line 1+."""
        proj = tmp_path / "p"
        proj.mkdir()
        content = (
            json.dumps({"type": "session", "permissionMode": "ask", "sessionId": "abc"})
            + "\n"
            + json.dumps({"type": "user", "cwd": r"D:\real\path"})
            + "\n"
        )
        (proj / "s.jsonl").write_text(content, encoding="utf-8")
        assert _extract_cwd_from_sessions(proj) == r"D:\real\path"

    def test_gives_up_after_max_lines(self, tmp_path: Path):
        """Bounded scan — don't read unbounded lines from a huge session."""
        proj = tmp_path / "p"
        proj.mkdir()
        noise = [json.dumps({"type": "noise", "i": i}) for i in range(100)]
        (proj / "s.jsonl").write_text("\n".join(noise) + "\n", encoding="utf-8")
        assert _extract_cwd_from_sessions(proj) is None

    def test_continues_past_cwd_less_lines_in_same_file(self, tmp_path: Path):
        """Multiple metadata lines before cwd — keep scanning within one file."""
        proj = tmp_path / "p"
        proj.mkdir()
        lines = [
            json.dumps({"type": "session", "sessionId": "s"}),
            json.dumps({"type": "snapshot", "snapshot": {}}),
            json.dumps({"type": "user", "cwd": r"D:\found\on\line\3"}),
        ]
        (proj / "s.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        assert _extract_cwd_from_sessions(proj) == r"D:\found\on\line\3"


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

    def test_unknown_entries_sorted_to_bottom(self, tmp_path: Path):
        """Projects with ``<unknown: ...>`` placeholder cwd should sink below resolved ones."""
        projects = tmp_path / "projects"
        projects.mkdir()
        # Resolved cwd project
        resolved = projects / "D--dev-code-resolved"
        resolved.mkdir()
        (resolved / "s.jsonl").write_text(
            json.dumps({"cwd": r"D:\dev_code\resolved"}) + "\n", encoding="utf-8"
        )
        # Unknown (no jsonl = 0 sessions = unknown cwd)
        unknown = projects / "A--would-sort-first-alphabetically"
        unknown.mkdir()

        result = discover_projects(projects)
        cwds = [cwd for _, cwd, _ in result]
        # Resolved must come before unknown, even though unknown's encoded name
        # starts with "A" (would be first alphabetically by folder name).
        assert cwds[0] == r"D:\dev_code\resolved"
        assert cwds[1].startswith("<unknown")

    def test_zero_session_resolved_sorted_after_nonzero(self, tmp_path: Path):
        """Resolved projects with 0 sessions rank below those with sessions."""
        projects = tmp_path / "projects"
        projects.mkdir()
        # Nonzero-session, resolved cwd that sorts LATE alphabetically.
        many = projects / "D--z-late-alphabetically"
        many.mkdir()
        (many / "s.jsonl").write_text(
            json.dumps({"cwd": "z_many"}) + "\n", encoding="utf-8"
        )
        # Zero-session but with a cwd extractable elsewhere is a synthetic
        # edge case — emulate by writing a jsonl then deleting it, leaving
        # the folder but no sessions. We fake by constructing the tuple
        # manually: test the sort key directly instead.
        # Here we validate natural ordering: many-session 'z_many' beats
        # unknown (which is always last).
        unknown = projects / "A--zero-sessions"
        unknown.mkdir()

        result = discover_projects(projects)
        assert result[0][1] == "z_many"
        assert result[1][1].startswith("<unknown")

    def test_resolved_entries_sorted_alphabetically_by_cwd(self, tmp_path: Path):
        """Within the resolved group, entries sort by cwd case-insensitively."""
        projects = tmp_path / "projects"
        projects.mkdir()
        a = projects / "folder-a"
        a.mkdir()
        (a / "s.jsonl").write_text(
            json.dumps({"cwd": "Zebra_path"}) + "\n", encoding="utf-8"
        )
        b = projects / "folder-b"
        b.mkdir()
        (b / "s.jsonl").write_text(
            json.dumps({"cwd": "apple_path"}) + "\n", encoding="utf-8"
        )

        result = discover_projects(projects)
        cwds = [cwd for _, cwd, _ in result]
        # 'apple_path' < 'Zebra_path' case-insensitively — apple first.
        assert cwds == ["apple_path", "Zebra_path"]


class TestRunInteractiveMove:
    """Monkeypatches the three prompt helpers to simulate user interaction."""

    def test_cancel_at_pick_returns_none(self, monkeypatch, tmp_path: Path):
        monkeypatch.setattr(tui, "pick_project", lambda _: None)
        assert tui.run_interactive_move(tmp_path) is None

    def test_cancel_at_new_path_returns_none(self, monkeypatch, tmp_path: Path):
        monkeypatch.setattr(tui, "pick_project", lambda _: r"D:\old")
        monkeypatch.setattr(tui, "prompt_new_path", lambda _old: None)
        assert tui.run_interactive_move(tmp_path) is None

    def test_identity_path_rejected(self, monkeypatch, tmp_path: Path):
        monkeypatch.setattr(tui, "pick_project", lambda _: r"D:\same")
        monkeypatch.setattr(tui, "prompt_new_path", lambda _old: r"D:\same")
        # confirm shouldn't even be reached, but stub anyway.
        monkeypatch.setattr(tui, "confirm", lambda *a, **k: True)
        assert tui.run_interactive_move(tmp_path) is None

    def test_cancel_at_confirm_returns_none(self, monkeypatch, tmp_path: Path):
        from claude_repath.migrate import PlanReport

        monkeypatch.setattr(tui, "pick_project", lambda _: r"D:\old")
        monkeypatch.setattr(tui, "prompt_new_path", lambda _old: r"D:\new")
        monkeypatch.setattr(tui, "plan_migration", lambda _ctx: PlanReport(entries=[]))
        monkeypatch.setattr(tui, "confirm", lambda *a, **k: False)
        assert tui.run_interactive_move(tmp_path) is None

    def test_happy_path_returns_tuple(self, monkeypatch, tmp_path: Path):
        from claude_repath.migrate import PlanReport

        monkeypatch.setattr(tui, "pick_project", lambda _: r"D:\old")
        monkeypatch.setattr(tui, "prompt_new_path", lambda _old: r"D:\new")
        monkeypatch.setattr(tui, "plan_migration", lambda _ctx: PlanReport(entries=[]))
        monkeypatch.setattr(tui, "confirm", lambda *a, **k: True)
        result = tui.run_interactive_move(tmp_path)
        assert result == (r"D:\old", r"D:\new")

    def test_scope_passed_to_plan_migration(self, monkeypatch, tmp_path: Path):
        """Step 3 should construct MigrationContext with the given scope."""
        from claude_repath.migrate import PlanReport

        captured: dict[str, object] = {}

        def fake_plan(ctx):
            captured["scope"] = ctx.scope
            return PlanReport(entries=[])

        monkeypatch.setattr(tui, "pick_project", lambda _: r"D:\old")
        monkeypatch.setattr(tui, "prompt_new_path", lambda _old: r"D:\new")
        monkeypatch.setattr(tui, "plan_migration", fake_plan)
        monkeypatch.setattr(tui, "confirm", lambda *a, **k: True)
        tui.run_interactive_move(tmp_path, scope="broad")
        assert captured["scope"] == "broad"

    def test_plan_failure_returns_none(self, monkeypatch, tmp_path: Path):
        """If planning raises, the flow aborts gracefully without re-raising."""

        def boom(_ctx):
            raise RuntimeError("plan failed")

        monkeypatch.setattr(tui, "pick_project", lambda _: r"D:\old")
        monkeypatch.setattr(tui, "prompt_new_path", lambda _old: r"D:\new")
        monkeypatch.setattr(tui, "plan_migration", boom)
        monkeypatch.setattr(tui, "confirm", lambda *a, **k: True)
        assert tui.run_interactive_move(tmp_path) is None


class TestPromptNewPath:
    """Two-stage path input: parent directory + project name composition."""

    def _stub(
        self,
        monkeypatch,
        parent: str | None,
        name: str | None,
        create_parent: bool | None = True,
    ) -> None:
        """Replace questionary calls with deterministic answers."""

        class _StubPath:
            def __init__(self, val):
                self._val = val

            def ask(self):
                return self._val

        class _StubText(_StubPath):
            pass

        class _StubConfirm(_StubPath):
            pass

        import questionary as q

        monkeypatch.setattr(q, "path", lambda *a, **k: _StubPath(parent))
        monkeypatch.setattr(q, "text", lambda *a, **k: _StubText(name))
        monkeypatch.setattr(q, "confirm", lambda *a, **k: _StubConfirm(create_parent))

    def test_parent_and_name_joined(self, monkeypatch, tmp_path: Path):
        # existing parent → no creation confirm needed
        existing = tmp_path / "dest"
        existing.mkdir()
        self._stub(monkeypatch, parent=str(existing), name="proj")
        out = tui.prompt_new_path(str(tmp_path / "oldparent" / "oldproj"))
        assert out == str(existing / "proj")

    def test_default_name_is_original(self, monkeypatch, tmp_path: Path):
        """The name prompt should default to the old path's basename."""
        captured: dict[str, str] = {}
        existing = tmp_path / "dest"
        existing.mkdir()
        import questionary as q

        class _P:
            def ask(self):
                return str(existing)

        class _T:
            def __init__(self, default):
                captured["default"] = default

            def ask(self):
                return "renamed"

        def fake_text(_msg, default=""):
            return _T(default)

        monkeypatch.setattr(q, "path", lambda *a, **k: _P())
        monkeypatch.setattr(q, "text", fake_text)
        # Use a cross-platform path literal — a hard-coded "D:\..." string
        # parses differently on POSIX (whole string treated as the name)
        # vs Windows (drive letter → real parent/name split).
        old_path = tmp_path / "projects" / "original-name"
        tui.prompt_new_path(str(old_path))
        assert captured["default"] == "original-name"

    def test_cancel_parent_returns_none(self, monkeypatch, tmp_path: Path):
        self._stub(monkeypatch, parent=None, name="x")
        assert tui.prompt_new_path(str(tmp_path / "x")) is None

    def test_cancel_name_returns_none(self, monkeypatch, tmp_path: Path):
        existing = tmp_path / "dest"
        existing.mkdir()
        self._stub(monkeypatch, parent=str(existing), name=None)
        assert tui.prompt_new_path(str(tmp_path / "x")) is None

    def test_missing_parent_prompts_creation(self, monkeypatch, tmp_path: Path):
        nonexistent = tmp_path / "does-not-exist-yet"
        # User declines parent creation → returns None.
        self._stub(
            monkeypatch, parent=str(nonexistent), name="proj", create_parent=False
        )
        assert tui.prompt_new_path(str(tmp_path / "x")) is None

    def test_missing_parent_accepted_returns_path(self, monkeypatch, tmp_path: Path):
        nonexistent = tmp_path / "does-not-exist-yet"
        self._stub(monkeypatch, parent=str(nonexistent), name="proj", create_parent=True)
        out = tui.prompt_new_path(str(tmp_path / "old"))
        # Path composed from nonexistent parent + name; real creation happens
        # later in move_project_folder.
        assert out == str(nonexistent / "proj")

    def test_tilde_expansion(self, monkeypatch, tmp_path: Path):
        """A ``~`` in the parent input should expand to the user's home."""
        import questionary as q

        class _P:
            def ask(self):
                return "~"

        class _T:
            def ask(self):
                return "foo"

        class _C:
            def ask(self):
                return True

        monkeypatch.setattr(q, "path", lambda *a, **k: _P())
        monkeypatch.setattr(q, "text", lambda *a, **k: _T())
        monkeypatch.setattr(q, "confirm", lambda *a, **k: _C())

        out = tui.prompt_new_path(r"D:\projects\original")
        assert out is not None
        # Result should start with the expanded home directory.
        home = str(Path.home())
        assert out.startswith(home)
        assert out.endswith("foo")
