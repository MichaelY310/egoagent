import os
import json
import subprocess
import threading
import uuid
import time
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))))
from config import CONFIG


def _check_blacklist(command: str) -> str:
    """Check if the command matches any blacklist pattern. Returns error message or None."""
    blacklist = CONFIG.get("command_blacklist", [])
    cmd_stripped = command.strip()
    for pattern in blacklist:
        if isinstance(pattern, str) and pattern in cmd_stripped:
            return f"Command blocked by blacklist: contains '{pattern}'"
    return None


def run_command(command: str, cwd: str = None, blocking: bool = True, timeout: int = 60, _context: dict = None):
    """Execute a shell command."""
    if not command:
        return json.dumps({"error": "command is empty."})

    # Blacklist check
    blocked = _check_blacklist(command)
    if blocked:
        return json.dumps({"error": blocked})

    if cwd and not os.path.isdir(cwd):
        return json.dumps({"error": f"Working directory not found: '{cwd}'."})

    env = os.environ.copy()
    env["PAGER"] = "cat"

    if blocking:
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
            output = result.stdout
            if result.stderr:
                output += "\n[STDERR]\n" + result.stderr

            # Truncate long output
            max_chars = 50000
            truncated = len(output) > max_chars
            if truncated:
                output = output[:max_chars] + "\n... (output truncated)"

            return json.dumps({
                "status": "done",
                "exit_code": result.returncode,
                "output": output,
                "truncated": truncated,
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
                command,
                shell=True,
                cwd=cwd,
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
