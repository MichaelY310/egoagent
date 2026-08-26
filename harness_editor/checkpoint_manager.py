"""Persistent, revision-checked file checkpoints for EgoAgent IDE.

Checkpoints are immutable snapshots.  Restoring one never deletes newer
checkpoints and every materialized restore is recorded in the shared Agent
change journal, so the user can still review or undo the restore decision.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional


_ROOT = Path(__file__).resolve().parent.parent
CHECKPOINT_DIR = _ROOT / ".egoagent_checkpoints"
_checkpoints: List[Dict] = []
_workspace: Optional[str] = None
_lock = threading.RLock()
_loaded = False
_SCHEMA_VERSION = 2


def configure(workspace=None, checkpoint_dir=None, *, load=True):
    """Configure storage/workspace; primarily useful for isolated tests."""
    global _workspace, CHECKPOINT_DIR, _loaded
    with _lock:
        _workspace = str(Path(workspace).resolve()) if workspace else None
        if checkpoint_dir is not None:
            CHECKPOINT_DIR = Path(checkpoint_dir).resolve()
        CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
        _checkpoints.clear()
        _loaded = False
        if load:
            _load_locked()
    return str(CHECKPOINT_DIR)


def init(workspace=None):
    """Backward-compatible initialization alias."""
    return configure(workspace=workspace)


def reload_store():
    global _loaded
    with _lock:
        _checkpoints.clear()
        _loaded = False
        _load_locked()
        return len(_checkpoints)


def create_checkpoint(label="", files=None, trigger="manual", workspace=None, metadata=None) -> Dict:
    """Create and durably persist an immutable checkpoint."""
    with _lock:
        _load_locked()
        workspace_root = _workspace_path(workspace)
        requested = list(files or [])
        snapshots = {}
        for value in requested:
            path = _resolve_target(value, workspace_root)
            snapshots[str(path)] = _snapshot(path, workspace_root)

        checkpoint_id = f"cp_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
        checkpoint = {
            "schema_version": _SCHEMA_VERSION,
            "id": checkpoint_id,
            "index": len(_checkpoints),
            "label": str(label or "Checkpoint")[:240],
            "timestamp": time.time(),
            "trigger": str(trigger or "manual")[:80],
            "workspace": str(workspace_root) if workspace_root else None,
            "file_count": len(snapshots),
            "snapshots": snapshots,
            "metadata": dict(metadata or {}),
        }
        checkpoint["mutation_counts"] = _mutation_counts(checkpoint)
        _checkpoints.append(checkpoint)
        _save_locked(checkpoint)
        return _summary(checkpoint, include_changes=True)


def list_checkpoints(workspace=None) -> List[Dict]:
    with _lock:
        _load_locked()
        root = _workspace_path(workspace) if workspace else None
        values = [item for item in _checkpoints if not root or item.get("workspace") == str(root)]
        return [_summary(item, include_changes=True) for item in reversed(values)]


def get_checkpoint(checkpoint_id, *, include_content=False) -> Optional[Dict]:
    with _lock:
        _load_locked()
        checkpoint = _find(checkpoint_id)
        if not checkpoint:
            return None
        result = _summary(checkpoint, include_changes=True)
        result["files"] = []
        for snapshot in checkpoint.get("snapshots", {}).values():
            item = {key: value for key, value in snapshot.items() if key != "content_b64"}
            if include_content:
                item["content_b64"] = snapshot.get("content_b64")
            result["files"].append(item)
        return result


def preview_restore(checkpoint_id, files=None) -> Dict:
    """Return exact restore impact and revisions to use for conflict-safe apply."""
    with _lock:
        _load_locked()
        checkpoint = _find(checkpoint_id)
        if not checkpoint:
            return {"ok": False, "checkpoint_id": checkpoint_id, "errors": ["Checkpoint not found"], "impacts": []}
        selected = _select_snapshots(checkpoint, files)
        impacts = []
        for snapshot in selected:
            path = Path(snapshot["path"])
            current = path.read_bytes() if path.is_file() else None
            current_revision = _revision(current)
            target_revision = snapshot.get("revision", "missing")
            if current_revision == target_revision:
                action = "unchanged"
            elif snapshot.get("existed"):
                action = "restore" if current is not None else "recreate"
            else:
                action = "delete"
            impacts.append({
                "path": snapshot["path"],
                "relative_path": snapshot.get("relative_path"),
                "artifact_type": snapshot.get("artifact_type", "file"),
                "action": action,
                "binary": bool(snapshot.get("binary")),
                "checkpoint_revision": target_revision,
                "current_revision": current_revision,
                "checkpoint_size": snapshot.get("size"),
                "current_size": None if current is None else len(current),
                "requires_delete_confirmation": action == "delete",
            })
        return {
            "ok": True,
            "checkpoint_id": checkpoint_id,
            "label": checkpoint.get("label"),
            "workspace": checkpoint.get("workspace"),
            "impacts": impacts,
            "changed": sum(item["action"] != "unchanged" for item in impacts),
            "expected_revisions": {item["path"]: item["current_revision"] for item in impacts},
        }


def rollback(checkpoint_id, files=None, expected_revisions=None, confirm_delete=False) -> Dict:
    """Selectively restore after checking the revisions observed in preview."""
    with _lock:
        _load_locked()
        checkpoint = _find(checkpoint_id)
        if not checkpoint:
            return _restore_result(checkpoint_id, errors=[f"Checkpoint '{checkpoint_id}' not found"])
        selected = _select_snapshots(checkpoint, files)
        expected = dict(expected_revisions or {})
        details, errors, conflicts, pending_deletes = [], [], [], []
        restored = 0
        transaction_id = f"checkpoint-restore-{checkpoint_id}-{uuid.uuid4().hex[:8]}"

        for snapshot in selected:
            path = Path(snapshot["path"])
            try:
                current = path.read_bytes() if path.is_file() else None
            except OSError as error:
                errors.append(f"Could not inspect {path}: {error}")
                continue
            current_revision = _revision(current)
            observed = expected.get(str(path), expected.get(snapshot.get("relative_path", "")))
            if observed is not None and observed != current_revision:
                conflicts.append({
                    "path": str(path),
                    "code": "revision_conflict",
                    "message": "File changed after restore preview",
                    "expected_revision": observed,
                    "current_revision": current_revision,
                })
                continue
            target = _decode(snapshot.get("content_b64")) if snapshot.get("existed") else None
            if current == target:
                details.append({"path": str(path), "action": "unchanged"})
                continue
            if target is None and current is not None and not confirm_delete:
                pending_deletes.append(str(path))
                continue
            try:
                _materialize(path, target)
                _record_restore(path, current, target, snapshot, transaction_id)
                action = "deleted" if target is None else "restored"
                details.append({"path": str(path), "action": action})
                restored += 1
            except (OSError, ValueError) as error:
                errors.append(f"Could not restore {path}: {error}")

        return _restore_result(
            checkpoint_id,
            restored_files=restored,
            details=details,
            errors=errors,
            conflicts=conflicts,
            pending_deletes=pending_deletes,
            transaction_id=transaction_id if restored else None,
        )


def rollback_to_index(index) -> Dict:
    with _lock:
        _load_locked()
        if index < 0 or index >= len(_checkpoints):
            return _restore_result(None, errors=[f"Invalid checkpoint index: {index}"])
        return rollback(_checkpoints[index]["id"])


def auto_checkpoint(file_path, label="", workspace=None) -> Dict:
    filename = Path(file_path).name
    return create_checkpoint(
        label=label or f"Before modifying {filename}",
        files=[file_path],
        trigger="pre_tool",
        workspace=workspace,
    )


def clear_all():
    global _loaded
    with _lock:
        _checkpoints.clear()
        CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
        removed = 0
        for path in CHECKPOINT_DIR.glob("cp_*.json"):
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
        _loaded = True
        return {"ok": True, "removed": removed}


def _workspace_path(workspace=None):
    value = workspace or _workspace
    return Path(value).resolve(strict=True) if value else None


def _resolve_target(value, workspace_root):
    path = Path(value)
    if not path.is_absolute():
        if workspace_root is None:
            raise ValueError("Relative checkpoint paths require a workspace")
        path = workspace_root / path
    path = path.resolve(strict=False)
    if workspace_root is not None:
        try:
            if os.path.commonpath((str(workspace_root), str(path))) != str(workspace_root):
                raise ValueError(f"Checkpoint path escapes workspace: {value}")
        except ValueError as error:
            raise ValueError(f"Checkpoint path escapes workspace: {value}") from error
    return path


def _snapshot(path, workspace_root):
    content = path.read_bytes() if path.is_file() else None
    binary = bool(content is not None and (b"\x00" in content or not _is_utf8(content)))
    relative = None
    if workspace_root:
        try:
            relative = path.relative_to(workspace_root).as_posix()
        except ValueError:
            pass
    return {
        "path": str(path),
        "relative_path": relative,
        "artifact_type": _artifact_type(relative),
        "existed": content is not None,
        "binary": binary,
        "content_b64": _encode(content),
        "revision": _revision(content),
        "size": None if content is None else len(content),
    }


def _artifact_type(relative_path):
    value = str(relative_path or "").replace("\\", "/").lower()
    if value.startswith("harness/"):
        return "harness"
    if value.startswith("identity/"):
        return "identity"
    if value.startswith("environment/"):
        return "environment"
    return "file"


def _mutation_counts(checkpoint):
    counts = {"file": 0, "harness": 0, "identity": 0, "environment": 0}
    for snapshot in checkpoint.get("snapshots", {}).values():
        kind = snapshot.get("artifact_type", "file")
        counts[kind] = counts.get(kind, 0) + 1
    return counts


def _summary(checkpoint, include_changes=False):
    result = {
        "id": checkpoint["id"],
        "index": checkpoint.get("index", 0),
        "label": checkpoint.get("label", "Checkpoint"),
        "timestamp": checkpoint.get("timestamp", 0),
        "trigger": checkpoint.get("trigger", "manual"),
        "workspace": checkpoint.get("workspace"),
        "file_count": checkpoint.get("file_count", len(checkpoint.get("snapshots", {}))),
        "mutation_counts": checkpoint.get("mutation_counts") or _mutation_counts(checkpoint),
        "metadata": checkpoint.get("metadata", {}),
    }
    if include_changes:
        preview = preview_restore(checkpoint["id"])
        result["changed_files"] = [item for item in preview.get("impacts", []) if item["action"] != "unchanged"]
        result["changed_count"] = len(result["changed_files"])
    return result


def _select_snapshots(checkpoint, files=None):
    snapshots = list(checkpoint.get("snapshots", {}).values())
    if not files:
        return snapshots
    wanted = {str(value).replace("\\", "/").lower() for value in files}
    return [
        item for item in snapshots
        if str(item.get("path", "")).replace("\\", "/").lower() in wanted
        or str(item.get("relative_path", "")).replace("\\", "/").lower() in wanted
    ]


def _find(checkpoint_id):
    return next((item for item in _checkpoints if item.get("id") == checkpoint_id), None)


def _restore_result(checkpoint_id, *, restored_files=0, details=None, errors=None, conflicts=None, pending_deletes=None, transaction_id=None):
    errors = list(errors or [])
    conflicts = list(conflicts or [])
    pending_deletes = list(pending_deletes or [])
    return {
        "ok": not errors and not conflicts and not pending_deletes,
        "checkpoint_id": checkpoint_id,
        "restored_files": restored_files,
        "removed_checkpoints": 0,
        "details": list(details or []),
        "errors": errors,
        "conflicts": conflicts,
        "delete_confirmation_required": bool(pending_deletes),
        "pending_deletes": pending_deletes,
        "transaction_id": transaction_id,
    }


def _materialize(path, content):
    if content is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.checkpoint-{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(content)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _record_restore(path, old_bytes, new_bytes, snapshot, transaction_id):
    from harness_editor.change_tracker import record_binary_change, record_change

    if not snapshot.get("binary") and _is_utf8(old_bytes) and _is_utf8(new_bytes):
        old_text = None if old_bytes is None else old_bytes.decode("utf-8")
        new_text = None if new_bytes is None else new_bytes.decode("utf-8")
        record_change(path, old_text, new_text, "checkpoint-restore", transaction_id=transaction_id)
    else:
        record_binary_change(path, old_bytes, new_bytes, "checkpoint-restore", transaction_id=transaction_id)


def _revision(content):
    return "missing" if content is None else "sha256:" + hashlib.sha256(content).hexdigest()


def _encode(content):
    return None if content is None else base64.b64encode(content).decode("ascii")


def _decode(value):
    return None if value is None else base64.b64decode(value.encode("ascii"))


def _is_utf8(content):
    if content is None:
        return True
    try:
        content.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def _load_locked():
    global _loaded
    if _loaded:
        return
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    _checkpoints.clear()
    for path in CHECKPOINT_DIR.glob("cp_*.json"):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(item, dict) and item.get("id"):
                _checkpoints.append(item)
        except (OSError, ValueError, TypeError):
            continue
    _checkpoints.sort(key=lambda item: (float(item.get("timestamp", 0)), str(item.get("id"))))
    for index, item in enumerate(_checkpoints):
        item["index"] = index
    _loaded = True


def _save_locked(checkpoint):
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    target = CHECKPOINT_DIR / f"{checkpoint['id']}.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, target)


_load_locked()
