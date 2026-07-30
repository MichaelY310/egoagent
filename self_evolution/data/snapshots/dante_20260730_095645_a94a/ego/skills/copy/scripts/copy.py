import os
import json
import shutil


def copy(src: str, dst: str):
    """复制文件或文件夹到目标路径。失败时返回 JSON 错误信息。"""
    if not src:
        return json.dumps({"error": "src is empty. Please provide a valid source path."})

    if not dst:
        return json.dumps({"error": "dst is empty. Please provide a valid destination path."})

    if not os.path.exists(src):
        return json.dumps({"error": f"Source not found: '{src}'. Check if the path is correct."})

    if not os.access(src, os.R_OK):
        return json.dumps({"error": f"Permission denied: cannot read '{src}'."})

    try:
        if os.path.isdir(src):
            # 复制整个目录
            if os.path.exists(dst):
                # 如果目标已存在，复制到目标下面
                dst = os.path.join(dst, os.path.basename(src))
            shutil.copytree(src, dst)
            return json.dumps({"success": True, "message": f"Directory copied: '{src}' -> '{dst}'"}, ensure_ascii=False)
        else:
            # 复制文件
            dst_dir = os.path.dirname(dst)
            if dst_dir and not os.path.exists(dst_dir):
                os.makedirs(dst_dir, exist_ok=True)
            shutil.copy2(src, dst)
            # 如果 dst 是目录，实际目标是 dst/basename
            actual_dst = os.path.join(dst, os.path.basename(src)) if os.path.isdir(dst) else dst
            return json.dumps({"success": True, "message": f"File copied: '{src}' -> '{actual_dst}'"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"Copy failed: {str(e)}"}, ensure_ascii=False)
