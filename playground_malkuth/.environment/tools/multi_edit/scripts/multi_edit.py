import json
import os


def multi_edit(file_path: str, edits: list):
    """Apply multiple string replacements to a single file.
    
    Each edit in the list should have:
      - old_string: the text to find
      - new_string: the replacement text
      - replace_all (optional): if true, replace all occurrences
    """
    if not file_path:
        return json.dumps({"error": "file_path is empty."})

    if not os.path.isabs(file_path):
        return json.dumps({"error": f"file_path must be absolute: '{file_path}'."})

    if not os.path.exists(file_path):
        return json.dumps({"error": f"File not found: '{file_path}'."})

    if not edits or not isinstance(edits, list):
        return json.dumps({"error": "edits must be a non-empty list."})

    try:
        content = open(file_path, "r", encoding="utf-8").read()
    except Exception as e:
        return json.dumps({"error": f"Cannot read file: {str(e)}"})

    results = []
    for i, edit in enumerate(edits):
        old_string = edit.get("old_string", "")
        new_string = edit.get("new_string", "")
        replace_all = edit.get("replace_all", False)

        if not old_string:
            results.append({"edit": i, "status": "skipped", "reason": "old_string is empty"})
            continue

        if old_string == new_string:
            results.append({"edit": i, "status": "skipped", "reason": "old_string == new_string"})
            continue

        count = content.count(old_string)
        if count == 0:
            results.append({"edit": i, "status": "failed", "reason": "old_string not found in file"})
            continue

        if count > 1 and not replace_all:
            results.append({"edit": i, "status": "failed", "reason": f"old_string found {count} times. Set replace_all=true or provide more context."})
            continue

        if replace_all:
            content = content.replace(old_string, new_string)
            results.append({"edit": i, "status": "ok", "replacements": count})
        else:
            content = content.replace(old_string, new_string, 1)
            results.append({"edit": i, "status": "ok", "replacements": 1})

    # Write back
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        return json.dumps({"error": f"Cannot write file: {str(e)}"})

    return json.dumps({"file": file_path, "results": results}, ensure_ascii=False)
