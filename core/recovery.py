"""
Recovery operations for corrupted Windrose save folders.

Strategy (order matters – each step is idempotent):
  1.  Remove stale LOCK             – unblocks RocksDB open.
  2.  Rebuild CURRENT               – if missing or pointing nowhere.
  3.  Prune extra MANIFESTs         – keep only the newest; move others to _orphans/.
  4.  Clone to _Recovered copy      – ALL repairs happen on the CLONE, never the original.
  5.  Attempt RocksDB repair()      – rocksdict exposes this; rewrites internal metadata.
  6.  Restore from backup           – last resort if above steps don't yield a readable DB.

The caller MUST call backup.create_backup() before invoking any function here.
"""

import logging
import re
import shutil
from pathlib import Path

from models.results import RecoveryResult

log = logging.getLogger("windrose.recovery")

LOCK_FILES = {"LOCK"}
TEMP_SUFFIXES = {".tmp", ".dbtmp"}


def recover_save(world_folder: Path, backup_source: Path | None = None) -> RecoveryResult:
    """
    Full recovery workflow.  Writes output to <world_folder>_Recovered/.
    Never touches world_folder directly.

    Args:
        world_folder:   Original (possibly corrupt) save directory.
        backup_source:  Optional clean backup to fall back to.

    Returns:
        RecoveryResult with success flag, list of operations performed, and
        the path of the recovered copy.
    """
    result = RecoveryResult(success=False)
    recovered = world_folder.parent / (world_folder.name + "_Recovered")

    # Step 1 – Clone to working copy.
    if recovered.exists():
        log.info("Removing previous _Recovered folder: %s", recovered)
        shutil.rmtree(recovered)
    try:
        shutil.copytree(src=world_folder, dst=recovered)
        result.operations.append(f"Cloned save to {recovered.name}")
    except Exception as exc:
        result.error = f"Clone failed: {exc}"
        return result

    result.recovered_path = recovered

    # Step 2 – Remove stale LOCK and temp files.
    _remove_lock_files(recovered, result)

    # Step 3 – Rebuild CURRENT if broken.
    _rebuild_current(recovered, result)

    # Step 4 – Prune conflicting MANIFESTs (keep newest).
    _prune_manifests(recovered, result)

    # Step 5 – Attempt RocksDB repair() on the clone.
    repaired = _rocksdb_repair(recovered, result)

    if not repaired and backup_source and backup_source.exists():
        # Step 6 – Restore from backup as last resort.
        _restore_from_backup(recovered, backup_source, result)

    # Final readability check.
    result.success = _can_open(recovered)
    if result.success:
        result.operations.append("RocksDB open-test PASSED on recovered copy")
    else:
        result.operations.append("RocksDB open-test FAILED – manual intervention may be needed")

    return result


# ---------------------------------------------------------------------------
# Step implementations
# ---------------------------------------------------------------------------

def _remove_lock_files(folder: Path, result: RecoveryResult) -> None:
    """
    Remove LOCK and *.tmp files.  LOCK prevents a second RocksDB process from
    opening the same directory.  It is safe to delete when no live process holds it.
    """
    for name in LOCK_FILES:
        p = folder / name
        if p.exists():
            p.unlink()
            result.operations.append(f"Removed stale {name}")
            log.info("Removed %s", p)

    for p in folder.iterdir():
        if p.suffix in TEMP_SUFFIXES:
            p.unlink()
            result.operations.append(f"Removed temp file {p.name}")


