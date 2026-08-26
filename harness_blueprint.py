"""Weak-model-friendly Harness Blueprint compiler and transaction service.

The runtime config is intentionally expressive, but that makes it a poor edit
format for small models.  A Blueprint keeps the graph as an ordered list of
steps with a compact vocabulary and explicit routes.  Compilation is
deterministic; all writes are validated, revision checked and made atomically.
"""

from __future__ import annotations

import copy
import difflib
import hashlib
import json
import os
import re
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

from pipeline_schema import SUPPORTED_OPS, canonical_op, validate_pipeline


BLUEPRINT_VERSION = 1

# The left side is deliberately short and stable.  The right side is the
# canonical runtime operation understood by PipelineRunner and Studio.
STEP_TYPE_TO_OP = {
    "input": "输入",
    "agent": "Agent",
    "tool_review": "工具审查",
    "text": "文本处理",
    "tool": "工具",
    "process": "进程",
    "workspace": "工作区",
    "python": "Python",
    "model": "模型",
    "context": "上下文",
    "memory": "记忆",
    "if": "条件",
    "data": "数据",
    "set": "保存数据",
    "get": "读取数据",
    "loop": "循环",
    "parallel": "并行",
    "map": "映射",
    "join": "合并",
    "approval": "人工审批",
    "subflow": "子流程",
    "checkpoint": "检查点",
    "output": "输出",
    "end": "结束",
}
OP_TO_STEP_TYPE = {value: key for key, value in STEP_TYPE_TO_OP.items()}

CONDITION_ALIASES = {
    "tool": "has_tool_calls",
    "tools": "has_tool_calls",
    "text": "has_text",
    "yes": "true",
    "no": "false",
    "otherwise": "default",
    "else": "default",
}

_SAFE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,79}$")
_RESERVED_STEP_FIELDS = {
    "id", "type", "op", "role", "agent", "next", "on", "routes", "config",
}


class BlueprintError(ValueError):
    """A user/model supplied Blueprint or patch is invalid."""


class RevisionConflict(BlueprintError):
    """The Harness changed after the model inspected it."""


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _revision(config: dict) -> str:
    payload = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _safe_name(value: Any, label: str) -> str:
    name = str(value or "").strip()
    if not _SAFE_NAME.fullmatch(name):
        raise BlueprintError(
            f"{label} must start with a letter/underscore and contain only letters, digits, '_' or '-'"
        )
    return name


def _deep_merge(target: dict, changes: dict) -> dict:
    """Merge a patch object.  ``null`` deletes a field."""
    result = copy.deepcopy(target)
    for key, value in changes.items():
        if value is None:
            result.pop(key, None)
        elif isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _normalize_roles(raw: Any) -> dict[str, dict]:
    if isinstance(raw, list):
        raw = {str(name): {"description": "", "required": True} for name in raw}
    if not isinstance(raw, dict) or not raw:
        raise BlueprintError("roles must be a non-empty object or list")
    roles: dict[str, dict] = {}
    for name, definition in raw.items():
        role = _safe_name(name, "role name")
        if isinstance(definition, str):
            definition = {"description": definition, "required": True}
        if not isinstance(definition, dict):
            raise BlueprintError(f"role {role!r} must be an object or description string")
        normalized = copy.deepcopy(definition)
        normalized.setdefault("description", "")
        normalized.setdefault("required", True)
        roles[role] = normalized
    return roles


def _normalize_route(route: dict) -> dict:
    if not isinstance(route, dict):
        raise BlueprintError("each route must be an object")
    target = route.get("to")
    condition = str(route.get("condition", "default") or "default")
    condition = CONDITION_ALIASES.get(condition, condition)
    normalized = {"condition": condition, "to": target}
    if route.get("when") is not None:
        normalized["when"] = str(route["when"])
    return normalized


def _step_routes(step: dict) -> list[dict]:
    routes: list[dict] = []
    if "routes" in step:
        raw_routes = step.get("routes")
        if not isinstance(raw_routes, list):
            raise BlueprintError(f"step {step.get('id')!r}.routes must be an array")
        routes.extend(_normalize_route(route) for route in raw_routes)
    if "on" in step:
        on = step.get("on")
        if not isinstance(on, dict):
            raise BlueprintError(f"step {step.get('id')!r}.on must be an object")
        for condition, target in on.items():
            routes.append(_normalize_route({"condition": condition, "to": target}))
    if "next" in step and not any(route["condition"] == "default" for route in routes):
        routes.append({"condition": "default", "to": step.get("next")})
    return routes


