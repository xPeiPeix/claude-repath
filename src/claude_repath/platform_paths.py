"""Cross-platform path helpers for detecting Claude Code Desktop artifacts.

These are purely read-only — ``claude-repath`` does not migrate Desktop
state. The helpers exist so ``doctor`` can truthfully report which state
locations are present on the user's machine.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _win_local_appdata() -> Path | None:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base)
    # Last-resort default.
    home = Path.home()
    fallback = home / "AppData" / "Local"
    return fallback if fallback.is_dir() else None


def desktop_local_storage_dir() -> Path | None:
    """Return the Claude Code Desktop Chromium Local Storage/leveldb path if present.

    * Windows: ``%LOCALAPPDATA%\\claude\\Local Storage\\leveldb``
    * macOS:   ``~/Library/Application Support/claude/Local Storage/leveldb``
    * Linux:   ``~/.config/claude/Local Storage/leveldb``

    Returns ``None`` if the directory doesn't exist on the current system.
    """
    candidate = _desktop_local_storage_candidate()
    return candidate if candidate is not None and candidate.is_dir() else None


def _desktop_local_storage_candidate() -> Path | None:
    """Return the expected path (without checking existence)."""
    if sys.platform.startswith("win") or sys.platform == "cygwin":
        local = _win_local_appdata()
        if local is None:
            return None
        return local / "claude" / "Local Storage" / "leveldb"
    if sys.platform == "darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "claude"
            / "Local Storage"
            / "leveldb"
        )
    # Linux / other POSIX
    return Path.home() / ".config" / "claude" / "Local Storage" / "leveldb"


def platform_label() -> str:
    """Short human label for the current platform."""
    if sys.platform.startswith("win") or sys.platform == "cygwin":
        return "Windows"
    if sys.platform == "darwin":
        return "macOS"
    if sys.platform.startswith("linux"):
        return "Linux"
    return sys.platform
