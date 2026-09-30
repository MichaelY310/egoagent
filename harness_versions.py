"""Immutable, runnable Flow versions for editable Harness directories."""

import hashlib
import json
import shutil
import time
from pathlib import Path


def harness_version_manifest(harness_dir):
    return Path(harness_dir) / ".versions" / "index.json"


def read_harness_versions(harness_dir):
    manifest_path = harness_version_manifest(harness_dir)
    if not manifest_path.is_file():
        return {"schema_version": 1, "harness": Path(harness_dir).name, "latest": "", "versions": []}
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data.setdefault("schema_version", 1)
    data.setdefault("harness", Path(harness_dir).name)
    data.setdefault("latest", "")
    data.setdefault("versions", [])
    return data


def snapshot_harness_version(harness_dir, *, label="", force=False):
    """Persist config, scripts and hooks as an immutable runnable snapshot."""
    harness_dir = Path(harness_dir)
    config_path = harness_dir / "config.json"
    if not config_path.is_file():
        raise FileNotFoundError(f"Harness config not found: {config_path}")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    canonical = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest_state = hashlib.sha256(canonical)
    for source in sorted(harness_dir.rglob("*"), key=lambda path: path.as_posix()):
        relative = source.relative_to(harness_dir)
        if ".versions" in relative.parts or not source.is_file() or relative.as_posix() == "config.json":
            continue
        digest_state.update(relative.as_posix().encode("utf-8"))
        digest_state.update(b"\0")
        digest_state.update(source.read_bytes())
    digest = digest_state.hexdigest()
    manifest = read_harness_versions(harness_dir)
    latest = next((item for item in reversed(manifest["versions"]) if item.get("id") == manifest.get("latest")), None)
    if latest and latest.get("digest") == digest and not force:
        return {**latest, "created": False}
    counter = max([int(item.get("number") or 0) for item in manifest["versions"]] or [0]) + 1
    version_id = f"v{counter:06d}-{time.strftime('%Y%m%d-%H%M%S')}-{digest[:8]}"
    snapshot_dir = harness_dir / ".versions" / version_id
    snapshot_dir.mkdir(parents=True, exist_ok=False)
    for item in harness_dir.iterdir():
        if item.name == ".versions":
            continue
        target = snapshot_dir / item.name
        if item.is_dir():
            shutil.copytree(item, target)
        elif item.is_file():
            shutil.copy2(item, target)
    record = {
        "id": version_id, "number": counter, "created_at": time.time(), "digest": digest,
        "parent": manifest.get("latest") or None, "label": str(label or f"Version {counter}"),
    }
    manifest["latest"] = version_id
    manifest["versions"].append(record)
    manifest_path = harness_version_manifest(harness_dir)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = manifest_path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(manifest_path)
    return {**record, "created": True}


def ensure_harness_versions(harness_dir):
    harness_dir = Path(harness_dir)
    manifest = read_harness_versions(harness_dir)
    if not manifest["versions"]:
        snapshot_harness_version(harness_dir, label="Imported baseline", force=True)
        manifest = read_harness_versions(harness_dir)
    return manifest


def resolve_harness_version_dir(harness_dir, version="latest"):
    harness_dir = Path(harness_dir)
    manifest = ensure_harness_versions(harness_dir)
    requested = str(version or "latest").strip()
    version_id = manifest.get("latest") if requested == "latest" else requested
    if not version_id or not any(item.get("id") == version_id for item in manifest["versions"]):
        raise FileNotFoundError(f"Harness version not found: {requested}")
    snapshot_dir = harness_dir / ".versions" / version_id
    if not (snapshot_dir / "config.json").is_file():
        raise FileNotFoundError(f"Harness version is incomplete: {version_id}")
    return snapshot_dir, version_id
