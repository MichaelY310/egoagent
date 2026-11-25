from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"


def _load_run(reference: str | dict[str, Any]) -> tuple[dict[str, Any], Path]:
    selector = reference if isinstance(reference, dict) else {"run": reference}
    directory = str(selector.get("run") or "")
    path = RESULTS / directory / "report.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    runs = report.get("runs") or []
    if selector.get("flow"):
        runs = [run for run in runs if run.get("flow") == selector["flow"]]
    if selector.get("task"):
        runs = [run for run in runs if run.get("task_id") == selector["task"]]
    if len(runs) != 1:
        raise ValueError(f"Expected exactly one selected run in {path}, found {len(runs)}")
    return runs[0], path


def _metrics(run: dict[str, Any], path: Path) -> dict[str, Any]:
    stats = run.get("stats") or {}
    tools = (run.get("tool_calls") or {}).get("counts") or {}
    context_modes = Counter()
    context_saved = 0
    for event in run.get("context_events") or []:
        data = event.get("data") or {}
        context_modes[str(data.get("mode") or event.get("type") or "unknown")] += 1
        context_saved += int(data.get("saved_tokens_estimated") or 0)
    actual_input = int(stats.get("input_tokens_actual") or 0)
    cached_input = int(stats.get("cached_input_tokens_actual") or 0)
    autonomous = (run.get("delegation") or {}).get("autonomous_subagents") or {}
    return {
        "report": str(path.relative_to(HERE.parent.parent)).replace("\\", "/"),
        "run_id": run.get("run_id"),
        "task": run.get("task_id"),
        "flow": run.get("flow"),
        "flow_version": run.get("flow_version"),
        "status": run.get("status"),
        "score": float(run.get("score") or 0),
        "steps_passed": sum(1 for step in run.get("steps") or [] if step.get("status") == "passed"),
        "steps_total": len(run.get("steps") or []),
        "model_calls": int(stats.get("model_calls") or 0),
        "tool_calls": int(stats.get("tool_calls") or 0),
        "tokens_actual": int(stats.get("tokens_actual") or 0),
        "input_tokens_actual": actual_input,
        "cached_input_tokens_actual": cached_input,
        "uncached_input_tokens_actual": max(0, actual_input - cached_input),
        "output_tokens_actual": int(stats.get("output_tokens_actual") or 0),
        "elapsed_seconds": round(float(stats.get("elapsed_seconds") or 0), 3),
        "tool_counts": tools,
        "selected_node_counts": {
            name: count
            for name, count in (run.get("node_counts") or {}).items()
            if name in {
                "curate", "compact", "evolve", "recall", "remember", "delegate",
                "checkpoint_before", "checkpoint_after", "review_changes",
                "repeat_guard", "prune_tools",
            }
        },
        "context_modes": dict(context_modes),
        "context_saved_tokens_estimated": context_saved,
        "memory_events": int((run.get("event_counts") or {}).get("memory") or 0),
        "autonomous_subagents": autonomous,
        "evolution_events": len(run.get("evolution_events") or []),
        "mutations": len(run.get("mutations") or []),
    }


def _pct(treatment: float, baseline: float) -> float | None:
    if not baseline:
        return None
    return round((treatment - baseline) / baseline * 100.0, 1)


def _comparison(case: dict[str, Any]) -> dict[str, Any]:
    baseline_run, baseline_path = _load_run(case["baseline"])
    treatment_run, treatment_path = _load_run(case["treatment"])
    baseline = _metrics(baseline_run, baseline_path)
    treatment = _metrics(treatment_run, treatment_path)
    return {
        **case,
        "baseline_metrics": baseline,
        "treatment_metrics": treatment,
        "delta_percent": {
            key: _pct(float(treatment[key]), float(baseline[key]))
            for key in ("tokens_actual", "uncached_input_tokens_actual", "model_calls", "tool_calls", "elapsed_seconds")
        },
        "score_delta": round(treatment["score"] - baseline["score"], 4),
    }


def _fmt_delta(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.1f}%"


def _run_cell(item: dict[str, Any]) -> str:
    return (
        f"{item['score']:.2f} ({item['steps_passed']}/{item['steps_total']}) · "
        f"{item['tokens_actual']:,} tok · {item['tool_calls']} tools · {item['elapsed_seconds']:.1f}s"
    )


