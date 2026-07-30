import os
import re
import json
import fnmatch


def search_files(pattern: str, path: str = ".", file_glob: str = None, limit: int = 50):
    """Search for a regex pattern in files. Returns matching lines with context."""
    if not pattern:
        return json.dumps({"error": "pattern is empty. Provide a search pattern."})

    if not os.path.exists(path):
        return json.dumps({"error": f"Path not found: '{path}'."})

    if not os.path.isdir(path):
        return json.dumps({"error": f"'{path}' is not a directory."})

    try:
        regex = re.compile(pattern)
    except re.error as e:
        return json.dumps({"error": f"Invalid regex pattern: {str(e)}"})

    matches = []
    files_searched = 0

    for root, dirs, files in os.walk(path):
        # Skip hidden dirs and common non-useful dirs
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('node_modules', '__pycache__', '.git')]

        for filename in files:
            if file_glob and not fnmatch.fnmatch(filename, file_glob):
                continue

            filepath = os.path.join(root, filename)
            files_searched += 1

            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    for line_num, line in enumerate(f, 1):
                        if regex.search(line):
                            matches.append({
                                "file": filepath,
                                "line": line_num,
                                "content": line.rstrip()[:200]  # 截断过长的行
                            })
                            if len(matches) >= limit:
                                break
            except (PermissionError, IsADirectoryError):
                continue

            if len(matches) >= limit:
                break
        if len(matches) >= limit:
            break

    result = {
        "matches": matches,
        "total_matches": len(matches),
        "files_searched": files_searched,
        "truncated": len(matches) >= limit,
    }

    if result["truncated"]:
        result["_hint"] = f"Results truncated at {limit}. Use a more specific pattern or file_glob to narrow results."

    return json.dumps(result, ensure_ascii=False)