def compile_blueprint(blueprint: dict, *, name: str | None = None) -> tuple[dict, list[str]]:
    """Compile a compact Blueprint into the full Harness config.

    Returns ``(config, warnings)``.  It never writes to disk.
    """
    if not isinstance(blueprint, dict):
        raise BlueprintError("blueprint must be an object")
    version = int(blueprint.get("version", BLUEPRINT_VERSION))
    if version != BLUEPRINT_VERSION:
        raise BlueprintError(f"unsupported blueprint version: {version}")
    harness_name = _safe_name(name or blueprint.get("name"), "harness name")
    roles = _normalize_roles(blueprint.get("roles", blueprint.get("slots")))
    raw_steps = blueprint.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise BlueprintError("steps must be a non-empty array")

    nodes: dict[str, dict] = {}
    ordered_ids: list[str] = []
    warnings: list[str] = []
    default_role = next(iter(roles)) if len(roles) == 1 else None

    for raw_step in raw_steps:
        if not isinstance(raw_step, dict):
            raise BlueprintError("each step must be an object")
        step_id = _safe_name(raw_step.get("id"), "step id")
        if step_id in nodes:
            raise BlueprintError(f"duplicate step id: {step_id}")
        raw_type = str(raw_step.get("type", raw_step.get("op", ""))).strip()
        op = STEP_TYPE_TO_OP.get(raw_type, canonical_op(raw_type))
        if op not in SUPPORTED_OPS:
            raise BlueprintError(
                f"step {step_id!r} has unknown type {raw_type!r}; use one of {sorted(STEP_TYPE_TO_OP)}"
            )

        config = raw_step.get("config", {})
        if not isinstance(config, dict):
            raise BlueprintError(f"step {step_id!r}.config must be an object")
        node = copy.deepcopy(config)
        # Friendly top-level properties are allowed so an 8B model does not
        # have to remember which fields live inside ``config``.
        for key, value in raw_step.items():
            if key not in _RESERVED_STEP_FIELDS:
                node[key] = copy.deepcopy(value)
        node["op"] = op

        role = raw_step.get("role", raw_step.get("agent", node.get("agent")))
        if role is None and op in {"Agent", "工具", "工具审查", "文本处理", "模型"}:
            role = default_role
        if role is not None:
            role = _safe_name(role, f"step {step_id!r} role")
            if role not in roles:
                raise BlueprintError(f"step {step_id!r} references missing role {role!r}")
            node["agent"] = role
        elif op in {"Agent", "工具", "工具审查", "文本处理"}:
            raise BlueprintError(f"step {step_id!r} ({raw_type}) needs a role because multiple roles exist")

        routes = _step_routes(raw_step)
        if routes:
            node["edges"] = routes
        else:
            node.setdefault("edges", [])
        nodes[step_id] = node
        ordered_ids.append(step_id)
        if op == "Python":
            warnings.append(
                f"step {step_id!r} uses Python; prefer if/data/workspace/process/subflow unless code is unavoidable"
            )

    start = str(blueprint.get("start") or ordered_ids[0])
    if start not in nodes:
        raise BlueprintError(f"start points to missing step {start!r}")

    for step_id, node in nodes.items():
        for route in node.get("edges", []):
            target = route.get("to")
            if target is not None and target not in nodes:
                raise BlueprintError(f"step {step_id!r} routes to missing step {target!r}")

    settings = blueprint.get("settings", {})
    if not isinstance(settings, dict):
        raise BlueprintError("settings must be an object")
    pipeline = copy.deepcopy(settings)
    pipeline.update({
        "start": start,
        "max_steps": int(blueprint.get("max_steps", pipeline.get("max_steps", 100))),
        "workspace_preview": bool(
            blueprint.get("workspace_preview", pipeline.get("workspace_preview", False))
        ),
        "nodes": nodes,
    })
    config = {
        "name": harness_name,
        "description": str(blueprint.get("description", "")),
        "slots": roles,
        "prompts": copy.deepcopy(blueprint.get("prompts", {})),
        "return_mode": str(blueprint.get("return_mode", "last")),
        "pipeline": pipeline,
    }
    if blueprint.get("identity_bindings"):
        bindings = blueprint.get("identity_bindings")
        if not isinstance(bindings, dict) or any(role not in roles for role in bindings):
            raise BlueprintError("identity_bindings must reference declared roles")
        config["identity_bindings"] = copy.deepcopy(bindings)
    if blueprint.get("permissions"):
        if not isinstance(blueprint.get("permissions"), dict):
            raise BlueprintError("permissions must be an object")
        config["permissions"] = copy.deepcopy(blueprint["permissions"])
    if config["return_mode"] not in {"all", "last"}:
        raise BlueprintError("return_mode must be 'all' or 'last'")
    errors = validate_pipeline(pipeline)
    if errors:
        raise BlueprintError("invalid compiled pipeline:\n- " + "\n- ".join(errors))

    reachable = _reachable_nodes(pipeline)
    unreachable = [step_id for step_id in ordered_ids if step_id not in reachable]
    if unreachable:
        warnings.append("unreachable steps: " + ", ".join(unreachable))
    return config, warnings