def _render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# EgoAgent Product Code Agent 验收 Campaign",
        "",
        f"> 生成时间：{summary['generated_at']}  ",
        "> 所有数字直接读取原始 `report.json`；模型输出具有随机性，单次结果只作为工程验收证据，不冒充统计显著性结论。",
        "",
        "## 控制变量对比",
        "",
        "| 实验 | Baseline | Treatment | Token Δ | 未缓存输入 Δ | Tool Δ | 结论 |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for case in summary["comparisons"]:
        delta = case["delta_percent"]
        lines.append(
            f"| {case['title']} | {_run_cell(case['baseline_metrics'])} | {_run_cell(case['treatment_metrics'])} | "
            f"{_fmt_delta(delta['tokens_actual'])} | {_fmt_delta(delta['uncached_input_tokens_actual'])} | "
            f"{_fmt_delta(delta['tool_calls'])} | {case['interpretation']} |"
        )
    lines.extend(["", "## 单项完整验收", ""])
    for item in summary["standalone"]:
        metrics = item["metrics"]
        lines.extend([
            f"### {item['title']}",
            "",
            f"- 结果：`{metrics['status']}`，score `{metrics['score']:.2f}`，步骤 `{metrics['steps_passed']}/{metrics['steps_total']}`。",
            f"- Flow：`{metrics['flow']}@{metrics['flow_version']}`。",
            f"- 用量：{metrics['tokens_actual']:,} actual tokens，{metrics['model_calls']} 次模型调用，{metrics['tool_calls']} 次工具调用，{metrics['elapsed_seconds']:.1f}s。",
            f"- 节点证据：`{json.dumps(metrics['selected_node_counts'], ensure_ascii=False)}`。",
            f"- 解释：{item['interpretation']}",
            f"- 原始报告：`{metrics['report']}`",
            "",
        ])
    lines.extend([
        "## 已验证的产品判断",
        "",
        "1. 自进化不是免费优化：学习阶段更贵；价值要通过后续 fresh-session 复用衡量。",
        "2. 经过验证的 Skill 可以在同 Session 热加载，也可以跨 Session 被发现并直接调用。",
        "3. 被动、低频、由 token 压力触发的压缩能降低 working context 与本组总 token；供应商未缓存输入存在方差，频繁主动重写历史则明确伤害前缀缓存。",
        "4. 持久记忆可以跨全新轨迹恢复未写入项目文件的事实；无记忆对照不会凭空恢复它。",
        "5. 子 Agent 的确定性价值是隔离上下文与文件范围；小规模任务上不保证减少总 token。",
        "6. 动态 Skill 写文件也进入统一 edit transaction，可在 IDE 中逐 hunk 审阅。",
        "7. 超长工具 observation 的头尾裁剪可显著降低后续模型输入；完整 observation 仍只在 lossless trajectory 中保留一份。",
        "8. Full Flow 对小型一次性修复有固定开销，产品应通过 Router 选择 Core 或 Full，而不是永远启用所有能力。",
        "",
        "## 复现",
        "",
        "```powershell",
        ".\\.venv\\Scripts\\python.exe experiments\\product_code_agent_acceptance\\run_matrix.py --tasks <task_id> --flows <flow_id> --identity adaptive_deepseek_coder --label <label>",
        ".\\.venv\\Scripts\\python.exe experiments\\product_code_agent_acceptance\\summarize_campaign.py",
        "```",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=HERE / "campaign_cases.json")
    parser.add_argument("--output-stem", type=Path, default=RESULTS / "CAMPAIGN_REPORT_20260904")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    summary = {
        "schema": manifest["schema"],
        "campaign_id": manifest["campaign_id"],
        "title": manifest["title"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "comparisons": [_comparison(case) for case in manifest["comparisons"]],
        "standalone": [],
    }
    for item in manifest.get("standalone") or []:
        run, path = _load_run(item["run"])
        summary["standalone"].append({**item, "metrics": _metrics(run, path)})
    args.output_stem.parent.mkdir(parents=True, exist_ok=True)
    args.output_stem.with_suffix(".json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.output_stem.with_suffix(".md").write_text(_render_markdown(summary), encoding="utf-8")
    print(args.output_stem.with_suffix(".md"))


if __name__ == "__main__":
    main()
