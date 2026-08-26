"""Execution backend helpers for the DAG Process node."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


class ProcessBackendError(ValueError):
    pass


@dataclass(frozen=True)
class ContainerInvocation:
    argv: list[str]
    engine: str
    engine_executable: str
    image: str
    container_name: str
    container_workdir: str
    host_env: dict[str, str]
    security: dict[str, Any]


_IMAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@-]{0,254}$")
_ENV_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _positive_number(value: Any, name: str, *, integer: bool = False) -> str:
    try:
        number = int(value) if integer else float(value)
    except (TypeError, ValueError) as error:
        raise ProcessBackendError(f"container {name} must be a positive number") from error
    if number <= 0:
        raise ProcessBackendError(f"container {name} must be a positive number")
    return str(number)


def build_container_invocation(
    *,
    backend: str,
    workspace: Path,
    cwd: Path,
    command: str,
    args: list[str],
    environment: dict[str, str],
    config: dict[str, Any],
    run_id: str,
    node_id: str,
) -> ContainerInvocation:
    engine = str(config.get("engine") or (backend if backend in {"docker", "podman"} else "docker")).lower()
    if engine not in {"docker", "podman"}:
        raise ProcessBackendError("container engine must be docker or podman")
    if backend in {"docker", "podman"} and engine != backend:
        raise ProcessBackendError(f"Process backend {backend} cannot use the {engine} engine")
    engine_executable = shutil.which(engine)
    if not engine_executable:
        raise ProcessBackendError(f"container engine is not installed or not on PATH: {engine}")

    image = str(config.get("image", "")).strip()
    if not image or not _IMAGE_RE.fullmatch(image):
        raise ProcessBackendError("container image is required and must be a registry/image reference")
    if not command:
        raise ProcessBackendError("container command is required")

    workspace = workspace.resolve()
    cwd = cwd.resolve()
    if cwd != workspace and workspace not in cwd.parents:
        raise ProcessBackendError("container working directory escapes Workspace")
    if "," in str(workspace):
        raise ProcessBackendError("container Workspace path cannot contain a comma")
    relative_cwd = cwd.relative_to(workspace).as_posix()
    container_workdir = "/workspace" + (f"/{relative_cwd}" if relative_cwd != "." else "")

    network = str(config.get("network", "none")).lower()
    if network not in {"none", "bridge", "host"}:
        raise ProcessBackendError("container network must be none, bridge or host")
    if network == "host" and not config.get("allow_host_network", False):
        raise ProcessBackendError("host networking requires allow_host_network=true")
    workspace_access = str(config.get("workspace_access", "rw")).lower()
    if workspace_access not in {"ro", "rw"}:
        raise ProcessBackendError("container workspace_access must be ro or rw")
    pull_policy = str(config.get("pull_policy", "never")).lower()
    if pull_policy not in {"never", "missing", "always"}:
        raise ProcessBackendError("container pull_policy must be never, missing or always")

    safe_run = re.sub(r"[^a-z0-9_.-]", "-", str(run_id).lower())[:24]
    safe_node = re.sub(r"[^a-z0-9_.-]", "-", str(node_id).lower())[:24]
    container_name = f"egoagent-{safe_run}-{safe_node}-{uuid.uuid4().hex[:8]}"[:63].strip("-.")

    pids_limit = _positive_number(config.get("pids_limit", 256), "pids_limit", integer=True)
    memory = str(config.get("memory", "512m")).strip().lower()
    if not re.fullmatch(r"[1-9][0-9]*(?:[bkmg])?", memory):
        raise ProcessBackendError("container memory must look like 512m, 2g or a positive byte count")
    cpus = _positive_number(config.get("cpus", 1), "cpus")

    mount = f"type=bind,source={workspace},target=/workspace,{workspace_access}"
    argv = [
        engine_executable,
        "run",
        "--name",
        container_name,
        "--rm",
        "--init",
        "--pull",
        pull_policy,
        "--network",
        network,
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        pids_limit,
        "--memory",
        memory,
        "--cpus",
        cpus,
        "--mount",
        mount,
        "--workdir",
        container_workdir,
        "--label",
        f"egoagent.run_id={run_id}",
        "--label",
        f"egoagent.node_id={node_id}",
    ]
    read_only_root = bool(config.get("read_only_root", True))
    if read_only_root:
        argv.append("--read-only")
    tmpfs_size = str(config.get("tmpfs_size", "64m")).strip().lower()
    if tmpfs_size:
        if not re.fullmatch(r"[1-9][0-9]*(?:[bkmg])?", tmpfs_size):
            raise ProcessBackendError("container tmpfs_size must look like 64m or 1g")
        argv.extend(["--tmpfs", f"/tmp:rw,nosuid,nodev,size={tmpfs_size}"])
    user = str(config.get("user", "")).strip()
    if user:
        if user.startswith("-") or not re.fullmatch(r"[A-Za-z0-9_.-]+(?::[A-Za-z0-9_.-]+)?", user):
            raise ProcessBackendError("container user must be a user or uid[:group/gid]")
        argv.extend(["--user", user])
    if config.get("gpus") not in (None, "", 0, False):
        if engine != "docker":
            raise ProcessBackendError("the generic GPU option currently requires Docker")
        gpus = str(config["gpus"])
        if gpus.startswith("-") or not re.fullmatch(r"[A-Za-z0-9_,.=:-]+", gpus):
            raise ProcessBackendError("invalid container GPU selector")
        argv.extend(["--gpus", gpus])

    host_env = os.environ.copy()
    for key, value in environment.items():
        key = str(key)
        if not _ENV_RE.fullmatch(key):
            raise ProcessBackendError(f"invalid container environment variable name: {key}")
        value = str(value)
        if "\x00" in value:
            raise ProcessBackendError(f"container environment variable contains NUL: {key}")
        host_env[key] = value
        # Docker/Podman copies the named host value without exposing it in the
        # process command line or persisted Process event.
        argv.extend(["--env", key])
    argv.extend([image, str(command), *[str(value) for value in args]])

    return ContainerInvocation(
        argv=argv,
        engine=engine,
        engine_executable=engine_executable,
        image=image,
        container_name=container_name,
        container_workdir=container_workdir,
        host_env=host_env,
        security={
            "network": network,
            "read_only_root": read_only_root,
            "workspace_access": workspace_access,
            "pids_limit": int(pids_limit),
            "memory": memory,
            "cpus": float(cpus),
            "pull_policy": pull_policy,
            "user": user or None,
            "gpus": config.get("gpus"),
        },
    )


def cleanup_container(invocation: ContainerInvocation, timeout: float = 10.0) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [invocation.engine_executable, "rm", "-f", invocation.container_name],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=max(1.0, float(timeout)),
            check=False,
            shell=False,
            env=invocation.host_env,
        )
        detail = (completed.stderr or completed.stdout or "").strip()
        missing = "no such container" in detail.lower() or "does not exist" in detail.lower()
        return {
            "attempted": True,
            "removed": completed.returncode == 0 or missing,
            "exit_code": completed.returncode,
            "detail": detail[-1000:],
        }
    except (OSError, subprocess.SubprocessError) as error:
        return {"attempted": True, "removed": False, "exit_code": None, "detail": str(error)[:1000]}


def container_runtime_status(engine: str = "docker", timeout: float = 5.0) -> dict[str, Any]:
    engine = str(engine).lower()
    executable = shutil.which(engine)
    if not executable:
        return {"available": False, "engine": engine, "reason": "executable not found"}
    try:
        completed = subprocess.run(
            [executable, "info", "--format", "{{json .ServerVersion}}"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=max(1.0, float(timeout)),
            check=False,
            shell=False,
        )
        return {
            "available": completed.returncode == 0,
            "engine": engine,
            "executable": executable,
            "version": completed.stdout.strip().strip('"') if completed.returncode == 0 else None,
            "reason": (completed.stderr or completed.stdout).strip()[-1000:] if completed.returncode else None,
        }
    except (OSError, subprocess.SubprocessError) as error:
        return {"available": False, "engine": engine, "executable": executable, "reason": str(error)}
