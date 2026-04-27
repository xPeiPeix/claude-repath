"""Typer-based command-line interface for claude-repath."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import __version__
from .backup import list_backups, rollback, start_backup
from .encoder import encode_path, find_worktree_folders
from .layers.base import MigrationContext
from .migrate import (
    ApplyReport,
    PhysicalMoveError,
    PlanReport,
    apply_migration,
    move_project_folder,
    plan_migration,
)

app = typer.Typer(
    help="Rewire Claude Code state when your project folder moves.",
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)
console = Console()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"claude-repath {__version__}")
        raise typer.Exit()


@app.callback()
def main_callback(
    _version: bool = typer.Option(
        None,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Claude Code project migrator."""


def _print_plan(report: PlanReport) -> None:
    for name, lines in report.entries:
        if not lines:
            continue
        body = "\n".join(lines)
        console.print(Panel(body, title=f"[cyan]{name}[/cyan]", expand=False))
    console.print(f"[dim]planned actions: {report.total_actions}[/dim]")


def _print_apply(report: ApplyReport) -> None:
    if not report.entries:
        console.print("[yellow]No changes applied.[/yellow]")
        return
    for name, changes in report.entries:
        body = "\n".join(f"• {c}" for c in changes)
        console.print(Panel(body, title=f"[green]{name}[/green]", expand=False))
    console.print(
        f"[green]✓ {report.total_changes} changes applied[/green]   "
        f"[dim]backup: {report.backup_root}[/dim]"
    )


def _check_preflight_locks(
    ctx: MigrationContext, path: str, *, force: bool, dry_run: bool
) -> None:
    """Hard-refuse migration if any process holds resources relevant to this run.

    Scans two scopes (both filtered for existence before checking):

    1. The source project directory (``path``) — catches shells that have
       ``cd``-ed into the project, IDEs/editors with files open, etc.
    2. ``~/.claude/projects/<encoded-source>/`` — catches a running Claude
       Code session actively writing ``.jsonl`` session files for *this*
       project. Other Claude Code sessions (operating on unrelated projects)
       are deliberately ignored — they are not a migration risk.

    This targeted scan replaces an earlier global "any ``claude.exe`` running"
    warning, which fired on every Claude Code window regardless of project
    and generated useless noise on multi-project machines.

    Exits with code 1 unless ``--force`` is passed or the user is in dry-run
    mode (in which case the report is informational only).
    """
    from .locks import find_locks_on_paths, format_lock_report

    source_dir = Path(path)
    state_dir = ctx.projects_dir / encode_path(path)
    scanned = [p for p in (source_dir, state_dir) if p.exists()]
    if not scanned:
        return

    # Explicit stage marker — on Windows this scan can take several seconds
    # even after the v0.9.2 parallelization because ``proc.open_files()`` does
    # a per-handle type query. Without a marker + spinner the user sees a gap
    # between "Yes, proceed" and the next visible step and assumes a hang.
    console.print("[cyan]●[/cyan] Pre-flight lock scan")
    with console.status(
        "[dim]scanning running processes for locks...[/dim]", spinner="dots"
    ):
        locks = find_locks_on_paths(scanned)
    if not locks:
        return
    prefix = "[yellow]dry-run preview: [/yellow]" if dry_run else ""
    scanned_lines = "\n".join(f"  [cyan]{p}[/cyan]" for p in scanned)
    console.print(
        Panel(
            f"{prefix}Processes hold resources under the source project "
            "or its Claude Code state directory:\n"
            f"{scanned_lines}\n\n"
            + format_lock_report(locks)
            + "\n\n[yellow]Close these processes, or pass "
            "[cyan]--force[/cyan] to proceed anyway.[/yellow]",
            title="[red]✗ Pre-flight lock check[/red]",
            border_style="red",
        )
    )
    if dry_run:
        return
    if not force:
        raise typer.Exit(code=1)
    console.print("[yellow]--force given; proceeding despite locks.[/yellow]")


def _check_env_sensitive_subdirs(path: str) -> None:
    """Warn (non-blocking) if the source contains venv / node_modules / etc.

    These directories embed absolute paths in binaries / scripts at creation
    time and will not function at the new location until rebuilt. claude-repath
    moves the bytes correctly but cannot rebuild them — every package manager
    has its own command and auto-running any is risky. The warning lists the
    affected subdirs and the rebuild command hint per kind; the migration
    itself proceeds regardless.
    """
    from .env_warn import find_env_sensitive_subdirs, format_env_warn_report

    entries = find_env_sensitive_subdirs(Path(path))
    if not entries:
        return
    console.print(
        Panel(
            f"The following subdirectories under:\n"
            f"  [cyan]{path}[/cyan]\n"
            f"embed absolute paths and will need to be rebuilt after the move:\n\n"
            + format_env_warn_report(entries)
            + "\n\n[dim]The move itself proceeds as normal — this is a heads-up "
            "only.[/dim]",
            title="[yellow]⚠ Path-sensitive subdirectories[/yellow]",
            border_style="yellow",
        )
    )


