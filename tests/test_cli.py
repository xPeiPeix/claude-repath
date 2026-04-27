"""End-to-end CLI tests via :mod:`typer.testing`.

Smoke tests for argument parsing and command dispatch. They're load-bearing
for two regression classes:

1. **Optional-argument regressions.** v1.0.0 makes ``doctor <path>`` and
   ``rollback <timestamp>`` accept ``None`` so no-args invocations land in
   interactive picker fallbacks. These tests pin that the explicit-arg
   path still parses correctly and reaches the command body — typer
   exit code ``2`` is the canary for an argument-parse failure.

2. **Version-number drift.** v0.5.1 shipped with ``pyproject.toml`` /
   ``plugin.json`` / ``marketplace.json`` bumped but
   ``src/claude_repath/__init__.py``'s ``__version__`` left at the old
   value — PyPI installed the right code but ``--version`` reported the
   stale string. ``test_version_matches_init`` catches this by asserting
   ``--version`` output equals ``claude_repath.__version__``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from claude_repath import __version__
from claude_repath.cli import app


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``Path.home()`` at an empty tmp dir.

    Without this, CLI tests would read the developer's real
    ``~/.claude/`` and ``~/.claude/.repath-backups/`` — fine on a clean
    box but flaky in CI with cached state. ``HOME`` covers POSIX,
    ``USERPROFILE`` covers Windows; both are honored by
    ``os.path.expanduser`` which underpins ``Path.home()``.
    """
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    return fake_home


class TestVersion:
    def test_version_matches_init(self, runner: CliRunner) -> None:
        """``--version`` output must equal ``claude_repath.__version__``.

        Regression guard for v0.5.1's "PyPI code right, ``--version``
        wrong" bug — the four-version-locations lesson pinned in
        ``.claude/rules/release.md`` codifies this as a release-blocker.
        """
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.stdout


class TestDoctor:
    def test_explicit_path_parses(
        self, runner: CliRunner, tmp_path: Path, isolated_home: Path
    ) -> None:
        """``doctor <path>`` must still parse after the ``Argument(None)`` change."""
        result = runner.invoke(app, ["doctor", str(tmp_path / "nonexistent")])
        # exit code 2 = typer arg-parse error. Anything else means parsing
        # succeeded and the command body ran (success or its own error).
        assert result.exit_code != 2

    def test_help_lists_path_as_optional(self, runner: CliRunner) -> None:
        """``doctor --help`` must show ``[PATH]`` (optional) not ``PATH`` (required)."""
        result = runner.invoke(app, ["doctor", "--help"])
        assert result.exit_code == 0
        # ``[PATH]`` (with brackets) = typer-rendered optional positional.
        assert "[PATH]" in result.stdout


class TestRollback:
    def test_explicit_timestamp_parses(
        self, runner: CliRunner, isolated_home: Path
    ) -> None:
        """``rollback <ts> --yes`` must still parse after ``Argument(None)`` change."""
        result = runner.invoke(app, ["rollback", "20260101-000000", "--yes"])
        # Backup directory doesn't exist under the isolated home, so the
        # command body raises ``FileNotFoundError`` and exits non-zero —
        # but exit code 2 (arg-parse failure) would mean the change broke
        # required-argument handling, which is the regression we're pinning.
        assert result.exit_code != 2

    def test_help_lists_timestamp_as_optional(self, runner: CliRunner) -> None:
        result = runner.invoke(app, ["rollback", "--help"])
        assert result.exit_code == 0
        assert "[TIMESTAMP]" in result.stdout


class TestList:
    def test_list_runs_with_empty_home(
        self, runner: CliRunner, isolated_home: Path
    ) -> None:
        """``list`` falls through cleanly when ``~/.claude/projects/`` is missing."""
        result = runner.invoke(app, ["list"])
        assert result.exit_code == 0


class TestListBackups:
    def test_list_backups_runs_with_empty_home(
        self, runner: CliRunner, isolated_home: Path
    ) -> None:
        """``list-backups`` falls through cleanly when no backups exist."""
        result = runner.invoke(app, ["list-backups"])
        assert result.exit_code == 0


class TestCompletion:
    def test_show_completion_dumps_script(self, runner: CliRunner) -> None:
        """``--show-completion bash`` returns a bash completion definition.

        Asserts on stable boilerplate (``complete -o default -F ...``)
        rather than the generated function name, because ``CliRunner``
        infers ``prog_name`` from the click app and emits ``_root_completion``
        in tests instead of the real ``_claude_repath_completion`` (which
        is what end users see when invoking the installed binary).
        """
        result = runner.invoke(app, ["--show-completion", "bash"])
        assert result.exit_code == 0
        # Both the function-definition opener and the ``complete``
        # registration line are stable across typer versions.
        assert "complete -o default -F" in result.stdout
