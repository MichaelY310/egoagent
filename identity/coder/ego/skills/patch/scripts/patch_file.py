import os
import json


def _unescape_llm_string(s: str) -> str:
    """Unescape literal \\n, \\t, \\\\  that LLMs often produce in JSON strings."""
    # Only unescape if the string contains literal backslash-n/t sequences
    # (real newlines would already be \n character, not two chars '\\' 'n')
    s = s.replace("\\n", "\n")
    s = s.replace("\\t", "\t")
    s = s.replace("\\\\", "\\")
    return s


def patch_file(file_path: str, old_string: str, new_string: str, replace_all: bool = False):
    """Replace old_string with new_string in a file. Returns error JSON on failure."""
    if not file_path:
        return json.dumps({"error": "file_path is empty."})

    if not os.path.exists(file_path):
        return json.dumps({"error": f"File not found: '{file_path}'."})

    if os.path.isdir(file_path):
        return json.dumps({"error": f"'{file_path}' is a directory, not a file."})

    if not os.access(file_path, os.R_OK | os.W_OK):
        return json.dumps({"error": f"Permission denied: cannot read/write '{file_path}'."})

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError:
        return json.dumps({"error": f"Cannot read '{file_path}': file appears to be binary."})
    except Exception as e:
        return json.dumps({"error": f"Failed to read '{file_path}': {str(e)}"})

    # LLMs often emit literal \n instead of actual newlines in JSON args; try unescaped version
    if old_string not in content:
        old_string_unescaped = _unescape_llm_string(old_string)
        new_string = _unescape_llm_string(new_string)
        if old_string_unescaped in content:
            old_string = old_string_unescaped
        # else: keep original old_string so the "not found" error is still accurate

    if old_string not in content:
        return json.dumps({
            "error": f"old_string not found in '{file_path}'. Use read_file to verify the current content.",
            "_hint": "Make sure old_string matches exactly, including whitespace and indentation."
        })

    if not replace_all:
        count = content.count(old_string)
        if count > 1:
            return json.dumps({
                "error": f"old_string found {count} times in '{file_path}'. "
                         "Provide more context to make it unique, or set replace_all=true.",
            })
        new_content = content.replace(old_string, new_string, 1)
    else:
        new_content = content.replace(old_string, new_string)

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)
    except Exception as e:
        return json.dumps({"error": f"Failed to write '{file_path}': {str(e)}"})

    # Record change for tracking
    try:
        import sys as _sys
        _ct_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "..", "..", "harness_editor")
        if os.path.isdir(_ct_path) and _ct_path not in _sys.path:
            _sys.path.insert(0, _ct_path)
        from change_tracker import record_change
        record_change(file_path, content, new_content, "patch_file")
    except Exception:
        pass

    replacements = content.count(old_string) if replace_all else 1
    return json.dumps({"status": "ok", "path": file_path, "replacements": replacements})
