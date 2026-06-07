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

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
    except PermissionError:
        return json.dumps({"error": f"Permission denied: cannot write to '{file_path}'."})
    except Exception as e:
        return json.dumps({"error": f"Failed to write '{file_path}': {str(e)}"})

    return json.dumps({"status": "ok", "path": file_path, "bytes_written": len(content.encode("utf-8"))})
