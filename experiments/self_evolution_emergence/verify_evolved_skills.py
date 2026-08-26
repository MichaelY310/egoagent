"""Reload model-generated Skills on unseen batches and verify real execution.

The emergence runner removes probe Identities after each case. Its report keeps
the exact successful ``create_tool`` arguments, so this verifier restores that
artifact into a fresh probe Identity, reloads the Agent, and explicitly asks it
to use the installed reusable capability on unseen data. This second phase is
an invocation test, not an additional emergence claim.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from experiments.self_evolution_emergence.run_deepseek_emergence import (  # noqa: E402
    RUN_ROOT,
    _clone_identity,
    _safe_remove,
    _summarize,
    _wait,
)
from task_bench.engine import TaskBenchManager  # noqa: E402


def _latest_report() -> Path:
    candidates = sorted(RUN_ROOT.glob("20*/report.json"), key=lambda path: path.stat().st_mtime)
    if not candidates:
        raise FileNotFoundError("no emergence report found")
    return candidates[-1]


def _successful_tool(case: dict) -> dict:
    for event in reversed(case.get("evolution_events", [])):
        data = event.get("data", {})
        if data.get("tool") != "create_tool":
            continue
        result = str(data.get("result", ""))
        arguments = data.get("arguments")
        if isinstance(arguments, dict) and result.startswith("✅ Tool"):
            return dict(arguments)
    raise ValueError(f"case {case.get('task_id')} has no successful create_tool artifact")


def _install_generated_tool(identity_name: str, arguments: dict) -> str:
    path = PROJECT_ROOT / "identity" / "dante" / "ego" / "skills" / "create_tool" / "scripts" / "create_tool.py"
    spec = importlib.util.spec_from_file_location("emergence_create_tool", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    payload = dict(arguments)
    payload["identity_name"] = identity_name
    result = str(module.create_tool(**payload))
    if not result.startswith("✅ Tool"):
        raise RuntimeError(result)
    return str(payload["tool_name"])


def _followup_spec(source_task: str, tool_name: str) -> dict:
    common = {
        "version": "ego.task.v1",
        "id": f"reuse_{source_task}",
        "title": f"Reuse {source_task}",
        "description": "Second-batch execution test for a model-generated Skill.",
        "category": "self-evolution-verification",
        "difficulty": "research",
        "selection": {"recommended_harness": "react_single"},
        "environment": {"backend": "local", "network": "disabled"},
        "execution": {"timeout_seconds": 300},
        "evolution": {"allowed": False},
    }
    if source_task == "latent_paper_recall":
        common.update({
            "prompt": "这是上一阶段之后的全新资料批次。请明确调用你已安装的可复用 Skill（不要重新用通用 grep/read 重演检索轨迹），然后回答：基准代号、上下文开销下降百分比、校验词，并引用文件。",
            "workspace": {"files": {
                "library/new_benchmark.md": "The new retrieval benchmark is NEBULA-4.",
                "library/new_compaction.txt": "Compact evidence reduced parent context overhead by 44%.",
                "library/new_protocol.md": "The verification checksum word for this batch is COBALT.",
                "library/noise.txt": "Unrelated greenhouse observation.",
            }},
            "evaluation": {"pass_score": 1, "checks": [
                {"type": "tool_called", "name": tool_name, "weight": 2},
                {"type": "response_contains", "value": "NEBULA-4"},
                {"type": "response_contains", "value": "44%"},
                {"type": "response_contains", "value": "COBALT"},
            ]},
        })
    elif source_task == "latent_delegated_search":
        common.update({
            "prompt": "这是新的事故批次。请明确调用上一阶段安装的可复用 Skill（不要逐个通用 read/search），输出根因、缓解措施和相对证据路径。",
            "workspace": {"files": {
                "incidents/delta.log": "root_cause=RC-101\nmitigation=renew the coordinator lease\n",
                "incidents/epsilon.log": "root_cause=RC-202\nmitigation=cap retry fanout at four\n",
                "incidents/README.md": "delta.log and epsilon.log are authoritative.",
                "incidents/noise.log": "RC-000 is only an example.",
            }},
            "evaluation": {"pass_score": 1, "checks": [
                {"type": "tool_called", "name": tool_name, "weight": 2},
                {"type": "response_contains", "value": "RC-101"},
                {"type": "response_contains", "value": "RC-202"},
            ]},
        })
    elif source_task == "latent_skill_extraction":
        common.update({
            "prompt": "这是新的事件批次。请明确调用上一阶段安装的可复用 Skill 来生成 out/events.json；不要手工逐条改写。完成后简短报告。",
            "workspace": {"files": {
                "inbox/events.txt": "id=EV-10 | sev=medium | owner=li\nid=EV-3|severity=high|owner=\n",
            }},
            "evaluation": {"pass_score": 1, "checks": [
                {"type": "tool_called", "name": tool_name, "weight": 2},
                {"type": "json_equals", "path": "out/events.json", "pointer": "/0/id", "expected": "EV-3"},
                {"type": "json_equals", "path": "out/events.json", "pointer": "/0/owner", "expected": "unassigned"},
                {"type": "json_equals", "path": "out/events.json", "pointer": "/1/severity", "expected": "MEDIUM"},
            ]},
        })
    else:
        raise ValueError(source_task)
    return common


def _verify_case(case: dict, destination: Path, index: int) -> dict:
    source_task = str(case["task_id"])
    identity_name = f"deepseek_probe_reuse_{destination.name}_{index}"
    identity_dir = _clone_identity(identity_name)
    allowed = {identity_name}
    try:
        arguments = _successful_tool(case)
        tool_name = _install_generated_tool(identity_name, arguments)
        task_dir = destination / "tasks" / source_task
        task_dir.mkdir(parents=True, exist_ok=False)
        spec = _followup_spec(source_task, tool_name)
        (task_dir / f"{spec['id']}.json").write_text(
            json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        before_skills = {path.name for path in (identity_dir / "ego" / "skills").iterdir() if path.is_dir()}
        manager = TaskBenchManager(PROJECT_ROOT, task_dir=task_dir, runs_dir=destination / "task_runs")
        created = manager.start({
            "task_id": spec["id"], "harness": "react_single", "identity": identity_name,
        })
        state = _wait(manager, created["id"])
        summary = _summarize(state, before_skills, identity_dir)
        summary.update({
            "source_task": source_task,
            "restored_tool": tool_name,
            "restored_from_run": case.get("run_id"),
            "forced_reuse_instruction": True,
        })
        return summary
    finally:
        _safe_remove(PROJECT_ROOT / "identity" / identity_name, allowed)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", nargs="?", type=Path)
    args = parser.parse_args()
    source_path = (args.report or _latest_report()).resolve()
    source = json.loads(source_path.read_text(encoding="utf-8"))
    stamp = time.strftime("reuse_%Y%m%d_%H%M%S")
    destination = RUN_ROOT / stamp
    destination.mkdir(parents=True, exist_ok=False)
    report = {
        "version": 1,
        "source_report": str(source_path),
        "method": "Restore exact model-generated create_tool artifact, reload a fresh Agent, explicitly require reuse on unseen data.",
        "cases": [],
    }
    for index, case in enumerate(source.get("cases", []), start=1):
        print(f"[{index}/{len(source.get('cases', []))}] reuse {case.get('task_id')}", flush=True)
        try:
            report["cases"].append(_verify_case(case, destination, index))
        except Exception as error:
            report["cases"].append({"source_task": case.get("task_id"), "status": "runner_error", "error": str(error)})
    path = destination / "reuse_report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(path, flush=True)
    return 0 if all(item.get("status") == "passed" for item in report["cases"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
