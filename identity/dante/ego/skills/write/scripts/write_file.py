import os
import json
import shutil
import time


def write_file(file_path: str, content: str):
    """Write content to a file. Creates a backup of existing files before overwriting.
    
    IMPORTANT: For modifying existing files, prefer using patch_file instead.
    write_file will COMPLETELY OVERWRITE the file with the provided content.
    Only use this for creating new files or when you intend to replace the entire content.
    
    Returns error JSON on failure.
    """
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

    # Create backup before overwriting existing file
    old_content = None
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                old_content = f.read()
            # Save backup
            backup_dir = os.path.join(os.path.dirname(file_path), ".egoagent_backups")
            os.makedirs(backup_dir, exist_ok=True)
            backup_name = os.path.basename(file_path) + f".{int(time.time())}.bak"
            shutil.copy2(file_path, os.path.join(backup_dir, backup_name))
        except Exception:
            pass  # Best effort backup

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

    result = {"status": "ok", "path": file_path, "bytes_written": len(content.encode("utf-8"))}
    if old_content is not None:
        result["warning"] = "Existing file was overwritten. Backup saved. Consider using patch_file for partial edits."
    return json.dumps(result)
