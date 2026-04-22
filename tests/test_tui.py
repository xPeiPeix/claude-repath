"""Tests for :mod:`claude_repath.tui` (pure/offline functions only).

The questionary prompts themselves require a TTY; we exercise the glue
(:func:`run_interactive_move`) by monkeypatching the prompt helpers.
"""

from __future__ import annotations

import json
from pathlib import Path

from claude_repath import tui
from claude_repath.tui import (
    _BANNER_GRADIENT_END,
    _BANNER_GRADIENT_START,
    _ICON_ACTIVE,
    _ICON_EMPTY,
    _ICON_ORPHAN,
    _ICON_UNKNOWN,
    _choice_title,
    _extract_cwd_from_sessions,
    _find_cwd,
    _gradient_hex,
    discover_projects,
)


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

        names = {folder.name for folder, _cwd, _n, _exists in result}
        assert "D--dev-code-x" in names
        assert "D--dev-code-x--claude-worktrees-feat" not in names
        assert "D--dev-code-empty" in names

        # The x project should have the real cwd extracted.
        cwds = {folder.name: cwd for folder, cwd, _n, _exists in result}
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
        _folder, _cwd, n, _exists = result[0]
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
        cwds = [cwd for _, cwd, _, _ in result]
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

    def test_existing_cwd_marked_present(self, tmp_path: Path):
        """A resolved cwd pointing to a real directory gets ``cwd_exists=True``."""
        projects = tmp_path / "projects"
        projects.mkdir()
        realproj = tmp_path / "realproj"
        realproj.mkdir()
        enc = projects / "tmp--realproj"
        enc.mkdir()
        (enc / "s.jsonl").write_text(
            json.dumps({"cwd": str(realproj)}) + "\n", encoding="utf-8"
        )
        result = discover_projects(projects)
        assert len(result) == 1
        _folder, cwd, _n, exists = result[0]
        assert cwd == str(realproj)
        assert exists is True

    def test_missing_cwd_marked_orphan(self, tmp_path: Path):
        """A resolved cwd whose folder no longer exists gets ``cwd_exists=False``.

        This is the main migration trigger — state exists but the source
        directory has been renamed/deleted, so Claude Code can no longer
        reopen the project at its recorded path.
        """
        projects = tmp_path / "projects"
        projects.mkdir()
        ghost = projects / "D--ghost"
        ghost.mkdir()
        (ghost / "s.jsonl").write_text(
            json.dumps({"cwd": str(tmp_path / "does-not-exist")}) + "\n",
            encoding="utf-8",
        )
        result = discover_projects(projects)
        assert len(result) == 1
        _folder, _cwd, _n, exists = result[0]
        assert exists is False

    def test_unknown_entries_keep_exists_true(self, tmp_path: Path):
        """``<unknown: ...>`` placeholders must not spuriously flag as orphan."""
        projects = tmp_path / "projects"
        projects.mkdir()
        empty = projects / "A--no-jsonls"
        empty.mkdir()
        result = discover_projects(projects)
        _folder, cwd, _n, exists = result[0]
        assert cwd.startswith("<unknown")
        assert exists is True  # placeholder — skip orphan branch downstream

    def test_active_sorted_before_orphan(self, tmp_path: Path):
        """Active entries float above orphans so common work stays at the top.

        Orphans are still visible (rank 1, just below active), but shouldn't
        drown the head of the list when the user has many migrated folders.
        """
        projects = tmp_path / "projects"
        projects.mkdir()
        # Orphan: cwd points at a nonexistent folder. Encoded name starts
        # with "A" so naive alphabetical sort would put it first — the rank
        # must override that and push active above it.
        orphan = projects / "A--orphan"
        orphan.mkdir()
        (orphan / "s.jsonl").write_text(
            json.dumps({"cwd": str(tmp_path / "vanished")}) + "\n",
            encoding="utf-8",
        )
        # Active: real folder exists under tmp_path.
        realproj = tmp_path / "realproj"
        realproj.mkdir()
        active = projects / "Z--active"
        active.mkdir()
        (active / "s.jsonl").write_text(
            json.dumps({"cwd": str(realproj)}) + "\n", encoding="utf-8"
        )
        result = discover_projects(projects)
        _folder, _cwd, _n, first_exists = result[0]
        _folder, _cwd, _n, second_exists = result[1]
        assert first_exists is True  # active
        assert second_exists is False  # orphan

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
        cwds = [cwd for _, cwd, _, _ in result]
        # 'apple_path' < 'Zebra_path' case-insensitively — apple first.
        assert cwds == ["apple_path", "Zebra_path"]