@app.command("move")
def move_cmd(
    old_path: str = typer.Argument(None, help="Current absolute project path"),
    new_path: str = typer.Argument(None, help="Desired new absolute project path"),
    dry_run: bool = typer.Option(
        False, "--dry-run", "-n", help="Show planned changes without applying"
    ),
    no_move: bool = typer.Option(
        False, "--no-move", help="Skip the physical folder move (only rewire state)"
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the interactive confirmation"
    ),
    scope: str = typer.Option(
        "narrow",
        "--scope",
        help="jsonl scan scope: 'narrow' (main + worktrees, safer default) "
        "or 'broad' (every project dir; rewrites cross-project references)",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Proceed even if pre-flight lock check finds processes holding "
        "resources under the path. Note: cannot bypass OS-level runtime "
        "locks (elevated processes, AV scans, etc.) — if one fires during "
        "the move itself, the physical move will still fail, but v0.4.1+ "
        "uses atomic rename so the source directory stays intact for retry.",
    ),
) -> None:
    """Move a project folder and rewire Claude Code state in one shot.

    Run without arguments to launch an interactive project picker (TUI).
    """
    if scope not in {"narrow", "broad"}:
        console.print(f"[red]✗ invalid --scope {scope!r}; expected 'narrow' or 'broad'[/red]")
        raise typer.Exit(code=2)

    from_tui = False
    if old_path is None or new_path is None:
        if dry_run:
            console.print(
                "[red]--dry-run requires explicit old/new paths — "
                "interactive mode already previews before applying.[/red]"
            )
            raise typer.Exit(code=2)
        from .tui import run_interactive_move
        default_projects = Path.home() / ".claude" / "projects"
        chosen = run_interactive_move(default_projects, scope=scope)
        if chosen is None:
            console.print("[yellow]cancelled[/yellow]")
            raise typer.Abort()
        old_path, new_path = chosen
        from_tui = True

    ctx = MigrationContext(old_path=old_path, new_path=new_path, scope=scope)

    scan_path = new_path if no_move else old_path

    if not from_tui:
        plan = plan_migration(ctx)
        console.rule("[bold]Migration Plan[/bold]")
        _print_plan(plan)
        if not no_move:
            console.print(
                f"[cyan]physical:[/cyan] mv {old_path} -> {new_path}"
            )

        _check_preflight_locks(ctx, scan_path, force=force, dry_run=dry_run)
        if not no_move:
            _check_env_sensitive_subdirs(scan_path)

        if dry_run:
            console.print("[dim]dry-run: no changes made[/dim]")
            raise typer.Exit()

        if not yes and not typer.confirm("Proceed with migration?"):
            raise typer.Abort()
    else:
        _check_preflight_locks(ctx, scan_path, force=force, dry_run=False)
        if not no_move:
            _check_env_sensitive_subdirs(scan_path)

    session = start_backup()
    console.print(f"[dim]backup session: {session.timestamp}[/dim]")

    moved = False
    if not no_move:
        # Explicit stage marker in addition to the spinner — the spinner
        # is live-redrawn and leaves no trace in the scrollback, so on
        # larger moves (or in terminals that don't render spinner frames
        # well) the user just saw a gap and suspected a hang. Print a
        # permanent "●" line before each stage so the phase is visible
        # both during and after execution.
        console.print(
            f"[cyan]●[/cyan] Moving project folder  "
            f"[dim]{old_path} → {new_path}[/dim]"
        )
        try:
            with console.status("[dim]copying files...[/dim]", spinner="dots"):
                move_project_folder(old_path, new_path)
            moved = True
        except (FileNotFoundError, FileExistsError) as exc:
            console.print(f"[red]✗ physical move failed:[/red] {exc}")
            raise typer.Exit(code=1) from exc
        except PhysicalMoveError as exc:
            console.print(
                Panel(
                    str(exc),
                    title="[red]✗ physical move failed (source intact)[/red]",
                    border_style="red",
                )
            )
            raise typer.Exit(code=1) from exc

    console.print("[cyan]●[/cyan] Rewiring Claude Code state")
    with console.status("[dim]updating state files...[/dim]", spinner="dots"):
        report = apply_migration(ctx, session)
    report.moved_folder = moved
    _print_apply(report)


