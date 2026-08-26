"""Run a budgeted real-task pilot for minimal-layer evolution.

The runner uses Harness-Bench Fast's original task setup and verifier while
executing DeepSeek V4 Flash through EgoAgent's real DAG runtime. Candidate
artifacts are authored from validation evidence only and then evaluated on a
fresh held-out task from the same tool family.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT_ROOT = Path(__file__).resolve().parent
EXTERNAL_ROOT = ROOT / "experiments" / "external" / "harness-bench-fast"
RUN_ROOT = EXPERIMENT_ROOT / "_runs"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(EXTERNAL_ROOT) not in sys.path:
    sys.path.insert(0, str(EXTERNAL_ROOT))

from llm.custom_llm import CustomLLM  # noqa: E402
from llm.env_config import load_local_env  # noqa: E402
from self_evolution.proof_evolution import (  # noqa: E402
    ARTIFACT_INTRUSION,
    select_empirical_evolution_artifact,
)
from task_bench.engine import TERMINAL_STATES, TaskBenchManager  # noqa: E402


load_local_env(ROOT)

LAYERS = ("knowledge", "skill", "harness")
CONTROL = "static"
GENERATED_PREFIX = "realbench_"
SECRET_PATTERN = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{10,}|(?:api[_-]?key|token|secret|password)\s*[:=]\s*[^\s,}]+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Family:
    name: str
    validation_task: str
    heldout_task: str
    tool: str


FAMILIES = {
    "logq": Family(
        name="logq",
        validation_task="task_372_cli_logq_percentile_window",
        heldout_task="task_373_cli_logq_mean_by_component",
        tool="logq",
    ),
    "cfgctl": Family(
        name="cfgctl",
        validation_task="task_378_cli_cfgctl_layered_merge",
        heldout_task="task_379_cli_cfgctl_diff_changed",
        tool="cfgctl",
    ),
}


def _require_external_benchmark() -> None:
    if not (EXTERNAL_ROOT / "harness_bench" / "tasks.py").is_file():
        raise RuntimeError(
            "Harness-Bench Fast is missing. Clone https://github.com/ai-forever/"
            "harness-bench-fast into experiments/external/harness-bench-fast"
        )


def _external_task(task_id: str):
    _require_external_benchmark()
    from harness_bench.tasks import get_task

    return get_task(task_id)


def _safe_text(value: str, limit: int = 20_000) -> str:
    return SECRET_PATTERN.sub("[REDACTED]", str(value or ""))[:limit]


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _clone_identity(source_name: str, target_name: str) -> Path:
    if not target_name.startswith(GENERATED_PREFIX):
        raise ValueError("generated identity must use the realbench_ prefix")
    source = ROOT / "identity" / source_name
    target = RUN_ROOT / "artifacts" / "identities" / target_name
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)
    id_path = target / "id.json"
    data = json.loads(id_path.read_text(encoding="utf-8"))
    data["name"] = target_name
    data["description"] = (
        str(data.get("description", ""))
        + " Isolated identity for real-task minimal-layer evaluation."
    )
    id_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def _install_identity(identity_dir: Path) -> Path:
    destination = ROOT / "identity" / identity_dir.name
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(identity_dir, destination)
    return destination


def _remove_generated_path(path: Path, parent: Path) -> None:
    resolved = path.resolve()
    if resolved.parent != parent.resolve() or not resolved.name.startswith(GENERATED_PREFIX):
        raise RuntimeError(f"refusing cleanup outside generated namespace: {resolved}")
    if resolved.is_dir():
        shutil.rmtree(resolved)


def _identity_name(stamp: str, family: Family, layer: str) -> str:
    return f"{GENERATED_PREFIX}{stamp}_{family.name}_{layer}"


def _protocol_path(stamp: str, family: Family) -> Path:
    return RUN_ROOT / stamp / "protocols" / f"{family.name}.json"


def _extract_json_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        value = json.loads(raw)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for index, char in enumerate(raw):
        if char != "{":
            continue
        try:
            value, _end = decoder.raw_decode(raw[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("authoring model did not return a JSON object")


def _tool_help(task: Any, tool: str) -> str:
    with tempfile.TemporaryDirectory(prefix="ego_realbench_help_") as temporary:
        workspace = Path(temporary)
        task.setup(workspace)
        executable = workspace / "tools" / tool
        result = __import__("subprocess").run(
            [sys.executable, str(executable), "--help"],
            cwd=workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
        if result.returncode != 0 or not output.strip():
            raise RuntimeError(f"could not read {tool} --help: exit={result.returncode}")
        return output[:24_000]


def author_protocol(family: Family, baseline: dict[str, Any]) -> dict[str, Any]:
    """Author a reusable protocol without exposing held-out task or verifier."""
    task = _external_task(family.validation_task)
    help_text = _tool_help(task, family.tool)
    failure = (baseline.get("verifier") or {}).get("message", "")
    trace = [
        {
            "name": call.get("name"),
            "arguments": call.get("arguments"),
            "result": _safe_text(call.get("result", ""), 1_600),
        }
        for call in baseline.get("tools", [])[-8:]
    ]
    client = CustomLLM({"type": "deepseek", "max_tokens": 1100, "temperature": 0.1})
    prompt = f"""
