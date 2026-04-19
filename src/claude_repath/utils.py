"""Shared helpers — path value rewriting and JSON traversal."""

from __future__ import annotations

from typing import Any


def _path_style_variants(old_path: str, new_path: str) -> list[tuple[str, str]]:
    """Return aligned (old, new) variant pairs across separator styles.

    A value may use forward slashes (``D:/dev/x``), backslashes (``D:\\dev\\x``),
    or mix them. We generate all distinct (old, new) pairs so matching works
    regardless of which style the stored value uses. The new path's style is
    aligned to its paired old variant so the rewrite preserves the original
    separator convention.
    """
    pairs: list[tuple[str, str]] = [(old_path, new_path)]
    candidates = [
        (old_path.replace("\\", "/"), new_path.replace("\\", "/")),
        (old_path.replace("/", "\\"), new_path.replace("/", "\\")),
    ]
    for pair in candidates:
        if pair not in pairs:
            pairs.append(pair)
    return pairs


def rewrite_path_value(value: str, old_path: str, new_path: str) -> tuple[str, bool]:
    """Rewrite a path-like string if it matches ``old_path`` exactly or as a prefix.

    Returns ``(new_value, was_changed)``. A "prefix match" means the value
    starts with ``old_path`` followed by either ``\\`` or ``/`` — this
    handles worktree subpaths like ``old_path\\.claude\\worktrees\\feat``.

    Tolerant of separator-style differences: ``D:/dev/x`` and ``D:\\dev\\x``
    are treated as equivalent. The rewrite preserves the original style.
    """
    for old_v, new_v in _path_style_variants(old_path, new_path):
        if value == old_v:
            return new_v, True
        for sep in ("\\", "/"):
            prefix = old_v + sep
            if value.startswith(prefix):
                return new_v + value[len(old_v) :], True
    return value, False


def patch_string_fields(
    obj: Any,
    old_path: str,
    new_path: str,
    field_names: frozenset[str] | None = None,
) -> bool:
    """Recursively rewrite matching strings inside a parsed JSON object.

    If ``field_names`` is provided, only dict keys in that set are patched.
    If ``None``, *every* string value encountered is considered for rewrite.

    Returns ``True`` if any modification was made. Mutates ``obj`` in place.
    """
    changed = False
    if isinstance(obj, dict):
        for k in list(obj.keys()):
            v = obj[k]
            if isinstance(v, str):
                if field_names is None or k in field_names:
                    new_v, was_changed = rewrite_path_value(v, old_path, new_path)
                    if was_changed:
                        obj[k] = new_v
                        changed = True
            elif isinstance(v, (dict, list)):
                if patch_string_fields(v, old_path, new_path, field_names):
                    changed = True
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            if isinstance(item, str):
                if field_names is None:
                    new_v, was_changed = rewrite_path_value(item, old_path, new_path)
                    if was_changed:
                        obj[i] = new_v
                        changed = True
            elif isinstance(item, (dict, list)):
                if patch_string_fields(item, old_path, new_path, field_names):
                    changed = True
    return changed
