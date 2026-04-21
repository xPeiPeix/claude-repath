"""Pre-flight warning for path-sensitive subdirectories under a project.

Python virtual environments and some other language-specific directories
embed **absolute paths** inside their binaries or scripts when created. After
a physical folder move, these internals still point at the *old* path:

* Python ``.venv/Scripts/*.exe`` (Windows) are trampoline binaries whose
  resource section hard-codes the absolute path to the venv's ``python.exe``
  at creation time. On Unix the scripts start with a ``#!/abs/path`` shebang.
  After a move, running ``pytest`` or any console script silently invokes the
  *old* path's ``python.exe`` (if still on disk) and imports from the old
  venv's ``site-packages``.
* ``node_modules/.bin/*.cmd`` (Windows) similarly hard-code node paths.

Unlike process locks (see :mod:`.locks`), this is a **warning**, not a hard
refusal: the move itself succeeds, but the user must ``rebuild`` these
directories after migration. claude-repath does not attempt the rebuild —
the right command varies by package manager (``uv sync`` vs ``pip install``
vs ``poetry install`` vs ``npm ci`` vs ``pnpm install`` …) and auto-running
any of them without user consent is risky.

Scans only the **first level** of the given path. Nested monorepo venvs are
out of scope — the user should handle those deliberately anyway.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EnvSensitiveEntry:
    """A subdirectory that embeds absolute paths and will need rebuilding."""

    path: Path
    kind: str
    reason: str


def find_env_sensitive_subdirs(path: Path) -> list[EnvSensitiveEntry]:
    """Return first-level subdirectories that will break after a physical move.

    Detection rules (intentionally conservative to avoid false positives):

    * ``.venv`` / ``venv`` — matched only if a ``pyvenv.cfg`` exists inside,
      which distinguishes a real Python virtual environment from an
      unrelated folder that happens to share the name.
    * ``node_modules`` — matched on folder name alone; the name is unique
      enough that false positives aren't a realistic concern.

    Returns an empty list if ``path`` does not exist or isn't a directory.
    Unreadable entries (permission errors) are silently skipped — this is a
    best-effort warning, not a gate.
    """
    if not path.is_dir():
        return []
    entries: list[EnvSensitiveEntry] = []
    try:
        children = list(path.iterdir())
    except OSError:
        return []
    for child in children:
        try:
            if not child.is_dir():
                continue
        except OSError:
            continue
        entry = _classify(child)
        if entry is not None:
            entries.append(entry)
    return entries


def _classify(child: Path) -> EnvSensitiveEntry | None:
    """Return an :class:`EnvSensitiveEntry` if ``child`` matches a known pattern."""
    name = child.name
    if name in {".venv", "venv"} and (child / "pyvenv.cfg").is_file():
        return EnvSensitiveEntry(
            path=child,
            kind="Python venv",
            reason=(
                "console-script binaries hard-code the absolute path to "
                "python.exe; rebuild with your package manager "
                "(e.g. `uv sync`, `pip install -e .`, `poetry install`)"
            ),
        )
    if name == "node_modules":
        return EnvSensitiveEntry(
            path=child,
            kind="Node modules",
            reason=(
                "`.bin/*.cmd` shims and pnpm symlinks may embed absolute "
                "paths; rebuild with `npm ci` / `pnpm install` / `yarn install`"
            ),
        )
    return None


def format_env_warn_report(entries: list[EnvSensitiveEntry]) -> str:
    """Render entries as a multi-line string for CLI display."""
    if not entries:
        return ""
    lines = [
        f"  • {e.path.name:<15} [{e.kind}] — {e.reason}" for e in entries
    ]
    return "\n".join(lines)
