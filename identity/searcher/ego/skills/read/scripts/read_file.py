import os
import json


def read_file(file_path: str, offset: int = None, limit: int = None):
    """读取文件内容，支持分页。失败时返回 JSON 错误信息供 LLM 理解。"""
    # 路径检查
    if not file_path:
        return json.dumps({"error": "file_path is empty. Please provide a valid file path."})

    if not os.path.exists(file_path):
        return json.dumps({"error": f"File not found: '{file_path}'. Check if the path is correct."})

    if os.path.isdir(file_path):
        return json.dumps({"error": f"'{file_path}' is a directory, not a file. Use a file path instead."})

    if not os.access(file_path, os.R_OK):
        return json.dumps({"error": f"Permission denied: cannot read '{file_path}'."})

    # 大文件警告
    file_size = os.path.getsize(file_path)
    MAX_CHARS = 100_000

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except UnicodeDecodeError:
        return json.dumps({"error": f"Cannot read '{file_path}': file appears to be binary."})
    except Exception as e:
        return json.dumps({"error": f"Failed to read '{file_path}': {str(e)}"})

    total_lines = len(lines)

    # 分页处理
    if offset is not None:
        start = max(0, offset - 1)  # 1-based to 0-based
    else:
        start = 0

    if limit is not None:
        end = start + limit
    else:
        end = total_lines

    content = "".join(lines[start:end])

    # 超长内容截断
    if len(content) > MAX_CHARS:
        return json.dumps({
            "error": f"File content too large ({len(content):,} chars, limit {MAX_CHARS:,}). "
                     f"The file has {total_lines} lines. Use offset and limit to read a smaller range.",
            "path": file_path,
            "total_lines": total_lines,
            "file_size": file_size,
        }, ensure_ascii=False)

    return content