def decompile_config(config: dict) -> dict:
    """Convert an existing full config to the compact, round-trippable form."""
    if not isinstance(config, dict) or not isinstance(config.get("pipeline"), dict):
        raise BlueprintError("config has no pipeline")
    pipeline = config["pipeline"]
    errors = validate_pipeline(pipeline)
    if errors:
        raise BlueprintError("invalid pipeline:\n- " + "\n- ".join(errors))
    steps = []
    for step_id, node in pipeline.get("nodes", {}).items():
        op = canonical_op(node.get("op", ""))
        extras = {
            key: copy.deepcopy(value)
            for key, value in node.items()
            if key not in {"op", "agent", "edges", "id"}
        }
        step = {
            "id": step_id,
            "type": OP_TO_STEP_TYPE.get(op, op),
        }
        if node.get("agent") is not None:
            step["role"] = node["agent"]
        if node.get("edges"):
            step["routes"] = copy.deepcopy(node["edges"])
        if extras:
            step["config"] = extras
        steps.append(step)
    settings = {
        key: copy.deepcopy(value)
        for key, value in pipeline.items()
        if key not in {"start", "max_steps", "workspace_preview", "nodes"}
    }
    blueprint = {
        "version": BLUEPRINT_VERSION,
        "name": config.get("name", "harness"),
        "description": config.get("description", ""),
        "roles": copy.deepcopy(config.get("slots", {})),
        "start": pipeline.get("start"),
        "steps": steps,
        "max_steps": pipeline.get("max_steps", 100),
        "workspace_preview": pipeline.get("workspace_preview", False),
        "return_mode": config.get("return_mode", "last"),
        "prompts": copy.deepcopy(config.get("prompts", {})),
        "identity_bindings": copy.deepcopy(config.get("identity_bindings", {})),
        "permissions": copy.deepcopy(config.get("permissions", {})),
    }
    if settings:
        blueprint["settings"] = settings
    return blueprint


def _reachable_nodes(pipeline: dict) -> set[str]:
    nodes = pipeline.get("nodes", {})
    pending = [pipeline.get("start")]
    seen: set[str] = set()
    pointer_fields = {
        "error_to", "empty_response_to", "tool_call_count_error_to", "stuck_to",
        "end_session_to", "auto_continue_to", "body_start", "join",
    }
    while pending:
        current = pending.pop()
        if current in seen or current not in nodes:
            continue
        seen.add(current)
        node = nodes[current]
        pending.extend(route.get("to") for route in node.get("edges", []) if route.get("to"))
        pending.extend(node.get(field) for field in pointer_fields if node.get(field))
        for branch in node.get("branches", []):
            pending.append(branch.get("start") if isinstance(branch, dict) else branch)
    return seen


