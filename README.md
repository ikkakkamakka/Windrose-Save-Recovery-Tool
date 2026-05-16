# Windrose-Save-Recovery-Tool
A desktop utility for diagnosing and recovering corrupted Windrose game saves. Supports both RocksDB and RocksDB_v2 save formats, with full awareness of Windrose's 22 named column families (R5BLIsland, R5BLBuilding, R5BLPlayerInWorld, etc.). Validates save integrity by checking CURRENT/MANIFEST structure, SST file health, stale LOCK files.
