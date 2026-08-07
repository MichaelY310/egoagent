"""File checkpoint/rollback system for EgoAgent IDE."""

import json
import os
import time
import hashlib
import shutil
from pathlib import Path
from typing import Dict, List, Optional

_checkpoints: List[Dict] = []
_workspace: Optional[str] = None

CHECKPOINT_DIR = Path(__file__).resolve().parent.parent / ".egoagent_checkpoints"


def init(workspace=None):
    """Initialize checkpoint manager, set workspace, create checkpoint directory."""
    global _workspace
    _workspace = workspace
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)


def create_checkpoint(label="", files=None, trigger="manual") -> Dict:
    """Create a checkpoint for the given files."""
    global _checkpoints

    if files is None:
        files = []

    cp_id = f"cp_{int(time.time())}_{len(_checkpoints)}"
    timestamp = time.time()
    snapshots = {}

    for file_path in files:
        path = Path(file_path)
        snapshot = {"path": str(file_path)}
        if path.exists():
            try:
                content = path.read_text(encoding="utf-8")
                md5_hash = hashlib.md5(content.encode("utf-8")).hexdigest()
                snapshot["existed"] = True
                snapshot["content"] = content
                snapshot["md5"] = md5_hash
            except (IOError, OSError, UnicodeDecodeError):
                snapshot["existed"] = True
                snapshot["content"] = None
                snapshot["md5"] = None
        else:
            snapshot["existed"] = False
            snapshot["content"] = None
            snapshot["md5"] = None
        snapshots[str(file_path)] = snapshot

    checkpoint = {
        "id": cp_id,
        "index": len(_checkpoints),
        "label": label,
        "timestamp": timestamp,
        "trigger": trigger,
        "file_count": len(snapshots),
        "snapshots": snapshots,
    }

    _checkpoints.append(checkpoint)
    _save_meta(checkpoint)

    return {
        "id": cp_id,
        "index": checkpoint["index"],
        "label": label,
        "timestamp": timestamp,
        "trigger": trigger,
        "file_count": len(snapshots),
    }


def list_checkpoints() -> List[Dict]:
    """Return all checkpoints without file content."""
    result = []
    for cp in _checkpoints:
        result.append({
            "id": cp["id"],
            "index": cp["index"],
            "label": cp["label"],
            "timestamp": cp["timestamp"],
            "trigger": cp["trigger"],
            "file_count": cp["file_count"],
        })
    return result


def rollback(cp_id) -> Dict:
    """Rollback to a specific checkpoint by id."""
    global _checkpoints

    target = None
    target_idx = None
    for i, cp in enumerate(_checkpoints):
        if cp["id"] == cp_id:
            target = cp
            target_idx = i
            break

    if target is None:
        return {
            "checkpoint_id": cp_id,
            "restored_files": 0,
            "removed_checkpoints": 0,
            "details": [],
            "errors": [f"Checkpoint '{cp_id}' not found"],
        }

    details = []
    errors = []
    restored_files = 0

    for file_path, snapshot in target["snapshots"].items():
        try:
            path = Path(file_path)
            if snapshot["existed"]:
                if snapshot["content"] is not None:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(snapshot["content"], encoding="utf-8")
                    details.append(f"Restored: {file_path}")
                    restored_files += 1
                else:
                    details.append(f"Skipped (unreadable at checkpoint time): {file_path}")
            else:
                if path.exists():
                    path.unlink()
                    details.append(f"Deleted (did not exist at checkpoint): {file_path}")
                    restored_files += 1
                else:
                    details.append(f"Already absent: {file_path}")
        except (IOError, OSError) as e:
            errors.append(f"Error restoring {file_path}: {e}")

    # Remove checkpoints after the target
    removed = _checkpoints[target_idx + 1:]
    removed_count = len(removed)
    for cp in removed:
        meta_path = CHECKPOINT_DIR / f"{cp['id']}.json"
        if meta_path.exists():
            meta_path.unlink()
    _checkpoints = _checkpoints[: target_idx + 1]

    return {
        "checkpoint_id": cp_id,
        "restored_files": restored_files,
        "removed_checkpoints": removed_count,
        "details": details,
        "errors": errors,
    }


def rollback_to_index(index) -> Dict:
    """Rollback to a specific checkpoint by index."""
    if index < 0 or index >= len(_checkpoints):
        return {
            "checkpoint_id": None,
            "restored_files": 0,
            "removed_checkpoints": 0,
            "details": [],
            "errors": [f"Invalid checkpoint index: {index}"],
        }
    return rollback(_checkpoints[index]["id"])


def auto_checkpoint(file_path, label="") -> Dict:
    """Create a single-file checkpoint with trigger='pre_tool'."""
    filename = Path(file_path).name
    if not label:
        label = f"Before modifying {filename}"
    return create_checkpoint(label=label, files=[file_path], trigger="pre_tool")


def clear_all():
    """Clear all checkpoints and remove checkpoint directory contents."""
    global _checkpoints
    _checkpoints = []
    if CHECKPOINT_DIR.exists():
        shutil.rmtree(CHECKPOINT_DIR)
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)


def _save_meta(checkpoint):
    """Save checkpoint metadata (without snapshots content) to disk."""
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    meta = {
        "id": checkpoint["id"],
        "index": checkpoint["index"],
        "label": checkpoint["label"],
        "timestamp": checkpoint["timestamp"],
        "trigger": checkpoint["trigger"],
        "file_count": checkpoint["file_count"],
    }
    meta_path = CHECKPOINT_DIR / f"{checkpoint['id']}.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
