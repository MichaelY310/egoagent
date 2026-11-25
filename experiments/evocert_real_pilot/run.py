"""Run the preregistered real-task EvoCert coalition pilot.

The evolver sees one validation trajectory and public tool help.  It then
materializes all coalitions of an Identity prompt update (I), a Knowledge
artifact (K), and a Flow preflight update (F).  Held-out and protected tasks
are evaluated only after authoring, in fresh workspaces, by Harness-Bench
Fast's original verifiers.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import itertools
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT_ROOT = Path(__file__).resolve().parent
RUN_ROOT = EXPERIMENT_ROOT / "_runs"
EXTERNAL_ROOT = ROOT / "experiments" / "external" / "harness-bench-fast"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(EXTERNAL_ROOT) not in sys.path:
    sys.path.insert(0, str(EXTERNAL_ROOT))

from experiments.evocert_real_pilot.analyze import (  # noqa: E402
    COMPONENTS,
    VARIANTS,
    analyze_report,
    canonical_variant,
)
from experiments.real_layer_evolution.run_harnessbench_pilot import (  # noqa: E402
    Family,
    _external_task,
    _safe_text,
    _task_spec,
    _tool_trace,
    _wait,
    author_protocol,
)
from task_bench.engine import TaskBenchManager  # noqa: E402


FORMAT = "ego.evocert-real-pilot.v1"
GENERATED_PREFIX = "realbench_evocert_"
BENCHMARK_COMMIT = "e63712131fbb9cbd584df5e2012e06618a88de5e"
PROTECTED_TASKS = (
    "task_385_cli_sort_multikey",
    "task_388_cli_grep_uniq_ranking",
)
FAMILIES = {
    "logq": Family(
        "logq",
        "task_372_cli_logq_percentile_window",
        "task_373_cli_logq_mean_by_component",
        "logq",
    ),
    "pktool": Family(
        "pktool",
        "task_374_cli_pktool_filter_decode",
        "task_375_cli_pktool_stats_corrupt",
        "pktool",
    ),
    "xtab": Family(
        "xtab",
        "task_376_cli_xtab_column_share",
        "task_377_cli_xtab_mean_pivot",
        "xtab",
    ),
    "cfgctl": Family(
        "cfgctl",
        "task_378_cli_cfgctl_layered_merge",
        "task_379_cli_cfgctl_diff_changed",
        "cfgctl",
    ),
}


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _tree_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file()) if path.exists() else 0


def _resource_gate() -> dict[str, Any]:
    max_gb = float(os.environ.get("EGO_EVOCERT_MAX_RUN_GB", "20"))
    min_free_gb = float(os.environ.get("EGO_EVOCERT_MIN_FREE_GB", "5"))
    usage = shutil.disk_usage(RUN_ROOT.parent)
    run_bytes = _tree_bytes(RUN_ROOT)
    report = {
        "run_gb": run_bytes / (1024 ** 3),
        "free_gb": usage.free / (1024 ** 3),
        "max_run_gb": max_gb,
        "min_free_gb": min_free_gb,
    }
    if report["run_gb"] > max_gb:
        raise RuntimeError(f"experiment directory exceeded {max_gb:g} GB")
    if report["free_gb"] < min_free_gb:
        raise RuntimeError(f"filesystem free space fell below {min_free_gb:g} GB")
    return report


def _candidate_name(stamp: str, family: Family, variant: str, kind: str) -> str:
    return f"{GENERATED_PREFIX}{stamp}_{family.name}_{variant.lower()}_{kind}"


def _clone_identity(stamp: str, family: Family, variant: str, protocol: dict[str, Any]) -> Path:
    name = _candidate_name(stamp, family, variant, "identity")
    target = RUN_ROOT / stamp / "materialized" / "identities" / name
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(ROOT / "identity" / "coder", target)
    identity_path = target / "id.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    identity["name"] = name
    identity["description"] = str(identity.get("description", ""))
    identity.setdefault("evolution_lineage", {})
    identity["evolution_lineage"].update(
        {
            "experiment": FORMAT,
            "source_task": family.validation_task,
            "variant": variant,
            "artifacts": list(variant) if variant != "none" else [],
        }
    )
    if "I" in variant:
        procedure = " ".join(str(item) for item in protocol.get("procedure") or [])
        failures = " ".join(str(item) for item in protocol.get("failure_modes") or [])
        identity["description"] += (
            " For unfamiliar command-line tools, inspect their public help before acting, "
            "derive a short execution plan, write the requested artifact, and verify it once. "
            f"Validation-derived procedure: {procedure} Common failure modes: {failures}"
        )
    _write_json(identity_path, identity)
    if "K" in variant:
        _materialize_knowledge(target, family, protocol)
    return target


def _materialize_knowledge(identity_dir: Path, family: Family, protocol: dict[str, Any]) -> None:
    name = f"{family.tool}_operation_protocol"
    target = identity_dir / "ego" / "knowledge" / name
    target.mkdir(parents=True, exist_ok=False)
    metadata = {
        "type": "knowledge",
        "name": name,
        "title": protocol["title"],
        "description": protocol["description"],
        "provenance": {
            "source": "validation_task_and_public_tool_help",
            "source_task": family.validation_task,
            "tool_help_sha256": protocol["authoring_metadata"]["tool_help_sha256"],
        },
    }
    body = (
        f"# {protocol['title']}\n\n{protocol['knowledge']}\n\n## Procedure\n"
        + "\n".join(f"{index}. {step}" for index, step in enumerate(protocol["procedure"], 1))
        + "\n\n## Failure modes\n"
        + "\n".join(f"- {item}" for item in protocol["failure_modes"])
        + "\n"
    )
    _write_json(target / "meta.json", metadata)
    (target / f"{name}.txt").write_text(body, encoding="utf-8")


def _materialize_flow(stamp: str, family: Family, protocol: dict[str, Any]) -> Path:
    name = _candidate_name(stamp, family, "shared", "flow")
    target = RUN_ROOT / stamp / "materialized" / "harnesses" / name
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    preflight_source = (
        "import pathlib,subprocess,sys; "
        "p=pathlib.Path(sys.argv[1]); "
        "r=subprocess.run([sys.executable,str(p),'--help'],capture_output=True,text=True,"
        "encoding='utf-8',errors='replace',timeout=30) if p.is_file() else None; "
        "print(((r.stdout or r.stderr)[:24000]) if r else 'family tool absent; preflight is a no-op'); "
        "raise SystemExit(r.returncode if r else 0)"
    )
    graph = {
        "name": name,
        "description": "Answer-free family tool preflight followed by the unchanged coding loop.",
        "slots": {"coder": {"description": "Task executor", "required": True}},
        "return_mode": "last",
        "evolution_lineage": {
            "experiment": FORMAT,
            "source_task": family.validation_task,
            "artifact": "F",
        },
        "pipeline": {
            "start": "input",
            "max_steps": 20,
            "max_node_steps": 90,
            "timeout_seconds": 900,
            "workspace_preview": True,
            "budget": {"max_model_calls": 18, "max_tool_calls": 48, "max_tokens": 180000},
            "context": {"request": "", "preflight": ""},
            "nodes": {
                "input": {
                    "id": "input",
                    "op": "输入",
                    "outputs": {"text": "request"},
                    "edges": [{"condition": "input", "to": "preflight"}],
                },
                "preflight": {
                    "id": "preflight",
                    "op": "进程",
                    "command": sys.executable,
                    "args": ["-c", preflight_source, f"tools/{family.tool}"],
                    "cwd": "$ctx.task.workspace",
                    "inputs": {"cwd": "$ctx.task.workspace"},
                    "max_output_chars": 26_000,
                    "timeout_seconds": 40,
                    "output_var": "preflight",
                    "edges": [{"condition": "process_succeeded", "to": "act"}],
                },
                "act": {
                    "id": "act",
                    "op": "Agent",
                    "agent": "coder",
                    "tools": "all",
                    "inputs": {
                        "instructions": (
                            str(protocol["harness_preflight"])
                            + "\nPublic preflight output:\n${ctx.preflight.stdout}\nTask: ${ctx.request}"
                        )
                    },
                    "timeout_seconds": 180,
                    "retry": {"max_attempts": 2, "delay_seconds": 1},
                    "edges": [
                        {"condition": "has_tool_calls", "to": "tools"},
                        {"condition": "has_text", "to": "output"},
                    ],
                },
                "tools": {
                    "id": "tools",
                    "op": "工具",
                    "agent": "coder",
                    "parallel": False,
                    "stuck_threshold": 3,
                    "edges": [
                        {"condition": "tools_executed", "to": "act"},
                        {"condition": "stuck", "to": "act"},
                    ],
                },
                "output": {
                    "id": "output",
                    "op": "结束",
                    "inputs": {"value": "$node.act.text"},
                    "record": True,
                    "edges": [],
                },
            },
        },
    }
    _write_json(target / "config.json", graph)
    return target


def _install_tree(source: Path, parent: Path) -> Path:
    destination = parent / source.name
    if destination.exists():
        if not destination.name.startswith(GENERATED_PREFIX):
            raise RuntimeError(f"refusing to replace non-experiment path: {destination}")
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    return destination


def _remove_installed(path: Path, parent: Path) -> None:
    resolved = path.resolve()
    if resolved.parent != parent.resolve() or not resolved.name.startswith(GENERATED_PREFIX):
        raise RuntimeError(f"refusing cleanup outside experiment namespace: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)


def _assert_no_sealed_leak(family: Family, protocol: dict[str, Any]) -> None:
    serialized = json.dumps(protocol, ensure_ascii=False)
    sealed_tasks = [_external_task(family.heldout_task)] + [_external_task(item) for item in PROTECTED_TASKS]
    forbidden = [value for task in sealed_tasks for value in (task.id, task.prompt) if value]
    if any(value in serialized for value in forbidden):
        raise RuntimeError("authored protocol contains held-out/protected content")


def _run_task(
    task_id: str,
    *,
    identity: str,
    harness: str,
    variant: str,
    family: Family,
    protocol: dict[str, Any],
    task_dir: Path,
    runs_dir: Path,
) -> dict[str, Any]:
    _resource_gate()
    external = _external_task(task_id)
    _task_spec(external, task_dir)
    manager = TaskBenchManager(ROOT, task_dir=task_dir, runs_dir=runs_dir)
    started = time.monotonic()
    created = manager.start(
        {"task_id": task_id, "identity": identity, "harness": harness, "debug_mode": "auto"}
    )
    state = _wait(manager, created["id"])
    verifier = external.verify(Path(state["workspace"]))
    stats = dict(state.get("stats") or {})
    tokens = int(stats.get("tokens_actual", 0) or 0)
    if not tokens:
        tokens = int(stats.get("input_tokens_actual", 0) or 0) + int(
            stats.get("output_tokens_actual", 0) or 0
        )
    if not tokens:
        tokens = int(stats.get("tokens_estimated", 0) or 0)
    terminal_ok = state.get("status") not in {"timeout", "error", "stopped"} and not state.get("error")
    passed = bool(verifier.passed and terminal_ok)
    traces = copy.deepcopy(state.get("node_traces") or [])
    trace_text = json.dumps(traces, ensure_ascii=False, default=str)
    knowledge_marker = f"{family.tool}_operation_protocol"
    activation = {
        "I": "I" in variant,
        "K": "K" in variant and (
            knowledge_marker in trace_text or str(protocol.get("title", "")) in trace_text
        ),
        "F": "F" in variant and any(trace.get("node_id") == "preflight" for trace in traces),
    }
    return {
        "task_id": task_id,
        "run_id": state.get("id"),
        "status": state.get("status"),
        "runtime_error": state.get("error"),
        "success": 1.0 if passed else 0.0,
        "verifier": {
            "passed": verifier.passed,
            "runtime_terminal_ok": terminal_ok,
            "message": _safe_text(verifier.message, 4_000),
        },
        "stats": stats,
        "tokens": tokens,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "workspace": str(state["workspace"]),
        "tools": _tool_trace(state),
        "node_ids": [trace.get("node_id") for trace in traces],
        "activation": activation,
        "artifacts": state.get("artifacts", []),
    }


def _find_row(rows: list[dict[str, Any]], split: str, task_id: str, repetition: int) -> dict[str, Any]:
    existing = next(
        (
            row
            for row in rows
            if row.get("split") == split
            and row.get("task_id") == task_id
            and int(row.get("repetition", 0)) == repetition
        ),
        None,
    )
    if existing is not None:
        return existing
    row = {"split": split, "task_id": task_id, "repetition": repetition}
    rows.append(row)
    return row


def _materialize_candidates(
    stamp: str, family: Family, protocol: dict[str, Any]
) -> tuple[dict[str, dict[str, str]], list[tuple[Path, Path]]]:
    flow_source = _materialize_flow(stamp, family, protocol)
    flow_installed = _install_tree(flow_source, ROOT / "harness")
    installed: list[tuple[Path, Path]] = [(flow_installed, ROOT / "harness")]
    candidates: dict[str, dict[str, str]] = {}
    for variant in VARIANTS:
        identity_source = _clone_identity(stamp, family, variant, protocol)
        identity_installed = _install_tree(identity_source, ROOT / "identity")
        installed.append((identity_installed, ROOT / "identity"))
        candidates[variant] = {
            "identity": identity_installed.name,
            "harness": flow_installed.name if "F" in variant else "bounded_coder_worker",
        }
    return candidates, installed


def _author_or_load(
    stamp: str,
    family: Family,
    family_root: Path,
    task_dir: Path,
    runs_dir: Path,
    resume: bool,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    protocol_path = family_root / "protocol.json"
    if resume and protocol_path.is_file():
        protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
        _assert_no_sealed_leak(family, protocol)
        return protocol, None

    bootstrap_name = _candidate_name(stamp, family, "authoring", "identity")
    source = RUN_ROOT / stamp / "materialized" / "identities" / bootstrap_name
    if source.exists():
        shutil.rmtree(source)
    shutil.copytree(ROOT / "identity" / "coder", source)
    identity = json.loads((source / "id.json").read_text(encoding="utf-8"))
    identity["name"] = bootstrap_name
    _write_json(source / "id.json", identity)
    installed = _install_tree(source, ROOT / "identity")
    try:
        baseline = _run_task(
            family.validation_task,
            identity=installed.name,
            harness="bounded_coder_worker",
            variant="none",
            family=family,
            protocol={"title": ""},
            task_dir=task_dir,
            runs_dir=runs_dir,
        )
        protocol = author_protocol(family, baseline)
        _assert_no_sealed_leak(family, protocol)
        _write_json(protocol_path, protocol)
        return protocol, baseline
    finally:
        _remove_installed(installed, ROOT / "identity")


def run_family(stamp: str, family: Family, repetitions: int, resume: bool) -> dict[str, Any]:
    family_root = RUN_ROOT / stamp / family.name
    task_dir = family_root / "task_specs"
    runs_dir = family_root / "task_runs"
    partial_path = family_root / "partial.json"
    task_dir.mkdir(parents=True, exist_ok=True)
    runs_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    if resume and partial_path.is_file():
        rows = list(json.loads(partial_path.read_text(encoding="utf-8")).get("rows") or [])

    protocol, baseline = _author_or_load(
        stamp, family, family_root, task_dir, runs_dir, resume
    )
    candidates, installed = _materialize_candidates(stamp, family, protocol)
    try:
        task_splits = (
            ("validation", family.validation_task),
            ("heldout", family.heldout_task),
            *(("protected", task_id) for task_id in PROTECTED_TASKS),
        )
        for repetition in range(1, repetitions + 1):
            for split, task_id in task_splits:
                row = _find_row(rows, split, task_id, repetition)
                for variant in VARIANTS:
                    if isinstance(row.get(variant), dict):
                        print(f"[{family.name}] {split} r{repetition} {variant}: resume", flush=True)
                        continue
                    print(f"[{family.name}] {split} r{repetition} {variant}: {task_id}", flush=True)
                    candidate = candidates[variant]
                    row[variant] = _run_task(
                        task_id,
                        identity=candidate["identity"],
                        harness=candidate["harness"],
                        variant=variant,
                        family=family,
                        protocol=protocol,
                        task_dir=task_dir,
                        runs_dir=runs_dir,
                    )
                    _write_json(partial_path, {"rows": rows, "resource": _resource_gate()})
    finally:
        for path, parent in reversed(installed):
            _remove_installed(path, parent)

    result = {
        "family": family.name,
        "validation_task": family.validation_task,
        "heldout_task": family.heldout_task,
        "protected_tasks": list(PROTECTED_TASKS),
        "protocol": protocol,
        "bootstrap_validation": baseline,
        "rows": rows,
    }
    _write_json(family_root / "result.json", result)
    return result


def _benchmark_revision() -> str:
    head = EXTERNAL_ROOT / ".git" / "HEAD"
    if not head.exists():
        return "unknown"
    import subprocess

    completed = subprocess.run(
        ["git", "-C", str(EXTERNAL_ROOT), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    return completed.stdout.strip() or "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--families", nargs="+", choices=sorted(FAMILIES), default=list(FAMILIES))
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--stamp", default=time.strftime("%Y%m%d_%H%M%S"))
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.repetitions <= 2:
        raise SystemExit("--repetitions must be 1 or 2 under the preregistered budget")
    if not (EXTERNAL_ROOT / "harness_bench" / "tasks.py").is_file():
        raise SystemExit(
            "Harness-Bench Fast is missing at experiments/external/harness-bench-fast"
        )
    revision = _benchmark_revision()
    if revision != BENCHMARK_COMMIT:
        raise SystemExit(
            f"benchmark revision mismatch: expected {BENCHMARK_COMMIT}, got {revision}"
        )
    _resource_gate()
    report_path = RUN_ROOT / args.stamp / "report.json"
    report: dict[str, Any]
    if args.resume and report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
    else:
        report = {
            "format": FORMAT,
            "stamp": args.stamp,
            "started_at": time.time(),
            "preregistration": "docs/EVOCERT_REAL_PILOT_PREREGISTRATION_20260902.md",
            "benchmark": {
                "name": "Harness-Bench Fast",
                "repository": "https://github.com/ai-forever/harness-bench-fast",
                "commit": revision,
                "license": "MIT",
            },
            "model": {
                "base_url_sha256": hashlib.sha256(
                    os.environ.get("EGOAGENT_LLM_BASE_URL", "").encode("utf-8")
                ).hexdigest(),
                "name": os.environ.get("EGOAGENT_LLM_MODEL", ""),
                "temperature": os.environ.get("EGOAGENT_LLM_TEMPERATURE", ""),
            },
            "protocol": {
                "components": list(COMPONENTS),
                "variants": list(VARIANTS),
                "repetitions": args.repetitions,
                "fresh_workspace_per_cell": True,
                "heldout_hidden_from_authoring": True,
                "protected_hidden_from_authoring": True,
                "original_verifier": True,
            },
            "families": [],
            "resource_start": _resource_gate(),
        }
    by_name = {item.get("family"): item for item in report.get("families") or []}
    for name in args.families:
        result = run_family(args.stamp, FAMILIES[name], args.repetitions, args.resume)
        by_name[name] = result
        report["families"] = [by_name[key] for key in args.families if key in by_name]
        report["resource_latest"] = _resource_gate()
        _write_json(report_path, report)
    report["completed_at"] = time.time()
    analysis = analyze_report(report)
    _write_json(report_path.with_name("analysis.json"), analysis)
    _write_json(report_path, report)
    print(json.dumps(analysis["quality_gate"], ensure_ascii=False, indent=2), flush=True)
    print(report_path, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
