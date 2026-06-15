import json


def stop_command(command_id: str, _context: dict = None):
    """Stop a running async command."""
    if not command_id:
        return json.dumps({"error": "command_id is empty."})

    running_commands = _context.get("running_commands", {}) if _context else {}

    if command_id not in running_commands:
        return json.dumps({"error": f"Command '{command_id}' not found."})

    cmd_info = running_commands[command_id]
    proc = cmd_info["process"]

    if proc.poll() is not None:
        return json.dumps({"status": "already_done", "exit_code": proc.poll(), "command_id": command_id})

    try:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except:
            proc.kill()
        return json.dumps({"status": "stopped", "command_id": command_id, "command": cmd_info["command"]})
    except Exception as e:
        return json.dumps({"error": f"Failed to stop command: {str(e)}"})
