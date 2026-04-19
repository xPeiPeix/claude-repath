"""Layer 4: rewrite ``~/.claude.json`` — the global Claude Code config.

The ``projects`` key is an object indexed by absolute project path. We
rename matching keys (exact or worktree-subpath prefix) and also patch
any nested string fields that happen to be absolute paths.
"""

from __future__ import annotations

import json

from claude_repath.backup import BackupSession
from claude_repath.utils import patch_string_fields, rewrite_path_value

from .base import MigrationContext


def _collect_key_remappings(
    projects: dict, old_path: str, new_path: str
) -> dict[str, str]:
    """Return ``{old_key: new_key}`` for every projects-key that needs renaming."""
    remappings: dict[str, str] = {}
    for key in list(projects.keys()):
        new_key, changed = rewrite_path_value(key, old_path, new_path)
        if changed and new_key != key:
            remappings[key] = new_key
    return remappings


def _apply_remappings(projects: dict, remappings: dict[str, str]) -> None:
    for old_k, new_k in remappings.items():
        if new_k in projects and new_k != old_k:
            raise ValueError(
                f"Collision in ~/.claude.json: cannot rename {old_k!r} -> {new_k!r} "
                f"because {new_k!r} already exists"
            )
        projects[new_k] = projects.pop(old_k)


def plan(ctx: MigrationContext) -> list[str]:
    path = ctx.global_json_path
    if not path.is_file():
        return [f"[skip] {path.name} not found"]
    data = json.loads(path.read_text(encoding="utf-8"))
    out: list[str] = []
    projects = data.get("projects") or {}
    remappings = _collect_key_remappings(projects, ctx.old_path, ctx.new_path)
    for old_k, new_k in remappings.items():
        out.append(f"[rekey] {path.name} projects: {old_k} -> {new_k}")

    # Also dry-scan nested string fields.
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    if patch_string_fields(snapshot, ctx.old_path, ctx.new_path, field_names=None):
        out.append(f"[rewrite] {path.name}: nested path strings will be updated")

    if not out:
        out.append(f"[noop] no references to old path in {path.name}")
    return out


def apply(ctx: MigrationContext, session: BackupSession) -> list[str]:
    path = ctx.global_json_path
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    changes: list[str] = []

    projects = data.get("projects") or {}
    remappings = _collect_key_remappings(projects, ctx.old_path, ctx.new_path)

    # Also rewrite nested string fields (non-key values that may contain paths).
    nested_changed = patch_string_fields(
        data, ctx.old_path, ctx.new_path, field_names=None
    )

    if not remappings and not nested_changed:
        return []

    session.save(path)
    if remappings:
        _apply_remappings(projects, remappings)
        data["projects"] = projects
        for old_k, new_k in remappings.items():
            changes.append(f"rekeyed projects: {old_k} -> {new_k}")
    if nested_changed:
        changes.append(f"rewrote nested path strings in {path.name}")

    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return changes
