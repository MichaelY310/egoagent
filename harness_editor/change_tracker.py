"""
文件变更追踪模块

跟踪 agent 执行过程中对文件的修改（patch_file, write_file, multi_edit 等），
支持查看 diff、接受/拒绝变更、全部回退。
"""

import difflib
import time
from pathlib import Path

# 全局变更列表
_changes = []


def record_change(file_path, old_content, new_content, tool_name):
    """记录一次文件变更。

    Args:
        file_path: 被修改的文件路径
        old_content: 修改前的内容（可为 None 表示新建文件）
        new_content: 修改后的内容
        tool_name: 触发变更的工具名
    """
    entry = {
        "index": len(_changes),
        "file_path": file_path,
        "old_content": old_content,
        "new_content": new_content,
        "timestamp": time.time(),
        "tool_name": tool_name,
        "status": "pending",
        "reject_reason": None,
    }
    _changes.append(entry)
    return entry["index"]


def get_changes():
    """返回所有变更记录（含 diff 摘要）。"""
    result = []
    for c in _changes:
        item = {
            "index": c["index"],
            "file_path": c["file_path"],
            "timestamp": c["timestamp"],
            "tool_name": c["tool_name"],
            "status": c["status"],
            "reject_reason": c["reject_reason"],
            "diff": compute_diff(c["old_content"] or "", c["new_content"] or ""),
        }
        result.append(item)
    return result


def accept_change(index):
    """标记变更为已接受。

    Returns:
        True 成功, False 索引无效或状态不是 pending
    """
    if index < 0 or index >= len(_changes):
        return False
    entry = _changes[index]
    if entry["status"] != "pending":
        return False
    entry["status"] = "accepted"
    return True


def reject_change(index, reason=None):
    """标记变更为已拒绝，并将文件回退到旧内容。

    Returns:
        True 成功, False 索引无效或状态不是 pending
    """
    if index < 0 or index >= len(_changes):
        return False
    entry = _changes[index]
    if entry["status"] != "pending":
        return False
    entry["status"] = "rejected"
    entry["reject_reason"] = reason

    # 回退文件
    _revert_file(entry)
    return True


def revert_all():
    """回退所有 pending 和 accepted 的变更（按逆序）。

    Returns:
        回退的数量
    """
    count = 0
    for entry in reversed(_changes):
        if entry["status"] in ("pending", "accepted"):
            _revert_file(entry)
            entry["status"] = "rejected"
            entry["reject_reason"] = "revert_all"
            count += 1
    return count


def clear_changes():
    """清空所有记录。"""
    _changes.clear()


def compute_diff(old_content, new_content):
    """计算统一 diff 块。

    Args:
        old_content: 旧文本
        new_content: 新文本

    Returns:
        diff 字符串列表（unified diff 格式）
    """
    if old_content is None:
        old_content = ""
    if new_content is None:
        new_content = ""

    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)

    diff_lines = list(difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile="before",
        tofile="after",
        lineterm="",
    ))
    return diff_lines


def _revert_file(entry):
    """将文件内容恢复为变更前的状态。"""
    file_path = entry["file_path"]
    old_content = entry["old_content"]

    if old_content is None:
        # 文件原本不存在，删除
        p = Path(file_path)
        if p.exists():
            p.unlink()
    else:
        p = Path(file_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(old_content, encoding="utf-8")
