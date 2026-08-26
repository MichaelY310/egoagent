"""Cross-platform product setup, diagnostics, privacy, and local updates.

No operation in this module contacts the network implicitly.  Proxy settings
are applied only to child/provider processes, diagnostics redact secrets, and
updates require an explicit local archive so offline installations remain
fully manageable.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


PRODUCT_SETTINGS_VERSION = "ego.product-settings.v1"
UPDATE_MANIFEST = "ego.update.v1"
SECRET_MARKERS = ("key", "token", "secret", "password", "passwd", "auth", "cookie")
UPDATE_EXCLUDES = {
    ".git", ".egoagent", ".runtime", ".runtime-logs", "node_modules", "dist", "void-web",
    "sessions", "logs", "tmp", "__pycache__", ".env", ".env.local",
}


class ProductRuntimeError(ValueError):
    pass


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _settings_path(root: Path) -> Path:
    return root / ".egoagent" / "product-settings.json"


def load_product_settings(root: Path | str) -> dict[str, Any]:
    path = _settings_path(Path(root).resolve())
    defaults = {
        "version": PRODUCT_SETTINGS_VERSION,
        "offline_mode": False,
        "proxy": {"http": "", "https": "", "no_proxy": "127.0.0.1,localhost"},
        "mirrors": {"pip_index_url": "", "npm_registry": ""},
        "privacy": {"diagnostic_logs": True, "include_prompts_in_diagnostics": False, "telemetry": False},
        "update": {"channel": "manual", "retain_rollbacks": 3},
    }
    if not path.is_file():
        return defaults
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defaults
    if raw.get("version") != PRODUCT_SETTINGS_VERSION:
        return defaults
    for section in ("proxy", "mirrors", "privacy", "update"):
        defaults[section].update(raw.get(section, {}) if isinstance(raw.get(section), dict) else {})
    defaults["offline_mode"] = bool(raw.get("offline_mode", False))
    return defaults


def save_product_settings(root: Path | str, changes: dict[str, Any]) -> dict[str, Any]:
    root = Path(root).resolve()
    current = load_product_settings(root)
    if "offline_mode" in changes:
        current["offline_mode"] = bool(changes["offline_mode"])
    for section in ("proxy", "mirrors", "privacy", "update"):
        if section in changes:
            if not isinstance(changes[section], dict):
                raise ProductRuntimeError(f"{section} must be an object")
            current[section].update(changes[section])
    for key in ("http", "https"):
        value = str(current["proxy"].get(key, ""))
        if value and not re.match(r"^https?://", value, re.I):
            raise ProductRuntimeError(f"proxy.{key} must start with http:// or https://")
    _atomic_json(_settings_path(root), current)
    apply_product_environment(root)
    return current


def apply_product_environment(root: Path | str, environment: dict[str, str] | None = None) -> dict[str, str]:
    settings = load_product_settings(Path(root).resolve())
    target = os.environ if environment is None else environment
    mapping = {
        "HTTP_PROXY": settings["proxy"].get("http", ""),
        "HTTPS_PROXY": settings["proxy"].get("https", ""),
        "NO_PROXY": settings["proxy"].get("no_proxy", ""),
        "PIP_INDEX_URL": settings["mirrors"].get("pip_index_url", ""),
        "NPM_CONFIG_REGISTRY": settings["mirrors"].get("npm_registry", ""),
        "EGOAGENT_OFFLINE": "1" if settings["offline_mode"] else "0",
        "EGOAGENT_TELEMETRY": "1" if settings["privacy"].get("telemetry") else "0",
    }
    for name, value in mapping.items():
        if value:
            target[name] = str(value)
            target[name.lower()] = str(value)
        # Empty product settings inherit the launching shell. This is
        # important behind corporate firewalls and for users in regions that
        # need a proxy; the old launcher erased those variables unconditionally.
    return mapping


def _command_version(command: list[str], timeout: float = 8) -> dict[str, Any]:
    executable = shutil.which(command[0])
    if not executable:
        return {"available": False, "reason": f"{command[0]} not found"}
    try:
        completed = subprocess.run([executable, *command[1:]], capture_output=True, text=True, timeout=timeout, shell=False)
        output = (completed.stdout or completed.stderr).strip().splitlines()
        return {"available": completed.returncode == 0, "version": output[0][:300] if output else "", "exit_code": completed.returncode}
    except (OSError, subprocess.SubprocessError) as error:
        return {"available": False, "reason": str(error)}


def _port_status(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            return True
    except OSError:
        return False


def _writable(path: Path) -> tuple[bool, str]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".write-probe-{uuid.uuid4().hex}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True, "writable"
    except OSError as error:
        return False, str(error)


def product_diagnostics(root: Path | str) -> dict[str, Any]:
    root = Path(root).resolve()
    settings = load_product_settings(root)
    python = {"available": True, "version": platform.python_version(), "executable": sys.executable}
    node = _command_version(["node", "--version"])
    npm = _command_version(["npm", "--version"])
    git = _command_version(["git", "--version"])
    docker = _command_version(["docker", "version", "--format", "{{.Server.Version}}"], timeout=12)
    paths = {}
    for label, path in {
        "project": root,
        "runtime": root / ".runtime",
        "state": root / ".egoagent",
        "task_runs": root / ".egoagent" / "task_runs",
    }.items():
        ok, reason = _writable(path)
        paths[label] = {"path": str(path), "writable": ok, "reason": reason}
    checks = {
        "python": python, "node": node, "npm": npm, "git": git, "docker": docker,
        "void_runtime": {
            "available": (root / "void-web" / "out" / "server-main.js").is_file(),
            "path": str(root / "void-web"),
        },
        "studio_dependencies": {
            "available": (root / "harness_editor" / "node_modules" / "typescript").is_dir(),
            "path": str(root / "harness_editor" / "node_modules"),
        },
        "paths": paths,
        "ports": {"void_8869": _port_status(8869), "studio_8765": _port_status(8765), "unified_8880": _port_status(8880)},
    }
    required = [python["available"], node.get("available", False), checks["void_runtime"]["available"]]
    return {
        "healthy": all(required) and all(item["writable"] for item in paths.values()),
        "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine()},
        "offline_mode": settings["offline_mode"],
        "proxy": {key: bool(value) for key, value in settings["proxy"].items()},
        "checks": checks,
        "timestamp": time.time(),
    }


def _quote_env(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def save_local_secret(root: Path | str, name: str, value: str) -> None:
    root = Path(root).resolve()
    name = str(name).strip()
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{2,80}", name):
        raise ProductRuntimeError("Secret environment name must be uppercase letters, numbers, and underscores")
    if not str(value).strip():
        raise ProductRuntimeError("API key cannot be empty")
    path = root / ".env.local"
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else ["# EgoAgent local secrets (gitignored)"]
    replacement = f"{name}={_quote_env(value.strip())}"
    updated, found = [], False
    for line in lines:
        if line.strip().startswith(f"{name}=") or line.strip().startswith(f"export {name}="):
            if not found:
                updated.append(replacement)
                found = True
        else:
            updated.append(line)
    if not found:
        updated.append(replacement)
    temporary = path.with_suffix(".local.tmp")
    temporary.write_text("\n".join(updated).rstrip() + "\n", encoding="utf-8")
    temporary.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    os.environ[name] = value.strip()


def configure_provider(root: Path | str, payload: dict[str, Any]) -> dict[str, Any]:
    provider = str(payload.get("provider") or "openai_compatible").strip().lower()
    presets = {
        "deepseek": ("https://api.deepseek.com", "deepseek-chat", "DEEPSEEK_API_KEY"),
        "siliconflow": ("https://api.siliconflow.cn/v1", "Qwen/Qwen3-8B", "SILICONFLOW_API_KEY"),
        "openai": ("https://api.openai.com/v1", "gpt-4.1-mini", "OPENAI_API_KEY"),
        "ollama": ("http://127.0.0.1:11434/v1", "qwen3:8b", ""),
        "openai_compatible": ("", "", "EGOAGENT_LLM_API_KEY"),
    }
    if provider not in presets:
        raise ProductRuntimeError(f"Unsupported provider preset: {provider}")
    default_url, default_model, default_env = presets[provider]
    base_url = str(payload.get("base_url") or default_url).strip().rstrip("/")
    model = str(payload.get("model") or default_model).strip()
    secret_name = str(payload.get("api_key_env") or default_env).strip()
    api_key = str(payload.get("api_key") or "").strip()
    if not base_url or not model:
        raise ProductRuntimeError("Base URL and model are required")
    if provider != "ollama":
        if not secret_name:
            raise ProductRuntimeError("A secret environment variable name is required")
        if api_key:
            save_local_secret(root, secret_name, api_key)
        elif not os.environ.get(secret_name):
            raise ProductRuntimeError(f"API key missing; enter it once or set {secret_name}")
    try:
        from harness_editor.model_router import assign_model_role, get_role_assignments, upsert_model_profile
    except ImportError:
        from model_router import assign_model_role, get_role_assignments, upsert_model_profile
    profile_id = re.sub(r"[^a-z0-9_-]+", "-", str(payload.get("id") or f"{provider}-{model}").lower()).strip("-")
    roles = list(payload.get("roles") or ["chat", "tool_use", "edit", "apply", "autocomplete", "reasoning", "judge", "evolver"])
    public = upsert_model_profile({
        "id": profile_id, "name": str(payload.get("name") or f"{provider} · {model}"),
        "provider": provider, "base_url": base_url, "model": model, "api_key_env": secret_name,
        "enabled": True, "priority": int(payload.get("priority") or 80), "roles": roles,
        "context_window": int(payload.get("context_window") or 128000),
        "max_tokens": int(payload.get("max_tokens") or 4096), "temperature": float(payload.get("temperature", 0.2)),
        "input_cost_per_m": float(payload.get("input_cost_per_m") or 0),
        "output_cost_per_m": float(payload.get("output_cost_per_m") or 0),
    })
    current = get_role_assignments()
    for role in roles:
        order = [profile_id, *[item for item in current.get(role, []) if item != profile_id]]
        assign_model_role(role, order)
    return {"configured": True, "profile": public, "secret_stored": bool(api_key), "secret_name": secret_name}


def _redact(value: Any, secrets: Iterable[str]) -> Any:
    if isinstance(value, dict):
        return {key: ("[REDACTED]" if any(mark in str(key).lower() for mark in SECRET_MARKERS) else _redact(child, secrets)) for key, child in value.items()}
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, str):
        result = value
        for secret in secrets:
            if secret:
                result = result.replace(secret, "[REDACTED]")
        result = re.sub(r"sk-[A-Za-z0-9_-]{12,}", "[REDACTED]", result)
        return result
    return value


def create_diagnostics_bundle(root: Path | str) -> Path:
    root = Path(root).resolve()
    destination = root / ".egoagent" / "diagnostics"
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / f"diagnostics-{time.strftime('%Y%m%d-%H%M%S')}.zip"
    secrets = [value for name, value in os.environ.items() if any(mark in name.lower() for mark in SECRET_MARKERS)]
    settings = load_product_settings(root)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("diagnostics.json", json.dumps(_redact(product_diagnostics(root), secrets), ensure_ascii=False, indent=2))
        archive.writestr("product-settings.json", json.dumps(_redact(settings, secrets), ensure_ascii=False, indent=2))
        for log_root in (root / ".runtime-logs", root / "harness_editor" / "logs"):
            if not log_root.is_dir() or not settings["privacy"].get("diagnostic_logs", True):
                continue
            for log in sorted(log_root.rglob("*")):
                if not log.is_file() or log.stat().st_size > 2_000_000:
                    continue
                try:
                    content = log.read_text(encoding="utf-8", errors="replace")
                    archive.writestr(f"logs/{log_root.name}/{log.relative_to(log_root).as_posix()}", _redact(content, secrets))
                except OSError:
                    continue
    return path


def _archive_member(name: str) -> str:
    value = str(name).replace("\\", "/").lstrip("/")
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise ProductRuntimeError(f"Unsafe update archive path: {name}")
    if path.parts[0] in UPDATE_EXCLUDES or any(part in {".git", "__pycache__"} for part in path.parts):
        raise ProductRuntimeError(f"Update archive targets protected runtime data: {name}")
    return path.as_posix()


def apply_local_update(root: Path | str, archive_path: Path | str) -> dict[str, Any]:
    root = Path(root).resolve()
    archive_path = Path(archive_path).resolve()
    if not archive_path.is_file():
        raise ProductRuntimeError(f"Update archive not found: {archive_path}")
    rollback_root = root / ".egoagent" / "updates" / f"rollback-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    rollback_root.mkdir(parents=True, exist_ok=False)
    replaced, created = [], []
    try:
        with zipfile.ZipFile(archive_path) as archive:
            manifest_name = ".egoagent-update.json"
            if manifest_name not in archive.namelist():
                raise ProductRuntimeError("Update archive is missing .egoagent-update.json")
            manifest = json.loads(archive.read(manifest_name))
            if manifest.get("format") != UPDATE_MANIFEST:
                raise ProductRuntimeError("Unsupported update manifest")
            members = []
            total = 0
            for info in archive.infolist():
                if info.is_dir() or info.filename == manifest_name:
                    continue
                relative = _archive_member(info.filename)
                total += info.file_size
                if info.file_size > 32 * 1024 * 1024 or total > 256 * 1024 * 1024:
                    raise ProductRuntimeError("Update archive exceeds safety limits")
                members.append((relative, info))
            for relative, info in members:
                target = root / relative
                if target.exists():
                    backup = rollback_root / "files" / relative
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, backup)
                    replaced.append(relative)
                else:
                    created.append(relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_suffix(target.suffix + ".update-tmp")
                temporary.write_bytes(archive.read(info))
                temporary.replace(target)
        rollback_manifest = {
            "format": UPDATE_MANIFEST, "created_at": time.time(), "archive": str(archive_path),
            "version": manifest.get("version"), "replaced": replaced, "created": created,
        }
        _atomic_json(rollback_root / "rollback.json", rollback_manifest)
    except Exception:
        if (rollback_root / "files").is_dir():
            for backup in (rollback_root / "files").rglob("*"):
                if backup.is_file():
                    target = root / backup.relative_to(rollback_root / "files")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(backup, target)
        for relative in created:
            try:
                (root / relative).unlink()
            except OSError:
                pass
        raise
    _prune_rollbacks(root)
    return {"updated": True, "version": manifest.get("version"), "rollback_id": rollback_root.name, "files": len(replaced) + len(created)}


def _prune_rollbacks(root: Path) -> None:
    keep = max(1, int(load_product_settings(root)["update"].get("retain_rollbacks", 3)))
    update_root = root / ".egoagent" / "updates"
    entries = sorted((path for path in update_root.glob("rollback-*") if path.is_dir()), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in entries[keep:]:
        shutil.rmtree(path, ignore_errors=True)


def list_rollbacks(root: Path | str) -> list[dict[str, Any]]:
    root = Path(root).resolve()
    result = []
    for path in sorted((root / ".egoagent" / "updates").glob("rollback-*/rollback.json"), reverse=True):
        try:
            result.append({"id": path.parent.name, **json.loads(path.read_text(encoding="utf-8"))})
        except (OSError, ValueError):
            continue
    return result


def rollback_update(root: Path | str, rollback_id: str) -> dict[str, Any]:
    root = Path(root).resolve()
    if Path(str(rollback_id)).name != str(rollback_id):
        raise ProductRuntimeError("Invalid rollback id")
    rollback_root = root / ".egoagent" / "updates" / rollback_id
    manifest_path = rollback_root / "rollback.json"
    if not manifest_path.is_file():
        raise ProductRuntimeError(f"Rollback not found: {rollback_id}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for relative in manifest.get("replaced", []):
        backup = rollback_root / "files" / _archive_member(relative)
        target = root / _archive_member(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup, target)
    for relative in manifest.get("created", []):
        target = root / _archive_member(relative)
        if target.is_file():
            target.unlink()
    manifest["rolled_back_at"] = time.time()
    _atomic_json(manifest_path, manifest)
    return {"rolled_back": True, "id": rollback_id, "restored": len(manifest.get("replaced", [])), "removed": len(manifest.get("created", []))}
