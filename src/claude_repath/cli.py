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
    PlanReport,
    apply_migration,
    detect_claude_processes,
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


def _warn_running_claude() -> None:
    pids = detect_claude_processes()
    if pids:
        console.print(
            Panel(
                f"Detected running claude process(es): {pids}\n"
                "State files may be locked or overwritten mid-migration.\n"
                "[bold]Close all Claude Code sessions before continuing.[/bold]",
                title="[red]⚠ WARNING[/red]",
                border_style="red",
            )
        )


@app.command("move")
def move_cmd(
    old_path: str = typer.Argument(..., help="Current absolute project path"),
    new_path: str = typer.Argument(..., help="Desired new absolute project path"),
    dry_run: bool = typer.Option(
        False, "--dry-run", "-n", help="Show planned changes without applying"
    ),
    no_move: bool = typer.Option(
        False, "--no-move", help="Skip the physical folder move (only rewire state)"
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the interactive confirmation"
    ),
) -> None:
    """Move a project folder and rewire Claude Code state in one shot."""
    ctx = MigrationContext(old_path=old_path, new_path=new_path)
    plan = plan_migration(ctx)

    console.rule("[bold]Migration Plan[/bold]")
    _print_plan(plan)
    if not no_move:
        console.print(
            f"[cyan]physical:[/cyan] mv {old_path} -> {new_path}"
        )

    if dry_run:
        console.print("[dim]dry-run: no changes made[/dim]")
        raise typer.Exit()

    _warn_running_claude()

    if not yes and not typer.confirm("Proceed with migration?"):
        raise typer.Abort()

    session = start_backup()
    console.print(f"[dim]backup session: {session.timestamp}[/dim]")

    moved = False
    if not no_move:
        try:
            move_project_folder(old_path, new_path)
            moved = True
        except (FileNotFoundError, FileExistsError) as exc:
            console.print(f"[red]✗ physical move failed:[/red] {exc}")
            raise typer.Exit(code=1) from exc

    report = apply_migration(ctx, session)
    report.moved_folder = moved
    _print_apply(report)


@app.command("rewire")
def rewire_cmd(
    old_path: str = typer.Argument(...),
    new_path: str = typer.Argument(...),
    dry_run: bool = typer.Option(False, "--dry-run", "-n"),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Rewire state only — assume the project folder was already moved."""
    # Same as `move --no-move`; implemented by delegating.
    move_cmd(
        old_path=old_path, new_path=new_path, dry_run=dry_run, no_move=True, yes=yes
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
