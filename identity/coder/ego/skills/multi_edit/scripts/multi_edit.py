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
        # newline="" keeps the file's exact line endings.  Universal newline
        # translation would otherwise turn an LF file into CRLF on Windows and
        # collapse unrelated edits into one whole-file review hunk.
        with open(file_path, "r", encoding="utf-8", newline="") as f:
            content = f.read()
    except UnicodeDecodeError:
        return json.dumps({"error": f"Cannot read '{file_path}': file appears to be binary."})

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
        with open(file_path, "w", encoding="utf-8", newline="") as f:
            f.write(content)
    except Exception as e:
        return json.dumps({"error": f"Failed to write '{file_path}': {str(e)}"})

    failed = [r for r in results if r["status"] != "ok"]
    return json.dumps({
        "status": "ok" if not failed else "partial",
        "path": file_path,
        "edits_applied": len([r for r in results if r["status"] == "ok"]),
        "edits_failed": len(failed),
        "details": results if failed else None
    }, ensure_ascii=False)
