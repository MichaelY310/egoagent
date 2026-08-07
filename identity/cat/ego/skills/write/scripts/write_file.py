import os
import json


def write_file(file_path: str, content: str):
    """Write content to a file. Returns error JSON on failure."""
    if not file_path:
        return json.dumps({"error": "file_path is empty. Please provide a valid file path."})

    # Ensure parent directory exists
    parent = os.path.dirname(file_path)
    if parent and not os.path.exists(parent):
        try:
            os.makedirs(parent, exist_ok=True)
        except Exception as e:
            return json.dumps({"error": f"Cannot create directory '{parent}': {str(e)}"})

    if os.path.isdir(file_path):
        return json.dumps({"error": f"'{file_path}' is a directory. Provide a file path."})

    # Read old content before overwriting (for change tracking)
    old_content = None
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                old_content = f.read()
        except Exception:
            pass

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
    except PermissionError:
        return json.dumps({"error": f"Permission denied: cannot write to '{file_path}'."})
    except Exception as e:
        return json.dumps({"error": f"Failed to write '{file_path}': {str(e)}"})

    # Record change for tracking
    try:
        import sys as _sys
        _ct_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "..", "..", "harness_editor")
        if os.path.isdir(_ct_path) and _ct_path not in _sys.path:
            _sys.path.insert(0, _ct_path)
        from change_tracker import record_change
        record_change(file_path, old_content, content, "write_file")
    except Exception:
        pass

    return json.dumps({"status": "ok", "path": file_path, "bytes_written": len(content.encode("utf-8"))})