@app.command("rewire")
def rewire_cmd(
    old_path: str = typer.Argument(...),
    new_path: str = typer.Argument(...),
    dry_run: bool = typer.Option(False, "--dry-run", "-n"),
    yes: bool = typer.Option(False, "--yes", "-y"),
    scope: str = typer.Option("narrow", "--scope"),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Proceed even if pre-flight lock check finds processes holding "
        "resources under the new path. Rewire only touches ~/.claude state, "
        "so runtime OS locks there are rare — but `--force` is still bounded "
        "by real filesystem permissions.",
    ),
) -> None:
    """Rewire state only — assume the project folder was already moved."""
    move_cmd(
        old_path=old_path,
        new_path=new_path,
        dry_run=dry_run,
        no_move=True,
        yes=yes,
        scope=scope,
        force=force,
    )


@app.command("doctor")
def doctor_cmd(
    path: str = typer.Argument(..., help="Absolute path of project to check"),
) -> None:
    """Diagnose the health of a project's Claude Code state."""
    ctx = MigrationContext(old_path=path, new_path=path)
    enc = encode_path(path)
    table = Table(title=f"Doctor: {path}", show_header=True)
    table.add_column("Check", style="cyan")
    table.add_column("Status")
    table.add_column("Details")

    project_dir = ctx.projects_dir / enc
    table.add_row(
        "projects/<enc>/",
        "[green]✓[/green]" if project_dir.is_dir() else "[red]✗[/red]",
        str(project_dir),
    )

    wts = find_worktree_folders(enc, ctx.projects_dir)
    table.add_row(
        "worktrees",
        f"[green]{len(wts)} found[/green]" if wts else "[dim]none[/dim]",
        ", ".join(w.name for w in wts) if wts else "",
    )

    gj = ctx.global_json_path
    found_key: str | None = None
    if gj.is_file():
        import json
        data = json.loads(gj.read_text(encoding="utf-8"))
        projects = data.get("projects") or {}
        # Match either exactly or by separator-style variant, since real
        # ~/.claude.json stores keys with forward slashes even on Windows.
        for candidate in (path, path.replace("\\", "/"), path.replace("/", "\\")):
            if candidate in projects:
                found_key = candidate
                break
    table.add_row(
        "~/.claude.json projects key",
        "[green]✓[/green]" if found_key else "[yellow]not listed[/yellow]",
        found_key or str(gj),
    )

    # Desktop (Chromium) Local Storage — read-only diagnostic, not migrated.
    from .platform_paths import desktop_local_storage_dir, platform_label
    desktop = desktop_local_storage_dir()
    desktop_status = (
        "[yellow]present (not auto-migrated)[/yellow]"
        if desktop
        else "[dim]not detected[/dim]"
    )
    desktop_detail = str(desktop) if desktop else f"no Claude Desktop data on {platform_label()}"
    table.add_row("Desktop Local Storage", desktop_status, desktop_detail)

    console.print(table)


@app.command("list")
def list_cmd() -> None:
    """List every project Claude Code has state for."""
    ctx = MigrationContext(old_path="", new_path="", claude_home=Path.home() / ".claude")
    if not ctx.projects_dir.is_dir():
        console.print(f"[yellow]{ctx.projects_dir} does not exist[/yellow]")
        return
    table = Table(title="Claude Code projects", show_header=True)
    table.add_column("Encoded folder", style="cyan")
    table.add_column("Sessions")
    table.add_column("Type")
    for sub in sorted(ctx.projects_dir.iterdir()):
        if not sub.is_dir():
            continue
        count = sum(1 for _ in sub.glob("*.jsonl"))
        kind = "[magenta]worktree[/magenta]" if "--claude-worktrees-" in sub.name else "project"
        table.add_row(sub.name, str(count), kind)
    console.print(table)


@app.command("rollback")
def rollback_cmd(
    timestamp: str = typer.Argument(..., help="Backup timestamp (see `list-backups`)"),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Restore a previous migration's backup."""
    if not yes and not typer.confirm(f"Rollback to backup {timestamp}?"):
        raise typer.Abort()
    count = rollback(timestamp)
    console.print(f"[green]✓ restored {count} item(s)[/green]")


@app.command("list-backups")
def list_backups_cmd() -> None:
    """Show every available backup, newest first."""
    backups = list_backups()
    if not backups:
        console.print("[dim]no backups found[/dim]")
        return
    table = Table(title="claude-repath backups", show_header=True)
    table.add_column("Timestamp", style="cyan")
    table.add_column("Path")
    for ts, path in backups:
        table.add_row(ts, str(path))
    console.print(table)


if __name__ == "__main__":
    app()