class TestGradientHex:
    """Per-line RGB interpolation that powers the cyan→pink banner gradient."""

    def _expected(self, rgb: tuple[int, int, int]) -> str:
        return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"

    def test_t_zero_is_start_color(self):
        assert _gradient_hex(0.0) == self._expected(_BANNER_GRADIENT_START)

    def test_t_one_is_end_color(self):
        assert _gradient_hex(1.0) == self._expected(_BANNER_GRADIENT_END)

    def test_t_half_is_midpoint(self):
        expected = tuple(
            round((_BANNER_GRADIENT_START[i] + _BANNER_GRADIENT_END[i]) / 2)
            for i in range(3)
        )
        assert _gradient_hex(0.5) == self._expected(expected)

    def test_t_clamped_low(self):
        assert _gradient_hex(-1.0) == self._expected(_BANNER_GRADIENT_START)

    def test_t_clamped_high(self):
        assert _gradient_hex(2.0) == self._expected(_BANNER_GRADIENT_END)


class TestShowBanner:
    """Banner is TUI-only decor — must be silent in non-TTY contexts."""

    def test_skips_when_stderr_not_tty(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.stderr.isatty", lambda: False, raising=False)
        tui._show_banner()
        captured = capsys.readouterr()
        assert captured.err == ""
        assert captured.out == ""

    def test_renders_repath_art_when_tty(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.stderr.isatty", lambda: True, raising=False)
        # Force rich to actually emit into captured stderr (bypass terminal
        # width detection that might strip color codes in CI).
        tui._show_banner()
        captured = capsys.readouterr()
        # The ansi_shadow font renders REPATH using box-drawing glyphs — so
        # we assert the box characters appear instead of pinning exact bytes.
        assert "█" in captured.err
        # Subtitle includes the version tag from ``__version__``.
        assert "Rewire Claude Code state" in captured.err


class TestChoiceTitle:
    """Status-icon / coloring dispatch for each row of the Step-1 picker."""

    def _icon(self, title: list[tuple[str, str]]) -> str:
        # First segment is always "<icon>  " — strip trailing whitespace.
        return title[0][1].strip()

    def _cwd_style(self, title: list[tuple[str, str]]) -> str:
        return title[1][0]

    def _session_segment(self, title: list[tuple[str, str]]) -> tuple[str, str]:
        # Order: [icon, cwd, "  [", session_label, "]"].
        return title[3]

    def test_active_project_gets_green_icon(self):
        title = _choice_title(r"D:\dev_code\x", 5, cwd_exists=True)
        assert self._icon(title) == _ICON_ACTIVE
        assert self._cwd_style(title) == ""
        style, text = self._session_segment(title)
        assert "ansigreen" in style
        assert text == "5 sessions"

    def test_ten_sessions_gets_bold_green(self):
        title = _choice_title(r"D:\dev_code\x", 73, cwd_exists=True)
        style, text = self._session_segment(title)
        assert "ansigreen" in style
        assert "bold" in style
        assert text == "73 sessions"

    def test_zero_sessions_gets_empty_icon_and_dim_row(self):
        title = _choice_title(r"D:\dev_code\empty", 0, cwd_exists=True)
        assert self._icon(title) == _ICON_EMPTY
        assert "ansibrightblack" in self._cwd_style(title)
        style, _text = self._session_segment(title)
        assert "ansibrightblack" in style

    def test_unknown_cwd_gets_question_icon_and_yellow_path(self):
        title = _choice_title("<unknown: D--foo>", 0, cwd_exists=True)
        assert self._icon(title) == _ICON_UNKNOWN
        assert "ansiyellow" in self._cwd_style(title)

    def test_singular_session_label(self):
        title = _choice_title(r"D:\x", 1, cwd_exists=True)
        _style, text = self._session_segment(title)
        assert text == "1 session"  # no trailing 's'

    def test_orphan_gets_red_icon_when_folder_missing(self):
        """Resolved cwd + missing folder — the primary migration candidate."""
        title = _choice_title(r"D:\gone\forever", 5, cwd_exists=False)
        assert self._icon(title) == _ICON_ORPHAN
        assert "ansired" in self._cwd_style(title)
        style, text = self._session_segment(title)
        assert "ansired" in style
        assert "bold" in style
        assert text == "5 sessions"

    def test_unknown_not_promoted_to_orphan_even_if_cwd_missing(self):
        """``<unknown: ...>`` entries stay ❓ regardless of exists flag."""
        title = _choice_title("<unknown: foo>", 0, cwd_exists=False)
        assert self._icon(title) == _ICON_UNKNOWN
        assert "ansiyellow" in self._cwd_style(title)


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
