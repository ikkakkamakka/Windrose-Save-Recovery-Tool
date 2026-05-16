"""
Backup system – creates timestamped snapshots before any repair.

Layout:
  <save_root>/Backups/YYYY-MM-DD_HH-MM-SS/<world_folder_name>/
                                              ├── CURRENT
                                              ├── MANIFEST-*
                                              └── ...

Rules:
  - NEVER called implicitly; caller must invoke create_backup() first.
  - Uses shutil.copytree to preserve all files verbatim.
  - Returns the backup Path so callers can reference it in logs.
"""

import hashlib
import logging
import shutil
from datetime import datetime
from pathlib import Path

log = logging.getLogger("windrose.backup")

# Backups folder lives two levels above the world folder:
#   .../Worlds<ID>/  →  .../Backups/
# but we accept an explicit base_dir override for flexibility.
DEFAULT_BACKUP_ROOT_NAME = "Backups"


def create_backup(world_folder: Path, backup_root: Path | None = None) -> Path:
    """
    Copy *world_folder* into a timestamped backup directory.

    Args:
        world_folder:  The world save directory to back up.
        backup_root:   Where to store backups. Defaults to
                       <world_folder.parent.parent>/Backups/.

    Returns:
        Path to the newly created backup (world subfolder inside timestamp dir).

    Raises:
        RuntimeError if the copy fails.
    """
    if backup_root is None:
        # Go up two levels: Worlds<ID> → RocksDB<ver> → SaveProfile → use that.
        backup_root = world_folder.parent.parent / DEFAULT_BACKUP_ROOT_NAME

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    dest = backup_root / timestamp / world_folder.name

    log.info("Creating backup: %s → %s", world_folder, dest)

    try:
        shutil.copytree(src=world_folder, dst=dest)
    except Exception as exc:
        raise RuntimeError(f"Backup failed: {exc}") from exc

    # Verify the copy by comparing file counts.
    src_count = sum(1 for _ in world_folder.rglob("*") if _.is_file())
    dst_count = sum(1 for _ in dest.rglob("*") if _.is_file())
    if src_count != dst_count:
        log.warning("Backup file count mismatch: src=%d dst=%d", src_count, dst_count)
    else:
        log.info("Backup verified: %d files copied", dst_count)

    _write_manifest(dest, world_folder)
    return dest


def _write_manifest(backup_dest: Path, original: Path) -> None:
    """
    Write a human-readable manifest (SHA-256 checksums) alongside the backup.
    This allows future integrity checks without opening RocksDB.
    """
    manifest_path = backup_dest.parent / "BACKUP_MANIFEST.txt"
    lines = [
        f"# Windrose Save Recovery Tool – Backup Manifest",
        f"# Source: {original}",
        f"# Created: {datetime.now().isoformat()}",
        "",
    ]
    for f in sorted(backup_dest.rglob("*")):
        if f.is_file():
            try:
                digest = _sha256(f)
                lines.append(f"{digest}  {f.relative_to(backup_dest)}")
            except OSError:
                lines.append(f"ERR_READ  {f.relative_to(backup_dest)}")

    manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.debug("Wrote backup manifest: %s", manifest_path)


def _sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while data := fh.read(chunk):
            h.update(data)
    return h.hexdigest()


def list_backups(world_folder: Path, backup_root: Path | None = None) -> list[Path]:
    """Return backup world folders sorted newest-first."""
    if backup_root is None:
        backup_root = world_folder.parent.parent / DEFAULT_BACKUP_ROOT_NAME

    if not backup_root.exists():
        return []

    results = []
    for ts_dir in sorted(backup_root.iterdir(), reverse=True):
        candidate = ts_dir / world_folder.name
        if candidate.is_dir():
            results.append(candidate)
    return results
