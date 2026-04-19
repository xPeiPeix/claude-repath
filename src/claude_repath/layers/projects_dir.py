"""Layer 2: rename ``~/.claude/projects/<encoded>/`` directories.

Also finds and renames worktree-derived folders whose names start with
``<old_encoded>--claude-worktrees-``.
"""

from __future__ import annotations

from claude_repath.backup import BackupSession
from claude_repath.encoder import encode_path, find_worktree_folders

from .base import MigrationContext


def plan(ctx: MigrationContext) -> list[str]:
    old_enc = encode_path(ctx.old_path)
    new_enc = encode_path(ctx.new_path)
    out: list[str] = []

    if not ctx.projects_dir.is_dir():
        return [f"[skip] {ctx.projects_dir} does not exist"]

    main_old = ctx.projects_dir / old_enc
    main_new = ctx.projects_dir / new_enc
    if main_old.exists():
        if old_enc == new_enc:
            out.append(f"[noop] main dir: encoding unchanged ({old_enc})")
        elif main_new.exists():
            out.append(f"[conflict] {new_enc}/ already exists — refusing to overwrite")
        else:
            out.append(f"[rename] projects/{old_enc}/ -> projects/{new_enc}/")
    else:
        out.append(f"[skip] projects/{old_enc}/ not found")

    for wt_old in find_worktree_folders(old_enc, ctx.projects_dir):
        suffix = wt_old.name[len(old_enc) :]
        wt_new_name = new_enc + suffix
        wt_new = ctx.projects_dir / wt_new_name
        if wt_old == wt_new:
            out.append(f"[noop] worktree: {wt_old.name} (encoding unchanged)")
        elif wt_new.exists():
            out.append(f"[conflict] {wt_new_name}/ already exists")
        else:
            out.append(f"[rename] projects/{wt_old.name}/ -> projects/{wt_new_name}/")
    return out


def apply(ctx: MigrationContext, session: BackupSession) -> list[str]:
    old_enc = encode_path(ctx.old_path)
    new_enc = encode_path(ctx.new_path)
    changes: list[str] = []

    if not ctx.projects_dir.is_dir():
        return []

    main_old = ctx.projects_dir / old_enc
    main_new = ctx.projects_dir / new_enc
    if main_old.exists() and old_enc != new_enc:
        if main_new.exists():
            raise FileExistsError(
                f"Refusing to overwrite existing {main_new}; remove it first."
            )
        session.save(main_old)
        # Record the rename target too — it doesn't exist yet, so backup will
        # be None. On rollback, the entry tells us to delete whatever ends up
        # at main_new (i.e. the renamed content).
        session.save(main_new)
        main_old.rename(main_new)
        changes.append(f"renamed projects/{old_enc}/ -> projects/{new_enc}/")

    for wt_old in find_worktree_folders(old_enc, ctx.projects_dir):
        suffix = wt_old.name[len(old_enc) :]
        wt_new = ctx.projects_dir / (new_enc + suffix)
        if wt_old == wt_new:
            continue
        if wt_new.exists():
            raise FileExistsError(f"Refusing to overwrite {wt_new}")
        session.save(wt_old)
        session.save(wt_new)
        wt_old.rename(wt_new)
        changes.append(f"renamed projects/{wt_old.name}/ -> projects/{wt_new.name}/")

    return changes
