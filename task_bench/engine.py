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
from harness_versions import read_harness_versions, resolve_harness_version_dir


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
    for relative, fixture in files.items():
        if Path(str(relative)).is_absolute() or ".." in Path(str(relative)).parts:
            raise TaskBenchError(f"Task {task_id} has unsafe fixture path: {relative}")
        if isinstance(fixture, dict) and "executable" in fixture and not isinstance(fixture["executable"], bool):
            raise TaskBenchError(f"Task {task_id} fixture executable flag must be boolean: {relative}")
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
        for relative, fixture in step_workspace.get("files", {}).items():
            if Path(str(relative)).is_absolute() or ".." in Path(str(relative)).parts:
                raise TaskBenchError(f"Task {task_id} step {step_id} has unsafe fixture path: {relative}")
            if isinstance(fixture, dict) and "executable" in fixture and not isinstance(fixture["executable"], bool):
                raise TaskBenchError(
                    f"Task {task_id} step {step_id} fixture executable flag must be boolean: {relative}"
                )
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
    for directory, children, files in os.walk(root):
        # Immutable versions are not current capabilities. Prune traversal,
        # rather than reading every historical snapshot on every Task.
        children[:] = sorted(child for child in children if child not in {
            "__pycache__", ".git", ".versions", "node_modules", ".venv",
        } and not (Path(directory) / child).is_symlink())
        for name in sorted(files):
            path = Path(directory) / name
            if path.is_symlink():
                continue
            try:
                result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
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
            elif kind in {"response_contains", "response_not_contains"}:
                response = _last_response(messages)
                needle = str(check.get("value", ""))
                contains = needle.lower() in response.lower() if not check.get("case_sensitive", False) else needle in response
                passed = contains if kind == "response_contains" else not contains
                summary = f"final response {'contains' if contains else 'does not contain'} requested text"
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
    def __init__(
        self,
        manager: "TaskBenchManager",
        spec: dict[str, Any],
        selection: dict[str, Any],
        debug_mode: str,
        *,
        recovery: Optional[dict[str, Any]] = None,
    ):
        self.manager = manager
        self.spec = copy.deepcopy(spec)
        self.id = f"run_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        self.run_dir = manager.runs_dir / self.id
        self.workspace = self.run_dir / "workspace"
        self._ide_context = [] if recovery else copy.deepcopy(selection.get("ide_context", []))
        self.selection = copy.deepcopy(selection)
        self._debug_paused_seconds = 0.0
        if not recovery:
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
        self.recovery = copy.deepcopy(recovery) if recovery else None
        self._recovery_checkpoint: Optional[Path] = None
        if self.recovery:
            source_state = self.recovery.get("source_state", {})
            self.state["recovery"] = {
                "source_run_id": source_state.get("id"),
                "source_status": source_state.get("status"),
                "source_step": self.recovery.get("step_id"),
                "checkpoint": Path(str(self.recovery.get("checkpoint", ""))).name,
                "checkpoint_phase": self.recovery.get("checkpoint_phase", "completed"),
                "source_stats": copy.deepcopy(source_state.get("stats", {})),
                "started_at": None,
            }

    def public(self, *, include_events: bool = True) -> dict[str, Any]:
        with self.lock:
            return _json_clone({key: value for key, value in self.state.items()
                                if include_events or key not in {"events", "node_traces", "outputs"}})

    def prepare(self) -> None:
        if self.recovery:
            source_workspace = Path(str(self.recovery["source_workspace"])).resolve()
            if not source_workspace.is_dir():
                raise TaskBenchError(f"Recovery workspace not found: {source_workspace}")
            shutil.copytree(source_workspace, self.workspace)
            checkpoint_name = Path(str(self.recovery["checkpoint"])).name
            self._recovery_checkpoint = self.workspace / ".egoagent" / "checkpoints" / checkpoint_name
            if not self._recovery_checkpoint.is_file():
                raise TaskBenchError(f"Recovery checkpoint was not copied: {checkpoint_name}")
            source_state = self.recovery.get("source_state", {})
            self.state["ide_context"] = copy.deepcopy(source_state.get("ide_context", []))
            completed_steps = []
            recovery_step_id = str(self.recovery.get("step_id", ""))
            for step in source_state.get("task_steps", []):
                if str(step.get("id", "")) == recovery_step_id:
                    break
                if step.get("evaluation") is not None and step.get("status") == "passed":
                    inherited = copy.deepcopy(step)
                    inherited["recovered_from"] = source_state.get("id")
                    completed_steps.append(inherited)
            self.state["task_steps"] = completed_steps
            self.state["recovery"]["inherited_steps"] = len(completed_steps)
        else:
            self.workspace.mkdir(parents=True, exist_ok=False)
            self._materialize_files(self.spec.get("workspace", {}).get("files", {}))
        ide_context_manifest = []
        for index, item in enumerate(self._ide_context if not self.recovery else []):
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
        if not self.recovery:
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
        if self.spec.get("evolution", {}).get("allowed", False):
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
            if isinstance(raw, dict) and raw.get("executable") is True:
                # Preserve executable task fixtures across the JSON embedding
                # boundary.  This is intentionally opt-in: ordinary task files
                # remain non-executable and the path is already workspace-bound.
                path.chmod(path.stat().st_mode | 0o111)

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
        with self.lock:
            self.state["status"] = "preparing"
            self.state["running"] = True
            self.state["started_at"] = time.time()
            if self.recovery:
                self.state["recovery"]["started_at"] = self.state["started_at"]
        self._persist()
        self.thread = threading.Thread(target=self._prepare_and_run, daemon=True, name=f"task-bench-{self.id}")
        self.thread.start()

    def _prepare_and_run(self) -> None:
        try:
            self.emit("task_preparing", {"backend": self.spec.get("environment", {}).get("backend", "local")})
            self.prepare()
            if self.stop_requested:
                with self.lock:
                    self.state.update(status="stopped", running=False, completed_at=time.time())
                self._persist()
                return
            with self.lock:
                self.state["status"] = "running"
            self._run()
        except Exception as error:
            with self.lock:
                self.state.update(status="stopped" if self.stop_requested else "error", running=False,
                                  paused=False, completed_at=time.time(), error=str(error))
            self.emit("error", {"message": str(error), "phase": "preparation"})
            self._persist()

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
            announced_pause = False
            while self.state["running"] and not self.stop_requested:
                if self.state["debug_mode"] == "auto":
                    self.state["paused"] = False
                    self.state["pause_requested"] = False
                    self.state["pending_node"] = None
                    if announced_pause:
                        _ctx.emit("debug_resumed", {"node_id": node_id})
                    return
                if self.step_budget > 0:
                    self.step_budget -= 1
                    self.state["paused"] = False
                    self.state["pause_requested"] = True
                    self.state["pending_node"] = None
                    if announced_pause:
                        _ctx.emit("debug_resumed", {"node_id": node_id})
                    return
                self.state["paused"] = True
                self.state["pause_requested"] = False
                if not announced_pause:
                    _ctx.emit("debug_paused", {"node_id": node_id, "reason": "user_debug_gate"})
                    announced_pause = True
                wait_started = time.monotonic()
                self.condition.wait(timeout=0.25)
                paused_seconds = time.monotonic() - wait_started
                self._debug_paused_seconds += paused_seconds
                _ctx.stats.started_at += paused_seconds
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
                self.state["status"] = "stopped"
                self.state["error"] = "Task stopped by user"
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
        if not self.state.get("paused") and time.time() - started - self._debug_paused_seconds > timeout:
            with self.condition:
                self.state["status"] = "timeout"
                self.state["error"] = f"Task exceeded {timeout:g}s timeout"
                self.condition.notify_all()
            return False
        return bool(self.state["running"]) and not self.stop_requested

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
        if not self.spec.get("evolution", {}).get("allowed", False):
            return {"harness_created": [], "identity_created": [], "harness_modified": [], "capability_added": [],
                    "harness_files": _manifest_diff({}, {}), "identity_files": _manifest_diff({}, {})}
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
            try:
                runnable_harness_dir, resolved_harness_version = resolve_harness_version_dir(
                    harness_dir, self.selection.get("harness_version", "latest")
                )
            except FileNotFoundError as error:
                raise TaskBenchError(str(error)) from error
            self.selection["harness_version"] = resolved_harness_version
            self.state["selection"]["harness_version"] = resolved_harness_version
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
            config = json.loads((runnable_harness_dir / "config.json").read_text(encoding="utf-8"))
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
            harness = Harness(runnable_harness_dir, agents, workspace=self.workspace)
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
            total_episode_count = len(episodes)
            episode_offset = 0
            if self.recovery:
                recovery_step_id = str(self.recovery.get("step_id", ""))
                episode_offset = next(
                    (index for index, item in enumerate(episodes) if str(item.get("id", "")) == recovery_step_id),
                    -1,
                )
                if episode_offset < 0:
                    raise TaskBenchError(f"Recovery step no longer exists in task: {recovery_step_id}")
                episodes = episodes[episode_offset:]
            aggregate_stats: dict[str, Any] = {}
            step_evaluations: list[dict[str, Any]] = [
                copy.deepcopy(step["evaluation"])
                for step in self.state.get("task_steps", [])
                if step.get("evaluation") is not None
            ]
            for relative_episode_index, episode in enumerate(episodes):
                episode_index = episode_offset + relative_episode_index
                recovering_episode = bool(self.recovery and relative_episode_index == 0)
                if not self._is_running():
                    break
                if not recovering_episode:
                    self._activate_step_workspace(episode)
                # Harbor starts each step with fresh model context unless the
                # task explicitly opts into trajectory continuation.
                if relative_episode_index and not episode.get("resume_trajectory", False):
                    try:
                        harness.session.save()
                    except Exception:
                        pass
                    harness = Harness(runnable_harness_dir, agents, workspace=self.workspace)
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
                # A resumed episode intentionally keeps the same Session and
                # native trajectory.  Relocating it here would either split a
                # supposedly continuous history or, once trace events exist,
                # be rejected by Session.set_save_dir.  Fresh episodes still
                # receive their own directory because a new Harness/Session
                # was constructed above.
                if relative_episode_index == 0 or not episode.get("resume_trajectory", False):
                    harness.session.set_save_dir(
                        self.run_dir / "session" / str(episode.get("id", episode_index + 1))
                    )
                step_state = {
                    "id": str(episode.get("id", episode_index + 1)),
                    "title": str(episode.get("title") or episode.get("id", "Step")),
                    "status": "running", "started_at": time.time(), "completed_at": None, "evaluation": None,
                }
                with self.lock:
                    self.state["task_step"] = step_state["id"]
                    self.state["task_steps"].append(step_state)
                self.emit("task_step_start", {
                    "step": step_state["id"],
                    "index": episode_index + 1,
                    "total": episode_offset + len(episodes),
                    "recovery": recovering_episode,
                })
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
                if not recovering_episode:
                    task_message = {"role": "user", "content": episode["prompt"] + ide_context_prompt, "name": "task_bench"}
                    harness.session.record(task_message)
                    harness.session.record_full(task_message.copy())
                harness.observation_metadata = {
                    "entry_type": "task", "source_run_id": self.id, "task_id": self.spec["id"],
                    "step": step_state["id"], "flow_version": resolved_harness_version,
                    "environment": self.spec.get("environment", {}),
                }
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
                    resume_from=str(self._recovery_checkpoint) if recovering_episode else None,
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
                # Pipeline cancellation is cooperative and returns its partial
                # context so the trajectory can be saved.  Do not score that
                # partial episode as passed merely because an earlier artifact
                # already satisfies its checker; the finally block marks the
                # active step with the terminal run status.
                if self.stop_requested or self.state.get("status") in {"stopped", "timeout"}:
                    break
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
                    score = (
                        sum(item.get("score", 0) for item in step_evaluations) / total_episode_count
                        if total_episode_count else 1.0
                    )
                    self.state["evaluation"] = {
                        "score": round(score, 4), "earned": sum(item.get("earned", 0) for item in step_evaluations),
                        "total_weight": sum(item.get("total_weight", 0) for item in step_evaluations),
                        "pass_score": 1.0,
                        "passed": len(step_evaluations) == total_episode_count and all(item.get("passed") for item in step_evaluations),
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
        self.manager._write_summary(self.run_dir, self.public(include_events=False))


class CodexCliTaskRun(TaskRun):
    """Run an unmodified Codex CLI episode behind Task Bench's common contract.

    This is intentionally an adapter, not a reimplementation.  The child owns
    its own model loop and native workspace-write sandbox while Task Bench owns
    fixture materialisation, time limits, deterministic evaluation, immutable
    records and UI projection.  Raw JSONL is retained so comparisons do not
    lose information when Codex adds new event types.
    """

    RUNNER_NAME = "codex_cli"

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.process: Optional[subprocess.Popen[str]] = None
        self.state["runner"] = {
            "name": self.RUNNER_NAME,
            "display_name": "Original Codex CLI",
            "version": "unresolved",
            "boundary": "codex_native_workspace_write",
            "raw_event_format": "codex exec --json",
        }
        self.state["policy"]["external_runner"] = True
        self.state["policy"]["sandbox"] = "Codex native workspace-write"

    @staticmethod
    def executable() -> Optional[str]:
        return shutil.which("codex") or shutil.which("codex.exe")

    def control(self, action: str) -> dict[str, Any]:
        if action == "stop":
            with self.condition:
                self.stop_requested = True
                self.state["status"] = "stopped"
                self.state["error"] = "Task stopped by user"
                process = self.process
                if process is not None and process.poll() is None:
                    try:
                        process.terminate()
                    except OSError:
                        pass
                self.condition.notify_all()
            return self.public()
        raise TaskBenchError("Original Codex CLI only supports Stop; pause/step is a Flow runtime capability")

    def send_input(self, value: str) -> None:
        raise TaskBenchError("Original Codex CLI benchmark episodes are non-interactive")

    def _resolve_version(self, executable: str) -> str:
        try:
            completed = subprocess.run(
                [executable, "--version"], capture_output=True, text=True, timeout=5, shell=False,
            )
            value = (completed.stdout or completed.stderr).strip().splitlines()
            return value[-1][:160] if value else "unknown"
        except (OSError, subprocess.SubprocessError):
            return "unknown"

    def _record_elapsed_seconds(self, completed_at: Optional[float] = None) -> float:
        """Persist wall time for parity with native EgoAgent Task runs.

        Upstream Codex reports token usage but not the enclosing Task Bench wall
        time.  The adapter owns that boundary, so derive it from the same durable
        timestamps shown in the UI instead of leaving comparison tables at zero.
        """

        finished = float(completed_at if completed_at is not None else time.time())
        started = float(self.state.get("started_at") or finished)
        elapsed = max(0.0, finished - started)
        self.state.setdefault("stats", {})["elapsed_seconds"] = elapsed
        return elapsed

    def _external_trace(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("type", "external.event"))
        item = event.get("item") if isinstance(event.get("item"), dict) else {}
        item_type = str(item.get("type", event_type))
        item_id = str(item.get("id", f"event-{len(self.state['events']) + 1}"))
        node_id = f"codex/{item_type}/{item_id[:18]}"
        op_names = {
            "agent_message": "Model",
            "reasoning": "Reasoning",
            "command_execution": "Tool",
            "file_change": "WorkspaceMutation",
            "mcp_tool_call": "Tool",
            "collab_tool_call": "Subagent",
            "web_search": "Browser",
            "todo_list": "Plan",
            "error": "Error",
        }
        with self.lock:
            self.state["events"].append({
                "sequence": len(self.state["events"]) + 1,
                "time": time.time(),
                "type": "external_runner_event",
                "data": _json_clone(event),
            })
            if len(self.state["events"]) > MAX_EVENTS:
                del self.state["events"][:-MAX_EVENTS]
            trace = next(
                (value for value in reversed(self.state["node_traces"]) if value.get("external_item_id") == item_id),
                None,
            )
            if event_type == "item.started" or (item and trace is None):
                trace = _new_trace(len(self.state["node_traces"]) + 1, {
                    "node_id": node_id, "op": op_names.get(item_type, item_type), "agent": "original_codex",
                    "input": item,
                })
                trace["external_item_id"] = item_id
                trace["status"] = "running" if event_type != "item.completed" else "completed"
                self.state["node_traces"].append(trace)
                self.state["step_count"] += 1
            if trace is not None:
                trace["output"] = item
                trace["status"] = "completed" if event_type == "item.completed" else trace.get("status", "running")
                if item_type in {"agent_message", "reasoning"}:
                    trace["model"]["response"] = str(item.get("text", ""))
                elif item_type in {"command_execution", "mcp_tool_call", "collab_tool_call", "web_search"}:
                    trace["tools"] = [{
                        "name": item.get("tool", item.get("server", item_type)),
                        "arguments": item.get("arguments", item.get("command")),
                        "result": item.get("result", item.get("aggregated_output")),
                        "blocked": str(item.get("status", "")).lower() in {"declined", "failed"},
                    }]
            if item_type == "agent_message" and item.get("text"):
                self.state["outputs"].append({
                    "type": "text", "agent": "original_codex", "node_id": node_id, "text": str(item["text"]),
                })
            if event_type == "item.completed" and item_type in {
                "command_execution", "mcp_tool_call", "collab_tool_call", "web_search",
            }:
                self.state["stats"]["tool_calls"] = int(self.state["stats"].get("tool_calls") or 0) + 1
            if event_type == "turn.completed" and isinstance(event.get("usage"), dict):
                usage = event["usage"]
                stats = self.state["stats"]
                stats["model_calls"] = int(stats.get("model_calls") or 0) + 1
                for key in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens"):
                    stats[key] = int(stats.get(key) or 0) + int(usage.get(key) or 0)
                stats["total_tokens"] = int(stats.get("input_tokens") or 0) + int(stats.get("output_tokens") or 0)

    def _run_codex_episode(self, executable: str, prompt: str, episode_id: str) -> tuple[int, str, str]:
        command = [
            executable, "exec", "--json", "--ephemeral", "--skip-git-repo-check",
            "--sandbox", "workspace-write", "-c", 'approval_policy="never"',
            "-C", str(self.workspace), "-",
        ]
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
        process = subprocess.Popen(
            command,
            cwd=str(self.workspace),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            shell=False,
            creationflags=creationflags,
            env=os.environ.copy(),
        )
        self.process = process
        assert process.stdin is not None and process.stdout is not None and process.stderr is not None
        process.stdin.write(prompt)
        process.stdin.close()
        stdout_queue: queue.Queue[Optional[str]] = queue.Queue()
        stderr_lines: list[str] = []

        def read_stdout() -> None:
            try:
                for raw_line in process.stdout:
                    stdout_queue.put(raw_line)
            finally:
                stdout_queue.put(None)

        def read_stderr() -> None:
            for raw_line in process.stderr:
                stderr_lines.append(raw_line)

        threading.Thread(target=read_stdout, daemon=True).start()
        threading.Thread(target=read_stderr, daemon=True).start()
        raw_lines: list[str] = []
        final_response = ""
        deadline = (self.state.get("started_at") or time.time()) + max(
            1.0, float(self.spec.get("execution", {}).get("timeout_seconds", 900))
        )
        stream_complete = False
        while not stream_complete:
            if self.stop_requested or time.time() > deadline:
                try:
                    process.terminate()
                except OSError:
                    pass
                if time.time() > deadline:
                    self.state["status"] = "timeout"
                    self.state["error"] = "Original Codex CLI exceeded the Task timeout"
                break
            try:
                line = stdout_queue.get(timeout=0.15)
            except queue.Empty:
                if process.poll() is not None:
                    continue
                continue
            if line is None:
                stream_complete = True
                continue
            raw_lines.append(line)
            try:
                event = json.loads(line)
            except ValueError:
                event = {"type": "stdout", "text": line.rstrip()}
            self._external_trace(event)
            item = event.get("item") if isinstance(event, dict) else None
            if (
                isinstance(item, dict) and item.get("type") == "agent_message"
                and event.get("type") in {"item.updated", "item.completed"}
            ):
                final_response = str(item.get("text", final_response))
        try:
            return_code = process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            return_code = process.wait(timeout=5)
        self.process = None
        raw_path = self.run_dir / f"codex-{episode_id}.jsonl"
        raw_path.write_text("".join(raw_lines), encoding="utf-8")
        return return_code, final_response, "".join(stderr_lines)[-16_000:]

    def _run(self) -> None:
        messages: list[dict[str, Any]] = []
        try:
            executable = self.executable()
            if not executable:
                raise TaskBenchError("Original Codex CLI was not found on PATH")
            self.state["runner"]["executable"] = executable
            self.state["runner"]["version"] = self._resolve_version(executable)
            episodes = list(self.spec.get("steps") or [{
                "id": "main", "title": self.spec.get("title", "Task"), "prompt": self.spec["prompt"],
                "workspace": {"files": {}}, "evaluation": self.spec.get("evaluation", {}),
            }])
            step_evaluations: list[dict[str, Any]] = []
            for index, episode in enumerate(episodes):
                if self.stop_requested:
                    break
                self._activate_step_workspace(episode)
                step = {
                    "id": str(episode.get("id", index + 1)),
                    "title": str(episode.get("title") or episode.get("id", "Step")),
                    "status": "running", "started_at": time.time(), "completed_at": None, "evaluation": None,
                }
                self.state["task_step"] = step["id"]
                self.state["task_steps"].append(step)
                self._external_trace({"type": "task_step.started", "item": {
                    "id": f"task-step-{step['id']}", "type": "task_step", "title": step["title"],
                }})
                return_code, response, stderr = self._run_codex_episode(executable, str(episode["prompt"]), step["id"])
                if response:
                    messages.append({"role": "assistant", "content": response, "name": "original_codex"})
                if return_code != 0:
                    raise TaskBenchError(f"Original Codex CLI exited {return_code}: {stderr or 'no stderr'}")
                if self.spec.get("steps"):
                    evaluation = evaluate_task(
                        {"evaluation": episode.get("evaluation", {})}, self.workspace,
                        messages=messages, traces=self.state["node_traces"], events=self.state["events"],
                    )
                    step_evaluations.append(evaluation)
                    step["evaluation"] = evaluation
                    step["status"] = "passed" if evaluation["passed"] else "failed"
                    step["completed_at"] = time.time()
                    if not evaluation["passed"]:
                        break
            if self.stop_requested:
                self.state["status"] = "stopped"
            elif self.state["status"] != "timeout":
                self.state["evaluation"] = evaluate_task(
                    self.spec, self.workspace, messages=messages,
                    traces=self.state["node_traces"], events=self.state["events"],
                )
                self.state["status"] = "passed" if self.state["evaluation"]["passed"] else "failed"
        except Exception as error:
            if self.state["status"] not in {"timeout", "stopped"}:
                self.state["status"] = "error"
            self.state["error"] = str(error)
            self._external_trace({"type": "error", "item": {
                "id": "runner-error", "type": "error", "message": str(error),
            }})
        finally:
            with self.condition:
                self.state["task_step"] = None
                self.state["artifacts"] = self._collect_artifacts()
                self.state["mutations"] = self._mutation_summary()
                self.state["completed_at"] = time.time()
                self._record_elapsed_seconds(self.state["completed_at"])
                self.state["running"] = False
                for step in self.state.get("task_steps", []):
                    if step.get("status") == "running":
                        step["status"] = self.state["status"]
                        step["completed_at"] = self.state["completed_at"]
                        step["evaluation"] = self.state.get("evaluation")
                self._persist()
                self.condition.notify_all()


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
                # Listing choices is a read-only, hot UI path. Snapshot only
                # the selected Flow when a run starts; do not hash/write every
                # Harness merely because Evaluate was opened.
                version_index = read_harness_versions(config_path.parent)
                harnesses.append({
                    "name": config_path.parent.name,
                    "description": config.get("description", ""),
                    "slots": config.get("slots", {}),
                    "node_count": len(config.get("pipeline", {}).get("nodes", {})),
                    "latest_version": version_index.get("latest", ""),
                    "versions": list(version_index.get("versions", [])),
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
        codex_executable = CodexCliTaskRun.executable()
        runners = [
            {
                "name": "ego_flow", "display_name": "EgoAgent Flow",
                "description": "Runs an immutable Flow version through EgoAgent's typed runtime.",
                "available": True, "supports_debug": True, "supports_identity": True,
                "boundary": "EgoAgent RuntimePolicy / optional task container",
            },
            {
                "name": "codex_cli", "display_name": "Original Codex CLI",
                "description": "Runs the installed upstream Codex CLI unchanged and ingests its JSONL trajectory.",
                "available": bool(codex_executable), "supports_debug": False, "supports_identity": False,
                "boundary": "Codex native workspace-write sandbox",
                "executable": codex_executable or "",
                "unavailable_reason": "codex executable was not found on PATH" if not codex_executable else "",
            },
        ]
        return {
            "harnesses": harnesses, "identities": identities,
            "environments": environments, "runners": runners,
        }

    def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        spec = self.task(str(payload.get("task_id", "")))
        runner_name = str(payload.get("runner") or "ego_flow")
        if runner_name not in {"ego_flow", "codex_cli"}:
            raise TaskBenchError(f"Unknown Task runner: {runner_name}")
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
            "runner": runner_name,
            "harness": payload.get("harness") or spec.get("selection", {}).get("recommended_harness", "react_single"),
            "harness_version": str(payload.get("harness_version") or "latest"),
            "identity": payload.get("identity") or spec.get("selection", {}).get("recommended_identity", "dante"),
            "environments": list(payload.get("environments", [])),
            "slot_bindings": dict(payload.get("slot_bindings", {})),
            "ide_context": ide_context,
        }
        if runner_name == "ego_flow":
            allowed_harnesses = spec.get("selection", {}).get("compatible_harnesses", [])
            allowed_identities = spec.get("selection", {}).get("compatible_identities", [])
            if allowed_harnesses and selection["harness"] not in allowed_harnesses:
                raise TaskBenchError(f"Harness {selection['harness']} is not compatible with task {spec['id']}")
            if allowed_identities and selection["identity"] not in allowed_identities:
                raise TaskBenchError(f"Identity {selection['identity']} is not compatible with task {spec['id']}")
            harness_dir = self.project_root / "harness" / _safe_name(selection["harness"], "harness")
            try:
                _snapshot_dir, resolved_version = resolve_harness_version_dir(
                    harness_dir, selection["harness_version"]
                )
            except FileNotFoundError as error:
                raise TaskBenchError(str(error)) from error
            # Never persist the floating word "latest" in an experiment record.
            # Replays and comparisons must resolve to the exact Flow bytes that ran.
            selection["harness_version"] = resolved_version
        else:
            if not CodexCliTaskRun.executable():
                raise TaskBenchError("Original Codex CLI was not found on PATH")
            selection["harness"] = "original_codex"
            selection["harness_version"] = "resolved_at_run"
            selection["identity"] = "codex_native"
            selection["slot_bindings"] = {}
        debug_mode = str(payload.get("debug_mode", "auto"))
        if debug_mode not in {"auto", "paused", "step"}:
            raise TaskBenchError("debug_mode must be auto, paused or step")
        if runner_name == "codex_cli" and debug_mode != "auto":
            raise TaskBenchError("Original Codex CLI runner does not support Flow pause/step debugging")
        if spec.get("evolution", {}).get("allowed", False):
            with self.lock:
                if any(
                    item.state.get("running") and item.spec.get("evolution", {}).get("allowed", False)
                    for item in self.runs.values()
                ):
                    raise TaskBenchError("Only one evolution-enabled Task may run at a time")
        run_type = CodexCliTaskRun if runner_name == "codex_cli" else TaskRun
        run = run_type(self, spec, selection, debug_mode)
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

    def _recovery_checkpoint(self, source: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
        """Return the newest completed checkpoint with an executable successor.

        An in-flight checkpoint is deliberately not eligible here: the runtime
        cannot know whether the interrupted side effect happened.  Resuming it
        needs a separate, explicit inspection/confirmation workflow rather
        than a convenient Task Bench button.
        """

        workspace = Path(str(source.get("workspace", ""))).resolve()
        expected_workspace = (
            self.runs_dir / _safe_name(str(source.get("id", "")), "run id") / "workspace"
        ).resolve()
        if workspace != expected_workspace:
            raise TaskBenchError("Recovery workspace does not match the confined Task run directory")
        root = workspace / ".egoagent" / "checkpoints"
        if not root.is_dir():
            raise TaskBenchError("This run has no checkpoint directory")
        candidates: list[tuple[float, Path, dict[str, Any]]] = []
        for path in root.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if payload.get("phase", "completed") != "completed" or payload.get("next_node") is None:
                continue
            candidates.append((float(payload.get("created_at") or path.stat().st_mtime), path, payload))
        if not candidates:
            raise TaskBenchError(
                "No safely resumable completed checkpoint was found; an in-flight side effect must be inspected manually"
            )
        _created_at, path, payload = max(candidates, key=lambda item: item[0])
        return path, payload

    def recover(self, run_id: str, *, debug_mode: str = "auto") -> dict[str, Any]:
        """Create an immutable-lineage recovery run from a terminal Task run."""

        source = self.get(run_id)
        if source.get("running") or source.get("status") not in TERMINAL_STATES:
            raise TaskBenchError("Only a finished Task run can be recovered")
        selection = copy.deepcopy(source.get("selection") or {})
        if selection.get("runner", "ego_flow") != "ego_flow":
            raise TaskBenchError("External runners own their own recovery protocol")
        if debug_mode not in {"auto", "paused", "step"}:
            raise TaskBenchError("debug_mode must be auto, paused or step")
        checkpoint, checkpoint_payload = self._recovery_checkpoint(source)
        task_snapshot = copy.deepcopy(source.get("task") or {})
        if not task_snapshot.get("id"):
            raise TaskBenchError("The source run does not contain an exact Task snapshot")
        step_id = str(
            ((checkpoint_payload.get("data") or {}).get("task") or {}).get("step")
            or source.get("task_step")
            or "main"
        )
        recovery = {
            "source_state": source,
            "source_workspace": source.get("workspace"),
            "checkpoint": str(checkpoint),
            "checkpoint_phase": checkpoint_payload.get("phase", "completed"),
            "step_id": step_id,
        }
        run = TaskRun(self, task_snapshot, selection, debug_mode, recovery=recovery)
        with self.lock:
            self.runs[run.id] = run
        try:
            run.start()
        except Exception:
            with self.lock:
                self.runs.pop(run.id, None)
            raise
        return run.public()

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 200))
        summaries: dict[str, dict[str, Any]] = {}
        legacy = []
        paths = sorted(self.runs_dir.glob("*/run.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:limit]
        for path in paths:
            try:
                index = path.with_name("summary.json")
                if index.is_file():
                    summary = json.loads(index.read_text(encoding="utf-8"))
                elif path.stat().st_size < 262144:
                    summary = self._write_summary(path.parent, json.loads(path.read_text(encoding="utf-8")))
                else:
                    # Legacy GB-scale recordings migrate in the background;
                    # they remain selectable by id while the small index builds.
                    summary = {"id": path.parent.name, "status": "indexing", "created_at": path.stat().st_mtime}
                    legacy.append(path)
                summaries[summary["id"]] = summary
            except (OSError, ValueError, KeyError):
                continue
        with self.lock:
            for run_id, run in self.runs.items():
                summaries[run_id] = self._summary(run.public(include_events=False))
            worker = getattr(self, "_history_index_thread", None)
            if legacy and not (worker and worker.is_alive()):
                def migrate():
                    for path in legacy:
                        try:
                            self._write_summary(path.parent, json.loads(path.read_text(encoding="utf-8")))
                        except (OSError, ValueError):
                            continue
                self._history_index_thread = threading.Thread(target=migrate, daemon=True, name="task-history-index")
                self._history_index_thread.start()
        return sorted(summaries.values(), key=lambda item: item.get("created_at") or 0, reverse=True)[:limit]

    @staticmethod
    def _summary(data: dict[str, Any]) -> dict[str, Any]:
        summary = {key: data.get(key) for key in (
            "id", "task_id", "selection", "status", "running", "created_at", "started_at", "completed_at", "evaluation", "error"
        )}
        # This is only an availability hint. recover() still validates the exact
        # completed-node checkpoint and workspace before executing anything.
        workspace = data.get("workspace")
        summary["recovery_available"] = bool(
            workspace and not data.get("running") and data.get("status") in TERMINAL_STATES
            and (data.get("selection") or {}).get("runner", "ego_flow") == "ego_flow"
            and next((Path(workspace) / ".egoagent" / "checkpoints").glob("*.json"), None)
        )
        return summary

    def _write_summary(self, directory: Path, data: dict[str, Any]) -> dict[str, Any]:
        summary = self._summary(data)
        temp = directory / f"summary.{uuid.uuid4().hex}.tmp"
        temp.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
        temp.replace(directory / "summary.json")
        return summary

    def compare_runs(self, run_ids: Iterable[str]) -> dict[str, Any]:
        """Build a deterministic, UI-ready comparison without an LLM judge.

        Raw runs remain canonical.  This projection aligns node invocations by
        sequence so two different Flow structures can still be inspected side
        by side instead of pretending that equal node names imply equal work.
        """
        ids = list(dict.fromkeys(_safe_name(value, "run id") for value in run_ids))
        if len(ids) < 2 or len(ids) > 8:
            raise TaskBenchError("Compare between 2 and 8 Task runs")
        runs = [self.get(run_id) for run_id in ids]

        def summary(run: dict[str, Any]) -> dict[str, Any]:
            started = run.get("started_at")
            completed = run.get("completed_at")
            stats = run.get("stats") or {}
            evaluation = run.get("evaluation") or {}
            return {
                "id": run.get("id"), "task_id": run.get("task_id"), "status": run.get("status"),
                "runner": (run.get("selection") or {}).get("runner", "ego_flow"),
                "runner_version": (run.get("runner") or {}).get("version"),
                "harness": (run.get("selection") or {}).get("harness"),
                "harness_version": (run.get("selection") or {}).get("harness_version"),
                "identity": (run.get("selection") or {}).get("identity"),
                "score": evaluation.get("score"), "passed": evaluation.get("passed"),
                "duration_seconds": round(float(completed) - float(started), 3) if started and completed else None,
                "model_calls": stats.get("model_calls"), "tool_calls": stats.get("tool_calls"),
                "tokens": stats.get("tokens") or stats.get("total_tokens"),
                "steps": run.get("step_count", 0), "error": run.get("error"),
                "evolution_events": len(run.get("evolution_events") or []),
            }

        summaries = [summary(run) for run in runs]
        trace_rows = []
        longest = max(len(run.get("node_traces") or []) for run in runs)
        for index in range(longest):
            lanes = []
            signatures = []
            for run in runs:
                traces = run.get("node_traces") or []
                trace = traces[index] if index < len(traces) else None
                if trace is None:
                    lanes.append(None)
                    signatures.append(None)
                    continue
                model = trace.get("model") or {}
                tools = trace.get("tools") or []
                lane = {
                    "sequence": trace.get("sequence"), "node_id": trace.get("node_id"),
                    "op": trace.get("op"), "agent": trace.get("agent"), "status": trace.get("status"),
                    "model_response": str(model.get("response") or ""),
                    "tool_names": [str(tool.get("name") or "") for tool in tools],
                    "output": trace.get("output"), "error": trace.get("error"),
                }
                lanes.append(lane)
                signatures.append((lane["op"], lane["agent"], lane["status"], tuple(lane["tool_names"])))
            present = [signature for signature in signatures if signature is not None]
            trace_rows.append({
                "index": index + 1,
                "diverged": len(present) != len(signatures) or len(set(present)) > 1,
                "lanes": lanes,
            })
        return {
            "schema": "ego.task-run-comparison.v1",
            "created_at": time.time(),
            "runs": summaries,
            "same_task": len({item.get("task_id") for item in summaries}) == 1,
            "trace_rows": trace_rows,
            "evolution": [{
                "run_id": run.get("id"),
                "events": run.get("evolution_events") or [],
                "final_mutations": run.get("mutations") or {},
            } for run in runs],
        }

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
