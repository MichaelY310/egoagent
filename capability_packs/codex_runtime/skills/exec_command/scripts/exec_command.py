import json
import os
from pathlib import Path

from config import CONFIG
from process_sessions import start_process_session
from secure_command import sanitized_subprocess_environment


def _blacklist_error(command: str):
    for pattern in CONFIG.get("command_blacklist", []):
        if isinstance(pattern, str) and pattern in command.strip():
            return f"Command blocked by blacklist: contains '{pattern}'"
    return None


def exec_command(
    cmd: str,
    workdir: str = "",
    yield_time_ms: int = 10000,
    max_output_chars: int = 50000,
    _context: dict = None,
):
    if not str(cmd or "").strip():
        return json.dumps({"ok": False, "error": "cmd is empty"})
    blocked = _blacklist_error(str(cmd))
    if blocked:
        return json.dumps({"ok": False, "status": "blocked", "error": blocked})
    context = _context or {}
    workspace = Path(str(context.get("workspace") or os.getcwd())).resolve()
    cwd = Path(workdir) if workdir else workspace
    cwd = cwd.resolve() if cwd.is_absolute() else (workspace / cwd).resolve()
    try:
        cwd.relative_to(workspace)
    except ValueError:
        return json.dumps({"ok": False, "error": "workdir escapes the current workspace"})
    if not cwd.is_dir():
        return json.dumps({"ok": False, "error": f"working directory not found: {cwd}"})
    sandbox = context.get("sandbox") or {}
    if str(sandbox.get("mode", "workspace")).lower() == "container":
        return json.dumps({
            "ok": False,
            "status": "unsupported",
            "error": "Persistent stdin sessions are unavailable in the ephemeral container backend; use the blocking run_command tool there."
        })
    registry = context.get("running_commands")
    if not isinstance(registry, dict):
        return json.dumps({"ok": False, "error": "process session registry is unavailable"})
    result = start_process_session(
        registry,
        command=str(cmd),
        cwd=str(cwd),
        env=sanitized_subprocess_environment(),
        yield_time_ms=max(0, min(30000, int(yield_time_ms))),
    )
    # Respect a smaller caller-provided output contract after the shared read.
    output = str(result.get("output") or "")
    limit = max(1000, min(100000, int(max_output_chars)))
    if len(output) > limit:
        result["output"] = output[:limit] + "\n...[output truncated]"
        result["truncated"] = True
    return json.dumps(result, ensure_ascii=False)
