import os
import json
import fnmatch


def ls(path: str, ignore: list = None):
    """List files and directories in the given path."""
    if not path:
        return json.dumps({"error": "path is empty."})
    if not os.path.exists(path):
        return json.dumps({"error": f"Path not found: '{path}'."})
    if not os.path.isdir(path):
        return json.dumps({"error": f"'{path}' is not a directory."})

    ignore = ignore or []
    entries = []
    try:
        for name in sorted(os.listdir(path)):
            if any(fnmatch.fnmatch(name, pat) for pat in ignore):
                continue
            full_path = os.path.join(path, name)
            entry_type = "dir" if os.path.isdir(full_path) else "file"
            entry = {"name": name, "type": entry_type}
            if entry_type == "file":
                entry["size"] = os.path.getsize(full_path)
            entries.append(entry)
    except PermissionError:
        return json.dumps({"error": f"Permission denied: cannot list '{path}'."})

    return json.dumps({"path": path, "entries": entries, "total": len(entries)}, ensure_ascii=False)
