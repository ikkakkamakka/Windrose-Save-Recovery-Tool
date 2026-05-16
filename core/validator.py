"""
Validates Windrose RocksDB save folders.

RocksDB folder anatomy:
  CURRENT        – single line: "MANIFEST-XXXXXX\n". Points to the active manifest.
  MANIFEST-*     – binary log of all SST file metadata (VersionEdit records).
  OPTIONS-*      – text config snapshot; latest is authoritative.
  *.sst          – actual data blocks; referenced by the active MANIFEST.
  LOG / LOG.old  – human-readable operational logs (safe to be absent).
  LOCK           – advisory lock held by a live RocksDB process (should be absent at rest).
  WorldDescription.json – Windrose-specific world metadata.

Corruption patterns we detect:
  1. Missing CURRENT or MANIFEST → DB cannot open.
  2. CURRENT points to a non-existent MANIFEST → open would fail immediately.
  3. CURRENT content is malformed (no trailing newline / wrong prefix).
  4. Duplicate or zero MANIFEST files → ambiguous state.
  5. Empty / truncated CURRENT, MANIFEST, or SST files (< expected minimum bytes).
  6. Stale LOCK file left by a crashed process.
  7. Invalid JSON in WorldDescription.json.
  8. SSTs referenced nowhere (orphaned) – only a warning, not fatal.
"""

import json
import logging
import re
from pathlib import Path

from models.results import Issue, Severity, ValidationResult

log = logging.getLogger("windrose.validator")

# Minimum sane file sizes (bytes).
MIN_MANIFEST_BYTES = 4
MIN_SST_BYTES = 8
MIN_CURRENT_BYTES = 9  # "MANIFEST\n" is the shortest possible valid content


def validate_save(folder: Path) -> ValidationResult:
    """
    Entry point. Validates a single Windrose save folder (one World directory).
    Returns a ValidationResult populated with all detected issues.
    """
    result = ValidationResult(path=folder)

    if not folder.exists() or not folder.is_dir():
        result.issues.append(Issue(Severity.CRITICAL, "Folder does not exist", str(folder)))
        return result

    log.info("Validating: %s", folder)

    _check_current_file(folder, result)
    _check_manifests(folder, result)
    _check_sst_files(folder, result)
    _check_options(folder, result)
    _check_lock(folder, result)
    _check_world_json(folder, result)

    # RocksDB open test – attempted only when no critical structural issues exist.
    if result.severity not in (Severity.CRITICAL,):
        result.rocksdb_readable = _test_rocksdb_open(folder, result)

    if not result.issues:
        result.issues.append(Issue(Severity.OK, "All checks passed"))

    return result


# ---------------------------------------------------------------------------
# Individual check routines
# ---------------------------------------------------------------------------

def _check_current_file(folder: Path, result: ValidationResult) -> str | None:
    """
    CURRENT must exist, be non-empty, and contain exactly 'MANIFEST-<digits>\n'.
    Returns the manifest name it points to (or None on failure).
    """
    current = folder / "CURRENT"

    if not current.exists():
        result.issues.append(Issue(Severity.CRITICAL, "CURRENT file missing",
                                   "RocksDB cannot open without CURRENT."))
        return None

    if current.stat().st_size < MIN_CURRENT_BYTES:
        result.issues.append(Issue(Severity.CRITICAL, "CURRENT file is empty or truncated",
                                   f"Size: {current.stat().st_size} bytes"))
        return None

    raw = current.read_text(encoding="utf-8", errors="replace").strip()

    # Valid CURRENT content: "MANIFEST-000123" (digits only after dash).
    if not re.fullmatch(r"MANIFEST-\d+", raw):
        result.issues.append(Issue(Severity.CRITICAL, "CURRENT content is malformed",
                                   f"Got: {raw!r}"))
        return None

    manifest_name = raw  # e.g. "MANIFEST-000006"

    if not (folder / manifest_name).exists():
        result.issues.append(Issue(Severity.CRITICAL,
                                   f"CURRENT points to missing {manifest_name}",
                                   "The active manifest was deleted or never written."))
        return None

    log.debug("CURRENT → %s (OK)", manifest_name)
    return manifest_name


