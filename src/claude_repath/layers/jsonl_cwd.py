"""Layer 3: rewrite ``cwd`` fields inside every session ``.jsonl`` file.

Each line of a ``.jsonl`` is an independent JSON object. We parse it,
recursively patch any ``cwd`` field that matches the old path (exact or
worktree-subpath prefix), and serialize back. Non-JSON lines are preserved
verbatim.
"""

from __future__ import annotations

import json
from pathlib import Path

from claude_repath.backup import BackupSession
from claude_repath.encoder import WORKTREE_INFIX, encode_path
from claude_repath.utils import patch_string_fields

from .base import MigrationContext

#: JSON keys whose string values are treated as cwd-like paths.
PATH_FIELDS: frozenset[str] = frozenset({"cwd"})


def _scan_dirs(ctx: MigrationContext) -> list[Path]:
    """Return the project subdirs to scan according to ``ctx.scope``.

    * ``"narrow"`` — only the main project's encoded dir and its worktree
      folders (both old and new encoding, since layer 2 may have renamed
      them already). Safe default.
    * ``"broad"`` — every subdirectory of ``projects/``. Also rewrites
      cross-project references where another project's jsonl happens to
      mention the old path.
    """
    if not ctx.projects_dir.is_dir():
        return []
    all_dirs = sorted(p for p in ctx.projects_dir.iterdir() if p.is_dir())
    if ctx.scope == "broad":
        return all_dirs
    old_enc = encode_path(ctx.old_path)
    new_enc = encode_path(ctx.new_path)
    relevant: list[Path] = []
    for p in all_dirs:
        for prefix in (old_enc, new_enc):
            if p.name == prefix or p.name.startswith(prefix + WORKTREE_INFIX):
                relevant.append(p)
                break
    return relevant


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
    dirs = _scan_dirs(ctx)
    if not dirs:
        return [f"[skip] no project dirs to scan under {ctx.projects_dir}"]
    out: list[str] = []
    for sub in dirs:
        for jsonl in sorted(sub.glob("*.jsonl")):
            content = jsonl.read_text(encoding="utf-8")
            if not _jsonl_mentions_path(content, ctx.old_path):
                continue
            _, count = _rewrite_content(content, ctx.old_path, ctx.new_path)
            if count > 0:
                out.append(f"[rewrite] {sub.name}/{jsonl.name}: {count} entries")
    if not out:
        out.append(f"[skip] no .jsonl files reference the old path (scope={ctx.scope})")
    return out


def apply(ctx: MigrationContext, session: BackupSession) -> list[str]:
    changes: list[str] = []
    for sub in _scan_dirs(ctx):
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
