import os
import json


def multi_edit(file_path: str, edits: list):
    """Perform multiple string replacements in a single file."""
    if not file_path:
        return json.dumps({"error": "file_path is empty."})
    if not os.path.exists(file_path):
        return json.dumps({"error": f"File not found: '{file_path}'."})
    if not os.path.isfile(file_path):
        return json.dumps({"error": f"'{file_path}' is not a file."})
    if not edits:
        return json.dumps({"error": "edits list is empty."})

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError:
        return json.dumps({"error": f"Cannot read '{file_path}': file appears to be binary."})

    old_content = content
    results = []
    for i, edit in enumerate(edits):
        old_string = edit.get("old_string", "")
        new_string = edit.get("new_string", "")
        if old_string not in content:
            results.append({"index": i, "status": "not_found", "old_string_preview": old_string[:50]})
            continue
        content = content.replace(old_string, new_string, 1)
        results.append({"index": i, "status": "ok"})

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        return json.dumps({"error": f"Failed to write '{file_path}': {str(e)}"})

    # Record change for tracking
    try:
        import sys as _sys
        _ct_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "..", "..", "harness_editor")
        if os.path.isdir(_ct_path) and _ct_path not in _sys.path:
            _sys.path.insert(0, _ct_path)
        from change_tracker import record_change
        record_change(file_path, old_content, content, "multi_edit")
    except Exception:
        pass

    failed = [r for r in results if r["status"] != "ok"]
    return json.dumps({
        "status": "ok" if not failed else "partial",
        "path": file_path,
        "edits_applied": len([r for r in results if r["status"] == "ok"]),
        "edits_failed": len(failed),
        "details": results if failed else None
    }, ensure_ascii=False)
