import os
import json
from pathlib import Path


def list_sessions(filter: str = "", limit: int = 20):
    """List available session directories with basic stats."""
    project_root = Path(__file__).resolve().parents[6]
    sessions_dir = project_root / "sessions"
    
    if not sessions_dir.is_dir():
        return json.dumps({"error": "Sessions directory not found."})
    
    sessions = []
    for d in sorted(sessions_dir.iterdir(), key=lambda x: x.name, reverse=True):
        if not d.is_dir():
            continue
        if filter and filter.lower() not in d.name.lower():
            continue
        
        info = {"name": d.name, "path": str(d)}
        
        # Try to get message count
        msgs_file = d / "messages.json"
        if msgs_file.exists():
            try:
                msgs = json.loads(msgs_file.read_text(encoding="utf-8"))
                info["message_count"] = len(msgs)
                # Extract harness name from directory name (part before date)
                parts = d.name.rsplit("_", 3)
                if len(parts) >= 3:
                    info["harness"] = "_".join(parts[:-3]) if len(parts) > 3 else parts[0]
            except:
                info["message_count"] = "?"
        else:
            info["message_count"] = 0
            info["note"] = "no messages.json"
        
        sessions.append(info)
        if len(sessions) >= limit:
            break
    
    if not sessions:
        return "No sessions found" + (f" matching '{filter}'" if filter else "") + "."
    
    lines = [f"Found {len(sessions)} session(s):", ""]
    for s in sessions:
        harness = s.get("harness", "?")
        count = s.get("message_count", "?")
        note = f" ({s['note']})" if "note" in s else ""
        lines.append(f"  {s['name']} [{harness}] - {count} msgs{note}")
    
    return "\n".join(lines)
