import json


def check_command_status(command_id: str, tail_lines: int = 50, _context: dict = None):
    """Get the status of a previously started async command."""
    if not command_id:
        return json.dumps({"error": "command_id is empty."})

    running_commands = _context.get("running_commands", {}) if _context else {}

    if command_id not in running_commands:
        return json.dumps({"error": f"Command '{command_id}' not found. It may have been started in a different session."})

    cmd_info = running_commands[command_id]
    proc = cmd_info["process"]
    output_lines = cmd_info["output_lines"]

    # Get tail of output
    tail = output_lines[-tail_lines:] if len(output_lines) > tail_lines else output_lines
    output_text = "".join(tail)

    if proc.poll() is None:
        return json.dumps({
            "status": "running",
            "command_id": command_id,
            "command": cmd_info["command"],
            "output": output_text,
            "total_lines": len(output_lines),
        }, ensure_ascii=False)
    else:
        return json.dumps({
            "status": "done",
            "command_id": command_id,
            "command": cmd_info["command"],
            "exit_code": proc.poll(),
            "output": output_text,
            "total_lines": len(output_lines),
        }, ensure_ascii=False)
