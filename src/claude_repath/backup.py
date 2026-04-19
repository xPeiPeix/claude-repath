"""Backup & rollback for claude-repath.

Every mutating migration step must first call :func:`start_backup` to open a
:class:`BackupSession`, then use :meth:`BackupSession.save` to snapshot any
file or directory before changing it. Each save is recorded in a JSON
manifest so :func:`rollback` can restore the original state even after
a crash mid-migration.

Backups live under ``~/.claude/.repath-backups/<timestamp>/`` by default.
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

BACKUP_ROOT_NAME = ".repath-backups"
MANIFEST_NAME = "manifest.json"


def default_backup_root() -> Path:
    return Path.home() / ".claude" / BACKUP_ROOT_NAME


@dataclass
class BackupSession:
    """A single backup run. Created by :func:`start_backup`."""

    timestamp: str
    root: Path
    _entries: list[dict] = field(default_factory=list, init=False, repr=False)

    @property
    def manifest_path(self) -> Path:
        return self.root / MANIFEST_NAME

    def save(self, original: Path) -> Path | None:
        """Snapshot ``original`` (file or directory) to the backup root.

        Returns the backup copy's path, or ``None`` if the source does not
        exist at backup time. Either way, the manifest is updated so rollback
        can act on this entry.
        """
        if not original.exists():
            self._record(original, None)
            return None
        index = len(self._entries)
        dest = self.root / "files" / f"{index:06d}_{original.name}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        if original.is_dir():
            shutil.copytree(original, dest)
        else:
            shutil.copy2(original, dest)
        self._record(original, dest)
        return dest

    def _record(self, original: Path, backup: Path | None) -> None:
        self._entries.append(
            {
                "original": str(original),
                "backup": str(backup) if backup is not None else None,
            }
        )
        # Write the manifest incrementally — a crash mid-way still leaves
        # a usable rollback record.
        self.manifest_path.write_text(
            json.dumps(
                {"timestamp": self.timestamp, "entries": self._entries},
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )


def start_backup(root: Path | None = None) -> BackupSession:
    """Create a new timestamped backup directory."""
    root = root if root is not None else default_backup_root()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup_dir = root / stamp
    suffix = 0
    while backup_dir.exists():
        suffix += 1
        backup_dir = root / f"{stamp}-{suffix}"
    backup_dir.mkdir(parents=True)
    session = BackupSession(timestamp=backup_dir.name, root=backup_dir)
    session.manifest_path.write_text(
        json.dumps({"timestamp": session.timestamp, "entries": []}, indent=2),
        encoding="utf-8",
    )
    return session


def rollback(timestamp: str, root: Path | None = None) -> int:
    """Restore every entry recorded in a backup's manifest.

    Entries whose source was missing at backup time are *removed* from the
    current filesystem (if they reappeared). Returns the number of restored
    items (entries whose backup was not ``None``).
    """
    root = root if root is not None else default_backup_root()
    backup_dir = root / timestamp
    manifest = backup_dir / MANIFEST_NAME
    if not manifest.is_file():
        raise FileNotFoundError(f"No backup manifest at {manifest}")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    restored = 0
    # Rollback in reverse order (LIFO). Later operations may have nested
    # effects inside earlier ones — e.g. layer 2 renames ``D--old/`` to
    # ``D--new/``, then layer 3 writes into ``D--new/``. Reversing undoes
    # the inner write first, then the outer rename removes the directory.
    for entry in reversed(data["entries"]):
        original = Path(entry["original"])
        backup = Path(entry["backup"]) if entry["backup"] else None
        if backup is None:
            if original.exists():
                _remove(original)
            continue
        if original.exists():
            _remove(original)
        original.parent.mkdir(parents=True, exist_ok=True)
        if backup.is_dir():
            shutil.copytree(backup, original)
        else:
            shutil.copy2(backup, original)
        restored += 1
    return restored


def list_backups(root: Path | None = None) -> list[tuple[str, Path]]:
    """Return ``(timestamp, dir)`` pairs for every valid backup, newest first."""
    root = root if root is not None else default_backup_root()
    if not root.is_dir():
        return []
    items = (
        (p.name, p)
        for p in root.iterdir()
        if p.is_dir() and (p / MANIFEST_NAME).is_file()
    )
    return sorted(items, key=lambda item: item[0], reverse=True)


def _remove(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
