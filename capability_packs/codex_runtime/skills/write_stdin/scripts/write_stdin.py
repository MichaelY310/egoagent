import json

from process_sessions import write_process_session


def write_stdin(
    session_id: str,
    chars: str = "",
    yield_time_ms: int = 250,
    max_output_chars: int = 50000,
    _context: dict = None,
):
    registry = (_context or {}).get("running_commands")
    if not isinstance(registry, dict):
        return json.dumps({"ok": False, "error": "process session registry is unavailable"})
    result = write_process_session(
        registry,
        str(session_id),
        chars=str(chars or ""),
        yield_time_ms=max(0, min(30000, int(yield_time_ms))),
        max_output_chars=max(1000, min(100000, int(max_output_chars))),
    )
    return json.dumps(result, ensure_ascii=False)
