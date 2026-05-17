# Windrose Save Recovery Tool

Desktop utility for validating and recovering corrupted Windrose save files (RocksDB-based).

## Quick Start

```bash
pip install -r requirements.txt
python main.py
```

## Requirements

- Python 3.12+
- `PySide6` – GUI
- `rocksdict` – RocksDB bindings (optional but enables live DB open-test and repair)

## Project Structure

```
windrose_tool/
├── main.py                        # Entry point
├── requirements.txt
├── core/
│   ├── validator.py               # Save validation logic
│   ├── backup.py                  # Timestamped backup creation
│   ├── recovery.py                # Repair operations (always on a clone)
│   └── rocksdb_utils.py           # Path detection, DB key enumeration
├── models/
│   └── results.py                 # ValidationResult, RecoveryResult, Severity
├── ui/
│   └── main_window.py             # PySide6 GUI
├── logs/
│   └── recovery.log               # Auto-created on first run
└── scripts/
    └── simulate_corrupt_save.py   # Test helper – creates fake saves
```

## Testing with Simulated Saves

```bash
# Create a healthy fake save
python scripts/simulate_corrupt_save.py --mode healthy

# Create a save with missing CURRENT
python scripts/simulate_corrupt_save.py --mode missing_current

# Other modes: bad_manifest | stale_lock | bad_json
```

Then open the tool, click **Auto-detect** or browse to `/tmp/windrose_test/`.

## Safety Guarantees

| Operation | Original files |
|-----------|---------------|
| Analyze   | Read-only, never modified |
| Repair    | Backup created first; output goes to `_Recovered` copy |
| Restore   | Safety backup made; `_Recovered` copy written |

The original save folder is **never modified directly**.

## Windrose Save Paths

```
Windows: %LOCALAPPDATA%\R5\Saved\SaveProfiles\<SteamID>\
              RocksDB\Worlds<ID>\
              RocksDB_v2\Worlds<ID>\
              RocksDB_v2_Backups\Worlds<ID>\
```

## Logs

All operations logged to `logs/recovery.log` (rotating, debug level).