def _rebuild_current(folder: Path, result: RecoveryResult) -> None:
    """
    CURRENT must contain exactly '<manifest_name>\n'.

    Recovery logic:
      - If CURRENT is missing or malformed → find the newest MANIFEST-* by
        modification time and write it as the new CURRENT.
      - If CURRENT points to a non-existent MANIFEST → same.

    We pick the *newest* manifest because RocksDB always writes a new manifest
    before deleting the old one; the newest is therefore the most complete.
    """
    current_path = folder / "CURRENT"
    manifests = sorted(folder.glob("MANIFEST-*"), key=lambda p: p.stat().st_mtime, reverse=True)

    if not manifests:
        result.operations.append("Cannot rebuild CURRENT – no MANIFEST files exist")
        log.error("No MANIFEST files in %s", folder)
        return

    newest = manifests[0]

    needs_rebuild = False
    if not current_path.exists():
        needs_rebuild = True
        reason = "CURRENT missing"
    else:
        raw = current_path.read_text(encoding="utf-8", errors="replace").strip()
        if not re.fullmatch(r"MANIFEST-\d+", raw):
            needs_rebuild = True
            reason = f"CURRENT malformed: {raw!r}"
        elif not (folder / raw).exists():
            needs_rebuild = True
            reason = f"CURRENT points to absent {raw}"
        else:
            reason = ""

    if needs_rebuild:
        current_path.write_text(newest.name + "\n", encoding="utf-8")
        msg = f"Rebuilt CURRENT → {newest.name} ({reason})"
        result.operations.append(msg)
        log.info(msg)
    else:
        log.debug("CURRENT is intact, no rebuild needed")


def _prune_manifests(folder: Path, result: RecoveryResult) -> None:
    """
    Keep only the MANIFEST that CURRENT points to.  Move extras to _orphans/
    so they're not deleted but don't confuse RocksDB.

    Background: after a crash mid-compaction, RocksDB may leave a partially
    written new MANIFEST alongside the old one.  The old one (referenced by
    CURRENT) is still valid; the new one is incomplete garbage.
    """
    current_path = folder / "CURRENT"
    if not current_path.exists():
        return

    active = current_path.read_text(encoding="utf-8", errors="replace").strip()
    orphan_dir = folder / "_orphans"

    for m in folder.glob("MANIFEST-*"):
        if m.name != active:
            orphan_dir.mkdir(exist_ok=True)
            dest = orphan_dir / m.name
            shutil.move(str(m), dest)
            result.operations.append(f"Moved orphan {m.name} → _orphans/")
            log.info("Orphaned %s", m.name)


def _rocksdb_repair(folder: Path, result: RecoveryResult) -> bool:
    """
    Call rocksdict's repair() utility.

    RocksDB repair() rewrites the MANIFEST by scanning all SST files on disk
    and reconstructing metadata from their table properties.  It cannot recover
    data that was never flushed to SST (memtable content lost on crash), but it
    often fixes a corrupted or missing MANIFEST that prevents normal open.
    """
    try:
        from rocksdict import Rdict
        Rdict.repair(str(folder))
        result.operations.append("rocksdict repair() completed successfully")
        log.info("RocksDB repair() succeeded on %s", folder)
        return True
    except ImportError:
        result.operations.append("rocksdict not available – skipping repair()")
        return False
    except Exception as exc:  # noqa: BLE001
        result.operations.append(f"rocksdict repair() failed: {exc}")
        log.warning("repair() failed: %s", exc)
        return False


def _restore_from_backup(target: Path, backup: Path, result: RecoveryResult) -> None:
    """
    Overwrite the _Recovered clone with files from a known-good backup.
    Only copies files that are missing or zero-byte in the target.
    This is additive – it will not overwrite files that already exist and
    have content, preserving any newer data from the corrupt save.
    """
    restored = 0
    for src_file in backup.rglob("*"):
        if not src_file.is_file():
            continue
        rel = src_file.relative_to(backup)
        dst_file = target / rel
        dst_file.parent.mkdir(parents=True, exist_ok=True)

        if not dst_file.exists() or dst_file.stat().st_size == 0:
            shutil.copy2(src_file, dst_file)
            restored += 1

    result.operations.append(f"Restored {restored} missing/empty files from backup")
    log.info("Restored %d files from backup %s", restored, backup)


def _can_open(folder: Path) -> bool:
    """Quick RocksDB open check (read-only)."""
    try:
        from rocksdict import Rdict, Options, AccessType
        opts = Options(raw_mode=True)
        db = Rdict(str(folder), options=opts, access_type=AccessType.read_only())
        db.close()
        return True
    except Exception:  # noqa: BLE001
        return False
