"""Layer 3: rewrite ``cwd`` fields inside every session ``.jsonl`` file.

Each line of a ``.jsonl`` is an independent JSON object. We parse it,
recursively patch any ``cwd`` field that matches the old path (exact or
worktree-subpath prefix), and serialize back. Non-JSON lines are preserved
verbatim.
"""

from __future__ import annotations

import json

from claude_repath.backup import BackupSession
from claude_repath.utils import patch_string_fields

from .base import MigrationContext

#: JSON keys whose string values are treated as cwd-like paths.
PATH_FIELDS: frozenset[str] = frozenset({"cwd"})


def _rewrite_content(
    content: str,
    old_path: str,
    new_path: str,
    fields: frozenset[str] = PATH_FIELDS,
) -> tuple[str, int]:
    """Return ``(new_content, lines_changed)``. Never writes the file itself."""
    trailing_newline = content.endswith("\n")
    new_lines: list[str] = []
    changed_count = 0
    for line in content.splitlines():
        if not line.strip():
            new_lines.append(line)
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            new_lines.append(line)
            continue
        if patch_string_fields(obj, old_path, new_path, fields):
            changed_count += 1
            new_lines.append(json.dumps(obj, ensure_ascii=False))
        else:
            new_lines.append(line)
    new_content = "\n".join(new_lines)
    if trailing_newline:
        new_content += "\n"
    return new_content, changed_count


def _jsonl_mentions_path(content: str, old_path: str) -> bool:
    """Quick check — does the file even mention the old path anywhere?"""
    # JSON-escape the backslashes and quotes so we match raw file text.
    needle = json.dumps(old_path)[1:-1]
    return needle in content


def plan(ctx: MigrationContext) -> list[str]:
    if not ctx.projects_dir.is_dir():
        return [f"[skip] {ctx.projects_dir} does not exist"]
    out: list[str] = []
    for sub in sorted(p for p in ctx.projects_dir.iterdir() if p.is_dir()):
        for jsonl in sorted(sub.glob("*.jsonl")):
            content = jsonl.read_text(encoding="utf-8")
            if not _jsonl_mentions_path(content, ctx.old_path):
                continue
            _, count = _rewrite_content(content, ctx.old_path, ctx.new_path)
            if count > 0:
                out.append(f"[rewrite] {sub.name}/{jsonl.name}: {count} entries")
    if not out:
        out.append("[skip] no .jsonl files reference the old path")
    return out


def apply(ctx: MigrationContext, session: BackupSession) -> list[str]:
    if not ctx.projects_dir.is_dir():
        return []
    changes: list[str] = []
    for sub in sorted(p for p in ctx.projects_dir.iterdir() if p.is_dir()):
        for jsonl in sorted(sub.glob("*.jsonl")):
            content = jsonl.read_text(encoding="utf-8")
            if not _jsonl_mentions_path(content, ctx.old_path):
                continue
            new_content, count = _rewrite_content(content, ctx.old_path, ctx.new_path)
            if count == 0:
                continue
            session.save(jsonl)
            jsonl.write_text(new_content, encoding="utf-8")
            changes.append(f"{sub.name}/{jsonl.name}: {count} entries")
    return changes
