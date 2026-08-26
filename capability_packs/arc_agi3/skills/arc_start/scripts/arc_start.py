import json

from arc_agi3_runtime import start_arc_session


def arc_start(game_id: str, seed: int = 0, _context: dict = None):
    workspace = (_context or {}).get("workspace")
    if not workspace:
        return json.dumps({"ok": False, "error": "workspace is unavailable"})
    return json.dumps(start_arc_session(workspace, game_id, seed=int(seed)), ensure_ascii=False)
