"""Docker-backed execution boundary for imported benchmark tasks."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Optional

from .engine import TaskBenchError, _inside


class TaskContainer:
    """Build one task image and expose its working tree through a bind mount.

    The model-facing filesystem remains the Task Bench host workspace, while
    process tools execute in the container against the same files.  This keeps
    read/write tools and shell commands coherent without granting host shell
    access to imported benchmark tasks.
    """

    def __init__(self, spec: dict[str, Any], workspace: Path, run_dir: Path):
        self.spec = spec
        self.workspace = Path(workspace).resolve()
        self.run_dir = Path(run_dir).resolve()
        self.config = spec.get("environment", {}).get("container", {}) or {}
        self.image = f"egoagent-task-{uuid.uuid4().hex[:12]}"
        self.name = f"egoagent-run-{uuid.uuid4().hex[:12]}"
        self.workdir = str(self.config.get("workdir") or "/app")
        self.logs_dir = self.run_dir / "container-logs"
        self.started = False

    @staticmethod
    def available() -> tuple[bool, str]:
        executable = shutil.which("docker")
        if not executable:
            return False, "Docker CLI is not installed or not on PATH"
        try:
            result = subprocess.run(
                [executable, "info", "--format", "{{json .ServerVersion}}"],
                capture_output=True,
                text=True,
                timeout=10,
                shell=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            return False, f"Docker health check failed: {error}"
        if result.returncode != 0:
            return False, (result.stderr or result.stdout or "Docker daemon is unavailable").strip()
        return True, "Docker daemon is ready"

    def _docker(self, args: list[str], *, timeout: float = 300, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["docker", *args], capture_output=True, text=True, timeout=timeout, shell=False,
        )
        if check and result.returncode != 0:
            output = (result.stderr or result.stdout).strip()[-4000:]
            raise TaskBenchError(f"Docker command failed ({' '.join(args[:3])}): {output}")
        return result

    def start(self) -> None:
        available, reason = self.available()
        if not available:
            raise TaskBenchError(f"Container task cannot start: {reason}")
        context_relative = str(self.config.get("build_context") or ".external/environment")
        dockerfile_relative = str(self.config.get("dockerfile") or f"{context_relative}/Dockerfile")
        context = _inside(self.workspace, context_relative)
        dockerfile = _inside(self.workspace, dockerfile_relative)
        if not context.is_dir() or not dockerfile.is_file():
            raise TaskBenchError(f"Container build files missing: {context_relative}, {dockerfile_relative}")
        dockerfile_arg = str(dockerfile.relative_to(context)) if context in dockerfile.parents else str(dockerfile)
        build_args = ["build", "--tag", self.image, "--file", dockerfile_arg, str(context)]
        self._docker(build_args, timeout=float(self.config.get("build_timeout_seconds") or 900))

        seed_name = f"{self.name}-seed"
        try:
            self._docker(["create", "--name", seed_name, self.image, "sh", "-lc", "true"])
            # Preserve files supplied by the image before the bind mount hides
            # the image workdir. docker cp merges them into the task workspace.
            copied = self._docker(["cp", f"{seed_name}:{self.workdir}/.", str(self.workspace)], check=False)
            if copied.returncode != 0 and "No such" not in (copied.stderr or ""):
                raise TaskBenchError(f"Could not seed container workspace: {(copied.stderr or copied.stdout).strip()}")
        finally:
            self._docker(["rm", "-f", seed_name], check=False)

        self.logs_dir.mkdir(parents=True, exist_ok=True)
        network = self.spec.get("environment", {}).get("network", "disabled")
        args = ["run", "--detach", "--name", self.name, "--workdir", self.workdir]
        if network == "disabled":
            args += ["--network", "none"]
        cpus = self.config.get("cpus")
        memory = self.config.get("memory_mb")
        if cpus:
            args += ["--cpus", str(cpus)]
        if memory:
            args += ["--memory", f"{int(memory)}m"]
        args += [
            "--mount", f"type=bind,source={self.workspace},target={self.workdir}",
            "--mount", f"type=bind,source={self.logs_dir},target=/logs",
            self.image, "sh", "-lc", "while :; do sleep 3600; done",
        ]
        self._docker(args)
        self.started = True

    def container_cwd(self, host_cwd: Optional[str]) -> str:
        if not host_cwd:
            return self.workdir
        resolved = Path(host_cwd).resolve()
        try:
            relative = resolved.relative_to(self.workspace).as_posix()
        except ValueError as error:
            raise TaskBenchError(f"Container cwd escapes task workspace: {host_cwd}") from error
        return self.workdir if relative == "." else f"{self.workdir.rstrip('/')}/{relative}"

    def context(self) -> dict[str, Any]:
        return {
            "container_name": self.name,
            "container_workdir": self.workdir,
            "container_workspace": str(self.workspace),
        }

    def execute(self, command: str, *, cwd: Optional[str] = None, timeout: float = 300) -> dict[str, Any]:
        if not self.started:
            raise TaskBenchError("Task container is not running")
        result = self._docker(
            ["exec", "--workdir", self.container_cwd(cwd), self.name, "sh", "-lc", str(command)],
            timeout=timeout,
            check=False,
        )
        return {
            "exit_code": result.returncode,
            "stdout": result.stdout[-16000:],
            "stderr": result.stderr[-16000:],
        }

    def run_verifier(self, check: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
        script = str(check.get("script") or "")
        host_script = _inside(self.workspace, script)
        if not host_script.is_file():
            return False, f"verifier script missing: {script}", {}
        relative = host_script.relative_to(self.workspace).as_posix()
        container_script = f"{self.workdir.rstrip('/')}/{relative}"
        result = self.execute(
            f"chmod +x {json.dumps(container_script)} && {json.dumps(container_script)}",
            timeout=max(1.0, min(float(check.get("timeout_seconds", 300)), 3600.0)),
        )
        reward_path = self.logs_dir / "verifier" / "reward.txt"
        reward = 0.0
        reward_error = ""
        try:
            reward = float(reward_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError) as error:
            reward_error = str(error)
            # Legacy Terminal-Bench verifiers only used the exit code.  Keep
            # that compatibility explicit instead of silently guessing.
            if check.get("legacy_terminal_bench") and result["exit_code"] == 0:
                reward = 1.0
        reward = max(0.0, min(reward, 1.0))
        threshold = float(check.get("minimum_reward", 1.0))
        details = {**result, "reward": reward, "minimum_reward": threshold, "reward_error": reward_error}
        return reward >= threshold and result["exit_code"] == 0, f"verifier reward {reward:g} (exit {result['exit_code']})", details

    def stop(self) -> None:
        if self.started:
            self._docker(["rm", "-f", self.name], timeout=30, check=False)
            self.started = False
        self._docker(["image", "rm", "-f", self.image], timeout=60, check=False)

    def __enter__(self) -> "TaskContainer":
        self.start()
        return self

    def __exit__(self, _type: Any, _value: Any, _traceback: Any) -> None:
        self.stop()
