"""TerminalBench-style tasks executed by EgoAgent's real DAG runtime.

The runner deliberately keeps one state object, pause gate and input queue per
run.  It therefore does not share the Studio's legacy global execution state.
Task workspaces are created below ``.egoagent/task_runs`` and all fixture and
evaluator paths are confined to that workspace.
"""

from __future__ import annotations

import copy
import base64
import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from permissions import NETWORK_TOOLS


TASK_SPEC_VERSION = "ego.task.v1"
TERMINAL_STATES = {"passed", "failed", "error", "stopped", "timeout"}
MAX_EVENTS = 1500
MAX_TRACES = 500

HARNESS_MUTATION_TOOLS = {
    "create_agent_system", "create_harness", "design_harness", "manage_harness", "modify_harness",
    "run_harness_test",
}
IDENTITY_MUTATION_TOOLS = {
    "copy_identity", "create_identity", "create_knowledge", "create_tool", "evolve_capabilities",
    "modify_identity", "run_evolution_cycle",
}


def evolution_context_instructions(
    identity_name: str,
    evolution: dict[str, Any],
    available_mutation_tools: Iterable[str] = (),
) -> str:
    """Return generic, evaluator-agnostic guidance for an evolution-enabled run.

    The policy describes the decision process and available artifact classes,
    but deliberately never mentions task checks or prescribes a task-specific
    answer.  This keeps emergence experiments honest while preventing a common
    weak-model failure mode: writing a proposal and mistaking it for an
    installed capability.
    """
    base = (
        f"Task Bench identity: {identity_name}. When a mutation tool asks for identity_name, "
        f"target exactly `{identity_name}` unless the task explicitly asks to create another Identity."
    )
    if not bool((evolution or {}).get("allowed", False)):
        return base

    targets = sorted({str(item).strip() for item in (evolution or {}).get("targets", []) if str(item).strip()})
    target_text = ", ".join(targets) if targets else "the mutation targets permitted by the runtime"
    confirmed_tools = sorted({str(item).strip() for item in available_mutation_tools if str(item).strip()})
    confirmed_text = (
        " The runtime has confirmed these mutation tools are callable in this run: "
        + ", ".join(f"`{name}`" for name in confirmed_tools)
        + "."
        if confirmed_tools else ""
    )
    return base + (
        "\n\nGoverned evolution is enabled for this run; permitted targets: " + target_text + "." + confirmed_text + " "
        "Treat evolution as an engineering decision, not as a mandatory ritual. First examine whether the "
        "pressure is repeated, reusable across future tasks, dependent on durable recall, or benefits from "
        "isolating a noisy process from the parent context. Compare no change with: Knowledge for durable "
        "facts, a deterministic Skill for a repeatable operation, a specialized Identity/sub-Agent for "
        "delegation or context isolation, and a Harness change for control-flow or coordination. Choose the "
        "smallest option whose expected reuse benefit exceeds its maintenance and safety cost. If you choose "
        "between several plausible artifacts, call `select_evolution_artifact` with honest normalized estimates "
        "so the choice and no-change alternative are auditable. Ordinary workspace read/write confinement does "
        "not disable the governed mutation tools listed in your tool schema; call a mutation tool directly rather "
        "than inferring that it is unavailable from a file-access error. If you choose to evolve, use the "
        "provided mutation tools to actually install the artifact and then verify it with "
        "inspection or a runnable test. A proposal, protocol, TODO, or ordinary file in the task workspace is "
        "evidence or planning only; it is not an installed evolution. `create_agent_system` is the concise way "
        "to create a reusable Identity plus a visual/runnable Harness from a role description. For a hidden "
        "worker, run a sub-harness with result-only output so its intermediate search or reasoning does not "
        "pollute the parent context. Never mutate merely to satisfy this guidance."
    )


class TaskBenchError(ValueError):
    pass