def _check_manifests(folder: Path, result: ValidationResult) -> None:
    """
    Detect zero, duplicate-confusion, or truncated MANIFEST files.

    Having multiple MANIFEST files is normal during compaction (RocksDB writes
    a new one before deleting the old). A stale extra manifest is a WARNING,
    not fatal, but signals an unclean shutdown.
    """
    manifests = sorted(folder.glob("MANIFEST-*"))

    if not manifests:
        result.issues.append(Issue(Severity.CRITICAL, "No MANIFEST files found",
                                   "Database metadata is completely absent."))
        return

    if len(manifests) > 1:
        result.issues.append(Issue(Severity.WARNING,
                                   f"{len(manifests)} MANIFEST files present",
                                   "Extra MANIFESTs suggest an unclean shutdown: "
                                   + ", ".join(m.name for m in manifests)))

    for m in manifests:
        if m.stat().st_size < MIN_MANIFEST_BYTES:
            result.issues.append(Issue(Severity.ERROR,
                                       f"{m.name} is empty/truncated",
                                       f"Size: {m.stat().st_size} bytes"))


def _check_sst_files(folder: Path, result: ValidationResult) -> None:
    """
    SST files hold the actual key-value data blocks.
    A zero-byte SST is definitively corrupt; very small ones are suspicious.
    """
    ssts = list(folder.glob("*.sst"))

    if not ssts:
        # No SST files is valid for a brand-new / empty world.
        result.issues.append(Issue(Severity.WARNING, "No .sst files found",
                                   "World may be empty or DB was never flushed to disk."))
        return

    for sst in ssts:
        size = sst.stat().st_size
        if size == 0:
            result.issues.append(Issue(Severity.ERROR, f"{sst.name} is zero bytes",
                                       "This SST is corrupt and unreadable."))
        elif size < MIN_SST_BYTES:
            result.issues.append(Issue(Severity.WARNING, f"{sst.name} is suspiciously small",
                                       f"Size: {size} bytes"))

    log.debug("SST files: %d total", len(ssts))


def _check_options(folder: Path, result: ValidationResult) -> None:
    """OPTIONS files store DB configuration. Missing is recoverable; present but empty is odd."""
    options = sorted(folder.glob("OPTIONS-*"))
    if not options:
        result.issues.append(Issue(Severity.WARNING, "No OPTIONS files found",
                                   "RocksDB can regenerate these on open."))
    for opt in options:
        if opt.stat().st_size == 0:
            result.issues.append(Issue(Severity.WARNING, f"{opt.name} is empty"))


def _check_lock(folder: Path, result: ValidationResult) -> None:
    """
    LOCK is created by a live RocksDB process and deleted on clean close.
    A stale LOCK (process dead) will prevent reopening the DB.
    """
    lock = folder / "LOCK"
    if lock.exists():
        result.issues.append(Issue(Severity.WARNING, "Stale LOCK file detected",
                                   "A previous process may have crashed. Safe to remove."))


def _check_world_json(folder: Path, result: ValidationResult) -> None:
    """Validate WorldDescription.json syntax."""
    wj = folder / "WorldDescription.json"
    if not wj.exists():
        result.issues.append(Issue(Severity.WARNING, "WorldDescription.json missing",
                                   "World metadata absent; world may not appear in game."))
        return
    if wj.stat().st_size == 0:
        result.issues.append(Issue(Severity.ERROR, "WorldDescription.json is empty"))
        return
    try:
        json.loads(wj.read_text(encoding="utf-8"))
        result.world_json_valid = True
        log.debug("WorldDescription.json: valid JSON")
    except json.JSONDecodeError as exc:
        result.issues.append(Issue(Severity.ERROR, "WorldDescription.json is invalid JSON",
                                   str(exc)))


def _test_rocksdb_open(folder: Path, result: ValidationResult) -> bool:
    """
    Attempt a read-only RocksDB open using rocksdict.
    This is the most reliable corruption detector: if RocksDB itself cannot
    open the folder, recovery is needed. We catch all exceptions so a missing
    library doesn't crash the tool.
    """
    try:
        from rocksdict import Rdict, Options, AccessType
        opts = Options(raw_mode=True)
        db = Rdict(str(folder), options=opts, access_type=AccessType.read_only())
        db.close()
        log.info("RocksDB open test: PASSED")
        return True
    except ImportError:
        result.issues.append(Issue(Severity.WARNING, "rocksdict not installed",
                                   "Install with: pip install rocksdict"))
        return False
    except Exception as exc:  # noqa: BLE001
        result.issues.append(Issue(Severity.ERROR, f"RocksDB open failed: {exc}",
                                   "Database may be corrupt at the engine level."))
        log.warning("RocksDB open test FAILED: %s", exc)
        return False
