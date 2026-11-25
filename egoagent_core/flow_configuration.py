"""Resolve an executable Flow's saved configuration without UI defaults.

Callers must pass the selected, immutable Flow version, not the live draft.
Unbound templates can be saved/edited, but cannot silently borrow a Chat Identity.
"""
from __future__ import annotations

from collections.abc import Mapping


RUN_MODES = {"agent", "chat", "ask", "plan", "debug", "evolve", "evaluate"}


def saved_flow_configuration(config: Mapping, harness_name: str) -> dict:
    pipeline = config.get("pipeline") or {}
    slots = config.get("slots") or {}
    if not isinstance(pipeline, Mapping) or not isinstance(slots, Mapping):
        raise ValueError("Flow 的 pipeline / slots 必须是对象；请在 Build 中修复后保存。")
    mode = str(pipeline.get("mode") or "agent").lower()
    if mode not in RUN_MODES:
        raise ValueError(f"Flow 的运行策略无效：{mode}；请在 Build 中修复后保存。")
    nodes = pipeline.get("nodes") or {}
    if not isinstance(nodes, Mapping):
        raise ValueError("Flow 的 nodes 必须是对象。")
    used = {str(node["agent"]) for node in nodes.values()
            if isinstance(node, Mapping) and node.get("agent")}
    agents, missing = {}, set(used - slots.keys())
    for slot, definition in slots.items():
        if not isinstance(definition, Mapping):
            raise ValueError(f"Flow 角色 {slot} 配置无效。")
        identity = str(definition.get("identity") or "").strip()
        if identity:
            agents[str(slot)] = identity
        elif definition.get("required") or slot in used:
            missing.add(str(slot))
    if missing:
        raise ValueError(
            "Flow 尚未配置 Identity：" + "、".join(sorted(missing))
            + "。请打开 Build → 角色与 Identity，为这些角色选择 Identity，保存新版本后重试。"
        )
    # Evolve is scoped to this Flow and its explicitly bound Identities. Neither
    # a stale browser cache nor a request payload may expand these targets.
    targets = []
    if mode == "evolve":
        targets = sorted({harness_name, *(value.replace("\\", "/").split("/")[-1] for value in agents.values())})
    return {"agents": agents, "mode": mode, "mutation_targets": targets}
