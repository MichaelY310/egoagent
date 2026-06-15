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
        if not os.path.isdir(path):
            return json.dumps({"error": f"'{path}' is not a directory."})
        search_pattern = os.path.join(path, pattern)
    else:
        search_pattern = pattern

    try:
        matches = glob_module.glob(search_pattern, recursive=True)
        # Filter out common noise
        matches = [m for m in matches if '/__pycache__/' not in m and '/.git/' not in m]
        # Sort by modification time (newest first)
        matches.sort(key=lambda f: os.path.getmtime(f) if os.path.exists(f) else 0, reverse=True)
        # Limit results
        truncated = len(matches) > 100
        matches = matches[:100]
    except Exception as e:
        return json.dumps({"error": f"Glob search failed: {str(e)}"})

    result = {
        "pattern": pattern,
        "matches": matches,
        "total": len(matches),
        "truncated": truncated,
    }
    return json.dumps(result, ensure_ascii=False)
