import json
import os
from pathlib import Path


def modify_harness(harness_name: str, action: str, target: str, value: str):
    """Modify an existing harness config.json with structured operations."""
    project_root = Path(__file__).resolve().parents[6]
    harness_dir = project_root / "harness" / harness_name
    config_path = harness_dir / "config.json"

    if not config_path.exists():
        return json.dumps({"error": f"Harness '{harness_name}' not found at {harness_dir}"})

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Failed to parse config.json: {e}"})

    try:
        val = json.loads(value) if value else None
    except json.JSONDecodeError:
        val = value  # treat as plain string

    pipeline = config.get("pipeline", {})
    nodes = pipeline.get("nodes", {})

    VALID_OPS = {"等待输入", "推理", "执行工具", "处理工具", "处理文字"}
    VALID_CONDITIONS = {"input", "has_tool_calls", "no_tool_calls", "has_text", "default"}

    if action == "update_node":
        if target not in nodes:
            return json.dumps({"error": f"Node '{target}' not found. Existing nodes: {list(nodes.keys())}"})
        if not isinstance(val, dict):
            return json.dumps({"error": "value must be a JSON object for update_node"})
        # Validate op field
        if "op" in val and val["op"] not in VALID_OPS:
            return json.dumps({"error": f"Invalid op '{val['op']}'. Valid ops: {list(VALID_OPS)}"})
        # Validate edges
        if "edges" in val:
            for edge in val["edges"]:
                cond = edge.get("condition", "")
                if cond and cond not in VALID_CONDITIONS:
                    return json.dumps({"error": f"Invalid edge condition '{cond}'. Valid: {list(VALID_CONDITIONS)}"})
                if "to" in edge and edge["to"] not in nodes and edge["to"] != target:
                    # Allow referencing nodes that will exist after add_node
                    pass
        nodes[target].update(val)

    elif action == "add_node":
        if not isinstance(val, dict) or "id" not in val:
            return json.dumps({"error": "value must be {\"id\": \"node_id\", ...node_fields} for add_node"})
        node_id = val.pop("id")
        if node_id in nodes:
            return json.dumps({"error": f"Node '{node_id}' already exists"})
        # Validate op
        if "op" in val and val["op"] not in VALID_OPS:
            return json.dumps({"error": f"Invalid op '{val['op']}'. Valid ops: {list(VALID_OPS)}"})
        nodes[node_id] = val

    elif action == "remove_node":
        if target not in nodes:
            return json.dumps({"error": f"Node '{target}' not found"})
        del nodes[target]
        # Also remove edges pointing to this node
        for nid, node in nodes.items():
            if "edges" in node:
                node["edges"] = [e for e in node["edges"] if e.get("to") != target]

    elif action == "update_edge":
        if not isinstance(val, dict):
            return json.dumps({"error": "value must be {\"source_node\", \"edge_index\", \"new_edge\"}"})
        src = val.get("source_node", target)
        idx = val.get("edge_index", 0)
        new_edge = val.get("new_edge", {})
        if src not in nodes:
            return json.dumps({"error": f"Source node '{src}' not found"})
        edges = nodes[src].get("edges", [])
        if idx >= len(edges):
            edges.append(new_edge)
        else:
            edges[idx] = new_edge
        nodes[src]["edges"] = edges

    elif action == "set_field":
        # Navigate dot-separated path
        parts = target.split(".")
        obj = config
        for p in parts[:-1]:
            if p not in obj:
                obj[p] = {}
            obj = obj[p]
        obj[parts[-1]] = val

    elif action == "replace_pipeline":
        if not isinstance(val, dict):
            return json.dumps({"error": "value must be a pipeline object for replace_pipeline"})
        config["pipeline"] = val

    else:
        return json.dumps({"error": f"Unknown action: '{action}'. Use: update_node, add_node, remove_node, update_edge, set_field, replace_pipeline"})

    # Write back
    pipeline["nodes"] = nodes
    config["pipeline"] = pipeline
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=4), encoding="utf-8")

    return json.dumps({
        "success": True,
        "harness": harness_name,
        "action": action,
        "target": target,
        "current_nodes": list(config["pipeline"]["nodes"].keys()),
        "current_slots": list(config.get("slots", {}).keys()),
    }, ensure_ascii=False)
