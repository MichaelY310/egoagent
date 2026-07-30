"""
从零设计并创建一个新的 harness 模板。
将 config.json 写入 harness/<name>/ 目录，之后可用 create_harness 调用。
"""
import json
from pathlib import Path


def design_harness(name: str, description: str, slots: dict, pipeline: dict,
                   prompts: dict = None, return_mode: str = "all"):
    from config import CONFIG

    # 确定 harness 模板根目录
    harness_root = Path(CONFIG.get("harness_template_repository", ""))
    if not harness_root.exists():
        harness_root = Path(__file__).resolve().parents[6] / "harness"
    if not harness_root.exists():
        harness_root.mkdir(parents=True, exist_ok=True)

    # 校验名称
    name = name.strip().replace(" ", "_")
    if not name:
        return "Error: name cannot be empty."

    harness_dir = harness_root / name
    if harness_dir.exists() and (harness_dir / "config.json").exists():
        return f"Error: harness template '{name}' already exists at {harness_dir}. Use a different name or modify it manually."

    # 校验 pipeline 基本结构
    if "start" not in pipeline:
        return "Error: pipeline must have a 'start' field specifying the first node name."
    if "nodes" not in pipeline:
        return "Error: pipeline must have a 'nodes' field with node definitions."

    nodes = pipeline["nodes"]
    start_node = pipeline["start"]
    if start_node not in nodes:
        return f"Error: start node '{start_node}' not found in nodes: {list(nodes.keys())}"

    # 校验每个 node
    valid_ops = {"等待输入", "推理", "处理工具", "处理文字", "执行工具"}
    valid_conditions = {"input", "has_tool_calls", "no_tool_calls", "has_text", "default"}
    slot_names = set(slots.keys())

    for node_name, node_def in nodes.items():
        op = node_def.get("op", "")
        if op not in valid_ops:
            return f"Error: node '{node_name}' has invalid op '{op}'. Valid: {valid_ops}"

        # 非 '等待输入' 节点必须指定 agent
        if op != "等待输入" and "agent" not in node_def:
            return f"Error: node '{node_name}' (op='{op}') must specify an 'agent' slot name."

        if "agent" in node_def and node_def["agent"] not in slot_names:
            return f"Error: node '{node_name}' references slot '{node_def['agent']}' which is not in slots: {slot_names}"

        # 校验 edges
        edges = node_def.get("edges", [])
        for edge in edges:
            if "condition" not in edge or "to" not in edge:
                return f"Error: node '{node_name}' has edge missing 'condition' or 'to': {edge}"
            if edge["condition"] not in valid_conditions:
                return f"Error: node '{node_name}' edge condition '{edge['condition']}' invalid. Valid: {valid_conditions}"
            if edge["to"] not in nodes:
                return f"Error: node '{node_name}' edge target '{edge['to']}' not in nodes: {list(nodes.keys())}"

    # Auto-generate default edges for nodes that lack them
    node_list = list(nodes.keys())
    for i, (node_name, node_def) in enumerate(nodes.items()):
        if node_def.get("edges"):
            continue  # already has edges
        op = node_def["op"]
        next_node = node_list[i + 1] if i + 1 < len(node_list) else None

        if op == "等待输入":
            if next_node:
                node_def["edges"] = [{"condition": "input", "to": next_node}]
        elif op == "推理":
            exec_node = None
            wait_node = None
            for nn, nd in nodes.items():
                if nd["op"] == "执行工具":
                    exec_node = nn
                if nd["op"] == "等待输入":
                    wait_node = nn
            edges = []
            if exec_node:
                edges.append({"condition": "has_tool_calls", "to": exec_node})
            if wait_node:
                edges.append({"condition": "has_text", "to": wait_node})
            elif next_node:
                edges.append({"condition": "default", "to": next_node})
            node_def["edges"] = edges
        elif op == "执行工具":
            infer_node = None
            for nn, nd in nodes.items():
                if nd["op"] == "推理":
                    infer_node = nn
                    break
            if infer_node:
                node_def["edges"] = [{"condition": "default", "to": infer_node}]
            elif next_node:
                node_def["edges"] = [{"condition": "default", "to": next_node}]
        elif op in ("处理工具", "处理文字"):
            if next_node:
                node_def["edges"] = [{"condition": "default", "to": next_node}]

    # 确保 slots 有正确结构
    for slot_name, slot_def in slots.items():
        if isinstance(slot_def, str):
            # 简写模式：字符串当做 description
            slots[slot_name] = {"description": slot_def, "required": True}
        elif isinstance(slot_def, dict):
            if "description" not in slot_def:
                slot_def["description"] = ""
            if "required" not in slot_def:
                slot_def["required"] = True

    # 组装 config
    config = {
        "name": name,
        "description": description,
        "slots": slots,
        "prompts": prompts or {},
        "return_mode": return_mode,
        "pipeline": {
            "start": pipeline["start"],
            "max_steps": pipeline.get("max_steps", 100),
            "workspace_preview": pipeline.get("workspace_preview", False),
            "nodes": nodes,
        },
    }

    # 写入文件
    harness_dir.mkdir(parents=True, exist_ok=True)
    config_path = harness_dir / "config.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=4), encoding="utf-8")

    return (
        f"✅ Harness template '{name}' created successfully!\n"
        f"Path: {harness_dir}\n"
        f"Slots: {', '.join(slot_names)}\n"
        f"Pipeline nodes: {', '.join(nodes.keys())}\n"
        f"Start: {start_node}\n"
        f"Max steps: {pipeline.get('max_steps', 100)}\n\n"
        f"You can now use it with create_harness:\n"
        f"  harness_dir: \"{harness_dir}\"\n"
        f"  agents: \"{', '.join(f'{s}:identity/<identity_name>' for s in slot_names)}\""
    )
