"""Machine-check the product claims made by the acceptance campaign.

This script deliberately verifies observable runtime evidence rather than
trusting prose emitted by a model.  It never performs network calls.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable
import xml.etree.ElementTree as ET


HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
OUTPUT = RESULTS / "PROOF_REPORT_20260904"


def load(directory: str, flow: str | None = None) -> dict[str, Any]:
    report = json.loads((RESULTS / directory / "report.json").read_text(encoding="utf-8"))
    runs = report.get("runs") or []
    if flow:
        runs = [run for run in runs if run.get("flow") == flow]
    if len(runs) != 1:
        raise AssertionError(f"expected one run in {directory} for {flow or '*'}, found {len(runs)}")
    return runs[0]


def tokens(run: dict[str, Any]) -> int:
    return int((run.get("stats") or {}).get("tokens_actual") or 0)


def uncached(run: dict[str, Any]) -> int:
    stats = run.get("stats") or {}
    return max(0, int(stats.get("input_tokens_actual") or 0) - int(stats.get("cached_input_tokens_actual") or 0))


def tool_count(run: dict[str, Any], name: str) -> int:
    return int((((run.get("tool_calls") or {}).get("counts") or {}).get(name)) or 0)


def node_count(run: dict[str, Any], name: str) -> int:
    return int(((run.get("node_counts") or {}).get(name)) or 0)


def native_events(run: dict[str, Any], runtime_event: str | None = None) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for raw_path in (run.get("native_trajectory") or {}).get("files") or []:
        for line in Path(raw_path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            if runtime_event is None:
                events.append(event)
                continue
            data = event.get("data") or {}
            if event.get("type") == "runtime.event" and data.get("event") == runtime_event:
                events.append(event)
    return events


def payload(event: dict[str, Any]) -> dict[str, Any]:
    data = event.get("data") or {}
    value = data.get("payload") if isinstance(data.get("payload"), dict) else data
    return value if isinstance(value, dict) else {}


checks: list[dict[str, Any]] = []


def check(identifier: str, claim: str, evidence: dict[str, Any], assertion: Callable[[], bool]) -> None:
    passed = False
    error = None
    try:
        passed = bool(assertion())
    except Exception as exc:  # evidence report must include malformed-run failures
        error = f"{type(exc).__name__}: {exc}"
    checks.append({"id": identifier, "passed": passed, "claim": claim, "evidence": evidence, "error": error})


learning_control = load("20260904_062148_quasar_learning_control_r1")
learning_evolver = load("20260904_062444_quasar_learning_evolver_r1")
learning_reviews = (learning_evolver.get("native_trajectory") or {}).get("evolution_reviews") or []
check(
    "governed_evolution",
    "Repeated work creates, repairs, verifies and hot-loads one reusable Skill without changing task accuracy.",
    {
        "control_score": learning_control.get("score"), "treatment_score": learning_evolver.get("score"),
        "capability_added": (learning_evolver.get("mutations") or {}).get("capability_added"),
        "create_skill_calls": tool_count(learning_evolver, "create_skill"),
        "verify_calls": tool_count(learning_evolver, "verify_identity_skill"),
        "hot_loaded_calls": tool_count(learning_evolver, "normalize_quasar_release_v3"),
    },
    lambda: (
        learning_control.get("score") == learning_evolver.get("score") == 1.0
        and any("normalize_quasar_release_v3" in path for path in (learning_evolver.get("mutations") or {}).get("capability_added", []))
        and tool_count(learning_evolver, "create_skill") == 1
        and tool_count(learning_evolver, "verify_identity_skill") >= 2
        and tool_count(learning_evolver, "normalize_quasar_release_v3") >= 1
        and any(item.get("evolved") and (item.get("verification_decision") or {}).get("verified") for item in learning_reviews)
    ),
)

transfer_control = load("20260904_063733_quasar_transfer_control_r1")
transfer_reuse = load("20260904_065355_quasar_transfer_direct_reuse_r3")
check(
    "fresh_session_skill_transfer",
    "A later fresh Session discovers and directly calls the evolved Skill once per task with fewer total tokens and tools.",
    {
        "control_tokens": tokens(transfer_control), "reuse_tokens": tokens(transfer_reuse),
        "control_tools": (transfer_control.get("stats") or {}).get("tool_calls"),
        "reuse_tools": (transfer_reuse.get("stats") or {}).get("tool_calls"),
        "skill_calls": tool_count(transfer_reuse, "normalize_quasar_release_v3"),
    },
    lambda: (
        transfer_control.get("score") == transfer_reuse.get("score") == 1.0
        and tool_count(transfer_reuse, "normalize_quasar_release_v3") == 3
        and tokens(transfer_reuse) < tokens(transfer_control)
        and int((transfer_reuse.get("stats") or {}).get("tool_calls") or 0) < int((transfer_control.get("stats") or {}).get("tool_calls") or 0)
    ),
)

memory_off = load("20260904_083249_cross_session_memory_off_r1")
memory_on = load("20260904_083434_cross_session_memory_on_r1")
check(
    "cross_session_memory",
    "A fact never written to project files is recovered in a fresh trajectory only when durable memory is enabled.",
    {"off_score": memory_off.get("score"), "on_score": memory_on.get("score"), "recall_nodes": node_count(memory_on, "recall")},
    lambda: memory_off.get("score") == 0.5 and memory_on.get("score") == 1.0 and node_count(memory_on, "recall") == 2,
)

context_off = load("20260904_081438_context_endurance_25_off_r1")
context_on = load("20260904_101415_context_endurance_25_compact_dedup_r3")
saved = [
    event for event in (context_on.get("native_trajectory") or {}).get("context_changes") or []
    if int(event.get("saved_tokens_estimated") or 0) > 0
]
check(
    "passive_context_compaction",
    "Pressure-triggered compaction preserves all 25 answers while reducing total tokens and estimated working-context size; provider cache variance remains explicit.",
    {
        "off_tokens": tokens(context_off), "on_tokens": tokens(context_on),
        "off_uncached": uncached(context_off), "on_uncached": uncached(context_on), "saving_events": saved,
    },
    lambda: (
        context_off.get("score") == context_on.get("score") == 1.0
        and tokens(context_on) < tokens(context_off)
        and len(saved) == 1
    ),
)

curation_off = load("20260904_080421_context_endurance_off_r3")
curation_on = load("20260904_080522_context_endurance_on_r3")
check(
    "frequent_curation_negative_control",
    "Frequent proactive history rewrites are detected as a cost regression rather than reported as an improvement.",
    {"off_tokens": tokens(curation_off), "on_tokens": tokens(curation_on), "off_uncached": uncached(curation_off), "on_uncached": uncached(curation_on)},
    lambda: curation_off.get("score") == curation_on.get("score") == 1.0 and tokens(curation_on) > tokens(curation_off) and uncached(curation_on) > uncached(curation_off),
)

delegation_off = load("20260904_074152_large_delegation_off_r2")
delegation_on = load("20260904_074451_large_delegation_on_r1")
check(
    "isolated_subagent",
    "One autonomous bounded worker completes an independent package, while the campaign records that total cost increases at this size.",
    {"children": (delegation_on.get("delegation") or {}).get("autonomous_subagents"), "off_tokens": tokens(delegation_off), "on_tokens": tokens(delegation_on)},
    lambda: (
        delegation_off.get("score") == delegation_on.get("score") == 1.0
        and ((delegation_on.get("delegation") or {}).get("autonomous_subagents") or {}).get("product_bounded_code_worker") == 1
        and tokens(delegation_on) > tokens(delegation_off)
    ),
)

small_core = load("20260904_092723_current_small_task_router_ab_r1", "product_core_code_agent")
small_full = load("20260904_092723_current_small_task_router_ab_r1", "product_adaptive_code_agent")
check(
    "small_task_router_boundary",
    "For a one-shot repair where no advanced mechanism fires, Core is cheaper and faster than Full.",
    {"core_tokens": tokens(small_core), "full_tokens": tokens(small_full), "core_seconds": (small_core.get("stats") or {}).get("elapsed_seconds"), "full_seconds": (small_full.get("stats") or {}).get("elapsed_seconds")},
    lambda: small_core.get("score") == small_full.get("score") == 1.0 and tokens(small_core) < tokens(small_full) and float((small_core.get("stats") or {}).get("elapsed_seconds")) < float((small_full.get("stats") or {}).get("elapsed_seconds")),
)

prune_off = load("20260904_100353_tool_observation_control_dedup_verified_r2")
prune_on = load("20260904_100055_tool_observation_pruning_dedup_verified_r2")
prune_events = [
    event for event in native_events(prune_on, "conversation_applied")
    if payload(event).get("mode") == "tool_prune"
]
long_reads = [
    payload(event).get("result", "") for event in native_events(prune_on, "tool")
    if payload(event).get("name") == "read_file"
]
check(
    "lossless_tool_observation_pruning",
    "A large source read is retained once in the exact trajectory while the model-facing copy is pruned and task accuracy is preserved.",
    {
        "off_tokens": tokens(prune_off), "on_tokens": tokens(prune_on),
        "off_uncached": uncached(prune_off), "on_uncached": uncached(prune_on),
        "prune_nodes": node_count(prune_on, "prune"), "prune_events": len(prune_events),
        "largest_exact_read_chars": max((len(str(value)) for value in long_reads), default=0),
        "saving_events": [payload(event) for event in prune_events if int(payload(event).get("saved_tokens_estimated") or 0) > 0],
    },
    lambda: (
        prune_off.get("score") == prune_on.get("score") == 1.0
        and tokens(prune_on) < tokens(prune_off)
        and uncached(prune_on) < uncached(prune_off)
        and len(prune_events) == node_count(prune_on, "prune")
        and max((len(str(value)) for value in long_reads), default=0) > 40_000
        and sum(int(payload(event).get("saved_tokens_estimated") or 0) > 0 for event in prune_events) == 1
    ),
)

full = load("20260904_111926_full_v24_resilience_r1")
required_nodes = {"compact", "recall", "checkpoint_before", "repeat_guard", "prune_tools", "remember", "checkpoint_after", "review_changes", "evolve"}
check(
    "full_long_horizon_flow",
    "The six-stage release task passes while exercising every declared long-horizon governance family.",
    {"score": full.get("score"), "steps": full.get("steps"), "required_node_counts": {name: node_count(full, name) for name in sorted(required_nodes)}},
    lambda: full.get("score") == 1.0 and len(full.get("steps") or []) == 6 and all(node_count(full, name) > 0 for name in required_nodes),
)

v24 = load("20260904_105818_v24_repeat_guard_regression_r1")
v24_config = json.loads(
    (HERE.parent.parent / "harness" / "product_adaptive_code_agent" / "config.json").read_text(encoding="utf-8")
)
v24_nodes = v24_config["pipeline"]["nodes"]
check(
    "v24_repeat_guard_regression",
    "The production Flow delegates exact-repeat policy to its declared component, avoids false positives on a real repair, and preserves task accuracy.",
    {
        "score": v24.get("score"), "flow_version": v24.get("flow_version"),
        "thresholds": v24_nodes["repeat_guard"]["component_inputs"]["thresholds"],
        "runtime_reject_identical": v24_nodes["infer"].get("reject_identical_tool_call"),
        "real_run_reminders": int((v24.get("event_counts") or {}).get("loop_guard_reminder") or 0),
    },
    lambda: (
        v24.get("score") == 1.0
        and str(v24.get("flow_version") or "").startswith("v000024-")
        and v24_nodes["infer"].get("reject_identical_tool_call") is False
        and v24_nodes["repeat_guard"]["component_inputs"]["thresholds"] == [2, 3, 5]
        and int((v24.get("event_counts") or {}).get("loop_guard_reminder") or 0) == 0
    ),
)

resilience_path = RESULTS / "RESILIENCE_JUNIT_20260904.xml"
resilience_root = ET.parse(resilience_path).getroot()
resilience_cases = {
    case.get("name", ""): case
    for case in resilience_root.iter("testcase")
}
required_resilience = {
    "test_stopped_task_recovers_in_new_workspace_without_replaying_completed_write",
    "test_multistep_recovery_inherits_completed_step_scores",
    "test_shipped_flow_repeat_guard_is_reachable_and_model_visible",
}
check(
    "safe_recovery_and_repeat_fault_injection",
    "Stopped one- and multi-step Tasks resume in cloned workspaces without replaying completed work, and a deliberately looping model receives a visible repeat reminder.",
    {
        "junit": str(resilience_path.relative_to(HERE.parent.parent)).replace("\\", "/"),
        "tests": sorted(resilience_cases),
        "failures": len(list(resilience_root.iter("failure"))),
        "errors": len(list(resilience_root.iter("error"))),
    },
    lambda: (
        required_resilience <= set(resilience_cases)
        and not list(resilience_root.iter("failure"))
        and not list(resilience_root.iter("error"))
    ),
)

report = {
    "schema": "ego.product-code-proof.v1",
    "passed": all(item["passed"] for item in checks),
    "checks_passed": sum(item["passed"] for item in checks),
    "checks_total": len(checks),
    "checks": checks,
}
OUTPUT.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
markdown = [
    "# EgoAgent Product Campaign 机器证明", "",
    f"> 结果：**{report['checks_passed']}/{report['checks_total']}** proof checks passed。", "",
    "| Proof | 状态 | 可验证主张 |", "|---|---:|---|",
]
for item in checks:
    markdown.append(f"| `{item['id']}` | {'PASS' if item['passed'] else 'FAIL'} | {item['claim']} |")
markdown.extend(["", "完整结构化证据见同目录 `PROOF_REPORT_20260904.json`。", ""])
OUTPUT.with_suffix(".md").write_text("\n".join(markdown), encoding="utf-8")
print(OUTPUT.with_suffix(".md"))
raise SystemExit(0 if report["passed"] else 2)