def blueprint_guide() -> dict:
    """Small enough to place directly in an 8B model's tool description."""
    from dag_contracts import compact_agent_contracts

    return {
        "version": BLUEPRINT_VERSION,
        "shape": {
            "name": "snake_case_name",
            "description": "what the Agent system does",
            "roles": {"worker": "role description"},
            "start": "first_step_id",
            "steps": [
                {
                    "id": "think",
                    "type": "agent",
                    "role": "worker",
                    "on": {"tools": "act", "text": "finish"},
                    "config": {"tools": "auto"},
                }
            ],
        },
        "step_types": sorted(STEP_TYPE_TO_OP),
        "common_routes": ["input", "tools", "text", "true", "false", "error", "default"],
        "references": ["$ctx.key", "$node.step_id.value", "$last.value", "$input"],
        "node_contracts": compact_agent_contracts(),
        "rules": [
            "Use if/data/set/get/workspace/process before python.",
            "Every route target must be an existing step id.",
            "Agent/tool steps use a role from roles.",
            "For one role, role may be omitted and is filled automatically.",
            "Use config only for advanced fields; friendly fields may also be placed on the step.",
        ],
    }


def apply_blueprint_operations(blueprint: dict, operations: Iterable[dict]) -> dict:
    """Apply constrained structural operations to a Blueprint in memory."""
    result = copy.deepcopy(blueprint)
    operations = list(operations)
    if not operations:
        raise BlueprintError("operations cannot be empty")

    def index_of(step_id: str) -> int:
        for index, step in enumerate(result.get("steps", [])):
            if step.get("id") == step_id:
                return index
        raise BlueprintError(f"step not found: {step_id}")

    for position, operation in enumerate(operations):
        if not isinstance(operation, dict):
            raise BlueprintError(f"operation {position} must be an object")
        action = str(operation.get("op", ""))
        if action == "replace_blueprint":
            replacement = operation.get("blueprint")
            if not isinstance(replacement, dict):
                raise BlueprintError("replace_blueprint requires blueprint")
            result = copy.deepcopy(replacement)
        elif action == "add_step":
            step = copy.deepcopy(operation.get("step"))
            if not isinstance(step, dict):
                raise BlueprintError("add_step requires step")
            _safe_name(step.get("id"), "step id")
            if any(existing.get("id") == step.get("id") for existing in result["steps"]):
                raise BlueprintError(f"step already exists: {step.get('id')}")
            if operation.get("after") is not None:
                result["steps"].insert(index_of(str(operation["after"])) + 1, step)
            elif operation.get("before") is not None:
                result["steps"].insert(index_of(str(operation["before"])), step)
            else:
                result["steps"].append(step)
        elif action in {"update_step", "replace_step"}:
            step_id = str(operation.get("id", ""))
            index = index_of(step_id)
            value = operation.get("changes" if action == "update_step" else "step")
            if not isinstance(value, dict):
                raise BlueprintError(f"{action} requires an object value")
            if action == "update_step":
                result["steps"][index] = _deep_merge(result["steps"][index], value)
            else:
                replacement = copy.deepcopy(value)
                replacement.setdefault("id", step_id)
                result["steps"][index] = replacement
        elif action == "remove_step":
            step_id = str(operation.get("id", ""))
            index = index_of(step_id)
            if result.get("start") == step_id:
                new_start = operation.get("new_start")
                if not new_start:
                    raise BlueprintError("removing the start step requires new_start")
                result["start"] = str(new_start)
            result["steps"].pop(index)
            # Remove incoming routes.  Explicit reconnection is required,
            # which prevents a small model from silently inventing semantics.
            for step in result["steps"]:
                step["routes"] = [
                    route for route in step.get("routes", []) if route.get("to") != step_id
                ]
                if step.get("next") == step_id:
                    step.pop("next", None)
                if isinstance(step.get("on"), dict):
                    step["on"] = {k: v for k, v in step["on"].items() if v != step_id}
        elif action == "connect":
            source = str(operation.get("from", ""))
            step = result["steps"][index_of(source)]
            condition = CONDITION_ALIASES.get(
                str(operation.get("condition", "default")), str(operation.get("condition", "default"))
            )
            target = operation.get("to")
            route = {"condition": condition, "to": target}
            if operation.get("when") is not None:
                route["when"] = str(operation["when"])
            routes = list(step.get("routes", []))
            if operation.get("replace", True):
                routes = [item for item in routes if item.get("condition") != condition]
            routes.append(route)
            step["routes"] = routes
            step.pop("next", None)
            step.pop("on", None)
        elif action == "disconnect":
            source = str(operation.get("from", ""))
            step = result["steps"][index_of(source)]
            condition = operation.get("condition")
            target = operation.get("to")
            step["routes"] = [
                route for route in step.get("routes", [])
                if not (
                    (condition is None or route.get("condition") == CONDITION_ALIASES.get(str(condition), str(condition)))
                    and (target is None or route.get("to") == target)
                )
            ]
        elif action == "set_start":
            result["start"] = str(operation.get("id", ""))
        elif action == "set_role":
            role = _safe_name(operation.get("name"), "role name")
            roles = result.setdefault("roles", {})
            definition = operation.get("definition", {})
            roles[role] = copy.deepcopy(definition)
        elif action == "remove_role":
            role = str(operation.get("name", ""))
            for step in result.get("steps", []):
                if step.get("role") == role:
                    raise BlueprintError(f"role {role!r} is still used by step {step.get('id')!r}")
            result.setdefault("roles", {}).pop(role, None)
            result.setdefault("identity_bindings", {}).pop(role, None)
        elif action == "rebind_identity":
            role = _safe_name(operation.get("role"), "role name")
            if role not in result.setdefault("roles", {}):
                raise BlueprintError(f"cannot bind undeclared role {role!r}")
            identity = _safe_name(operation.get("identity"), "identity name")
            result.setdefault("identity_bindings", {})[role] = identity
        elif action == "unbind_identity":
            role = _safe_name(operation.get("role"), "role name")
            result.setdefault("identity_bindings", {}).pop(role, None)
        elif action == "set_permissions":
            value = operation.get("permissions")
            if not isinstance(value, dict):
                raise BlueprintError("set_permissions requires an object")
            result["permissions"] = copy.deepcopy(value)
        elif action == "set_ports":
            step_id = str(operation.get("id", ""))
            ports = operation.get("ports")
            if not isinstance(ports, dict):
                raise BlueprintError("set_ports requires an object")
            step = result["steps"][index_of(step_id)]
            step.setdefault("config", {})["ports"] = copy.deepcopy(ports)
        elif action == "set_limits":
            if operation.get("max_steps") is not None:
                maximum = int(operation["max_steps"])
                if maximum < 1 or maximum > 100000:
                    raise BlueprintError("max_steps must be between 1 and 100000")
                result["max_steps"] = maximum
        elif action == "set_return":
            mode = str(operation.get("mode", ""))
            if mode not in {"last", "all"}:
                raise BlueprintError("set_return mode must be last or all")
            result["return_mode"] = mode
        elif action == "set_prompt":
            prompt = _safe_name(operation.get("name"), "prompt name")
            result.setdefault("prompts", {})[prompt] = copy.deepcopy(operation.get("value", ""))
        elif action == "remove_prompt":
            result.setdefault("prompts", {}).pop(str(operation.get("name", "")), None)
        elif action == "set_fields":
            changes = operation.get("changes")
            if not isinstance(changes, dict):
                raise BlueprintError("set_fields requires changes")
            protected = {"version", "steps", "roles"}
            if protected.intersection(changes):
                raise BlueprintError("set_fields cannot replace version, steps or roles")
            result = _deep_merge(result, changes)
        else:
            raise BlueprintError(f"unknown operation {action!r}")
    return result


