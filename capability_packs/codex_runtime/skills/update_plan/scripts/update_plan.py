import json
import time


def update_plan(plan: list, explanation: str = "", _context: dict = None):
    if not isinstance(plan, list):
        return json.dumps({"ok": False, "error": "plan must be an array"})
    normalized = []
    active = 0
    for index, item in enumerate(plan):
        if not isinstance(item, dict) or not str(item.get("step") or "").strip():
            return json.dumps({"ok": False, "error": f"plan item {index} needs a non-empty step"})
        status = str(item.get("status") or "pending")
        if status not in {"pending", "in_progress", "completed"}:
            return json.dumps({"ok": False, "error": f"invalid status at plan item {index}: {status}"})
        active += status == "in_progress"
        normalized.append({"step": str(item["step"]).strip(), "status": status})
    if active > 1:
        return json.dumps({"ok": False, "error": "at most one plan item may be in_progress"})
    state = (_context or {}).get("plan_state")
    if not isinstance(state, dict):
        return json.dumps({"ok": False, "error": "plan state is unavailable"})
    state.clear()
    state.update({"items": normalized, "explanation": str(explanation or ""), "updated_at": time.time()})
    return json.dumps({"ok": True, "plan": normalized, "explanation": str(explanation or "")}, ensure_ascii=False)
