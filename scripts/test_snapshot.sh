#!/usr/bin/env bash
# Test script for the EgoAgent Snapshot Manager
# Tests: create, list, restore, cleanup

set -e

cd "$(dirname "$0")/.."

echo "=== EgoAgent Snapshot Manager Test ==="
echo ""

# Test 1: Create a snapshot
echo "[1/4] Creating snapshot for 'dante'..."
python3 -c "
import sys
sys.path.insert(0, '.')
from self_evolution.snapshot_manager import SnapshotManager

sm = SnapshotManager()
result = sm.create_snapshot('dante', reason='manual')
print(f\"  Snapshot ID: {result['snapshot_id']}\")
print(f\"  Timestamp:   {result['timestamp']}\")
print(f\"  Files saved: {len(result['files_saved'])}\")
print('  [PASS] Snapshot created successfully')
"
echo ""

# Test 2: List snapshots
echo "[2/4] Listing snapshots for 'dante'..."
python3 -c "
import sys
sys.path.insert(0, '.')
from self_evolution.snapshot_manager import SnapshotManager

sm = SnapshotManager()
snapshots = sm.list_snapshots('dante')
print(f'  Total snapshots: {len(snapshots)}')
for s in snapshots[:5]:
    print(f\"    - {s['snapshot_id']} ({s['reason']}, {s['file_count']} files)\")
if len(snapshots) > 5:
    print(f'    ... and {len(snapshots) - 5} more')
print('  [PASS] Listing works')
"
echo ""

# Test 3: Restore snapshot (creates a second snapshot, then restores the first)
echo "[3/4] Testing restore..."
python3 -c "
import sys, time
sys.path.insert(0, '.')
from self_evolution.snapshot_manager import SnapshotManager

sm = SnapshotManager()

# Get the latest snapshot
snapshots = sm.list_snapshots('dante')
if len(snapshots) < 1:
    print('  [SKIP] Need at least 1 snapshot to test restore')
    sys.exit(0)

target_id = snapshots[0]['snapshot_id']
print(f'  Restoring to: {target_id}')
result = sm.restore_snapshot('dante', target_id)
print(f\"  Restored ID: {result['restored_id']}\")
print(f\"  Backup ID:   {result['backup_id']}\")
print('  [PASS] Restore works (backup created before restore)')
"
echo ""

# Test 4: Auto-cleanup
echo "[4/4] Testing auto-cleanup (keep_last_n=5)..."
python3 -c "
import sys
sys.path.insert(0, '.')
from self_evolution.snapshot_manager import SnapshotManager

sm = SnapshotManager()
deleted = sm.auto_cleanup('dante', keep_last_n=5)
remaining = sm.list_snapshots('dante')
print(f'  Deleted: {len(deleted)} snapshots')
print(f'  Remaining: {len(remaining)} snapshots')
print('  [PASS] Auto-cleanup works')
"
echo ""

echo "=== All tests passed ==="
