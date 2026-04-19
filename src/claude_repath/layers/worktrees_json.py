"""Layer 5: rewrite ``~/.claude/git-worktrees.json`` if present.

The structure of this file is not formally documented, so we take the
conservative approach: parse it as JSON, then recursively patch any
string value that matches the old path (exact or prefix).
"""

from __future__ import annotations

import json

from claude_repath.backup import BackupSession
from claude_repath.utils import patch_string_fields

from .base import MigrationContext


def plan(ctx: MigrationContext) -> list[str]:
    path = ctx.worktrees_json_path
    if not path.is_file():
        return [f"[skip] {path.name} not present"]
    data = json.loads(path.read_text(encoding="utf-8"))
    if patch_string_fields(data, ctx.old_path, ctx.new_path, field_names=None):
        return [f"[rewrite] {path.name}: path strings will be updated"]
    return [f"[noop] no references to old path in {path.name}"]


def apply(ctx: MigrationContext, session: BackupSession) -> list[str]:
    path = ctx.worktrees_json_path
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not patch_string_fields(data, ctx.old_path, ctx.new_path, field_names=None):
        return []
    session.save(path)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return [f"rewrote paths in {path.name}"]
