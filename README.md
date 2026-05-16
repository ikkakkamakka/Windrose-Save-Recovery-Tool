# Windrose Save Recovery Tool

A desktop utility for diagnosing and recovering corrupted Windrose game saves.
Built for players who have experienced crashes, failed migrations, or saves that
no longer appear in the game's world selection screen.

---

## The Problem

Windrose stores world save data in RocksDB databases. When the game crashes mid-write,
or during the migration from `RocksDB` to `RocksDB_v2`, the database can be left in
a state that prevents it from opening. The most common symptoms:

- A world that has disappeared from the in-game list
- A stale `LOCK` file left by a crashed process, blocking re-entry
- A missing or malformed `CURRENT` file that RocksDB cannot resolve
- A corrupt or incomplete `MANIFEST` from an interrupted write

This tool detects all of the above, reports exactly what is wrong, and attempts
safe recovery without ever modifying your original save.

---

## Features

**Validation**
- Verifies the `CURRENT` file exists and points to a valid `MANIFEST`
- Checks all `MANIFEST-*` files for truncation or zero-byte corruption
- Inspects every `.sst` file for emptiness
- Detects stale `LOCK` files from crashed processes
- Validates `WorldDescription.json` syntax
- Performs a live RocksDB open test across all 22 Windrose column families
- Reports record counts per column family (`R5BLIsland`, `R5BLBuilding`, `R5BLPlayerInWorld`, etc.)

**Recovery**
- Removes stale `LOCK` and temporary files
- Rebuilds a missing or malformed `CURRENT` file
- Prunes orphaned `MANIFEST` files from unclean shutdowns
- Runs RocksDB's built-in `repair()` to reconstruct metadata from SST table properties
- Can restore missing or empty files from a selected backup

**Backup System**
- Creates a full timestamped backup before any operation
- Writes a SHA-256 checksum manifest alongside each backup
- All repairs are output to a `_Recovered` copy — the original is never modified

**Supports both save formats**
- `RocksDB`
- `RocksDB_v2`
- `RocksDB_v2_Backups`

---

## Installation

Requires Python 3.12 or later.

```bash
git clone https://github.com/ikkakkamakka/Windrose-Save-Recovery-Tool.git
cd Windrose-Save-Recovery-Tool
pip install -r requirements.txt
python main.py
```

**Dependencies**

| Package | Purpose |
|---|---|
| `PySide6` | Desktop GUI |
| `rocksdict` | RocksDB bindings (open test, repair, key enumeration) |

`rocksdict` ships pre-built wheels for Windows x64 via pip. If installation fails
on your platform, the tool remains fully functional for all file-structure checks;
only the live RocksDB open test and `repair()` call are skipped.

---

## Usage

**1. Select your save folder**

Click `Browse` and navigate to your world's save directory, or use `Auto-detect`
to have the tool locate the default Windrose save path automatically.

Default Windows path:
```
%LOCALAPPDATA%\R5\Saved\SaveProfiles\<SteamID>\RocksDB_v2\Worlds<WorldID>\
```

**2. Analyze**

Click `Analyze Save` to run a full structural and engine-level validation.
The diagnostics panel will report every issue found, colour-coded by severity,
along with a per-column-family record count.

**3. Repair**

Click `Repair Save` to attempt recovery. You will be asked to confirm before
anything happens. The tool will:

1. Create a timestamped backup of the original
2. Clone the save to `<WorldFolder>_Recovered`
3. Remove stale lock and temp files
4. Rebuild `CURRENT` if missing or malformed
5. Move orphan `MANIFEST` files out of the way
6. Run `rocksdict.repair()` on the clone
7. Confirm the recovered copy opens cleanly

**4. Restore Backup**

If a previous backup exists, select it from the `Available Backups` dropdown
and click `Restore Backup` to recover from it.

---

## Project Structure

```
windrose_tool/
├── main.py                        Entry point
├── requirements.txt
├── core/
│   ├── validator.py               Structural and engine-level validation
│   ├── backup.py                  Timestamped backup creation and verification
│   ├── recovery.py                Repair pipeline (always operates on a clone)
│   └── rocksdb_utils.py           Path detection, CF enumeration, key sampling
├── models/
│   └── results.py                 ValidationResult, RecoveryResult, Severity
├── ui/
│   └── main_window.py             PySide6 GUI with threaded workers
├── logs/
│   └── recovery.log               Created at runtime
└── scripts/
    └/simulate_corrupt_save.py     Test helper — generates fake saves in 5 corruption modes
```

---

## Testing Without a Real Windrose Install

```bash
# Healthy save
python scripts/simulate_corrupt_save.py --mode healthy

# Missing CURRENT file
python scripts/simulate_corrupt_save.py --mode missing_current

# Zero-byte MANIFEST
python scripts/simulate_corrupt_save.py --mode bad_manifest

# Stale LOCK file
python scripts/simulate_corrupt_save.py --mode stale_lock

# Truncated WorldDescription.json
python scripts/simulate_corrupt_save.py --mode bad_json
```

Output is written to `/tmp/windrose_test/`. Browse to that directory in the tool
to test each scenario.

---

## Safety Guarantees

| Operation | What happens to the original |
|---|---|
| Analyze | Read-only. Nothing is written. |
| Repair | Backup created first. Output goes to `_Recovered`. Original untouched. |
| Restore | Safety backup made. Output goes to `_Recovered`. Original untouched. |

The tool will never delete, overwrite, or modify any file in your original save
directory. Every destructive action requires explicit confirmation.

---

## Logs

All operations are written to `logs/recovery.log` at debug level. If you are
reporting an issue, please include the relevant section of this log.

---

## License

MIT
