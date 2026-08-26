"""Isolated background-run workspaces and conflict-safe review handoff."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Iterable

from harness_editor.change_tracker import apply_text_change, get_last_operation_error, record_binary_change


IGNORED = {
    ".git", ".egoagent", "node_modules", "dist", "build", "out", "target",
    "__pycache__", ".venv", "venv", ".pytest_cache", ".mypy_cache", "coverage",
}
MAX_HANDOFF_FILE = 20 * 1024 * 1024


def _revision(value: bytes | None) -> str:
    return "missing" if value is None else hashlib.sha256(value).hexdigest()


def _files(root: Path) -> Dict[str, bytes]:
    output: Dict[str, bytes] = {}
    for current_root, directories, names in os.walk(root):
        current = Path(current_root)
        directories[:] = [name for name in directories if name not in IGNORED]
        for name in names:
            path = current / name
            relative = path.relative_to(root).as_posix()
            try:
                path.resolve().relative_to(root)
                if path.stat().st_size > MAX_HANDOFF_FILE:
                    continue
                output[relative] = path.read_bytes()
            except (OSError, ValueError):
                continue
    return output


def _manifest_path(isolated: Path) -> Path:
    return isolated.parent / "manifest.json"


def create_isolated_workspace(source: Any, run_id: str) -> Dict[str, Any]:
    source_root = Path(str(source)).expanduser().resolve()
    if not source_root.is_dir():
        raise ValueError(f"workspace does not exist: {source_root}")
    run_id = str(run_id)
    if not run_id or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in run_id):
        raise ValueError("invalid background run id")
    isolated = source_root / ".egoagent" / "background_runs" / run_id / "workspace"
    if isolated.exists():
        raise ValueError(f"isolated workspace already exists: {isolated}")
    isolated.parent.mkdir(parents=True, exist_ok=True)

    def ignore(_directory, names):
        return [name for name in names if name in IGNORED]

    shutil.copytree(source_root, isolated, ignore=ignore, symlinks=False)
    base = _files(isolated)
    manifest = {
        "version": 1,
        "run_id": run_id,
        "source_workspace": str(source_root),
        "isolated_workspace": str(isolated),
        "created_at": time.time(),
        "base": {relative: _revision(content) for relative, content in base.items()},
    }
    temporary = _manifest_path(isolated).with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, _manifest_path(isolated))
    return {
        "strategy": "copy",
        "source_workspace": str(source_root),
        "workspace": str(isolated),
        "manifest": str(_manifest_path(isolated)),
        "files": len(base),
    }


def fork_isolated_workspace(source: Any, snapshot: Any, run_id: str) -> Dict[str, Any]:
    """Create a fresh reviewable isolation whose contents start from another run.

    The immutable base remains the user's current source workspace, while the
    materialized files are copied from ``snapshot``.  This makes a fork safe to
    execute independently and keeps later handoff conflicts meaningful.
    """
    source_root = Path(str(source)).expanduser().resolve()
    snapshot_root = Path(str(snapshot)).expanduser().resolve()
    if not snapshot_root.is_dir():
        raise ValueError(f"fork snapshot does not exist: {snapshot_root}")
    isolated = create_isolated_workspace(source_root, run_id)
    isolated_root = Path(isolated["workspace"])
    current = _files(isolated_root)
    desired = _files(snapshot_root)
    for relative in sorted(set(current) - set(desired)):
        target = (isolated_root / relative).resolve()
        target.relative_to(isolated_root)
        target.unlink(missing_ok=True)
    for relative, content in desired.items():
        target = (isolated_root / relative).resolve()
        target.relative_to(isolated_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    isolated["forked_from_workspace"] = str(snapshot_root)
    return isolated


def _load_manifest(source: Any, isolated: Any, run_id: str) -> tuple[Path, Path, Dict[str, Any]]:
    source_root = Path(str(source)).resolve()
    isolated_root = Path(str(isolated)).resolve()
    expected_parent = source_root / ".egoagent" / "background_runs" / str(run_id)
    try:
        isolated_root.relative_to(expected_parent.resolve())
    except ValueError as error:
        raise ValueError("isolated workspace does not belong to this run") from error
    manifest = json.loads(_manifest_path(isolated_root).read_text(encoding="utf-8"))
    if manifest.get("run_id") != str(run_id) or Path(manifest.get("source_workspace", "")).resolve() != source_root:
        raise ValueError("background workspace manifest mismatch")
    return source_root, isolated_root, manifest


def preview_handoff(source: Any, isolated: Any, run_id: str) -> Dict[str, Any]:
    source_root, isolated_root, manifest = _load_manifest(source, isolated, run_id)
    base_revisions = manifest.get("base", {})
    current = _files(source_root)
    proposed = _files(isolated_root)
    changes = []
    for relative in sorted(set(base_revisions) | set(proposed)):
        base_revision = str(base_revisions.get(relative, "missing"))
        proposed_bytes = proposed.get(relative)
        proposed_revision = _revision(proposed_bytes)
        if proposed_revision == base_revision:
            continue
        current_bytes = current.get(relative)
        current_revision = _revision(current_bytes)
        binary = any(b"\0" in value[:8192] for value in (current_bytes, proposed_bytes) if value is not None)
        kind = "created" if base_revision == "missing" else "deleted" if proposed_bytes is None else "modified"
        entry = {
            "path": relative,
            "kind": kind,
            "binary": binary,
            "base_revision": base_revision,
            "current_revision": current_revision,
            "proposed_revision": proposed_revision,
            "conflict": current_revision != base_revision,
            "size": len(proposed_bytes or b""),
        }
        if not binary:
            before = (current_bytes or b"").decode("utf-8", errors="replace").splitlines()
            after = (proposed_bytes or b"").decode("utf-8", errors="replace").splitlines()
            entry["diff"] = "\n".join(list(difflib.unified_diff(before, after, fromfile=f"source/{relative}", tofile=f"background/{relative}", lineterm=""))[:500])
        changes.append(entry)
    return {
        "run_id": str(run_id), "source_workspace": str(source_root),
        "isolated_workspace": str(isolated_root), "changes": changes,
        "conflicts": sum(1 for item in changes if item["conflict"]),
        "expected_revisions": {item["path"]: item["current_revision"] for item in changes},
    }


def apply_handoff(
    source: Any,
    isolated: Any,
    run_id: str,
    paths: Iterable[str],
    expected_revisions: Dict[str, str],
    *,
    confirm_delete: bool = False,
) -> Dict[str, Any]:
    preview = preview_handoff(source, isolated, run_id)
    source_root = Path(preview["source_workspace"])
    isolated_root = Path(preview["isolated_workspace"])
    by_path = {item["path"]: item for item in preview["changes"]}
    selected = list(dict.fromkeys(str(value).replace("\\", "/") for value in paths))
    if not selected:
        raise ValueError("at least one handoff path is required")
    unknown = [value for value in selected if value not in by_path]
    if unknown:
        raise ValueError(f"unknown handoff paths: {', '.join(unknown)}")
    if any(by_path[value]["kind"] == "deleted" for value in selected) and not confirm_delete:
        return {"ok": False, "delete_confirmation_required": True, "paths": [value for value in selected if by_path[value]["kind"] == "deleted"], "preview": preview}
    applied, conflicts = [], []
    transaction_id = f"background-handoff:{run_id}"
    for relative in selected:
        entry = by_path[relative]
        if expected_revisions.get(relative) != entry["current_revision"] or entry["conflict"]:
            conflicts.append({"path": relative, "expected": expected_revisions.get(relative), "current": entry["current_revision"], "base": entry["base_revision"]})
            continue
        target = (source_root / relative).resolve()
        proposal = (isolated_root / relative).resolve()
        try:
            target.relative_to(source_root)
            proposal.relative_to(isolated_root)
        except ValueError:
            conflicts.append({"path": relative, "error": "path escapes workspace"})
            continue
        old_bytes = target.read_bytes() if target.is_file() else None
        new_bytes = proposal.read_bytes() if proposal.is_file() else None
        if entry["binary"]:
            if new_bytes is None:
                if target.exists():
                    target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(f".{target.name}.handoff.tmp")
                temporary.write_bytes(new_bytes)
                os.replace(temporary, target)
            record_binary_change(target, old_bytes, new_bytes, "background_handoff", transaction_id)
        else:
            old_text = old_bytes.decode("utf-8", errors="strict") if old_bytes is not None else None
            new_text = new_bytes.decode("utf-8", errors="strict") if new_bytes is not None else None
            change_id = apply_text_change(target, old_text, new_text, "background_handoff", transaction_id)
            if change_id is None:
                conflicts.append({"path": relative, "error": get_last_operation_error()})
                continue
        applied.append(relative)
    return {"ok": not conflicts, "applied": applied, "conflicts": conflicts, "transaction_id": transaction_id}
