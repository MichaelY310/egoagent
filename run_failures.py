"""Normalize runtime failures into stable, user-facing terminal reasons."""

from __future__ import annotations

from typing import Any


def classify_run_failure(message: Any, error_type: str = "") -> dict[str, Any]:
    text = str(message or "").strip()
    lower = text.lower()
    type_lower = str(error_type or "").lower()
    if "context" in lower and any(token in lower for token in ("length", "window", "maximum", "too long", "token")):
        code, title, action, recoverable = (
            "context_limit", "上下文达到模型上限", "压缩上下文、删除无关内容或换用更大上下文模型后重试。", True,
        )
    elif "max token" in lower or "token budget" in lower:
        code, title, action, recoverable = (
            "token_budget", "本次运行达到 Token 预算", "提高 Harness 预算或从最近检查点继续。", True,
        )
    elif "max tool" in lower or "tool call budget" in lower:
        code, title, action, recoverable = (
            "tool_budget", "本次运行达到工具调用上限", "检查是否存在循环，再提高工具预算或继续。", True,
        )
    elif "max node" in lower or "node steps" in lower or "max model calls" in lower:
        code, title, action, recoverable = (
            "step_budget", "本次运行达到步骤上限", "检查 DAG 循环条件，或提高步骤/模型调用预算。", True,
        )
    elif "timeout" in lower or "timed out" in lower or "timeoute" in type_lower:
        code, title, action, recoverable = (
            "timeout", "操作超时", "查看最后运行节点；可重试、提高超时，或停止卡住的子进程。", True,
        )
    # Windows reports an outbound socket denied by an inherited process/network
    # boundary as "forbidden by its access permissions" (WinError 10013).  That
    # is not an EgoAgent tool permission and there is no approval card that can
    # authorize it.  Classify provider connectivity before the deliberately
    # broad permission fallback so the UI gives an actionable diagnosis.
    elif "winerror 10013" in lower or "forbidden by its access permissions" in lower:
        code, title, action, recoverable = (
            "network_access", "模型网络连接被当前进程拦截",
            "请从普通用户终端重新启动 EgoAgent；若仍失败，再检查 Windows 防火墙或代理设置。无需批准文件或命令操作。", True,
        )
    elif any(token in lower for token in (
        "failed to establish a new connection", "connection refused", "network is unreachable",
        "no route to host", "connection aborted", "connection reset",
    )):
        code, title, action, recoverable = (
            "network_connection", "无法连接模型服务", "检查网络或代理后重试；EgoAgent 没有执行文件修改。", True,
        )
    elif "permission" in lower or "approval" in lower:
        code, title, action, recoverable = (
            "permission", "操作被安全策略拦截", "在审批卡中明确允许一次，或到设置中调整当前工作区策略。", True,
        )
    elif any(token in lower for token in ("name resolution", "getaddrinfo", "dns", "failed to resolve")):
        code, title, action, recoverable = (
            "dns", "模型服务域名解析失败", "检查网络或代理；EgoAgent 没有执行文件修改。", True,
        )
    elif "rate limit" in lower or "429" in lower:
        code, title, action, recoverable = (
            "rate_limit", "模型服务限流", "稍后重试或切换模型/供应商。", True,
        )
    elif any(token in lower for token in ("401", "403", "api key", "unauthorized", "authentication")):
        code, title, action, recoverable = (
            "authentication", "模型服务鉴权失败", "检查服务端 API Key 和模型供应商配置。", True,
        )
    elif "cancel" in lower:
        code, title, action, recoverable = (
            "cancelled", "运行已停止", "可以修改输入后重新开始。", True,
        )
    else:
        code, title, action, recoverable = (
            "runtime_error", "Agent 运行失败", "展开运行记录查看最后节点、错误类型和可重试输入。", False,
        )
    return {
        "code": code,
        "title": title,
        "message": text,
        "action": action,
        "recoverable": recoverable,
    }


def output_limit_notice(*, finish_reason: Any = None, node: Any = None) -> dict[str, Any]:
    return {
        "code": "output_limit",
        "title": "模型输出达到上限",
        "message": "当前回复不是完整结果。",
        "action": "发送“继续”可从当前 Session 接着生成；已完成的文件改动仍保留并可逐段审查。",
        "recoverable": True,
        "finish_reason": finish_reason,
        "node": node,
    }
