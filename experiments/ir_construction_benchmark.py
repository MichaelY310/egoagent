"""Weak-model Harness construction benchmark across five representations.

This is an executable experiment, not a prompt-only demo.  It parses every
answer, compiles it through the real pipeline validator, measures exact edit
accuracy, and keeps held-out task families separate from development cases.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import statistics
import sys
import sys
import time
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ego_ir import apply_operations as apply_ir_operations, compile_document as compile_ir, decompile_config as decompile_ir, dumps as dump_ir, guide as ir_guide, text_to_config
from harness_blueprint import blueprint_guide, compile_blueprint, decompile_config as decompile_blueprint
from llm.env_config import load_local_env
from llm.providers import create_provider
from pipeline_schema import canonical_op, validate_pipeline


REPRESENTATIONS = ("full_json", "blueprint", "egoir", "json_patch", "high_level_tools")


def base_config(name: str) -> dict[str, Any]:
    return {
        "name": name, "description": "benchmark base", "slots": {"worker": {"required": True, "description": "primary worker"}},
        "prompts": {}, "return_mode": "last",
        "pipeline": {"start": "input", "max_steps": 20, "workspace_preview": False, "nodes": {
            "input": {"op": "输入", "edges": [{"condition": "input", "to": "work"}]},
            "work": {"op": "Agent", "agent": "worker", "tools": "auto", "edges": [{"condition": "has_text", "to": "finish"}]},
            "finish": {"op": "输出", "value": "$last.text", "edges": []},
        }},
    }


def cases() -> list[dict[str, Any]]:
    return [
        {"id": "train_bound", "split": "train", "instruction": "Reduce the maximum DAG steps to 8.", "operations": [{"op": "set_limits", "max_steps": 8}]},
        {"id": "train_context", "split": "train", "instruction": "Insert a Context node named compact immediately before work. Configure action=auto_compact and max_tokens=8000. Replace the input->work route with input -(input)-> compact -(default)-> work.", "operations": [
            {"op": "add_node", "before": "work", "node": {"id": "compact", "op": "context", "config": {"action": "auto_compact", "max_tokens": 8000}}},
            {"op": "disconnect", "from": "input", "to": "work"}, {"op": "connect", "from": "input", "condition": "input", "to": "compact"}, {"op": "connect", "from": "compact", "condition": "default", "to": "work"},
        ]},
        {"id": "validation_approval", "split": "validation", "instruction": "Add a human approval node named approve immediately after work with JSON proposal input, boolean decision output, and prompt_text='Approve result?'. Replace work->finish with work -(has_text)-> approve -(approved)-> finish.", "operations": [
            {"op": "add_node", "after": "work", "node": {"id": "approve", "op": "approval", "ports": {"in": {"proposal": "json"}, "out": {"decision": "boolean"}}, "config": {"prompt_text": "Approve result?"}}},
            {"op": "disconnect", "from": "work", "to": "finish"}, {"op": "connect", "from": "work", "condition": "has_text", "to": "approve"}, {"op": "connect", "from": "approve", "condition": "approved", "to": "finish"},
        ]},
        {"id": "heldout_rebind", "split": "heldout", "instruction": "Bind worker to Identity researcher and require network approval in Harness permissions.", "operations": [
            {"op": "rebind", "role": "worker", "identity": "researcher"}, {"op": "set_permissions", "permissions": {"network": "ask"}},
        ]},
        {"id": "heldout_result_only", "split": "heldout", "instruction": "Insert a result-only Subflow node named search immediately before work. Configure harness=search_agent, return_mode=last and result_only=true, with a string query input port and string result output port. Replace input->work with input -(input)-> search -(default)-> work.", "operations": [
            {"op": "add_node", "before": "work", "node": {"id": "search", "op": "subflow", "ports": {"in": {"query": "string"}, "out": {"result": "string"}}, "config": {"harness": "search_agent", "return_mode": "last", "result_only": True}}},
            {"op": "disconnect", "from": "input", "to": "work"}, {"op": "connect", "from": "input", "condition": "input", "to": "search"}, {"op": "connect", "from": "search", "condition": "default", "to": "work"},
        ]},
    ]


def _strip_fence(text: str) -> str:
    value = str(text or "").strip()
    fenced = re.search(r"```(?:json|text|egoir)?\s*(.*?)```", value, re.S | re.I)
    return (fenced.group(1) if fenced else value).strip()


def _pointer_parts(pointer: str) -> list[str]:
    if not pointer.startswith("/"):
        raise ValueError(f"invalid JSON pointer: {pointer}")
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/") if part != ""]


def apply_json_patch(value: Any, operations: list[dict[str, Any]]) -> Any:
    result = copy.deepcopy(value)
    for operation in operations:
        parts = _pointer_parts(str(operation.get("path", "")))
        if not parts:
            if operation.get("op") in {"add", "replace"}:
                result = copy.deepcopy(operation.get("value"))
                continue
            raise ValueError("cannot remove document root")
        parent = result
        for part in parts[:-1]:
            parent = parent[int(part)] if isinstance(parent, list) else parent[part]
        key = parts[-1]
        if operation.get("op") == "remove":
            parent.pop(int(key)) if isinstance(parent, list) else parent.pop(key)
        elif operation.get("op") in {"add", "replace"}:
            if isinstance(parent, list):
                if key == "-": parent.append(copy.deepcopy(operation.get("value")))
                elif operation["op"] == "add": parent.insert(int(key), copy.deepcopy(operation.get("value")))
                else: parent[int(key)] = copy.deepcopy(operation.get("value"))
            else:
                parent[key] = copy.deepcopy(operation.get("value"))
        else:
            raise ValueError(f"unsupported JSON Patch operation: {operation.get('op')}")
    return result


def json_patch_diff(before: Any, after: Any, path: str = "") -> list[dict[str, Any]]:
    if isinstance(before, dict) and isinstance(after, dict):
        operations = []
        for key in sorted(before.keys() - after.keys()):
            operations.append({"op": "remove", "path": f"{path}/{key}"})
        for key in sorted(after.keys() - before.keys()):
            operations.append({"op": "add", "path": f"{path}/{key}", "value": after[key]})
        for key in sorted(before.keys() & after.keys()):
            operations.extend(json_patch_diff(before[key], after[key], f"{path}/{key}"))
        return operations
    if before != after:
        return [{"op": "replace", "path": path or "/", "value": after}]
    return []


def expected(case: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    base = base_config(case["id"])
    document = apply_ir_operations(decompile_ir(base), case["operations"])
    return base, compile_ir(document)


def oracle_answer(representation: str, case: dict[str, Any]) -> str:
    base, target = expected(case)
    if representation == "full_json": return json.dumps(target, ensure_ascii=False)
    if representation == "blueprint": return json.dumps(decompile_blueprint(target), ensure_ascii=False)
    if representation == "egoir": return dump_ir(decompile_ir(target))
    if representation == "json_patch": return json.dumps(json_patch_diff(base, target), ensure_ascii=False)
    return json.dumps({"operations": case["operations"]}, ensure_ascii=False)


def prompt_for(representation: str, case: dict[str, Any]) -> str:
    base, _ = expected(case)
    common = f"Task: {case['instruction']}\nReturn only the requested representation, without explanation."
    if representation == "full_json": return common + "\nReturn the complete Harness config JSON.\nBASE:\n" + json.dumps(base, ensure_ascii=False)
    if representation == "blueprint": return common + "\nReturn complete Blueprint JSON.\nGUIDE:\n" + json.dumps(blueprint_guide(), ensure_ascii=False) + "\nBASE:\n" + json.dumps(decompile_blueprint(base), ensure_ascii=False)
    if representation == "egoir": return common + "\nReturn complete EGOIR/1 text.\nGUIDE:\n" + json.dumps(ir_guide(), ensure_ascii=False) + "\nBASE:\n" + dump_ir(decompile_ir(base))
    if representation == "json_patch": return common + "\nReturn an RFC 6902 JSON Patch array for the full config.\nBASE:\n" + json.dumps(base, ensure_ascii=False)
    return common + "\nReturn exactly one JSON object shaped {\"operations\":[...]}. Do NOT return EGOIR/1 text and do not copy the whole Harness. The operations array may use only: add_node, remove_node, update_node, replace_node, connect, disconnect, set_start, set_role, remove_role, rebind, unbind, set_ports, set_limits, set_permissions, set_return, set_prompt. For connect/disconnect, from/condition/to MUST be top-level fields, never nested under edge. For rebind use role and identity. For set_limits put max_steps at the operation top level.\nExamples: {\"operations\":[{\"op\":\"set_limits\",\"max_steps\":12},{\"op\":\"connect\",\"from\":\"a\",\"condition\":\"default\",\"to\":\"b\"}]}\nGUIDE:\n" + json.dumps(ir_guide(), ensure_ascii=False) + "\nBASE:\n" + dump_ir(decompile_ir(base))


def parse_answer(representation: str, case: dict[str, Any], answer: str) -> dict[str, Any]:
    base, _ = expected(case)
    raw = _strip_fence(answer)
    if representation == "full_json": config = json.loads(raw)
    elif representation == "blueprint": config, _ = compile_blueprint(json.loads(raw), name=base["name"])
    elif representation == "egoir": config = text_to_config(raw)
    elif representation == "json_patch": config = apply_json_patch(base, json.loads(raw))
    else:
        payload = json.loads(raw)
        operations = payload.get("operations") if isinstance(payload, dict) else payload
        config = compile_ir(apply_ir_operations(decompile_ir(base), operations))
    errors = validate_pipeline(config.get("pipeline", {}))
    if errors: raise ValueError("; ".join(errors))
    return config


def _leaf_paths(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        result = {}
        for key, child in value.items(): result.update(_leaf_paths(child, f"{prefix}/{key}"))
        return result
    if isinstance(value, list):
        result = {}
        for index, child in enumerate(value): result.update(_leaf_paths(child, f"{prefix}/{index}"))
        return result
    return {prefix or "/": value}


def _semantic_config(config: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(config)
    aliases = {"tool": "has_tool_calls", "tools": "has_tool_calls", "text": "has_text", "yes": "true", "no": "false", "otherwise": "default", "else": "default"}
    for node in value.get("pipeline", {}).get("nodes", {}).values():
        node["op"] = canonical_op(node.get("op", ""))
        for edge in node.get("edges", []):
            edge["condition"] = aliases.get(edge.get("condition"), edge.get("condition"))
    return value


def score_answer(case: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    base, target = expected(case)
    base, target, config = _semantic_config(base), _semantic_config(target), _semantic_config(config)
    base_leaves, target_leaves, actual_leaves = _leaf_paths(base), _leaf_paths(target), _leaf_paths(config)
    expected_changes = {path for path in set(base_leaves) | set(target_leaves) if base_leaves.get(path, object()) != target_leaves.get(path, object())}
    actual_changes = {path for path in set(base_leaves) | set(actual_leaves) if base_leaves.get(path, object()) != actual_leaves.get(path, object())}
    correct = {path for path in expected_changes & actual_changes if actual_leaves.get(path, object()) == target_leaves.get(path, object())}
    precision = len(correct) / len(actual_changes) if actual_changes else (1.0 if not expected_changes else 0.0)
    recall = len(correct) / len(expected_changes) if expected_changes else 1.0
    accuracy = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"valid": True, "exact": config == target, "edit_accuracy": round(accuracy, 4), "expected_changes": len(expected_changes), "actual_changes": len(actual_changes)}


def run_benchmark(*, role: str = "evolver", repeats: int = 1, mock_oracle: bool = False, representations: tuple[str, ...] = REPRESENTATIONS) -> dict[str, Any]:
    load_local_env(ROOT)
    client = None
    profile = {"id": "oracle", "model": "deterministic-oracle"}
    if not mock_oracle:
        from harness_editor.model_router import route_model
        profile = route_model(role, include_secret=True)
        if profile.get("error"): raise RuntimeError(profile["error"])
        client = create_provider(profile)
    records = []
    for case in cases():
        for representation in representations:
            for repeat in range(max(1, repeats)):
                prompt = prompt_for(representation, case)
                started = time.perf_counter()
                usage, error, answer = {}, "", ""
                try:
                    if mock_oracle:
                        answer = oracle_answer(representation, case)
                    else:
                        response = client.chat(
                            [{"role": "system", "content": "You edit declarative Agent Harnesses precisely. Obey the requested output format literally."}, {"role": "user", "content": prompt}],
                            max_tokens=5000,
                            temperature=0,
                            response_format={"type": "json_object"} if representation in {"full_json", "blueprint", "high_level_tools"} else None,
                        )
                        answer = response["choices"][0]["message"].get("content", "")
                        usage = response.get("usage", {})
                    config = parse_answer(representation, case, answer)
                    score = score_answer(case, config)
                except Exception as exc:
                    score, error = {"valid": False, "exact": False, "edit_accuracy": 0.0}, f"{type(exc).__name__}: {exc}"
                records.append({
                    "task_id": case["id"], "split": case["split"], "representation": representation, "repeat": repeat,
                    "prompt_chars": len(prompt), "answer_chars": len(answer), "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    "usage": usage, "error": error, "answer": answer, **score,
                })
    summary = {}
    for representation in representations:
        subset = [item for item in records if item["representation"] == representation]
        heldout = [item for item in subset if item["split"] == "heldout"]
        summary[representation] = {
            "validity": statistics.fmean(float(item["valid"]) for item in subset),
            "first_run_success": statistics.fmean(float(item["exact"]) for item in subset),
            "edit_accuracy": statistics.fmean(item["edit_accuracy"] for item in subset),
            "generalization": statistics.fmean(float(item["exact"]) for item in heldout),
            "prompt_chars": statistics.fmean(item["prompt_chars"] for item in subset),
            "latency_ms": statistics.fmean(item["latency_ms"] for item in subset),
            "input_tokens": sum(int(item["usage"].get("prompt_tokens", 0)) for item in subset),
            "output_tokens": sum(int(item["usage"].get("completion_tokens", 0)) for item in subset),
        }
    report = {"format": "ego.ir-benchmark.v1", "model": {key: profile.get(key) for key in ("id", "provider", "model")}, "mock_oracle": mock_oracle, "repeats": repeats, "summary": summary, "records": records, "created_at": time.time()}
    output = ROOT / ".egoagent" / "research" / f"ir-benchmark-{time.strftime('%Y%m%d-%H%M%S')}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["path"] = str(output)
    return report


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", default="evolver")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--mock-oracle", action="store_true", help="Validate benchmark infrastructure without claiming model performance")
    parser.add_argument("--representations", nargs="*", choices=REPRESENTATIONS, default=list(REPRESENTATIONS))
    args = parser.parse_args()
    print(json.dumps(run_benchmark(role=args.role, repeats=args.repeats, mock_oracle=args.mock_oracle, representations=tuple(args.representations)), ensure_ascii=False, indent=2))
