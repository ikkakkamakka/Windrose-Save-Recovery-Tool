"""
Creates a fake Windrose save folder tree to test the tool without a real install.

Usage:
    python scripts/simulate_corrupt_save.py [--mode {healthy,missing_current,bad_manifest,stale_lock,bad_json}]
    Outputs to:  /tmp/windrose_test/RocksDB_v2/Worlds0001/
"""

import argparse
import shutil
import struct
from pathlib import Path


BASE = Path("/tmp/windrose_test/RocksDB/Worlds0001")

WORLD_JSON = '{"WorldName":"TestWorld","Seed":12345,"Version":"1.2.0"}'
WORLD_JSON_BAD = '{"WorldName":"TestWorld","Seed":12345, "Version":  '  # truncated

# Minimal valid MANIFEST header (RocksDB VersionEdit magic bytes).
MANIFEST_BYTES = b"\x00\x01\x02\x03" + b"fake_manifest_data" * 4


def write_healthy(folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "MANIFEST-000006").write_bytes(MANIFEST_BYTES)
    (folder / "CURRENT").write_text("MANIFEST-000006\n")
    (folder / "OPTIONS-000005").write_text("[Version]\n  rocksdb_version=8.0.0\n")
    (folder / "LOG").write_text("2024/01/01-00:00:00 Starting db\n")
    (folder / "000003.sst").write_bytes(b"\xff\xfe" + b"\x00" * 512)
    (folder / "WorldDescription.json").write_text(WORLD_JSON)
    print(f"Created HEALTHY save at {folder}")


def write_missing_current(folder: Path):
    write_healthy(folder)
    (folder / "CURRENT").unlink()
    print(f"Removed CURRENT from {folder}")


def write_bad_manifest(folder: Path):
    write_healthy(folder)
    (folder / "MANIFEST-000006").write_bytes(b"")  # zero-byte = corrupt
    print(f"Zeroed MANIFEST-000006 in {folder}")


def write_stale_lock(folder: Path):
    write_healthy(folder)
    (folder / "LOCK").write_text("")
    print(f"Added stale LOCK to {folder}")


def write_bad_json(folder: Path):
    write_healthy(folder)
    (folder / "WorldDescription.json").write_text(WORLD_JSON_BAD)
    print(f"Wrote truncated WorldDescription.json in {folder}")


MODES = {
    "healthy": write_healthy,
    "missing_current": write_missing_current,
    "bad_manifest": write_bad_manifest,
    "stale_lock": write_stale_lock,
    "bad_json": write_bad_json,
}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=MODES.keys(), default="healthy")
    parser.add_argument("--out", default=str(BASE))
    args = parser.parse_args()

    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)

    MODES[args.mode](out)
    print(f"\nTest folder ready. Run the tool and browse to:\n  {out.parent.parent}")