class HarnessBlueprintService:
    """Filesystem transaction boundary used by model tools and the Studio API."""

    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root).resolve()
        self.harness_root = self.project_root / "harness"
        self.transaction_root = self.project_root / "self_evolution" / "data" / "harness_transactions"

    def _harness_dir(self, name: str) -> Path:
        safe = _safe_name(name, "harness name")
        path = (self.harness_root / safe).resolve()
        if path.parent != self.harness_root.resolve():
            raise BlueprintError("harness path escapes harness root")
        return path

    def load(self, name: str) -> dict:
        path = self._harness_dir(name) / "config.json"
        if not path.is_file():
            raise BlueprintError(f"harness not found: {name}")
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise BlueprintError(f"cannot read harness {name!r}: {error}") from error
        blueprint = decompile_config(config)
        return {"blueprint": blueprint, "config": config, "revision": _revision(config)}

    def validate(self, blueprint: dict, *, name: str | None = None) -> dict:
        config, warnings = compile_blueprint(blueprint, name=name)
        return {"ok": True, "config": config, "revision": _revision(config), "warnings": warnings}

    def create(self, blueprint: dict, *, dry_run: bool = False) -> dict:
        config, warnings = compile_blueprint(blueprint)
        harness_dir = self._harness_dir(config["name"])
        path = harness_dir / "config.json"
        if path.exists():
            raise BlueprintError(f"harness already exists: {config['name']}")
        result = {
            "ok": True,
            "action": "create",
            "harness": config["name"],
            "revision": _revision(config),
            "warnings": warnings,
            "config": config,
            "blueprint": decompile_config(config),
            "dry_run": bool(dry_run),
        }
        if not dry_run:
            harness_dir.mkdir(parents=True, exist_ok=False)
            _atomic_write(path, _json_text(config))
        return result

    def patch(
        self,
        name: str,
        operations: Iterable[dict],
        *,
        expected_revision: str | None = None,
        dry_run: bool = False,
        reason: str = "",
        actor: str = "agent",
    ) -> dict:
        loaded = self.load(name)
        if expected_revision and expected_revision != loaded["revision"]:
            raise RevisionConflict(
                f"revision conflict: expected {expected_revision}, current {loaded['revision']}; reload before patching"
            )
        operations = list(operations)
        updated_blueprint = apply_blueprint_operations(loaded["blueprint"], operations)
        updated_blueprint["name"] = name
        updated_config, warnings = compile_blueprint(updated_blueprint, name=name)
        before_text = _json_text(loaded["config"])
        after_text = _json_text(updated_config)
        diff = "".join(difflib.unified_diff(
            before_text.splitlines(keepends=True),
            after_text.splitlines(keepends=True),
            fromfile=f"harness/{name}/config.json@{loaded['revision']}",
            tofile=f"harness/{name}/config.json@{_revision(updated_config)}",
        ))
        transaction_id = f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        transaction = {
            "version": 1,
            "id": transaction_id,
            "timestamp": time.time(),
            "harness": name,
            "actor": actor,
            "reason": reason,
            "revision_before": loaded["revision"],
            "revision_after": _revision(updated_config),
            "operations": copy.deepcopy(operations),
            "warnings": warnings,
            "before": loaded["config"],
            "after": updated_config,
            "diff": diff,
        }
        result = {
            "ok": True,
            "action": "patch",
            "harness": name,
            "transaction_id": transaction_id,
            "revision_before": loaded["revision"],
            "revision": _revision(updated_config),
            "warnings": warnings,
            "diff": diff,
            "blueprint": decompile_config(updated_config),
            "config": updated_config,
            "dry_run": bool(dry_run),
        }
        if not dry_run:
            self.transaction_root.mkdir(parents=True, exist_ok=True)
            _atomic_write(self.transaction_root / f"{transaction_id}.json", _json_text(transaction))
            _atomic_write(self._harness_dir(name) / "config.json", after_text)
        return result

    def rollback(self, transaction_id: str, *, expected_revision: str | None = None) -> dict:
        tx_name = str(transaction_id or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", tx_name):
            raise BlueprintError("invalid transaction id")
        path = self.transaction_root / f"{tx_name}.json"
        if not path.is_file():
            raise BlueprintError(f"transaction not found: {tx_name}")
        transaction = json.loads(path.read_text(encoding="utf-8"))
        name = transaction["harness"]
        loaded = self.load(name)
        required = expected_revision or transaction["revision_after"]
        if loaded["revision"] != required:
            raise RevisionConflict(
                f"rollback conflict: expected current revision {required}, got {loaded['revision']}"
            )
        before = transaction["before"]
        compile_blueprint(decompile_config(before), name=name)
        _atomic_write(self._harness_dir(name) / "config.json", _json_text(before))
        return {
            "ok": True,
            "action": "rollback",
            "harness": name,
            "transaction_id": tx_name,
            "revision": _revision(before),
        }


def legacy_modify_harness(
    project_root: str | Path,
    harness_name: str,
    action: str,
    target: str,
    value,
    *,
    actor: str = "legacy:modify_harness",
) -> dict:
    """Route the old mutation vocabulary through Blueprint transactions.

    The old tool signature remains available for saved identities, but the
    candidate is now schema-validated, revision checked, diffed and recorded
    as a reversible transaction. New model-facing code should use
    ``manage_harness`` instead.
    """
    service = HarnessBlueprintService(project_root)
    loaded = service.load(harness_name)
    config = copy.deepcopy(loaded["config"])
    try:
        parsed_value = json.loads(value) if isinstance(value, str) and value else value
    except json.JSONDecodeError:
        parsed_value = value

    pipeline = config.setdefault("pipeline", {})
    nodes = pipeline.setdefault("nodes", {})

    if action == "update_node":
        if target not in nodes:
            raise BlueprintError(f"node not found: {target}")
        if not isinstance(parsed_value, dict):
            raise BlueprintError("update_node value must be a JSON object")
        nodes[target] = _deep_merge(nodes[target], copy.deepcopy(parsed_value))
    elif action == "add_node":
        if not isinstance(parsed_value, dict) or not parsed_value.get("id"):
            raise BlueprintError('add_node value must contain an "id"')
        node_value = copy.deepcopy(parsed_value)
        node_id = _safe_name(node_value.pop("id"), "node id")
        if node_id in nodes:
            raise BlueprintError(f"node already exists: {node_id}")
        nodes[node_id] = node_value
    elif action == "remove_node":
        if target not in nodes:
            raise BlueprintError(f"node not found: {target}")
        del nodes[target]
        for node in nodes.values():
            node["edges"] = [edge for edge in node.get("edges", []) if edge.get("to") != target]
        if pipeline.get("start") == target:
            raise BlueprintError("cannot remove the start node without choosing a new start; use manage_harness")
    elif action == "update_edge":
        if not isinstance(parsed_value, dict):
            raise BlueprintError("update_edge value must be a JSON object")
        source = str(parsed_value.get("source_node") or target)
        if source not in nodes:
            raise BlueprintError(f"source node not found: {source}")
        index = int(parsed_value.get("edge_index", 0))
        edge = parsed_value.get("new_edge")
        if not isinstance(edge, dict):
            raise BlueprintError("update_edge requires new_edge")
        edges = list(nodes[source].get("edges", []))
        if index < 0 or index > len(edges):
            raise BlueprintError(f"edge_index out of range: {index}")
        if index == len(edges):
            edges.append(copy.deepcopy(edge))
        else:
            edges[index] = copy.deepcopy(edge)
        nodes[source]["edges"] = edges
    elif action == "set_field":
        parts = [part for part in str(target).split(".") if part]
        if not parts or any(part in {"__proto__", "constructor"} for part in parts):
            raise BlueprintError("invalid field path")
        current = config
        for part in parts[:-1]:
            child = current.setdefault(part, {})
            if not isinstance(child, dict):
                raise BlueprintError(f"field path crosses a non-object at {part}")
            current = child
        current[parts[-1]] = copy.deepcopy(parsed_value)
    elif action == "replace_pipeline":
        if not isinstance(parsed_value, dict):
            raise BlueprintError("replace_pipeline value must be a JSON object")
        config["pipeline"] = copy.deepcopy(parsed_value)
    else:
        raise BlueprintError(
            "unknown legacy action; use manage_harness for the current Blueprint operation vocabulary"
        )

    # Small models frequently vary the casing of the friendly operation name
    # (for example ``If`` instead of ``if``). Canonicalize every node here so
    # the compatibility adapter is forgiving while the final schema remains
    # strict about the resulting runtime operation.
    for node in config.get("pipeline", {}).get("nodes", {}).values():
        raw_op = node.get("op")
        if isinstance(raw_op, str):
            normalized = canonical_op(raw_op)
            if normalized == raw_op:
                normalized = canonical_op(raw_op.lower())
            node["op"] = normalized

    candidate = decompile_config(config)
    result = service.patch(
        harness_name,
        [{"op": "replace_blueprint", "blueprint": candidate}],
        expected_revision=loaded["revision"],
        reason=f"legacy compatibility action: {action} {target}",
        actor=actor,
    )
    return {
        "success": True,
        "harness": harness_name,
        "action": action,
        "target": target,
        "transaction_id": result["transaction_id"],
        "revision_before": result["revision_before"],
        "revision": result["revision"],
        "diff": result["diff"],
        "warnings": result["warnings"],
        "current_nodes": list(result["config"].get("pipeline", {}).get("nodes", {})),
    }


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
