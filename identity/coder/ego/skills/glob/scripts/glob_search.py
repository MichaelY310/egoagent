import os
import json
import glob as glob_module


def glob_search(pattern: str, path: str = None):
    """Find files matching a glob pattern."""
    if not pattern:
        return json.dumps({"error": "pattern is empty."})
    if path:
        if not os.path.exists(path):
            return json.dumps({"error": f"Path not found: '{path}'."})
        search_pattern = os.path.join(path, pattern)
    else:
        search_pattern = pattern

    try:
        matches = glob_module.glob(search_pattern, recursive=True)
        matches = [m for m in matches if '/__pycache__/' not in m and '/.git/' not in m]
        matches.sort(key=lambda f: os.path.getmtime(f) if os.path.exists(f) else 0, reverse=True)
        truncated = len(matches) > 100
        matches = matches[:100]
    except Exception as e:
        return json.dumps({"error": f"Glob search failed: {str(e)}"})

    return json.dumps({"pattern": pattern, "matches": matches, "total": len(matches), "truncated": truncated}, ensure_ascii=False)
