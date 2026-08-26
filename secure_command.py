"""Safe command execution primitives used by Agent shell tools."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping

from process_backends import ProcessBackendError, build_container_invocation, cleanup_container


_SECRET_ENV_RE = re.compile(
    r"(?:API[_-]?KEY|TOKEN|PASSWORD|PASSWD|SECRET|CREDENTIAL|PRIVATE[_-]?KEY|AUTH|COOKIE|SESSION)",
    re.IGNORECASE,
)
_ESSENTIAL_WINDOWS_ENV = {
    "ALLUSERSPROFILE", "APPDATA", "COMSPEC", "COMMONPROGRAMFILES", "COMMONPROGRAMFILES(X86)",
    "COMMONPROGRAMW6432", "HOMEDRIVE", "HOMEPATH", "LOCALAPPDATA", "NUMBER_OF_PROCESSORS",
    "OS", "PATH", "PATHEXT", "PROCESSOR_ARCHITECTURE", "PROGRAMDATA", "PROGRAMFILES",
    "PROGRAMFILES(X86)", "PROGRAMW6432", "PROMPT", "PSMODULEPATH", "PUBLIC", "SYSTEMDRIVE",
    "SYSTEMROOT", "TEMP", "TMP", "USERDOMAIN", "USERNAME", "USERPROFILE", "WINDIR",
}


def sanitized_subprocess_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    """Remove credential-looking variables before model-authored code runs."""

    source = source or os.environ
    result: dict[str, str] = {}
    for key, value in source.items():
        normalized = str(key).upper()
        if _SECRET_ENV_RE.search(normalized):
            continue
        if os.name == "nt" or normalized in {"PATH", "HOME", "LANG", "LC_ALL", "TMP", "TEMP", "SHELL", "USER"}:
            if os.name != "nt" or normalized in _ESSENTIAL_WINDOWS_ENV or normalized.startswith("EGOAGENT_SAFE_"):
                result[str(key)] = str(value)
    result["PAGER"] = "cat"
    result["GIT_TERMINAL_PROMPT"] = "0"
    result["GCM_INTERACTIVE"] = "Never"
    return result


def execute_container_command(
    command: str,
    *,
    cwd: str | os.PathLike[str],
    timeout: int,
    context: Mapping[str, Any],
) -> dict[str, Any]:
    sandbox = context.get("sandbox", {})
    if not isinstance(sandbox, Mapping):
        sandbox = {}
    workspace = Path(str(context.get("workspace") or cwd)).resolve()
    cwd_path = Path(cwd).resolve()
    config = dict(sandbox)
    config.setdefault("image", "python:3.12-slim")
    config.setdefault("network", "none")
    config.setdefault("read_only_root", True)
    config.setdefault("workspace_access", "rw")
    config.setdefault("pull_policy", "never")
    invocation = build_container_invocation(
        backend="container",
        workspace=workspace,
        cwd=cwd_path,
        command="sh",
        args=["-lc", command],
        environment={},
        config=config,
        run_id=str(context.get("run_id") or "interactive"),
        node_id="run-command",
    )
    try:
        completed = subprocess.run(
            invocation.argv,
            shell=False,
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=max(1, int(timeout)),
            env=invocation.host_env,
            check=False,
        )
        output = completed.stdout or ""
        if completed.stderr:
            output += ("\n" if output else "") + "[STDERR]\n" + completed.stderr
        return {
            "ok": completed.returncode == 0,
            "status": "done",
            "exit_code": completed.returncode,
            "output": output,
            "sandbox": {
                "mode": "container",
                "engine": invocation.engine,
                "image": invocation.image,
                **invocation.security,
            },
        }
    except subprocess.TimeoutExpired as error:
        return {
            "ok": False,
            "status": "timeout",
            "error": f"Sandboxed command timed out after {timeout}s.",
            "output": ((error.stdout or "") if isinstance(error.stdout, str) else ""),
            "sandbox": {"mode": "container", "engine": invocation.engine, "image": invocation.image},
        }
    finally:
        cleanup_container(invocation)


def sandbox_failure(error: BaseException, sandbox: Mapping[str, Any]) -> dict[str, Any]:
    mode = str(sandbox.get("mode", "workspace"))
    return {
        "ok": False,
        "status": "blocked",
        "error": f"{mode} sandbox unavailable; command was not run: {error}",
        # Fail-closed is an execution invariant, not caller-controlled input.
        "sandbox": {"mode": mode, "fail_closed": True},
    }


__all__ = [
    "ProcessBackendError",
    "execute_container_command",
    "sanitized_subprocess_environment",
    "sandbox_failure",
]