You are distilling a reusable capability from ONE validation run. You must not
write a solution to the validation instance. Produce a compact protocol that
will transfer to unseen tasks using the same unfamiliar CLI tool.

Tool: {family.tool}
Validation task prompt:
{task.prompt}

Public `{family.tool} --help` output:
{help_text}

Validation verifier observation:
{failure}

Recent tool trace (may be empty):
{json.dumps(trace, ensure_ascii=False)}

Return JSON only with these fields:
{{
  "title": "short protocol title",
  "description": "when this capability should be invoked",
  "knowledge": "concise stable facts and flag semantics learned from --help",
  "procedure": ["general step", "general step"],
  "failure_modes": ["general pitfall"],
  "harness_preflight": "one concise instruction for a deterministic preflight node"
}}

Do not include expected output values, fixture rows, gold answers, verifier
implementation, or any mention of an unseen/held-out task.
"""
    response = client.chat(
        [
            {"role": "system", "content": "Distill transferable procedures; never leak benchmark answers."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=1100,
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    content = response["choices"][0]["message"].get("content") or ""
    protocol = _extract_json_object(content)
    required = ("title", "description", "knowledge", "procedure", "failure_modes", "harness_preflight")
    missing = [key for key in required if key not in protocol]
    if missing:
        raise ValueError(f"authored protocol missing fields: {missing}")
    serialized = json.dumps(protocol, ensure_ascii=False)
    heldout = _external_task(family.heldout_task)
    forbidden = [heldout.id, heldout.prompt]
    if any(item and item in serialized for item in forbidden):
        raise ValueError("held-out content leaked into authored protocol")
    protocol["authoring_metadata"] = {
        "model": client.last_response_metadata.get("model"),
        "usage": client.last_response_metadata.get("usage", {}),
        "latency_ms": client.last_response_metadata.get("latency_ms"),
        "provider_request_id": client.last_response_metadata.get("provider_request_id"),
        "source_task": family.validation_task,
        "tool_help_sha256": hashlib.sha256(help_text.encode("utf-8")).hexdigest(),
    }
    return protocol


def _materialize_knowledge(identity_dir: Path, family: Family, protocol: dict[str, Any]) -> None:
    name = f"{family.tool}_operation_protocol"
    target = identity_dir / "ego" / "knowledge" / name
    target.mkdir(parents=True, exist_ok=False)
    meta = {
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
        f"# {protocol['title']}\n\n{protocol['knowledge']}\n\n"
        "## Procedure\n"
        + "\n".join(f"{i}. {step}" for i, step in enumerate(protocol["procedure"], start=1))
        + "\n\n## Failure modes\n"
        + "\n".join(f"- {item}" for item in protocol["failure_modes"])
        + "\n"
    )
    _write_json(target / "meta.json", meta)
    (target / f"{name}.txt").write_text(body, encoding="utf-8")


def _materialize_skill(identity_dir: Path, family: Family, protocol: dict[str, Any]) -> None:
    name = f"inspect_{family.tool}_protocol"
    target = identity_dir / "ego" / "skills" / name
    scripts = target / "scripts"
    scripts.mkdir(parents=True, exist_ok=False)
    meta = {
        "type": "function",
        "title": protocol["title"],
        "name": name,
        "description": protocol["description"],
        "parameters": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Absolute task workspace containing tools/",
                }
            },
            "required": ["workspace"],
        },
        "provenance": {
            "source": "validation_task_and_public_tool_help",
            "source_task": family.validation_task,
            "tool_help_sha256": protocol["authoring_metadata"]["tool_help_sha256"],
        },
    }
    _write_json(target / "meta.json", meta)
    function_source = f'''"""Validation-derived, answer-free protocol reader."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROCEDURE = {json.dumps(protocol['procedure'], ensure_ascii=False, indent=2)}