def _json_clone(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except Exception:
        return str(value)


def _safe_name(value: str, label: str) -> str:
    value = str(value or "").strip()
    if not value or Path(value).name != value or value in {".", ".."}:
        raise TaskBenchError(f"Invalid {label}: {value!r}")
    return value


def _resolve_slot_identity(
    slots: dict[str, Any],
    slot_name: str,
    selected_identity: str,
    explicit_bindings: dict[str, Any],
) -> str:
    """Resolve Task Bench's primary Identity and optional per-slot overrides."""

    slot = slots.get(slot_name, {})
    slot_default = slot.get("identity") if isinstance(slot, dict) else None
    selected_for_single_slot = selected_identity if len(slots) == 1 else None
    return str(
        explicit_bindings.get(slot_name)
        or selected_for_single_slot
        or slot_default
        or selected_identity
    )


def _discover_environment_dirs(project_root: Path) -> dict[str, Path]:
    """Resolve both packaged ``environment/<name>`` and workspace ``.environment`` packs.

    Environment Manager has always exposed workspace-scoped packs, while Task
    Bench historically listed only the older packaged directory. Keeping the
    lookup here gives the picker and the runner one identical contract.
    """
    project_root = project_root.resolve()
    candidates: list[tuple[str, Path]] = []
    packaged = project_root / "environment"
    if packaged.is_dir():
        candidates.extend((path.name, path) for path in sorted(packaged.iterdir()) if path.is_dir())
    root_pack = project_root / ".environment"
    if root_pack.is_dir():
        candidates.append((project_root.name, root_pack))
    for child in sorted(project_root.iterdir()) if project_root.is_dir() else []:
        child_pack = child / ".environment"
        if child.is_dir() and child_pack.is_dir():
            candidates.append((child.name, child_pack))
    resolved: dict[str, Path] = {}
    for name, path in candidates:
        resolved.setdefault(name, path.resolve())
    return resolved


def _inside(root: Path, requested: str) -> Path:
    root = root.resolve()
    candidate = (root / str(requested)).resolve()
    if candidate != root and root not in candidate.parents:
        raise TaskBenchError(f"Path escapes task workspace: {requested}")
    return candidate


def _validate_spec(raw: dict[str, Any], source: Path) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise TaskBenchError(f"Task spec must be an object: {source}")
    if raw.get("version") != TASK_SPEC_VERSION:
        raise TaskBenchError(f"Unsupported task version in {source}: {raw.get('version')!r}")
    task_id = _safe_name(raw.get("id", ""), "task id")
    if not str(raw.get("title", "")).strip():
        raise TaskBenchError(f"Task {task_id} has no title")
    if not str(raw.get("prompt", "")).strip():
        raise TaskBenchError(f"Task {task_id} has no prompt")
    workspace = raw.get("workspace", {})
    if workspace is not None and not isinstance(workspace, dict):
        raise TaskBenchError(f"Task {task_id} workspace must be an object")
    files = (workspace or {}).get("files", {})
    if not isinstance(files, dict):
        raise TaskBenchError(f"Task {task_id} workspace.files must be an object")
    for relative in files:
        if Path(str(relative)).is_absolute() or ".." in Path(str(relative)).parts:
            raise TaskBenchError(f"Task {task_id} has unsafe fixture path: {relative}")
    evaluation = raw.get("evaluation", {})
    if not isinstance(evaluation, dict) or not isinstance(evaluation.get("checks", []), list):
        raise TaskBenchError(f"Task {task_id} evaluation.checks must be an array")
    for index, check in enumerate(evaluation.get("checks", []), start=1):
        if not isinstance(check, dict) or not check.get("type"):
            raise TaskBenchError(f"Task {task_id} evaluation check {index} must be an object with type")
        if check.get("type") == "json_equals" and "expected" not in check:
            raise TaskBenchError(
                f"Task {task_id} json_equals check {index} requires expected (not value)"
            )
    steps = raw.get("steps", []) or []
    if not isinstance(steps, list):
        raise TaskBenchError(f"Task {task_id} steps must be an array")
    step_ids: set[str] = set()
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            raise TaskBenchError(f"Task {task_id} step {index} must be an object")
        step_id = _safe_name(step.get("id", ""), "step id")
        if step_id in step_ids:
            raise TaskBenchError(f"Task {task_id} has duplicate step id: {step_id}")
        step_ids.add(step_id)
        if not str(step.get("prompt", "")).strip():
            raise TaskBenchError(f"Task {task_id} step {step_id} has no prompt")
        step_evaluation = step.get("evaluation", {})
        if not isinstance(step_evaluation, dict) or not isinstance(step_evaluation.get("checks", []), list):
            raise TaskBenchError(f"Task {task_id} step {step_id} evaluation.checks must be an array")
        step_workspace = step.get("workspace", {}) or {}
        if not isinstance(step_workspace, dict) or not isinstance(step_workspace.get("files", {}), dict):
            raise TaskBenchError(f"Task {task_id} step {step_id} workspace.files must be an object")
        for relative in step_workspace.get("files", {}):
            if Path(str(relative)).is_absolute() or ".." in Path(str(relative)).parts:
                raise TaskBenchError(f"Task {task_id} step {step_id} has unsafe fixture path: {relative}")
    normalized = copy.deepcopy(raw)
    normalized.setdefault("description", "")
    normalized.setdefault("category", "general")
    normalized.setdefault("difficulty", "starter")
    normalized.setdefault("tags", [])
    normalized.setdefault("selection", {})
    normalized.setdefault("environment", {"backend": "local", "network": "inherit"})
    normalized.setdefault("execution", {})
    normalized.setdefault("evolution", {"allowed": False})
    normalized.setdefault("steps", [])
    normalized["source"] = str(source)
    normalized["evaluation"].setdefault("pass_score", 1.0)
    return normalized


def load_task_specs(task_dir: Path) -> list[dict[str, Any]]:
    task_dir = Path(task_dir)
    specs: list[dict[str, Any]] = []
    if not task_dir.is_dir():
        return specs
    for path in sorted(task_dir.glob("*.json")):
        if path.name == "schema.json":
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        specs.append(_validate_spec(raw, path))
    seen: set[str] = set()
    for spec in specs:
        if spec["id"] in seen:
            raise TaskBenchError(f"Duplicate task id: {spec['id']}")
        seen.add(spec["id"])
    return specs


def _manifest(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not root.is_dir():
        return result
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in {"__pycache__", ".git"} for part in path.parts):
            continue
        try:
            relative = path.relative_to(root).as_posix()
            result[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            continue
    return result


def _manifest_diff(before: dict[str, str], after: dict[str, str]) -> dict[str, list[str]]:
    return {
        "created": sorted(path for path in after if path not in before),
        "modified": sorted(path for path in after if path in before and after[path] != before[path]),
        "deleted": sorted(path for path in before if path not in after),
    }


def _pointer(value: Any, pointer: str) -> Any:
    current = value
    if pointer in {"", "/"}:
        return current
    for token in str(pointer).strip("/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(token)]
        elif isinstance(current, dict):
            current = current[token]
        else:
            raise KeyError(pointer)
    return current


def _last_response(messages: Iterable[dict[str, Any]]) -> str:
    for message in reversed(list(messages)):
        if message.get("role") == "assistant":
            return str(message.get("content", ""))
    return ""


def _run_command_check(check: dict[str, Any], workspace: Path) -> tuple[bool, str, dict[str, Any]]:
    command = check.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(item, str) for item in command):
        raise TaskBenchError("command evaluator requires a non-empty string array")
    cwd = _inside(workspace, check.get("cwd", "."))
    if not cwd.is_dir():
        return False, f"cwd does not exist: {check.get('cwd', '.')}", {}
    timeout = max(1.0, min(float(check.get("timeout_seconds", 30)), 300.0))
    safe_env = {
        key: value for key, value in os.environ.items()
        if not any(marker in key.lower() for marker in ("key", "token", "secret", "password", "passwd", "auth", "cookie"))
    }
    safe_env["EGOAGENT_TASK_WORKSPACE"] = str(workspace)
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        shell=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=safe_env,
    )
    expected = [int(code) for code in check.get("success_codes", [0])]
    details = {
        "command": command,
        "exit_code": completed.returncode,
        "stdout": completed.stdout[-8000:],
        "stderr": completed.stderr[-8000:],
    }
    return completed.returncode in expected, f"exit {completed.returncode}", details


def evaluate_task(
    spec: dict[str, Any],
    workspace: Path,
    *,
    messages: Optional[list[dict[str, Any]]] = None,
    traces: Optional[list[dict[str, Any]]] = None,
    events: Optional[list[dict[str, Any]]] = None,
    mutations: Optional[dict[str, Any]] = None,
    container: Any = None,
) -> dict[str, Any]:
    """Run deterministic checks and return a weighted score with evidence."""
    messages = messages or []
    traces = traces or []
    events = events or []
    mutations = mutations or {}
    checks = spec.get("evaluation", {}).get("checks", [])
    results: list[dict[str, Any]] = []
    total_weight = 0.0
    earned = 0.0

    for index, check in enumerate(checks):
        kind = str(check.get("type", ""))
        weight = max(0.0, float(check.get("weight", 1.0)))
        total_weight += weight
        passed = False
        summary = ""
        details: dict[str, Any] = {}
        try:
            if kind == "file_exists":
                path = _inside(workspace, check.get("path", ""))
                passed = path.is_file() if check.get("kind", "file") == "file" else path.exists()
                summary = f"{check.get('path')}: {'exists' if passed else 'missing'}"
            elif kind in {"file_contains", "file_not_contains"}:
                path = _inside(workspace, check.get("path", ""))
                content = path.read_text(encoding="utf-8")
                needle = str(check.get("value", ""))
                haystack = content if check.get("case_sensitive", True) else content.lower()
                compared = needle if check.get("case_sensitive", True) else needle.lower()
                contains = compared in haystack
                passed = contains if kind == "file_contains" else not contains
                summary = f"{check.get('path')} {'contains' if contains else 'does not contain'} requested text"
            elif kind == "file_regex":
                path = _inside(workspace, check.get("path", ""))
                content = path.read_text(encoding="utf-8")
                passed = re.search(str(check.get("pattern", "")), content, re.MULTILINE) is not None
                summary = f"regex {'matched' if passed else 'did not match'} in {check.get('path')}"
            elif kind == "json_equals":
                path = _inside(workspace, check.get("path", ""))
                actual = _pointer(json.loads(path.read_text(encoding="utf-8")), str(check.get("pointer", "")))
                expected = check.get("expected")
                passed = actual == expected
                summary = f"{check.get('path')}#{check.get('pointer', '')}: {actual!r}"
                details = {"actual": actual, "expected": expected}
            elif kind == "response_contains":
                response = _last_response(messages)
                needle = str(check.get("value", ""))
                passed = needle.lower() in response.lower() if not check.get("case_sensitive", False) else needle in response
                summary = f"final response {'contains' if passed else 'misses'} requested text"
            elif kind == "node_visited":
                node_id = str(check.get("node", ""))
                count = sum(1 for trace in traces if trace.get("node_id") == node_id)
                passed = count >= int(check.get("minimum", 1))
                summary = f"node {node_id} visited {count} time(s)"
            elif kind == "op_visited":
                op = str(check.get("op", ""))
                count = sum(1 for trace in traces if trace.get("op") == op)
                passed = count >= int(check.get("minimum", 1))
                summary = f"op {op} visited {count} time(s)"
            elif kind == "tool_called":
                tool = str(check.get("name", ""))
                count = sum(
                    1 for trace in traces for call in trace.get("tools", [])
                    if str(call.get("name", "")).split(":")[-1] == tool or str(call.get("name", "")) == tool
                )
                passed = count >= int(check.get("minimum", 1))
                summary = f"tool {tool} called {count} time(s)"
            elif kind in {"harness_created", "identity_created", "harness_modified", "capability_added"}:
                bucket = {
                    "harness_created": "harness_created",
                    "identity_created": "identity_created",
                    "harness_modified": "harness_modified",
                    "capability_added": "capability_added",
                }[kind]
                values = list(mutations.get(bucket, []))
                requested = str(check.get("name", ""))
                passed = bool(values) if not requested else any(requested == item or requested in item for item in values)
                summary = f"{bucket}: {', '.join(values) if values else 'none'}"
            elif kind == "event_emitted":
                event_name = str(check.get("event", ""))
                count = sum(1 for event in events if event.get("type") == event_name)
                passed = count >= int(check.get("minimum", 1))
                summary = f"event {event_name} emitted {count} time(s)"
            elif kind == "command":
                passed, summary, details = _run_command_check(check, workspace)
            elif kind == "harbor_verifier":
                if container is None:
                    passed = False
                    summary = "container verifier requires an active Docker task runtime"
                    details = {"error": "container_runtime_unavailable"}
                else:
                    passed, summary, details = container.run_verifier(check)
            else:
                summary = f"unsupported evaluator: {kind}"
        except (OSError, ValueError, KeyError, IndexError, subprocess.SubprocessError) as error:
            summary = f"check error: {error}"
            details = {"error": type(error).__name__}

        if passed:
            earned += weight
        results.append({
            "id": str(check.get("id", f"check_{index + 1}")),
            "type": kind,
            "passed": passed,
            "weight": weight,
            "summary": summary,
            "details": details,
        })

    score = earned / total_weight if total_weight else 1.0
    pass_score = float(spec.get("evaluation", {}).get("pass_score", 1.0))
    return {
        "score": round(score, 4),
        "earned": earned,
        "total_weight": total_weight,
        "pass_score": pass_score,
        "passed": score >= pass_score,
        "checks": results,
    }


def _new_trace(sequence: int, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "sequence": sequence,
        "node_id": data.get("node_id", ""),
        "op": data.get("op", ""),
        "agent": data.get("agent", ""),
        "status": "entered",
        "input": data.get("input"),
        "last_output": data.get("last_output"),
        "output": None,
        "model": {"request": None, "response": "", "tool_calls": []},
        "tools": [],
        "started_at": time.time(),
    }


class TaskRun:
    def __init__(self, manager: "TaskBenchManager", spec: dict[str, Any], selection: dict[str, Any], debug_mode: str):
        self.manager = manager
        self.spec = copy.deepcopy(spec)
        self.id = f"run_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        self.run_dir = manager.runs_dir / self.id
        self.workspace = self.run_dir / "workspace"
        self._ide_context = copy.deepcopy(selection.get("ide_context", []))
        self.selection = copy.deepcopy(selection)
        self.selection["ide_context"] = [
            {
                key: value for key, value in item.items() if key != "content"
            } | {
                "content_sha256": hashlib.sha256(str(item.get("content", "")).encode("utf-8")).hexdigest(),
                "content_bytes": len(str(item.get("content", "")).encode("utf-8")),
            }
            for item in self._ide_context
        ]
        self.state: dict[str, Any] = {
            "id": self.id,
            "task_id": spec["id"],
            "task": {key: value for key, value in spec.items() if key != "source"},
            "selection": self.selection,
            "status": "created",
            "running": False,
            "debug_mode": "paused" if debug_mode in {"paused", "step"} else "auto",
            "paused": False,
            "pause_requested": debug_mode in {"paused", "step"},
            "pending_node": None,
            "current_node": None,
            "step_count": 0,
            "task_step": None,
            "task_steps": [],
            "node_traces": [],
            "events": [],
            "outputs": [],
            "evolution_events": [],
            "evaluation": None,
            "mutations": {},
            "artifacts": [],
            "workspace": str(self.workspace),
            "created_at": time.time(),
            "started_at": None,
            "completed_at": None,
            "error": None,
            "stats": {},
            "policy": {"hidden_tools": [], "network": spec.get("environment", {}).get("network", "inherit")},
        }
        self.lock = threading.RLock()
        self.condition = threading.Condition(self.lock)
        self.input_queue: queue.Queue[Optional[str]] = queue.Queue()
        self.step_budget = 0
        self.stop_requested = False
        self.thread: Optional[threading.Thread] = None
        self._before_harness: dict[str, str] = {}
        self._before_identity: dict[str, str] = {}
        self._before_harness_roots: set[str] = set()
        self._before_identity_roots: set[str] = set()
        self.container: Any = None

    def public(self, *, include_events: bool = True) -> dict[str, Any]:
        with self.lock:
            payload = _json_clone(self.state)
        if not include_events:
            payload.pop("events", None)
            payload.pop("node_traces", None)
            payload.pop("outputs", None)
        return payload

    def prepare(self) -> None:
        self.workspace.mkdir(parents=True, exist_ok=False)
        self._materialize_files(self.spec.get("workspace", {}).get("files", {}))
        ide_context_manifest = []
        for index, item in enumerate(self._ide_context):
            source_name = Path(str(item.get("relativePath") or item.get("path") or f"context_{index + 1}.txt")).name
            safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", source_name).strip("._") or f"context_{index + 1}.txt"
            relative = f".egoagent/ide_context/{index + 1:02d}_{safe_name}"
            target = _inside(self.workspace, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            content = str(item.get("content", ""))
            target.write_text(content, encoding="utf-8")
            ide_context_manifest.append({
                "kind": item.get("kind", "file"),
                "source_path": item.get("path", ""),
                "relative_path": relative,
                "language": item.get("language", ""),
                "start_line": item.get("startLine"),
                "end_line": item.get("endLine"),
                "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "content_bytes": len(content.encode("utf-8")),
            })
        self.state["ide_context"] = ide_context_manifest
        environment = self.spec.get("environment", {})
        env_config = {
            "task_id": self.spec["id"],
            "backend": environment.get("backend", "local"),
            "network": environment.get("network", "inherit"),
            "selected_packs": list(self.selection.get("environments", [])),
            "external_format": self.spec.get("external_format"),
        }
        ego_dir = self.workspace / ".egoagent"
        ego_dir.mkdir(exist_ok=True)
        (ego_dir / "environment.json").write_text(json.dumps(env_config, ensure_ascii=False, indent=2), encoding="utf-8")
        self._before_harness = _manifest(self.manager.project_root / "harness")
        self._before_identity = _manifest(self.manager.project_root / "identity")
        self._before_harness_roots = {
            path.name for path in (self.manager.project_root / "harness").iterdir() if path.is_dir()
        }
        self._before_identity_roots = {
            path.name for path in (self.manager.project_root / "identity").iterdir() if path.is_dir()
        }
        self._persist()

    def _materialize_files(self, files: dict[str, Any]) -> None:
        for relative, raw in files.items():
            path = _inside(self.workspace, relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(raw, dict) and "content_base64" in raw:
                try:
                    path.write_bytes(base64.b64decode(str(raw["content_base64"]), validate=True))
                except (ValueError, TypeError) as error:
                    raise TaskBenchError(f"Invalid base64 fixture {relative}: {error}") from error
            else:
                content = raw.get("content", "") if isinstance(raw, dict) else raw
                path.write_text(str(content), encoding="utf-8")

    def _activate_step_workspace(self, step: dict[str, Any]) -> None:
        self._materialize_files(step.get("workspace", {}).get("files", {}))
        external = self.spec.get("external_format", {}) or {}
        if external.get("type") != "harbor":
            return
        step_id = _safe_name(step.get("id", ""), "step id")
        workdir = self.workspace / ".external" / "steps" / step_id / "workdir"
        if workdir.is_dir():
            shutil.copytree(workdir, self.workspace, dirs_exist_ok=True)

    def start(self) -> None:
        self.prepare()
        with self.lock:
            self.state["status"] = "running"
            self.state["running"] = True
            self.state["started_at"] = time.time()
        self.thread = threading.Thread(target=self._run, daemon=True, name=f"task-bench-{self.id}")
        self.thread.start()

    def _latest_trace(self, node_id: str) -> Optional[dict[str, Any]]:
        for trace in reversed(self.state["node_traces"]):
            if trace.get("node_id") == node_id:
                return trace
        return None

    def emit(self, event_type: str, raw_data: dict[str, Any]) -> None:
        data = _json_clone(raw_data if isinstance(raw_data, dict) else {"value": raw_data})
        with self.lock:
            event = {"sequence": len(self.state["events"]) + 1, "time": time.time(), "type": event_type, "data": data}
            self.state["events"].append(event)
            if len(self.state["events"]) > MAX_EVENTS:
                del self.state["events"][:-MAX_EVENTS]
            node_id = str(data.get("node_id", ""))
            if event_type == "node_input" and node_id:
                self.state["node_traces"].append(_new_trace(len(self.state["node_traces"]) + 1, data))
                if len(self.state["node_traces"]) > MAX_TRACES:
                    del self.state["node_traces"][:-MAX_TRACES]
            elif node_id:
                trace = self._latest_trace(node_id)
                if trace:
                    if event_type == "node_enter":
                        trace["status"] = "running"
                    elif event_type == "model_request":
                        trace["model"]["request"] = {k: v for k, v in data.items() if k not in {"run_id", "node_id"}}
                    elif event_type == "token":
                        trace["model"]["response"] = str(trace["model"].get("response", "")) + str(data.get("text", ""))
                    elif event_type == "model_response":
                        trace["model"]["response"] = data.get("text", trace["model"].get("response", ""))
                        trace["model"]["tool_calls"] = data.get("tool_calls", [])
                    elif event_type in {"tool", "blocked"}:
                        trace["tools"].append({
                            "name": data.get("name", data.get("tool", "")),
                            "arguments": data.get("arguments"),
                            "result": data.get("result"),
                            "blocked": event_type == "blocked",
                            "reason": data.get("reason", ""),
                        })
                    elif event_type == "node_output":
                        trace["output"] = data.get("output")
                        trace["status"] = "error" if data.get("status") == "error" else "ok"
                    elif event_type == "node_exit":
                        trace["status"] = "error" if data.get("status") == "error" else "completed"
                        trace["completed_at"] = time.time()
            if event_type == "node_enter":
                self.state["current_node"] = data.get("node_id")
                self.state["step_count"] += 1
            if event_type == "token":
                self.state["outputs"].append({"type": "text", "agent": data.get("agent", "agent"), "text": data.get("text", ""), "node_id": node_id})
            elif event_type in {"tool", "blocked"}:
                self.state["outputs"].append({"type": event_type, "agent": data.get("agent", "agent"), "node_id": node_id, **data})
            if len(self.state["outputs"]) > 1000:
                del self.state["outputs"][:-1000]
            if event_type in {"harness_mutation", "identity_evolution", "agent_system_created"}:
                self.state["evolution_events"].append(event)

    def before_node(self, _ctx: Any, node_id: str, _node: dict[str, Any]) -> None:
        with self.condition:
            self.state["pending_node"] = node_id
            while self.state["running"]:
                if self.state["debug_mode"] == "auto":
                    self.state["paused"] = False
                    self.state["pause_requested"] = False
                    self.state["pending_node"] = None
                    return
                if self.step_budget > 0:
                    self.step_budget -= 1
                    self.state["paused"] = False
                    self.state["pause_requested"] = True
                    self.state["pending_node"] = None
                    return
                self.state["paused"] = True
                self.state["pause_requested"] = False
                self.condition.wait(timeout=0.25)
            self.state["paused"] = False
            self.state["pending_node"] = None

    def control(self, action: str) -> dict[str, Any]:
        with self.condition:
            if self.state["status"] in TERMINAL_STATES:
                raise TaskBenchError("Task run is already finished")
            if action in {"resume", "auto"}:
                self.state["debug_mode"] = "auto"
                self.state["paused"] = False
                self.state["pause_requested"] = False
                self.step_budget = 0
            elif action == "pause":
                self.state["debug_mode"] = "paused"
                self.state["pause_requested"] = True
            elif action in {"step", "continue"}:
                self.state["debug_mode"] = "paused"
                self.state["paused"] = False
                self.state["pause_requested"] = True
                self.step_budget = 1
            elif action == "stop":
                self.stop_requested = True
                self.state["running"] = False
                self.state["paused"] = False
                self.input_queue.put(None)
            else:
                raise TaskBenchError("action must be pause, step, auto/resume, or stop")
            self.condition.notify_all()
        return self.public()

    def send_input(self, value: str) -> None:
        if not self.state["running"]:
            raise TaskBenchError("Task run is not running")
        self.input_queue.put(str(value))

    def _is_running(self) -> bool:
        timeout = max(1.0, float(self.spec.get("execution", {}).get("timeout_seconds", 900)))
        started = self.state.get("started_at") or time.time()
        if time.time() - started > timeout:
            with self.condition:
                self.state["status"] = "timeout"
                self.state["error"] = f"Task exceeded {timeout:g}s timeout"
                self.condition.notify_all()
            return False
        return bool(self.state["running"])

    def _get_input(self) -> Optional[str]:
        """Wait cooperatively so stop and task timeout are honored promptly."""
        while self._is_running():
            try:
                return self.input_queue.get(timeout=0.25)
            except queue.Empty:
                continue
        return None

    def _collect_artifacts(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for path in sorted(self.workspace.rglob("*")):
            if not path.is_file() or ".egoagent" in path.parts:
                continue
            try:
                relative = path.relative_to(self.workspace).as_posix()
                size = path.stat().st_size
                preview = ""
                if size <= 100_000:
                    preview = path.read_text(encoding="utf-8")[:4000]
                result.append({"path": relative, "size": size, "preview": preview})
            except (OSError, UnicodeDecodeError):
                continue
        return result[:500]

    def _mutation_summary(self) -> dict[str, Any]:
        harness_diff = _manifest_diff(self._before_harness, _manifest(self.manager.project_root / "harness"))
        identity_diff = _manifest_diff(self._before_identity, _manifest(self.manager.project_root / "identity"))

        def roots(paths: Iterable[str]) -> list[str]:
            return sorted({path.split("/", 1)[0] for path in paths if "/" in path})

        harness_created_roots = set(roots(harness_diff["created"]))
        identity_created_roots = set(roots(identity_diff["created"]))
        harness_created = sorted(harness_created_roots - self._before_harness_roots)
        identity_created = sorted(identity_created_roots - self._before_identity_roots)
        harness_modified = sorted(
            (set(roots(harness_diff["modified"])) | set(roots(harness_diff["deleted"]))
             | (harness_created_roots & self._before_harness_roots))
            - set(harness_created)
        )
        capability_added = sorted(
            path for path in identity_diff["created"]
            if "/ego/skills/" in f"/{path}" or "/ego/knowledge/" in f"/{path}"
        )
        return {
            "harness_created": harness_created,
            "identity_created": identity_created,
            "harness_modified": harness_modified,
            "capability_added": capability_added,
            "harness_files": harness_diff,
            "identity_files": identity_diff,
        }

    def _run(self) -> None:
        harness = None
        try:
            from agent_factory import AgentFactory
            from harness import Harness, runtime_scope
            from permissions import RuntimePolicy
            from pipeline_engine import PipelineRunner
            from task_bench.container_runtime import TaskContainer

            harness_name = _safe_name(self.selection.get("harness", ""), "harness")
            identity_name = _safe_name(self.selection.get("identity", ""), "identity")
            harness_dir = self.manager.project_root / "harness" / harness_name
            identity_dir = self.manager.project_root / "identity" / identity_name
            if not (harness_dir / "config.json").is_file():
                raise TaskBenchError(f"Harness not found: {harness_name}")
            if not (identity_dir / "id.json").is_file():
                raise TaskBenchError(f"Identity not found: {identity_name}")
            if self.spec.get("environment", {}).get("backend") == "container":
                self.emit("container_status", {"status": "building", "backend": "docker"})
                self.container = TaskContainer(self.spec, self.workspace, self.run_dir)
                self.container.start()
                self.emit("container_status", {
                    "status": "running", "backend": "docker", "container": self.container.name,
                })
            config = json.loads((harness_dir / "config.json").read_text(encoding="utf-8"))
            slots = config.get("slots", {})
            explicit_bindings = self.selection.get("slot_bindings", {})
            environments = []
            available_environments = _discover_environment_dirs(self.manager.project_root)
            for env_name in self.selection.get("environments", []):
                safe_env = _safe_name(env_name, "environment")
                env_dir = available_environments.get(safe_env)
                if env_dir is None or not env_dir.is_dir():
                    raise TaskBenchError(f"Environment not found: {safe_env}")
                environments.append(env_dir)
            agent_factory = AgentFactory(identity_roots=(self.manager.project_root / "identity",))
            agents = {}
            for slot_name in slots:
                bound_identity = _resolve_slot_identity(
                    slots, slot_name, identity_name, explicit_bindings
                )
                bound_dir = self.manager.project_root / "identity" / _safe_name(bound_identity, "identity")
                if not (bound_dir / "id.json").is_file():
                    raise TaskBenchError(f"Identity not found for slot {slot_name}: {bound_identity}")
                agents[slot_name] = agent_factory.create(
                    bound_dir,
                    name=slot_name,
                    workspace=self.workspace,
                    environments=environments,
                )
                self._apply_tool_policy(agents[slot_name])
                agents[slot_name].context_instructions = self._agent_context_instructions(
                    agents[slot_name], bound_identity
                )
                agents[slot_name]._runtime_context["task_run_id"] = self.id
                agents[slot_name]._runtime_context["task_id"] = self.spec["id"]
                if self.container is not None:
                    agents[slot_name]._runtime_context.update(self.container.context())
            if not slots:
                agents["agent"] = agent_factory.create(
                    identity_dir,
                    name="agent",
                    workspace=self.workspace,
                    environments=environments,
                )
                self._apply_tool_policy(agents["agent"])
                agents["agent"].context_instructions = self._agent_context_instructions(
                    agents["agent"], identity_name
                )
                agents["agent"]._runtime_context["task_run_id"] = self.id
                agents["agent"]._runtime_context["task_id"] = self.spec["id"]
                if self.container is not None:
                    agents["agent"]._runtime_context.update(self.container.context())
            harness = Harness(harness_dir, agents, workspace=self.workspace)
            # Harness binds workspace environments by reinitializing every
            # Agent, which can re-add tools removed above. Enforce the task
            # policy again after that reload so mutation/network restrictions
            # cannot be bypassed by Harness construction.
            for bound_agent in agents.values():
                self._apply_tool_policy(bound_agent)
                bound_identity = Path(bound_agent.identity.identity_path).name
                bound_agent.context_instructions = self._agent_context_instructions(
                    bound_agent, bound_identity
                )
                bound_agent._runtime_context["task_run_id"] = self.id
                bound_agent._runtime_context["task_id"] = self.spec["id"]
                bound_agent._runtime_context["is_running"] = self._is_running
                if self.container is not None:
                    bound_agent._runtime_context.update(self.container.context())
            # A benchmark case is a one-shot episode. The task prompt is
            # already the latest user message, so the first Input node consumes
            # it; a later Input node must finish instead of waiting for manual
            # chat input until the task timeout expires.
            has_steps = bool(self.spec.get("steps"))
            episodes = list(self.spec.get("steps") or [{
                "id": "main", "title": self.spec.get("title", "Task"), "prompt": self.spec["prompt"],
                "workspace": {"files": {}}, "evaluation": self.spec.get("evaluation", {}),
                "resume_trajectory": False,
            }])
            aggregate_stats: dict[str, Any] = {}
            step_evaluations: list[dict[str, Any]] = []
            for episode_index, episode in enumerate(episodes):
                if not self._is_running():
                    break
                self._activate_step_workspace(episode)
                # Harbor starts each step with fresh model context unless the
                # task explicitly opts into trajectory continuation.
                if episode_index and not episode.get("resume_trajectory", False):
                    try:
                        harness.session.save()
                    except Exception:
                        pass
                    harness = Harness(harness_dir, agents, workspace=self.workspace)
                    for bound_agent in agents.values():
                        self._apply_tool_policy(bound_agent)
                        bound_identity = Path(bound_agent.identity.identity_path).name
                        bound_agent.context_instructions = self._agent_context_instructions(
                            bound_agent, bound_identity
                        )
                        bound_agent._runtime_context["task_run_id"] = self.id
                        bound_agent._runtime_context["task_id"] = self.spec["id"]
                        bound_agent._runtime_context["is_running"] = self._is_running
                        if self.container is not None:
                            bound_agent._runtime_context.update(self.container.context())
                harness._non_interactive = not bool(self.spec.get("execution", {}).get("interactive", False))
                harness._task_run_id = self.id
                harness.session.set_save_dir(self.run_dir / "session" / str(episode.get("id", episode_index + 1)))
                step_state = {
                    "id": str(episode.get("id", episode_index + 1)),
                    "title": str(episode.get("title") or episode.get("id", "Step")),
                    "status": "running", "started_at": time.time(), "completed_at": None, "evaluation": None,
                }
                with self.lock:
                    self.state["task_step"] = step_state["id"]
                    self.state["task_steps"].append(step_state)
                self.emit("task_step_start", {"step": step_state["id"], "index": episode_index + 1, "total": len(episodes)})
                ide_context_manifest = self.state.get("ide_context", [])
                ide_context_prompt = ""
                if ide_context_manifest:
                    entries = "\n".join(
                        f"- {item['relative_path']} (source: {item.get('source_path') or 'IDE selection'}, sha256: {item['content_sha256'][:12]})"
                        for item in ide_context_manifest
                    )
                    ide_context_prompt = (
                        "\n\n[IDE context supplied by the user]\n"
                        "The following immutable copies were attached to this run. Read them from the task workspace when relevant:\n"
                        + entries
                    )
                task_message = {"role": "user", "content": episode["prompt"] + ide_context_prompt, "name": "task_bench"}
                harness.session.record(task_message)
                harness.session.record_full(task_message.copy())
                runner = PipelineRunner(
                    harness,
                    on_output=self.emit,
                    get_input=self._get_input,
                    is_running=self._is_running,
                    before_node=self.before_node,
                    permission_policy=RuntimePolicy.for_task(
                        self.workspace,
                        network=self.spec.get("environment", {}).get("network", "disabled"),
                        evolution_allowed=bool(self.spec.get("evolution", {}).get("allowed", False)),
                        evolution_targets=self.spec.get("evolution", {}).get("targets", []),
                    ),
                    initial_data={"task": {
                        "id": self.spec["id"], "step": step_state["id"],
                        "prompt": episode["prompt"], "workspace": str(self.workspace),
                        "ide_context": ide_context_manifest,
                    }},
                )
                with runtime_scope(output_callback=self.emit):
                    context = runner.run()
                current_stats = context.stats.as_dict()
                for key, value in current_stats.items():
                    if isinstance(value, (int, float)):
                        aggregate_stats[key] = aggregate_stats.get(key, 0) + value
                    elif key == "provider_request_ids":
                        aggregate_stats.setdefault(key, []).extend(value or [])
                    else:
                        aggregate_stats[key] = value
                if has_steps:
                    messages = list(getattr(harness.session, "messages", []) or [])
                    evaluation = evaluate_task(
                        {"evaluation": episode.get("evaluation", {})}, self.workspace,
                        messages=messages, traces=self.state["node_traces"], events=self.state["events"],
                        mutations=self._mutation_summary(), container=self.container,
                    )
                    step_evaluations.append(evaluation)
                    step_state["evaluation"] = evaluation
                    step_state["status"] = "passed" if evaluation["passed"] else "failed"
                    step_state["completed_at"] = time.time()
                    self.emit("task_step_complete", {
                        "step": step_state["id"], "status": step_state["status"], "score": evaluation["score"],
                    })
                    harness.session.trace(
                        "evaluation.completed",
                        {
                            "task_run_id": self.id,
                            "task_id": self.spec["id"],
                            "step": step_state["id"],
                            "score": evaluation["score"],
                            "passed": evaluation["passed"],
                            "pass_score": evaluation.get("pass_score"),
                            "checks": evaluation.get("checks", []),
                            "reward_source": "task_bench_deterministic_checker",
                        },
                        run_id=context.run_id,
                        harness=harness.name,
                    )
                    if not evaluation["passed"]:
                        break
            with self.lock:
                self.state["stats"] = aggregate_stats
                self.state["task_step"] = None
                if has_steps:
                    checks = []
                    for step, evaluation in zip(self.state["task_steps"], step_evaluations):
                        for check in evaluation.get("checks", []):
                            checks.append({**check, "id": f"{step['id']}:{check.get('id', 'check')}"})
                    score = sum(item.get("score", 0) for item in step_evaluations) / len(episodes) if episodes else 1.0
                    self.state["evaluation"] = {
                        "score": round(score, 4), "earned": sum(item.get("earned", 0) for item in step_evaluations),
                        "total_weight": sum(item.get("total_weight", 0) for item in step_evaluations),
                        "pass_score": 1.0, "passed": len(step_evaluations) == len(episodes) and all(item.get("passed") for item in step_evaluations),
                        "checks": checks, "steps": step_evaluations,
                    }
        except queue.Empty:
            with self.lock:
                self.state["status"] = "timeout"
                self.state["error"] = "Task waited for input for too long"
        except Exception as error:
            with self.lock:
                if self.state["status"] not in {"timeout", "stopped"}:
                    self.state["status"] = "stopped" if self.stop_requested else "error"
                self.state["error"] = str(error)
            self.emit("error", {"message": str(error), "error_type": type(error).__name__})
        finally:
            try:
                if harness is not None:
                    harness.session.save()
            except Exception:
                pass
            with self.lock:
                self.state["paused"] = False
                self.state["pending_node"] = None
                self.state["current_node"] = None
                self.state["mutations"] = self._mutation_summary()
                self.state["artifacts"] = self._collect_artifacts()
                if self.state["status"] not in {"error", "stopped", "timeout"}:
                    self.state["status"] = "evaluating"
                    evaluation = self.state.get("evaluation")
                    if evaluation is None:
                        messages = list(getattr(getattr(harness, "session", None), "messages", []) or [])
                        evaluation = evaluate_task(
                            self.spec,
                            self.workspace,
                            messages=messages,
                            traces=self.state["node_traces"],
                            events=self.state["events"],
                            mutations=self.state["mutations"],
                            container=self.container,
                        )
                        self.state["evaluation"] = evaluation
                    self.state["status"] = "passed" if evaluation["passed"] else "failed"
                self.state["completed_at"] = time.time()
                # A task without an explicit ``steps`` array is represented in
                # the UI by one synthetic ``main`` step.  Keep that row in sync
                # with the final task evaluation instead of leaving a finished
                # run displaying a permanently "running" child step.
                for step in reversed(self.state.get("task_steps", [])):
                    if step.get("status") != "running":
                        continue
                    step["status"] = self.state["status"]
                    step["completed_at"] = self.state["completed_at"]
                    if len(self.state.get("task_steps", [])) == 1:
                        step["evaluation"] = self.state.get("evaluation")
                    break
            if self.container is not None:
                try:
                    self.container.stop()
                    self.emit("container_status", {"status": "stopped", "backend": "docker"})
                except Exception as cleanup_error:
                    self.emit("container_status", {
                        "status": "cleanup_error", "backend": "docker", "error": str(cleanup_error),
                    })
            # Publish running=false only after evaluation, container cleanup and
            # the final durable snapshot are complete. Callers can therefore
            # safely remove or inspect a run directory as soon as it finishes.
            with self.condition:
                self.state["running"] = False
                self._persist()
                self.condition.notify_all()

    def _apply_tool_policy(self, agent: Any) -> None:
        """Hide tools forbidden by the task before any model sees their schema."""
        forbidden = set()
        if self.spec.get("environment", {}).get("network") == "disabled":
            forbidden.update(NETWORK_TOOLS)
        evolution = self.spec.get("evolution", {})
        targets = set(evolution.get("targets", []))
        if not evolution.get("allowed", False):
            forbidden.update(HARNESS_MUTATION_TOOLS)
            forbidden.update(IDENTITY_MUTATION_TOOLS)
        else:
            if not ({"agent", "harness"} & targets):
                forbidden.update(HARNESS_MUTATION_TOOLS)
            if not ({"identity", "skill", "knowledge"} & targets):
                forbidden.update(IDENTITY_MUTATION_TOOLS)
        hidden = []
        for full_name in list(agent.tools):
            short_name = agent._short_name(full_name)
            if short_name in forbidden:
                hidden.append(short_name)
                del agent.tools[full_name]
        with self.lock:
            existing = set(self.state["policy"].get("hidden_tools", []))
            self.state["policy"]["hidden_tools"] = sorted(existing | set(hidden))

    def _agent_context_instructions(self, agent: Any, identity_name: str) -> str:
        visible = {
            agent._short_name(description.get("function", {}).get("name", ""))
            for description in agent.get_tools_desc()
            if isinstance(description, dict)
        }
        mutation_tools = visible & (HARNESS_MUTATION_TOOLS | IDENTITY_MUTATION_TOOLS)
        return evolution_context_instructions(
            identity_name,
            self.spec.get("evolution", {}),
            mutation_tools,
        )

    def _persist(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        temp = self.run_dir / "run.json.tmp"
        final = self.run_dir / "run.json"
        temp.write_text(json.dumps(self.public(), ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(final)


class TaskBenchManager:
    def __init__(self, project_root: Path, task_dir: Optional[Path] = None, runs_dir: Optional[Path] = None):
        self.project_root = Path(project_root).resolve()
        self.task_dir = Path(task_dir or self.project_root / "task_bench" / "tasks").resolve()
        self.runs_dir = Path(runs_dir or self.project_root / ".egoagent" / "task_runs").resolve()
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.runs: dict[str, TaskRun] = {}

    def tasks(self) -> list[dict[str, Any]]:
        return load_task_specs(self.task_dir)

    def task(self, task_id: str) -> dict[str, Any]:
        for spec in self.tasks():
            if spec["id"] == task_id:
                return spec
        raise TaskBenchError(f"Task not found: {task_id}")

    def options(self) -> dict[str, Any]:
        harnesses = []
        for config_path in sorted((self.project_root / "harness").glob("*/config.json")):
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
                harnesses.append({
                    "name": config_path.parent.name,
                    "description": config.get("description", ""),
                    "slots": config.get("slots", {}),
                    "node_count": len(config.get("pipeline", {}).get("nodes", {})),
                })
            except (OSError, ValueError):
                continue
        identities = []
        for id_path in sorted((self.project_root / "identity").glob("*/id.json")):
            try:
                data = json.loads(id_path.read_text(encoding="utf-8"))
                identities.append({"name": id_path.parent.name, "description": data.get("description", ""), "role": data.get("role", "")})
            except (OSError, ValueError):
                continue
        environments = []
        for name, env_dir in _discover_environment_dirs(self.project_root).items():
            config = {}
            try:
                if (env_dir / "config.json").is_file():
                    config = json.loads((env_dir / "config.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
            environments.append({"name": name, "description": config.get("description", ""), "path": str(env_dir)})
        return {"harnesses": harnesses, "identities": identities, "environments": environments}

    def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        spec = self.task(str(payload.get("task_id", "")))
        raw_ide_context = payload.get("ide_context", [])
        if not isinstance(raw_ide_context, list) or len(raw_ide_context) > 20:
            raise TaskBenchError("ide_context must be a list with at most 20 items")
        ide_context = []
        total_context_bytes = 0
        for item in raw_ide_context:
            if not isinstance(item, dict):
                raise TaskBenchError("ide_context items must be objects")
            content = str(item.get("content", ""))
            content_bytes = len(content.encode("utf-8"))
            if content_bytes > 262_144:
                raise TaskBenchError("an IDE context item exceeds 256 KiB")
            total_context_bytes += content_bytes
            if total_context_bytes > 1_048_576:
                raise TaskBenchError("IDE context exceeds the 1 MiB run limit")
            ide_context.append({
                "kind": "selection" if item.get("kind") == "selection" else "file",
                "path": str(item.get("path", "")),
                "relativePath": str(item.get("relativePath", "")),
                "language": str(item.get("language", "")),
                "startLine": item.get("startLine"),
                "endLine": item.get("endLine"),
                "content": content,
            })
        selection = {
            "harness": payload.get("harness") or spec.get("selection", {}).get("recommended_harness", "react_single"),
            "identity": payload.get("identity") or spec.get("selection", {}).get("recommended_identity", "dante"),
            "environments": list(payload.get("environments", [])),
            "slot_bindings": dict(payload.get("slot_bindings", {})),
            "ide_context": ide_context,
        }
        allowed_harnesses = spec.get("selection", {}).get("compatible_harnesses", [])
        allowed_identities = spec.get("selection", {}).get("compatible_identities", [])
        if allowed_harnesses and selection["harness"] not in allowed_harnesses:
            raise TaskBenchError(f"Harness {selection['harness']} is not compatible with task {spec['id']}")
        if allowed_identities and selection["identity"] not in allowed_identities:
            raise TaskBenchError(f"Identity {selection['identity']} is not compatible with task {spec['id']}")
        debug_mode = str(payload.get("debug_mode", "auto"))
        if debug_mode not in {"auto", "paused", "step"}:
            raise TaskBenchError("debug_mode must be auto, paused or step")
        if spec.get("evolution", {}).get("allowed", False):
            with self.lock:
                if any(
                    item.state.get("running") and item.spec.get("evolution", {}).get("allowed", False)
                    for item in self.runs.values()
                ):
                    raise TaskBenchError("Only one evolution-enabled Task may run at a time")
        run = TaskRun(self, spec, selection, debug_mode)
        with self.lock:
            self.runs[run.id] = run
        run.start()
        return run.public()

    def get(self, run_id: str) -> dict[str, Any]:
        with self.lock:
            run = self.runs.get(run_id)
        if run is not None:
            return run.public()
        path = self.runs_dir / _safe_name(run_id, "run id") / "run.json"
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
        raise TaskBenchError(f"Task run not found: {run_id}")

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        summaries: dict[str, dict[str, Any]] = {}
        for path in sorted(self.runs_dir.glob("*/run.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                summaries[data["id"]] = {key: data.get(key) for key in (
                    "id", "task_id", "selection", "status", "running", "created_at", "started_at", "completed_at", "evaluation", "error"
                )}
            except (OSError, ValueError, KeyError):
                continue
        with self.lock:
            for run_id, run in self.runs.items():
                data = run.public(include_events=False)
                summaries[run_id] = {key: data.get(key) for key in (
                    "id", "task_id", "selection", "status", "running", "created_at", "started_at", "completed_at", "evaluation", "error"
                )}
        return sorted(summaries.values(), key=lambda item: item.get("created_at") or 0, reverse=True)[:max(1, min(limit, 200))]

    def control(self, run_id: str, action: str) -> dict[str, Any]:
        with self.lock:
            run = self.runs.get(run_id)
        if run is None:
            raise TaskBenchError("Only a live Task run can be controlled")
        return run.control(action)

    def input(self, run_id: str, value: str) -> dict[str, Any]:
        with self.lock:
            run = self.runs.get(run_id)
        if run is None:
            raise TaskBenchError("Only a live Task run accepts input")
        run.send_input(value)
        return {"ok": True, "run_id": run_id}
