import os
import json
import subprocess
import threading
import uuid
import time
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))))
from config import CONFIG
from secure_command import (
    ProcessBackendError,
    command_blacklist_match,
    execute_container_command,
    sanitized_subprocess_environment,
    sandbox_failure,
    windows_python_c_invocation,
)


def _check_blacklist(command: str) -> str:
    """Check if the command matches any blacklist pattern. Returns error message or None."""
    pattern = command_blacklist_match(command, CONFIG.get("command_blacklist", []))
    if pattern:
        return f"Command blocked by blacklist: matches '{pattern}'"
    return None


def run_command(command: str, cwd: str = None, blocking: bool = True, timeout: int = 60, _context: dict = None):
    """Execute a shell command."""
    if not command:
        return json.dumps({"error": "command is empty."})

    # Blacklist check
    blocked = _check_blacklist(command)
    if blocked:
        return json.dumps({"error": blocked})

    context_workspace = str((_context or {}).get("workspace") or "").strip()
    if cwd:
        cwd = str(cwd)
        if not os.path.isabs(cwd) and context_workspace:
            cwd = os.path.join(context_workspace, cwd)
    else:
        cwd = context_workspace or os.getcwd()
    cwd = os.path.realpath(cwd)
    if not os.path.isdir(cwd):
        return json.dumps({"error": f"Working directory not found: '{cwd}'."})

    # Model-authored processes do not inherit API keys, auth tokens or other
    # credential-looking environment variables. Named secret injection belongs
    # to the typed DAG Process node, where it is explicitly authorized and
    # redacted from traces.
    env = sanitized_subprocess_environment()

    sandbox = (_context or {}).get("sandbox") or {}
    sandbox_mode = str(sandbox.get("mode", "workspace")).lower()
    if sandbox_mode == "container":
        if not blocking:
            return json.dumps({
                "ok": False,
                "status": "blocked",
                "error": "Background commands are disabled in the ephemeral container sandbox. Run it in blocking mode or use a DAG Process node.",
                "sandbox": {"mode": "container"},
            }, ensure_ascii=False)
        try:
            payload = execute_container_command(
                command,
                cwd=cwd,
                timeout=timeout,
                context=_context or {},
            )
        except (OSError, ValueError, ProcessBackendError, subprocess.SubprocessError) as error:
            # A selected strong sandbox is a security boundary, not a best-
            # effort preference. Never silently fall back to the host because
            # Docker/Podman is stopped or an image is missing.
            payload = sandbox_failure(error, sandbox)
        if payload is None:
            payload = sandbox_failure(
                RuntimeError("container backend returned no execution result"),
                sandbox,
            )
        output = str(payload.get("output", ""))
        max_chars = 50000
        payload["truncated"] = len(output) > max_chars
        if payload["truncated"]:
            payload["output"] = output[:max_chars] + "\n... (output truncated)"
        return json.dumps(payload, ensure_ascii=False)

    # Task Bench container tasks expose the same bind-mounted workspace to
    # file tools, but process execution must stay inside Docker.  These values
    # are injected by the trusted runner and are never accepted from the model.
    container_name = (_context or {}).get("container_name")
    process_args = command
    use_shell = True
    process_cwd = cwd
    if container_name:
        workspace = os.path.realpath(str((_context or {}).get("container_workspace") or ""))
        workdir = str((_context or {}).get("container_workdir") or "/app")
        relative = os.path.relpath(os.path.realpath(cwd or workspace), workspace).replace("\\", "/")
        if relative == ".." or relative.startswith("../"):
            return json.dumps({"error": "Container working directory escapes the task workspace."})
        container_cwd = workdir if relative in {"", "."} else workdir.rstrip("/") + "/" + relative
        process_args = ["docker", "exec", "--workdir", container_cwd, str(container_name), "sh", "-lc", command]
        use_shell = False
        process_cwd = None
    else:
        python_invocation = windows_python_c_invocation(command)
        if python_invocation:
            process_args = python_invocation
            use_shell = False

    if blocking:
        try:
            result = subprocess.run(
                process_args,
                shell=use_shell,
                cwd=process_cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
            # Some Windows shell commands and mocked/custom subprocess runners
            # may return ``None`` for an empty captured stream.  Treat that as
            # an empty string so a successful no-output command never crashes
            # while computing the truncation boundary.
            output = result.stdout or ""
            if result.stderr:
                output += "\n[STDERR]\n" + result.stderr

            # Truncate long output
            max_chars = 50000
            truncated = len(output) > max_chars
            if truncated:
                output = output[:max_chars] + "\n... (output truncated)"

            return json.dumps({
                "ok": result.returncode == 0,
                "status": "done",
                "exit_code": result.returncode,
                "output": output,
                "truncated": truncated,
                "sandbox": {"mode": "workspace", "strong_isolation": False},
            }, ensure_ascii=False)
        except subprocess.TimeoutExpired:
            return json.dumps({"error": f"Command timed out after {timeout}s."})
        except Exception as e:
            return json.dumps({"error": f"Command execution failed: {str(e)}"})
    else:
        # Async execution — 使用 _context 共享 running_commands
        running_commands = _context["running_commands"] if _context else {}
        cmd_id = str(uuid.uuid4())[:8]
        try:
            proc = subprocess.Popen(
                process_args,
                shell=use_shell,
                cwd=process_cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
            )
            running_commands[cmd_id] = {
                "process": proc,
                "command": command,
                "output_lines": [],
                "start_time": time.time(),
            }

            # Background thread to collect output
            def _collect_output():
                for line in proc.stdout:
                    running_commands[cmd_id]["output_lines"].append(line)

            t = threading.Thread(target=_collect_output, daemon=True)
            t.start()

            return json.dumps({
                "status": "started",
                "command_id": cmd_id,
                "message": f"Command started in background. Use check_command_status(command_id='{cmd_id}') to check progress."
            })
        except Exception as e:
            return json.dumps({"error": f"Failed to start command: {str(e)}"})