FAILURE_MODES = {json.dumps(protocol['failure_modes'], ensure_ascii=False, indent=2)}


def {name}(workspace: str):
    root = Path(workspace).resolve()
    tool = (root / "tools" / {family.tool!r}).resolve()
    if root not in tool.parents or not tool.is_file():
        return json.dumps({{"error": "tool is missing from the supplied workspace"}})
    completed = subprocess.run(
        [sys.executable, str(tool), "--help"], cwd=root, capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=30, check=False,
    )
    return json.dumps({{
        "tool": {family.tool!r},
        "exit_code": completed.returncode,
        "help": (completed.stdout or completed.stderr)[:24000],
        "procedure": PROCEDURE,
        "failure_modes": FAILURE_MODES,
    }}, ensure_ascii=False)
'''
    (scripts / f"{name}.py").write_text(function_source, encoding="utf-8")


def _materialize_harness(stamp: str, family: Family, protocol: dict[str, Any]) -> Path:
    name = f"{GENERATED_PREFIX}{stamp}_{family.name}_harness"
    target = RUN_ROOT / "artifacts" / "harnesses" / name
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    graph = {
        "name": name,
        "description": "Validation-derived typed preflight plus bounded coding loop.",
        "slots": {"coder": {"description": "Task executor", "required": True}},
        "return_mode": "last",
        "pipeline": {
            "start": "input",
            "max_steps": 20,
            "max_node_steps": 90,
            "timeout_seconds": 900,
            "workspace_preview": True,
            "budget": {"max_model_calls": 18, "max_tool_calls": 48, "max_tokens": 180000},
            # TaskBench injects a structured ``task`` object containing the
            # workspace path.  Keep it intact: the Input node writes the user
            # prompt to ``request`` instead of shadowing that object.
            "context": {"request": "", "preflight": ""},
            "nodes": {
                "input": {
                    "id": "input", "op": "输入", "outputs": {"text": "request"},
                    "edges": [{"condition": "input", "to": "preflight"}],
                },
                "preflight": {
                    "id": "preflight",
                    "op": "进程",
                    "command": sys.executable,
                    "args": [f"tools/{family.tool}", "--help"],
                    "cwd": "$ctx.task.workspace",
                    "inputs": {
                        "cwd": "$ctx.task.workspace",
                    },
                    "max_output_chars": 26_000,
                    "timeout_seconds": 30,
                    "output_var": "preflight",
                    "edges": [{"condition": "process_succeeded", "to": "act"}],
                },
                "act": {
                    "id": "act", "op": "Agent", "agent": "coder", "tools": "all",
                    "inputs": {
                        "instructions": (
                            protocol["harness_preflight"]
                            + "\nPreflight help output: ${ctx.preflight.stdout}\nTask: ${ctx.request}"
                        )
                    },
                    "timeout_seconds": 120,
                    "retry": {"max_attempts": 2, "delay_seconds": 1},
                    "edges": [
                        {"condition": "has_tool_calls", "to": "tools"},
                        {"condition": "has_text", "to": "output"},
                    ],
                },
                "tools": {
                    "id": "tools", "op": "工具", "agent": "coder", "parallel": False,
                    "stuck_threshold": 3,
                    "edges": [
                        {"condition": "tools_executed", "to": "act"},
                        {"condition": "stuck", "to": "act"},
                    ],
                },
                "output": {
                    "id": "output", "op": "结束",
                    "inputs": {"value": "$node.act.text"}, "record": True, "edges": [],
                },
            },
        },
    }
    _write_json(target / "config.json", graph)
    return target


def materialize_candidates(stamp: str, family: Family, protocol: dict[str, Any]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for layer in (CONTROL,) + LAYERS:
        identity_name = _identity_name(stamp, family, layer)
        identity = _clone_identity("coder", identity_name)
        if layer == "knowledge":
            _materialize_knowledge(identity, family, protocol)
        elif layer in {"skill", "harness"}:
            _materialize_skill(identity, family, protocol)
        _install_identity(identity)
        result[layer] = {"identity": identity_name, "harness": "bounded_coder_worker"}
    harness = _materialize_harness(stamp, family, protocol)
    installed = ROOT / "harness" / harness.name
    if installed.exists():
        shutil.rmtree(installed)
    shutil.copytree(harness, installed)
    result["harness"]["harness"] = harness.name
    return result


def _embedded_files(task: Any) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ego_realbench_fixture_") as temporary:
        workspace = Path(temporary)
        task.setup(workspace)
        files: dict[str, Any] = {}
        total = 0
        for path in sorted(workspace.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(workspace).as_posix()
            data = path.read_bytes()
            total += len(data)
            if len(data) > 16 * 1024 * 1024 or total > 64 * 1024 * 1024:
                raise RuntimeError("task fixture exceeds EgoAgent import limits")
            try:
                text = data.decode("utf-8")
                # Harness-Bench instruments CLI tools with an invocation log.
                # setup() runs in a temporary staging directory, so relocate
                # that generated absolute literal to the final task workspace.
                # A relative path is resolved from the workspace because every
                # benchmark command is executed with that cwd.
                staged_log = repr(str((workspace / ".hb_tool_calls").resolve()))
                text = text.replace(staged_log, repr(".hb_tool_calls"))
                files[relative] = text
            except UnicodeDecodeError:
                import base64

                files[relative] = {"content_base64": base64.b64encode(data).decode("ascii")}
        return files


def _task_spec(task: Any, task_dir: Path) -> Path:
    spec = {
        "version": "ego.task.v1",
        "id": task.id,
        "title": task.name,
        "description": "External Harness-Bench Fast task evaluated by its original verifier.",
        "category": "external-real-task",
        "difficulty": "real",
        "tags": list(task.tags) + ["harness-bench-fast", "original-verifier"],
        "prompt": task.prompt,
        "workspace": {"files": _embedded_files(task)},
        "selection": {"recommended_harness": "bounded_coder_worker", "recommended_identity": "coder"},
        "environment": {"backend": "local", "network": "disabled"},
        "execution": {"timeout_seconds": 900},
        "evolution": {"allowed": False},
        "evaluation": {"pass_score": 1.0, "checks": []},
    }
    path = task_dir / f"{task.id}.json"
    _write_json(path, spec)
    return path


def _wait(manager: TaskBenchManager, run_id: str, timeout: float = 960) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    state = manager.get(run_id)
    while state.get("status") not in TERMINAL_STATES and time.monotonic() < deadline:
        time.sleep(0.25)
        state = manager.get(run_id)
    if state.get("status") not in TERMINAL_STATES:
        try:
            manager.control(run_id, "stop")
        except Exception:
            pass
        raise TimeoutError(f"task {run_id} did not finish within {timeout}s")
    return state


def _tool_trace(state: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for trace in state.get("node_traces", []):
        for call in trace.get("tools", []):
            result.append(
                {
                    "node": trace.get("node_id"),
                    "name": call.get("name"),
                    "arguments": call.get("arguments"),
                    "result": _safe_text(call.get("result", ""), 4_000),
                    "blocked": bool(call.get("blocked")),
                }
            )
    return result


def run_task(
    task_id: str,
    *,
    identity: str,
    harness: str,
    task_dir: Path,
    runs_dir: Path,
) -> dict[str, Any]:
    external = _external_task(task_id)
    _task_spec(external, task_dir)
    manager = TaskBenchManager(ROOT, task_dir=task_dir, runs_dir=runs_dir)
    started = time.monotonic()
    created = manager.start(
        {"task_id": task_id, "identity": identity, "harness": harness, "debug_mode": "auto"}
    )
    state = _wait(manager, created["id"])
    workspace = Path(state["workspace"])
    verifier = external.verify(workspace)
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
        "workspace": str(workspace),
        "tools": _tool_trace(state),
        "artifacts": state.get("artifacts", []),
    }


def _candidate_measurements(layer: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    measurements = []
    for row in rows:
        base = row["static"]
        evolved = row[layer]
        measurements.append(
            {
                "task_id": f"{row['task_id']}:r{row['repetition']}",
                "split": row["split"],
                "baseline": {
                    "success": base["success"],
                    "tokens": max(1, base["tokens"]),
                    "cost": max(1, base["tokens"]),
                },
                "candidate": {
                    "success": evolved["success"],
                    "tokens": max(1, evolved["tokens"]),
                    "cost": max(1, evolved["tokens"]),
                    "within_budget": evolved["status"] not in {"timeout", "error", "stopped"},
                },
            }
        )
    # The held-out verifier is an independent trusted lineage. The validation
    # trajectory supplies the second lineage; repeated executions of either do
    # not manufacture additional provenance.
    evidence = [
        {
            "source": "task_run",
            "lineage_id": "validation-task-family",
            "observation": "candidate authored from a validation trajectory and public tool help",
        },
        {
            "source": "deterministic_checker",
            "lineage_id": "heldout-original-verifier",
            "observation": "the external benchmark's original verifier scored a fresh held-out task",
        },
    ]
    kind = "none" if layer == CONTROL else layer
    intrusion = ARTIFACT_INTRUSION[kind]
    return {
        "kind": kind,
        "maintenance_cost": min(1.0, intrusion * 0.35),
        "regression_risk": min(1.0, intrusion * 0.18),
        "evidence": evidence,
        "measurements": measurements,
    }


def cleanup(installed: dict[str, dict[str, str]]) -> None:
    identities = {entry["identity"] for entry in installed.values()}
    harnesses = {entry["harness"] for entry in installed.values() if entry["harness"].startswith(GENERATED_PREFIX)}
    for name in harnesses:
        _remove_generated_path(ROOT / "harness" / name, ROOT / "harness")
    for name in identities:
        _remove_generated_path(ROOT / "identity" / name, ROOT / "identity")


def run_family(
    stamp: str,
    family: Family,
    repetitions: int,
    skip_authoring: bool,
    resume: bool,
    rerun_layers: set[str],
) -> dict[str, Any]:
    family_root = RUN_ROOT / stamp / family.name
    task_dir = family_root / "task_specs"
    runs_dir = family_root / "task_runs"
    task_dir.mkdir(parents=True, exist_ok=True)
    protocol_path = _protocol_path(stamp, family)
    partial_path = family_root / "partial.json"
    rows: list[dict[str, Any]] = []
    if resume and partial_path.is_file():
        rows = list(json.loads(partial_path.read_text(encoding="utf-8")).get("rows") or [])

    baseline: dict[str, Any] | None = None
    if resume and protocol_path.is_file():
        protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    elif skip_authoring:
        if not protocol_path.is_file():
            raise RuntimeError(f"--skip-authoring requested but protocol is missing: {protocol_path}")
        protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    else:
        bootstrap_identity = _identity_name(stamp, family, "authoring_static")
        bootstrap_dir = _clone_identity("coder", bootstrap_identity)
        _install_identity(bootstrap_dir)
        try:
            baseline = run_task(
                family.validation_task,
                identity=bootstrap_identity,
                harness="bounded_coder_worker",
                task_dir=task_dir,
                runs_dir=runs_dir,
            )
        finally:
            _remove_generated_path(ROOT / "identity" / bootstrap_identity, ROOT / "identity")
        protocol = author_protocol(family, baseline)
        _write_json(protocol_path, protocol)

    installed = materialize_candidates(stamp, family, protocol)
    try:
        for repetition in range(1, repetitions + 1):
            for split, task_id in (
                ("validation", family.validation_task),
                ("heldout", family.heldout_task),
            ):
                row, resumed = _merge_resumed_cell(
                    rows,
                    family=family.name,
                    split=split,
                    task_id=task_id,
                    repetition=repetition,
                )
                for layer in (CONTROL,) + LAYERS:
                    if layer in row and layer not in rerun_layers:
                        print(
                            f"[{family.name}] {split} r{repetition} {layer}: resume existing",
                            flush=True,
                        )
                        continue
                    print(
                        f"[{family.name}] {split} r{repetition} {layer}: {task_id}",
                        flush=True,
                    )
                    entry = installed[layer]
                    row[layer] = run_task(
                        task_id,
                        identity=entry["identity"],
                        harness=entry["harness"],
                        task_dir=task_dir,
                        runs_dir=runs_dir,
                    )
                    _write_json(partial_path, {"rows": rows})
    finally:
        cleanup(installed)

    # Include a true no-op candidate.  Otherwise equal-success runs could force
    # the selector to promote an unnecessary artifact merely because every
    # offered option mutates the agent.
    candidates = [_candidate_measurements(layer, rows) for layer in (CONTROL,) + LAYERS]
    selection = select_empirical_evolution_artifact(
        candidates,
        minimum_gain=0.0,
        noninferiority_margin=0.0,
        regression_tolerance=1.0,
        simplicity_epsilon=0.02,
        bootstrap_samples=1_000,
        require_provenance=True,
    )
    metrics = {}
    for layer in (CONTROL,) + LAYERS:
        layer_runs = [row[layer] for row in rows]
        metrics[layer] = {
            "n": len(layer_runs),
            "success_rate": sum(item["success"] for item in layer_runs) / max(1, len(layer_runs)),
            "mean_tokens": sum(item["tokens"] for item in layer_runs) / max(1, len(layer_runs)),
            "mean_seconds": sum(item["elapsed_seconds"] for item in layer_runs) / max(1, len(layer_runs)),
        }
    result = {
        "family": family.name,
        "validation_task": family.validation_task,
        "heldout_task": family.heldout_task,
        "protocol": protocol,
        "bootstrap_validation": baseline,
        "rows": rows,
        "metrics": metrics,
        "selection": selection,
    }
    _write_json(family_root / "result.json", result)
    return result


def _merge_resumed_cell(
    rows: list[dict[str, Any]],
    *,
    family: str,
    split: str,
    task_id: str,
    repetition: int,
) -> tuple[dict[str, Any], bool]:
    """Return the canonical mutable row used by resume/report generation."""
    existing = next(
        (
            item for item in rows
            if item.get("split") == split
            and item.get("task_id") == task_id
            and int(item.get("repetition", 0)) == repetition
        ),
        None,
    )
    if existing is not None:
        return existing, True
    row = {
        "family": family,
        "split": split,
        "task_id": task_id,
        "repetition": repetition,
    }
    rows.append(row)
    return row, False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--families", nargs="+", choices=sorted(FAMILIES), default=["logq", "cfgctl"])
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--stamp", default=time.strftime("%Y%m%d_%H%M%S"))
    parser.add_argument("--skip-authoring", action="store_true")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse an existing protocol and completed cells from partial.json.",
    )
    parser.add_argument(
        "--rerun-layers",
        nargs="*",
        choices=[CONTROL, *LAYERS],
        default=[],
        help="With --resume, replace only these completed cells.",
    )
    args = parser.parse_args()
    if args.repetitions < 1 or args.repetitions > 10:
        raise SystemExit("--repetitions must be between 1 and 10")
    _require_external_benchmark()
    report = {
        "format": "ego.real-minimal-layer-pilot.v1",
        "evidence_level": "real-model-real-task-original-verifier",
        "provider": "deepseek",
        "model": os.environ.get("EGOAGENT_LLM_MODEL", "deepseek-v4-flash"),
        "benchmark": {
            "name": "Harness-Bench Fast",
            "repository": "https://github.com/ai-forever/harness-bench-fast",
            "license": "MIT",
        },
        "protocol": {
            "repetitions": args.repetitions,
            "fresh_workspace_per_run": True,
            "heldout_hidden_from_authoring": True,
            "original_verifier": True,
            "docker": False,
        },
        "limitations": [
            "The public benchmark does not supply oracle minimal-layer labels.",
            "This pilot isolates Knowledge, Skill and Harness, not Identity or child-Agent interventions.",
            "A one-repetition smoke run estimates integration correctness, not statistical power.",
        ],
        "families": [],
    }
    destination = RUN_ROOT / args.stamp
    destination.mkdir(parents=True, exist_ok=True)
    for name in args.families:
        report["families"].append(
            run_family(
                args.stamp,
                FAMILIES[name],
                args.repetitions,
                args.skip_authoring,
                args.resume,
                set(args.rerun_layers),
            )
        )
        _write_json(destination / "report.json", report)
    print(destination / "report.json", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
