"""Versioned, integrity-checked EgoAgent package archives.

The format is deliberately small: a JSON manifest plus immutable files under
``payload/`` in a ZIP-compatible ``.egoagentpkg`` archive.  Installation is a
transaction across the canonical repository component roots.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import re
import shutil
import tempfile
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Optional


FORMAT = "ego.agent-package.v1"
EGOAGENT_VERSION = "0.1.0"
COMPONENT_ROOTS = {
    "identity": "identity",
    "harness": "harness",
    "environment": "environment",
    "task": "task_bench/tasks",
    "tests": "tests/package",
    "ego": "self_evolution/packages",
}
ALLOWED_PERMISSIONS = {"read", "write", "process", "network", "mutation", "secrets"}
MAX_FILES = 10_000
MAX_UNPACKED_BYTES = 250 * 1024 * 1024
SECRET_NAMES = {".env", ".env.local", "credentials", "credentials.json", "secrets.json", "id_rsa", "id_ed25519"}
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
SAFE_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,99}$")


class PackageError(ValueError):
    pass


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _safe_relative(value: Any) -> str:
    text = str(value).replace("\\", "/").strip("/")
    path = PurePosixPath(text)
    if not text or path.is_absolute() or ".." in path.parts or any(part in {"", "."} for part in path.parts):
        raise PackageError(f"unsafe package path: {value}")
    return path.as_posix()


def _safe_name(value: Any, label: str) -> str:
    text = str(value or "")
    if not SAFE_NAME.fullmatch(text):
        raise PackageError(f"invalid {label}: {text!r}")
    return text


def _contains_secret(value: Any, path: tuple[str, ...] = ()) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).lower()
            if lowered in {"api_key", "apikey", "token", "password", "secret", "authorization"} and child not in (None, "", "[REDACTED]"):
                return True
            if _contains_secret(child, (*path, str(key))):
                return True
    elif isinstance(value, list):
        return any(_contains_secret(item, path) for item in value)
    return False


def validate_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise PackageError(f"manifest format must be {FORMAT}")
    package = manifest.get("package")
    if not isinstance(package, dict):
        raise PackageError("manifest.package must be an object")
    _safe_name(package.get("name"), "package name")
    version = str(package.get("version", ""))
    if not SEMVER.fullmatch(version):
        raise PackageError("package version must be semantic versioning, for example 1.0.0")
    components = manifest.get("components")
    if not isinstance(components, list) or not components:
        raise PackageError("manifest.components must be a non-empty array")
    seen = set()
    for component in components:
        if not isinstance(component, dict) or component.get("kind") not in COMPONENT_ROOTS:
            raise PackageError(f"unsupported component kind: {component.get('kind') if isinstance(component, dict) else component}")
        name = _safe_name(component.get("name"), "component name")
        component["path"] = _safe_relative(component.get("path") or f"{component['kind']}/{name}")
        identity = (component["kind"], name)
        if identity in seen:
            raise PackageError(f"duplicate component: {component['kind']}/{name}")
        seen.add(identity)
    permissions = manifest.get("permissions", [])
    if not isinstance(permissions, list) or any(str(value) not in ALLOWED_PERMISSIONS for value in permissions):
        raise PackageError(f"permissions must be chosen from {sorted(ALLOWED_PERMISSIONS)}")
    dependencies = manifest.get("dependencies", {})
    if not isinstance(dependencies, dict):
        raise PackageError("dependencies must be an object")
    for name, constraint in dependencies.items():
        _safe_name(name, "dependency name")
        if not isinstance(constraint, str) or not constraint.strip():
            raise PackageError("dependency constraints must be non-empty strings")
    if _contains_secret(manifest):
        raise PackageError("package manifest contains a plaintext secret")
    return manifest


def build_manifest(
    name: str,
    version: str,
    components: Iterable[dict[str, Any]],
    *,
    description: str = "",
    permissions: Optional[Iterable[str]] = None,
    compatibility: Optional[dict[str, Any]] = None,
    provenance: Optional[dict[str, Any]] = None,
    dependencies: Optional[dict[str, str]] = None,
    examples: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    normalized = []
    for component in components:
        item = dict(component)
        source = item.pop("source", None)
        item.setdefault("path", f"{item.get('kind')}/{item.get('name')}")
        if source is not None:
            item["source"] = str(source)
        normalized.append(item)
    manifest = {
        "format": FORMAT,
        "package": {"name": name, "version": version, "description": description},
        "components": normalized,
        "permissions": sorted(set(str(value) for value in (permissions or []))),
        "compatibility": compatibility or {"egoagent": f">={EGOAGENT_VERSION}"},
        "provenance": provenance or {"created_at": time.time(), "tool": "egoagent"},
        "dependencies": dependencies or {},
        "examples": examples or [],
    }
    return validate_manifest(manifest)


def _component_files(root: Path, component: dict[str, Any]) -> list[tuple[Path, str]]:
    source = Path(str(component.get("source") or ""))
    source = source.resolve() if source.is_absolute() else (root / source).resolve()
    try:
        source.relative_to(root)
    except ValueError as error:
        raise PackageError(f"component source escapes repository: {source}") from error
    if not source.exists():
        raise PackageError(f"component source does not exist: {source}")
    candidates = [source] if source.is_file() else sorted(path for path in source.rglob("*") if path.is_file())
    output = []
    for path in candidates:
        if path.is_symlink():
            raise PackageError(f"symlinks are not packageable: {path}")
        relative = path.name if source.is_file() else path.relative_to(source).as_posix()
        if path.name.lower() in SECRET_NAMES or path.name.lower().endswith((".pem", ".key")):
            raise PackageError(f"secret-like file is not packageable: {path.name}")
        archive_path = f"payload/{component['path']}/{relative}"
        output.append((path, _safe_relative(archive_path)))
    return output


def pack_package(manifest: dict[str, Any], source_root: Any, output_path: Any, *, signing_key: bytes | None = None) -> dict[str, Any]:
    root = Path(str(source_root)).resolve()
    output = Path(str(output_path)).resolve()
    normalized = validate_manifest(copy.deepcopy(manifest))
    files: dict[str, str] = {}
    payloads: dict[str, bytes] = {}
    total = 0
    for component in normalized["components"]:
        declared_source = Path(str(component.get("source") or ""))
        declared_source = declared_source.resolve() if declared_source.is_absolute() else (root / declared_source).resolve()
        component["layout"] = "file" if declared_source.is_file() else "directory"
        for source, archive_path in _component_files(root, component):
            content = source.read_bytes()
            total += len(content)
            if len(payloads) >= MAX_FILES or total > MAX_UNPACKED_BYTES:
                raise PackageError("package exceeds file or unpacked-size limits")
            payloads[archive_path] = content
            files[archive_path] = _sha256(content)
        component.pop("source", None)
    normalized["files"] = dict(sorted(files.items()))
    normalized["integrity"] = {"algorithm": "sha256", "manifest": _sha256(_json_bytes(normalized["files"]))}
    if signing_key:
        unsigned = copy.deepcopy(normalized)
        unsigned.pop("signature", None)
        normalized["signature"] = {"algorithm": "hmac-sha256", "value": hmac.new(signing_key, _json_bytes(unsigned), hashlib.sha256).hexdigest()}
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        manifest_info = zipfile.ZipInfo("manifest.json", (2020, 1, 1, 0, 0, 0))
        manifest_info.external_attr = 0o600 << 16
        archive.writestr(manifest_info, json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"))
        for archive_path, content in sorted(payloads.items()):
            info = zipfile.ZipInfo(archive_path, (2020, 1, 1, 0, 0, 0))
            info.external_attr = 0o600 << 16
            archive.writestr(info, content, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    os.replace(temporary, output)
    return {"path": str(output), "name": normalized["package"]["name"], "version": normalized["package"]["version"], "files": len(payloads), "size": output.stat().st_size, "sha256": _sha256(output.read_bytes()), "manifest": normalized}


def inspect_package(path: Any, *, signing_key: bytes | None = None, require_signature: bool = False) -> dict[str, Any]:
    archive_path = Path(str(path)).resolve()
    total = 0
    with zipfile.ZipFile(archive_path, "r") as archive:
        infos = archive.infolist()
        if len(infos) > MAX_FILES + 1:
            raise PackageError("archive contains too many files")
        names = []
        for info in infos:
            name = _safe_relative(info.filename)
            names.append(name)
            total += info.file_size
            if total > MAX_UNPACKED_BYTES:
                raise PackageError("archive exceeds unpacked-size limit")
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise PackageError(f"archive contains a symlink: {name}")
        if "manifest.json" not in names:
            raise PackageError("archive has no manifest.json")
        manifest = validate_manifest(json.loads(archive.read("manifest.json")))
        expected = manifest.get("files", {})
        if not isinstance(expected, dict) or set(expected) != {name for name in names if name != "manifest.json"}:
            raise PackageError("archive file list does not match manifest")
        for name, digest in expected.items():
            if _sha256(archive.read(name)) != digest:
                raise PackageError(f"integrity mismatch: {name}")
    signature = manifest.get("signature")
    signature_status = "unsigned"
    if signature:
        if signature.get("algorithm") != "hmac-sha256":
            raise PackageError("unsupported signature algorithm")
        if signing_key:
            unsigned = copy.deepcopy(manifest)
            unsigned.pop("signature", None)
            expected_signature = hmac.new(signing_key, _json_bytes(unsigned), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected_signature, str(signature.get("value", ""))):
                raise PackageError("package signature is invalid")
            signature_status = "verified"
        else:
            signature_status = "present-unverified"
    elif require_signature:
        raise PackageError("a trusted signature is required")
    return {"path": str(archive_path), "sha256": _sha256(archive_path.read_bytes()), "size": archive_path.stat().st_size, "files": len(manifest["files"]), "signature_status": signature_status, "manifest": manifest}


def _tree_digest(path: Path) -> str:
    digest = hashlib.sha256()
    candidates = [path] if path.is_file() else sorted(item for item in path.rglob("*") if item.is_file())
    for item in candidates:
        relative = item.name if path.is_file() else item.relative_to(path).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.read_bytes())
    return digest.hexdigest()


def _target_for(root: Path, component: dict[str, Any]) -> Path:
    base = (root / COMPONENT_ROOTS[component["kind"]]).resolve()
    target = (base / component["name"]).resolve()
    target.relative_to(base)
    return target


def install_package(path: Any, repository_root: Any, *, allow_update: bool = False, signing_key: bytes | None = None, require_signature: bool = False) -> dict[str, Any]:
    root = Path(str(repository_root)).resolve()
    inspected = inspect_package(path, signing_key=signing_key, require_signature=require_signature)
    manifest = inspected["manifest"]
    package_name = manifest["package"]["name"]
    state_root = root / ".egoagent" / "packages"
    installed_path = state_root / "installed" / f"{package_name}.json"
    if installed_path.exists() and not allow_update:
        raise PackageError(f"package is already installed: {package_name}")
    stage = state_root / "stage" / uuid.uuid4().hex
    backup = state_root / "backups" / package_name / f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"
    staged_targets: list[tuple[Path, Path, dict[str, Any]]] = []
    moved_backups: list[tuple[Path, Path]] = []
    installed_targets: list[Path] = []
    stage.mkdir(parents=True, exist_ok=False)
    try:
        with zipfile.ZipFile(inspected["path"], "r") as archive:
            for component in manifest["components"]:
                source_prefix = f"payload/{component['path']}/"
                component_stage = stage / component["kind"] / component["name"]
                matches = [name for name in manifest["files"] if name.startswith(source_prefix)]
                if not matches:
                    raise PackageError(f"component is empty: {component['kind']}/{component['name']}")
                for name in matches:
                    relative = _safe_relative(name[len(source_prefix):])
                    destination = (component_stage / Path(relative)).resolve()
                    destination.relative_to(component_stage.resolve())
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(archive.read(name))
                staged_value = component_stage
                if component.get("layout") == "file":
                    staged_files = [value for value in component_stage.rglob("*") if value.is_file()]
                    if len(staged_files) != 1:
                        raise PackageError(f"file component must contain exactly one file: {component['kind']}/{component['name']}")
                    staged_value = staged_files[0]
                target = _target_for(root, component)
                if target.exists() and not allow_update:
                    raise PackageError(f"component target already exists: {target}")
                staged_targets.append((staged_value, target, component))
        backup.mkdir(parents=True, exist_ok=True)
        for component_stage, target, component in staged_targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                backup_target = backup / component["kind"] / component["name"]
                backup_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(target), str(backup_target))
                moved_backups.append((backup_target, target))
            shutil.move(str(component_stage), str(target))
            installed_targets.append(target)
        record = {
            "format": "ego.installed-package.v1",
            "installed_at": time.time(),
            "archive_sha256": inspected["sha256"],
            "signature_status": inspected["signature_status"],
            "manifest": manifest,
            "targets": [
                {"kind": component["kind"], "name": component["name"], "path": str(target), "revision": _tree_digest(target)}
                for _stage, target, component in staged_targets
            ],
            "backup": str(backup) if moved_backups else None,
        }
        installed_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = installed_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, installed_path)
        return {"ok": True, "installed": record, "state": str(installed_path)}
    except BaseException:
        for target in reversed(installed_targets):
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            else:
                target.unlink(missing_ok=True)
        for backup_target, target in reversed(moved_backups):
            target.parent.mkdir(parents=True, exist_ok=True)
            if backup_target.exists():
                shutil.move(str(backup_target), str(target))
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def list_installed(repository_root: Any) -> list[dict[str, Any]]:
    directory = Path(str(repository_root)).resolve() / ".egoagent" / "packages" / "installed"
    result = []
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        try:
            result.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return result


def uninstall_package(name: str, repository_root: Any, *, force: bool = False) -> dict[str, Any]:
    package_name = _safe_name(name, "package name")
    root = Path(str(repository_root)).resolve()
    record_path = root / ".egoagent" / "packages" / "installed" / f"{package_name}.json"
    if not record_path.is_file():
        raise PackageError(f"package is not installed: {package_name}")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    conflicts = []
    for target in record.get("targets", []):
        path = Path(target["path"]).resolve()
        if path.exists() and _tree_digest(path) != target.get("revision"):
            conflicts.append(str(path))
    if conflicts and not force:
        raise PackageError(f"installed components have local changes: {', '.join(conflicts)}")
    trash = root / ".egoagent" / "packages" / "uninstalled" / f"{package_name}-{int(time.time())}"
    moved = []
    try:
        for target in record.get("targets", []):
            path = Path(target["path"]).resolve()
            if path.exists():
                destination = trash / target["kind"] / target["name"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), str(destination))
                moved.append((destination, path))
        record_path.unlink()
        return {"ok": True, "name": package_name, "recoverable_from": str(trash), "conflicts_forced": conflicts}
    except BaseException:
        for source, destination in reversed(moved):
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.exists():
                shutil.move(str(source), str(destination))
        raise


def fork_package(path: Any, output_path: Any, new_name: str, new_version: str = "0.1.0", *, signing_key: bytes | None = None) -> dict[str, Any]:
    inspected = inspect_package(path)
    manifest = copy.deepcopy(inspected["manifest"])
    original = {"name": manifest["package"]["name"], "version": manifest["package"]["version"], "sha256": inspected["sha256"]}
    manifest["package"]["name"] = _safe_name(new_name, "package name")
    if not SEMVER.fullmatch(new_version):
        raise PackageError("fork version must use semantic versioning")
    manifest["package"]["version"] = new_version
    manifest.setdefault("provenance", {})["forked_from"] = original
    manifest.pop("signature", None)
    validate_manifest(manifest)
    output = Path(str(output_path)).resolve()
    with tempfile.TemporaryDirectory() as temporary_name:
        temporary_root = Path(temporary_name)
        with zipfile.ZipFile(inspected["path"], "r") as archive:
            for component in manifest["components"]:
                prefix = f"payload/{component['path']}/"
                source = temporary_root / component["path"]
                for archive_name in manifest["files"]:
                    if archive_name.startswith(prefix):
                        relative = _safe_relative(archive_name[len(prefix):])
                        destination = source / relative
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes(archive.read(archive_name))
                component["source"] = str(source.relative_to(temporary_root))
        return pack_package(manifest, temporary_root, output, signing_key=signing_key)
