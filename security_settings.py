"""Workspace-scoped security settings for interactive EgoAgent runs.

The settings file is intentionally small and declarative.  It is not a
sandbox by itself; :mod:`permissions` consumes it as the approval boundary and
the command tool consumes the sandbox section as the execution boundary.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping


SETTINGS_VERSION = 1
SETTINGS_RELATIVE_PATH = Path(".egoagent") / "security.json"
PROFILES = {"strict", "balanced", "trusted", "unrestricted"}
SANDBOX_MODES = {"workspace", "container", "off"}
DECISIONS = {"allow", "ask", "deny"}


DEFAULT_SECURITY_SETTINGS: dict[str, Any] = {
    "version": SETTINGS_VERSION,
    "profile": "balanced",
    "require_dangerous_approval": True,
    "dangerous_action_decision": "ask",
    "critical_action_decision": "ask",
    "unknown_tool_decision": "ask",
    "network_decision": "ask",
    "secret_decision": "deny",
    "allow_sensitive_files": False,
    "workspace_only": True,
    "sandbox": {
        # ``workspace`` means in-process file guards plus approval-gated host
        # commands.  It is deliberately not called an OS sandbox in the UI.
        "mode": "workspace",
        "engine": "docker",
        "image": "python:3.12-slim",
        "network": "none",
        "read_only_root": True,
        "workspace_access": "rw",
        "pids_limit": 256,
        "memory": "512m",
        "cpus": 1,
        "tmpfs_size": "64m",
        "pull_policy": "never",
        "fail_closed": True,
    },
}


def _decision(value: Any, default: str) -> str:
    normalized = str(value or default).strip().lower()
    return normalized if normalized in DECISIONS else default


def normalize_security_settings(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a validated copy without accepting arbitrary runtime options."""

    source = raw if isinstance(raw, Mapping) else {}
    result = copy.deepcopy(DEFAULT_SECURITY_SETTINGS)
    profile = str(source.get("profile", result["profile"])).strip().lower()
    result["profile"] = profile if profile in PROFILES else "balanced"
    for key in (
        "require_dangerous_approval", "allow_sensitive_files", "workspace_only",
    ):
        if key in source:
            result[key] = bool(source[key])
    for key in (
        "dangerous_action_decision", "critical_action_decision",
        "unknown_tool_decision", "network_decision", "secret_decision",
    ):
        result[key] = _decision(source.get(key), result[key])

    sandbox_source = source.get("sandbox", {})
    if not isinstance(sandbox_source, Mapping):
        sandbox_source = {}
    sandbox = result["sandbox"]
    mode = str(sandbox_source.get("mode", sandbox["mode"])).strip().lower()
    sandbox["mode"] = mode if mode in SANDBOX_MODES else "workspace"
    engine = str(sandbox_source.get("engine", sandbox["engine"])).strip().lower()
    sandbox["engine"] = engine if engine in {"docker", "podman"} else "docker"
    network = str(sandbox_source.get("network", sandbox["network"])).strip().lower()
    sandbox["network"] = network if network in {"none", "bridge"} else "none"
    workspace_access = str(sandbox_source.get("workspace_access", sandbox["workspace_access"])).strip().lower()
    sandbox["workspace_access"] = workspace_access if workspace_access in {"ro", "rw"} else "rw"
    pull_policy = str(sandbox_source.get("pull_policy", sandbox["pull_policy"])).strip().lower()
    sandbox["pull_policy"] = pull_policy if pull_policy in {"never", "missing", "always"} else "never"
    for key in ("image", "memory", "tmpfs_size"):
        if key in sandbox_source:
            sandbox[key] = str(sandbox_source[key]).strip()
    for key in ("pids_limit", "cpus"):
        if key in sandbox_source:
            sandbox[key] = sandbox_source[key]
    if "read_only_root" in sandbox_source:
        sandbox["read_only_root"] = bool(sandbox_source["read_only_root"])
    # A selected strong sandbox must never degrade silently to host execution.
    # This invariant is intentionally not configurable by a Harness or UI call.
    sandbox["fail_closed"] = True

    # Profiles provide safe, predictable presets while the explicit controls
    # remain editable.  Unrestricted is the only profile allowed to disable
    # the workspace boundary without the normalizer silently widening access.
    if result["profile"] != "unrestricted":
        result["workspace_only"] = True
    result["version"] = SETTINGS_VERSION
    return result


def security_settings_path(workspace: str | os.PathLike[str] | Path) -> Path:
    root = Path(workspace).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"workspace does not exist: {root}")
    return root / SETTINGS_RELATIVE_PATH


def load_security_settings(workspace: str | os.PathLike[str] | Path) -> dict[str, Any]:
    path = security_settings_path(workspace)
    if not path.is_file():
        return normalize_security_settings(None)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return normalize_security_settings(None)
    return normalize_security_settings(raw)


def save_security_settings(workspace: str | os.PathLike[str] | Path, raw: Mapping[str, Any]) -> dict[str, Any]:
    path = security_settings_path(workspace)
    settings = normalize_security_settings(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="security-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(settings, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            Path(temporary).unlink(missing_ok=True)
        except OSError:
            pass
    return settings


def sandbox_capability(settings: Mapping[str, Any]) -> dict[str, Any]:
    sandbox = normalize_security_settings(settings)["sandbox"]
    mode = sandbox["mode"]
    if mode != "container":
        return {
            "requested": mode,
            "available": mode == "workspace",
            "strong_isolation": False,
            "label": "Workspace guard" if mode == "workspace" else "No sandbox",
            "reason": (
                "File tools are confined by resolved-path checks; host commands still run with the current user account."
                if mode == "workspace" else
                "Sandboxing is disabled by an unrestricted workspace setting."
            ),
        }
    from process_backends import container_runtime_status

    status = container_runtime_status(str(sandbox.get("engine", "docker")), timeout=3)
    return {
        "requested": mode,
        "available": bool(status.get("available")),
        "strong_isolation": bool(status.get("available")),
        "label": f"{str(sandbox.get('engine', 'docker')).title()} container",
        "reason": status.get("reason"),
        "engine": status,
    }
