"""Utility helpers for RocksDB path detection and DB introspection."""

import os
import re
from pathlib import Path


# Folder name patterns used by Windrose across versions.
ROCKSDB_PATTERNS = re.compile(r"^RocksDB(_v\d+)?(_Backups)?$")


def find_save_roots(base: Path) -> list[Path]:
    """
    Walk from base looking for folders matching RocksDB* patterns.
    Returns a flat list of World* subdirectories inside each RocksDB folder.
    """
    worlds: list[Path] = []
    if not base.exists():
        return worlds

    for entry in base.iterdir():
        if entry.is_dir() and ROCKSDB_PATTERNS.match(entry.name):
            for sub in entry.iterdir():
                if sub.is_dir() and sub.name.startswith("Worlds"):
                    worlds.append(sub)
    return sorted(worlds)


def default_windrose_root() -> Path | None:
    """Return %LOCALAPPDATA%\\R5\\Saved\\SaveProfiles if it exists."""
    local = os.environ.get("LOCALAPPDATA")
    if local:
        p = Path(local) / "R5" / "Saved" / "SaveProfiles"
        if p.exists():
            return p
    return None


def iter_db_keys(folder: Path, limit: int = 20) -> list[tuple[bytes, bytes]]:
    """
    Open DB read-only and yield up to *limit* key-value pairs.
    Used for diagnostics display. Returns empty list if DB unreadable.
    """
    try:
        from rocksdict import Rdict, Options, AccessType
        opts = Options(raw_mode=True)
        db = Rdict(str(folder), options=opts, access_type=AccessType.read_only())
        pairs = []
        for i, (k, v) in enumerate(db.items()):
            if i >= limit:
                break
            pairs.append((k, v))
        db.close()
        return pairs
    except Exception:  # noqa: BLE001
        return []
