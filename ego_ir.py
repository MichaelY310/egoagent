"""Canonical, typed, line-oriented representation of an EgoAgent Harness.

EgoIR is intentionally less error-prone than one large nested JSON document:
each line is an independent record and common structural edits touch one line.
JSON payloads keep strings unambiguous and preserve unknown runtime fields, so
compile/decompile is lossless for current Harness configs.
"""

from __future__ import annotations

import copy
import difflib
import hashlib
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

from dag_contracts import PORT_TYPES, compact_agent_contracts
from pipeline_schema import SUPPORTED_OPS, canonical_op, validate_pipeline


EGOIR_VERSION = 1
RECORD_ORDER = {name: index for index, name in enumerate(("harness", "role", "bind", "permission", "prompt", "node", "edge", "start"))}


class EgoIRError(ValueError):
    pass


def revision(value: dict[str, Any]) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _name(value: Any, label: str) -> str:
    result = str(value or "").strip()
    if not re.fullmatch(r"[\w-]+", result, re.UNICODE) or result in {".", ".."}:
        raise EgoIRError(f"invalid {label}: {value!r}")
    return result


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _validate_ports(node_id: str, ports: Any) -> None:
    if ports is None:
        return
    if not isinstance(ports, dict):
        raise EgoIRError(f"node {node_id}.ports must be an object")
    for direction in ("in", "out"):
        values = ports.get(direction, {})
        if not isinstance(values, dict):
            raise EgoIRError(f"node {node_id}.ports.{direction} must be an object")
        for name, definition in values.items():
            _name(name, f"node {node_id} port")
            port_type = definition.get("type", "any") if isinstance(definition, dict) else definition
            if str(port_type) not in PORT_TYPES:
                raise EgoIRError(f"node {node_id} port {name!r} has unknown type {port_type!r}")


def decompile_config(config: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(config, dict) or not isinstance(config.get("pipeline"), dict):
        raise EgoIRError("Harness config has no pipeline")
    errors = validate_pipeline(config["pipeline"])
    if errors and config["pipeline"].get("nodes"):
        raise EgoIRError("invalid Harness pipeline:\n- " + "\n- ".join(errors))
    pipeline = config["pipeline"]
    top_extra = {key: copy.deepcopy(value) for key, value in config.items() if key not in {
        "name", "description", "slots", "prompts", "return_mode", "pipeline", "identity_bindings", "permissions",
    }}
    pipeline_extra = {key: copy.deepcopy(value) for key, value in pipeline.items() if key not in {
        "start", "nodes", "max_steps", "workspace_preview",
    }}
    document: dict[str, Any] = {
        "version": EGOIR_VERSION,
        "name": str(config.get("name") or "harness"),
        "description": str(config.get("description") or ""),
        "return_mode": str(config.get("return_mode") or "last"),
        "limits": {"max_steps": int(pipeline.get("max_steps", 100))},
        "workspace_preview": bool(pipeline.get("workspace_preview", False)),
        "roles": copy.deepcopy(config.get("slots", {})),
        "identity_bindings": copy.deepcopy(config.get("identity_bindings", {})),
        "permissions": copy.deepcopy(config.get("permissions", {})),
        "prompts": copy.deepcopy(config.get("prompts", {})),
        "start": pipeline.get("start"),
        "nodes": [],
        "edges": [],
        "pipeline_extra": pipeline_extra,
        "config_extra": top_extra,
        "presence": {
            "config": [key for key in ("description", "slots", "prompts", "return_mode", "identity_bindings", "permissions") if key in config],
            "pipeline": [key for key in ("start", "max_steps", "workspace_preview", "nodes") if key in pipeline],
        },
    }
    for node_id, raw in pipeline.get("nodes", {}).items():
        node = copy.deepcopy(raw)
        edges = node.pop("edges", []) or []
        record = {
            "id": node_id,
            "op": node.pop("op", ""),
            "config": node,
            "presence": [key for key in ("agent", "ports", "edges") if key in raw],
        }
        if "agent" in record["config"]:
            record["role"] = record["config"].pop("agent")
        if "ports" in record["config"]:
            record["ports"] = record["config"].pop("ports")
        document["nodes"].append(record)
        for edge in edges:
            document["edges"].append({"from": node_id, **copy.deepcopy(edge)})
    validate_document(document)
    return document


def compile_document(document: dict[str, Any]) -> dict[str, Any]:
    validate_document(document)
    nodes: dict[str, dict[str, Any]] = {}
    for record in document["nodes"]:
        node = copy.deepcopy(record.get("config", {}))
        node["op"] = record["op"]
        node_presence = record.get("presence")
        include_default = node_presence is None
        if record.get("role") is not None and (include_default or "agent" in node_presence):
            node["agent"] = record["role"]
        if record.get("ports") is not None and (include_default or "ports" in node_presence):
            node["ports"] = copy.deepcopy(record["ports"])
        if include_default or "edges" in node_presence:
            node["edges"] = []
        nodes[record["id"]] = node
    for edge in document.get("edges", []):
        source = edge["from"]
        nodes[source].setdefault("edges", []).append({key: copy.deepcopy(value) for key, value in edge.items() if key != "from"})
    pipeline = copy.deepcopy(document.get("pipeline_extra", {}))
    presence = document.get("presence")
    pipeline_presence = set((presence or {}).get("pipeline", ()))
    include_defaults = presence is None
    pipeline["start"] = document["start"]
    pipeline["nodes"] = nodes
    if include_defaults or "max_steps" in pipeline_presence:
        pipeline["max_steps"] = int(document.get("limits", {}).get("max_steps", 100))
    if include_defaults or "workspace_preview" in pipeline_presence:
        pipeline["workspace_preview"] = bool(document.get("workspace_preview", False))
    config = copy.deepcopy(document.get("config_extra", {}))
    config["name"] = document["name"]
    config["pipeline"] = pipeline
    config_presence = set((presence or {}).get("config", ()))
    if include_defaults or "description" in config_presence:
        config["description"] = document.get("description", "")
    if include_defaults or "slots" in config_presence:
        config["slots"] = copy.deepcopy(document.get("roles", {}))
    if include_defaults or "prompts" in config_presence:
        config["prompts"] = copy.deepcopy(document.get("prompts", {}))
    if include_defaults or "return_mode" in config_presence:
        config["return_mode"] = document.get("return_mode", "last")
    if document.get("identity_bindings") or "identity_bindings" in config_presence:
        config["identity_bindings"] = copy.deepcopy(document["identity_bindings"])
    if document.get("permissions") or "permissions" in config_presence:
        config["permissions"] = copy.deepcopy(document["permissions"])
    errors = validate_pipeline(pipeline)
    if errors and nodes:
        raise EgoIRError("invalid compiled pipeline:\n- " + "\n- ".join(errors))
    return config


def validate_document(document: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(document, dict) or int(document.get("version", 0)) != EGOIR_VERSION:
        raise EgoIRError(f"EgoIR version must be {EGOIR_VERSION}")
    _name(document.get("name"), "Harness name")
    if document.get("return_mode", "last") not in {"last", "all"}:
        raise EgoIRError("return_mode must be last or all")
    roles = document.get("roles", {})
    if not isinstance(roles, dict):
        raise EgoIRError("roles must be an object")
    for role in roles:
        _name(role, "role")
    bindings = document.get("identity_bindings", {})
    if not isinstance(bindings, dict) or any(role not in roles for role in bindings):
        raise EgoIRError("identity_bindings must reference declared roles")
    nodes = document.get("nodes")
    if not isinstance(nodes, list):
        raise EgoIRError("nodes must be an array")
    node_ids: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            raise EgoIRError("each node must be an object")
        node_id = _name(node.get("id"), "node id")
        if node_id in node_ids:
            raise EgoIRError(f"duplicate node id: {node_id}")
        node_ids.add(node_id)
        op = canonical_op(str(node.get("op", "")))
        if op not in SUPPORTED_OPS:
            raise EgoIRError(f"node {node_id} has unsupported op: {node.get('op')!r}")
        if node.get("role") is not None and node["role"] not in roles:
            raise EgoIRError(f"node {node_id} references undeclared role {node['role']!r}")
        if not isinstance(node.get("config", {}), dict):
            raise EgoIRError(f"node {node_id}.config must be an object")
        _validate_ports(node_id, node.get("ports"))
    if nodes:
        start = _name(document.get("start"), "start node")
        if start not in node_ids:
            raise EgoIRError(f"start references missing node: {start}")
    elif document.get("start") not in {None, ""}:
        raise EgoIRError("an empty Harness cannot have a start node")
    for edge in document.get("edges", []):
        if not isinstance(edge, dict):
            raise EgoIRError("each edge must be an object")
        source = _name(edge.get("from"), "edge source")
        target = edge.get("to")
        if source not in node_ids or (target is not None and target not in node_ids):
            raise EgoIRError(f"edge references missing node: {source} -> {target}")
        if not str(edge.get("condition", "default")).strip():
            raise EgoIRError(f"edge from {source} has an empty condition")
    max_steps = int(document.get("limits", {}).get("max_steps", 100))
    if max_steps < 1 or max_steps > 100000:
        raise EgoIRError("limits.max_steps must be between 1 and 100000")
    return {"ok": True, "revision": revision(document), "nodes": len(nodes), "edges": len(document.get("edges", []))}


def dumps(document: dict[str, Any]) -> str:
    validate_document(document)
    lines = ["EGOIR/1"]
    lines.append("harness\t" + _json({
        "name": document["name"], "description": document.get("description", ""),
        "return_mode": document.get("return_mode", "last"), "limits": document.get("limits", {}),
        "workspace_preview": bool(document.get("workspace_preview", False)),
        "pipeline_extra": document.get("pipeline_extra", {}), "config_extra": document.get("config_extra", {}),
        "presence": document.get("presence"),
    }))
    for role, definition in document.get("roles", {}).items():
        lines.append("role\t" + _json({"id": role, "definition": definition}))
    for role, identity in document.get("identity_bindings", {}).items():
        lines.append("bind\t" + _json({"role": role, "identity": identity}))
    if document.get("permissions"):
        lines.append("permission\t" + _json(document["permissions"]))
    for name, value in document.get("prompts", {}).items():
        lines.append("prompt\t" + _json({"id": name, "value": value}))
    for node in document["nodes"]:
        lines.append("node\t" + _json(node))
    for edge in document.get("edges", []):
        lines.append("edge\t" + _json(edge))
    lines.append("start\t" + _json(document["start"]))
    return "\n".join(lines) + "\n"


def loads(text: str) -> dict[str, Any]:
    lines = str(text).splitlines()
    first = next((line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")), "")
    if first != "EGOIR/1":
        raise EgoIRError("EgoIR text must start with EGOIR/1")
    document: dict[str, Any] = {
        "version": EGOIR_VERSION, "roles": {}, "identity_bindings": {}, "permissions": {},
        "prompts": {}, "nodes": [], "edges": [],
    }
    header_seen = False
    start_seen = False
    for line_number, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#") or line == "EGOIR/1":
            continue
        kind, separator, payload = line.partition("\t")
        if not separator:
            raise EgoIRError(f"line {line_number}: records use <kind><TAB><json>")
        try:
            value = json.loads(payload)
        except ValueError as error:
            raise EgoIRError(f"line {line_number}: invalid JSON: {error}") from error
        if kind == "harness":
            if header_seen or not isinstance(value, dict):
                raise EgoIRError(f"line {line_number}: duplicate or invalid harness record")
            header_seen = True
            document.update(value)
        elif kind == "role":
            document["roles"][_name(value.get("id"), "role")] = copy.deepcopy(value.get("definition", {}))
        elif kind == "bind":
            document["identity_bindings"][_name(value.get("role"), "role")] = str(value.get("identity", ""))
        elif kind == "permission":
            if not isinstance(value, dict):
                raise EgoIRError(f"line {line_number}: permission must be an object")
            document["permissions"] = value
        elif kind == "prompt":
            document["prompts"][_name(value.get("id"), "prompt")] = copy.deepcopy(value.get("value", ""))
        elif kind == "node":
            document["nodes"].append(value)
        elif kind == "edge":
            document["edges"].append(value)
        elif kind == "start":
            if start_seen:
                raise EgoIRError(f"line {line_number}: duplicate start record")
            start_seen = True
            document["start"] = value
        else:
            raise EgoIRError(f"line {line_number}: unknown record {kind!r}")
    if not header_seen or not start_seen:
        raise EgoIRError("EgoIR needs one harness and one start record")
    document.setdefault("description", "")
    document.setdefault("return_mode", "last")
    document.setdefault("limits", {"max_steps": 100})
    document.setdefault("workspace_preview", False)
    document.setdefault("pipeline_extra", {})
    document.setdefault("config_extra", {})
    document.setdefault("presence", None)
    validate_document(document)
    return document


def guide() -> dict[str, Any]:
    return {
        "format": "EGOIR/1 followed by one tab-separated JSON record per line",
        "records": ["harness", "role", "bind", "permission", "prompt", "node", "edge", "start"],
        "node": {"id": "think", "op": "agent", "role": "worker", "ports": {"in": {"request": "message"}, "out": {"answer": "message"}}, "config": {}},
        "edge": {"from": "think", "condition": "tools", "to": "act"},
        "port_types": sorted(PORT_TYPES),
        "node_contracts": compact_agent_contracts(),
        "mutations": {
            "set_limits": {"op": "set_limits", "max_steps": 12},
            "add_node": {"op": "add_node", "before": "target", "node": {"id": "new", "op": "context", "config": {}}},
            "connect": {"op": "connect", "from": "source", "condition": "default", "to": "target"},
            "disconnect": {"op": "disconnect", "from": "source", "to": "target"},
            "set_role": {"op": "set_role", "id": "worker", "definition": {"required": True}},
            "rebind": {"op": "rebind", "role": "worker", "identity": "researcher"},
            "set_permissions": {"op": "set_permissions", "permissions": {"network": "ask"}},
        },
        "rules": [
            "Use one record per line; comments start with #.",
            "Prefer condition/data/workspace/process/subflow over Python.",
            "Every node, role, binding and edge reference must exist.",
            "Loops are ordinary back-edges and must fit limits.max_steps.",
            "Keep unknown node options inside config so round-tripping stays lossless.",
        ],
    }


def config_to_text(config: dict[str, Any]) -> str:
    return dumps(decompile_config(config))


def text_to_config(text: str) -> dict[str, Any]:
    return compile_document(loads(text))


def apply_operations(document: dict[str, Any], operations: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Apply the small, revision-friendly structural mutation language."""
    result = copy.deepcopy(document)
    operations = list(operations)
    if not operations:
        raise EgoIRError("operations cannot be empty")

    def node_index(node_id: str) -> int:
        for index, node in enumerate(result["nodes"]):
            if node.get("id") == node_id:
                return index
        raise EgoIRError(f"node not found: {node_id}")

    for index, operation in enumerate(operations, start=1):
        if not isinstance(operation, dict):
            raise EgoIRError(f"operation {index} must be an object")
        action = str(operation.get("op", ""))
        if action == "replace_document":
            replacement = operation.get("document")
            if not isinstance(replacement, dict):
                raise EgoIRError("replace_document requires document")
            result = copy.deepcopy(replacement)
        elif action == "add_node":
            node = copy.deepcopy(operation.get("node"))
            if not isinstance(node, dict):
                raise EgoIRError("add_node requires node")
            _name(node.get("id"), "node id")
            if any(item.get("id") == node["id"] for item in result["nodes"]):
                raise EgoIRError(f"node already exists: {node['id']}")
            if operation.get("after"):
                result["nodes"].insert(node_index(str(operation["after"])) + 1, node)
            elif operation.get("before"):
                result["nodes"].insert(node_index(str(operation["before"])), node)
            else:
                result["nodes"].append(node)
        elif action in {"update_node", "replace_node"}:
            node_id = str(operation.get("id", ""))
            position = node_index(node_id)
            value = operation.get("changes" if action == "update_node" else "node")
            if not isinstance(value, dict):
                raise EgoIRError(f"{action} requires an object")
            if action == "replace_node":
                replacement = copy.deepcopy(value)
                replacement.setdefault("id", node_id)
                result["nodes"][position] = replacement
            else:
                current = result["nodes"][position]
                for key, item in value.items():
                    if key == "config" and isinstance(item, dict):
                        current.setdefault("config", {}).update(copy.deepcopy(item))
                    else:
                        current[key] = copy.deepcopy(item)
        elif action == "remove_node":
            node_id = str(operation.get("id", ""))
            if result.get("start") == node_id:
                replacement = operation.get("new_start")
                if not replacement:
                    raise EgoIRError("removing start requires new_start")
                result["start"] = str(replacement)
            result["nodes"].pop(node_index(node_id))
            result["edges"] = [edge for edge in result.get("edges", []) if edge.get("from") != node_id and edge.get("to") != node_id]
        elif action == "connect":
            if isinstance(operation.get("edge"), dict):
                operation = {**operation, **operation["edge"]}
            source, target = str(operation.get("from", "")), operation.get("to")
            condition = str(operation.get("condition") or "default")
            edge = {"from": source, "condition": condition, "to": target}
            if operation.get("when") is not None:
                edge["when"] = str(operation["when"])
            if operation.get("replace", True):
                result["edges"] = [item for item in result.get("edges", []) if not (item.get("from") == source and item.get("condition", "default") == condition)]
            result.setdefault("edges", []).append(edge)
        elif action == "disconnect":
            if isinstance(operation.get("edge"), dict):
                operation = {**operation, **operation["edge"]}
            source, target, condition = str(operation.get("from", "")), operation.get("to"), operation.get("condition")
            result["edges"] = [edge for edge in result.get("edges", []) if not (
                edge.get("from") == source and (target is None or edge.get("to") == target)
                and (condition is None or edge.get("condition", "default") == condition)
            )]
        elif action == "set_start":
            result["start"] = str(operation.get("id", ""))
        elif action in {"set_role", "add_role"}:
            role_record = operation.get("role") if isinstance(operation.get("role"), dict) else {}
            role_id = operation.get("id") or role_record.get("id")
            definition = operation.get("definition", role_record.get("definition", {}))
            result.setdefault("roles", {})[_name(role_id, "role")] = copy.deepcopy(definition)
        elif action == "remove_role":
            role = _name(operation.get("id"), "role")
            if any(node.get("role") == role for node in result["nodes"]):
                raise EgoIRError(f"role is still used: {role}")
            result.setdefault("roles", {}).pop(role, None)
            result.setdefault("identity_bindings", {}).pop(role, None)
        elif action == "rebind":
            role = _name(operation.get("role"), "role")
            if role not in result.setdefault("roles", {}):
                raise EgoIRError(f"cannot bind undeclared role: {role}")
            result.setdefault("identity_bindings", {})[role] = _name(operation.get("identity"), "identity")
        elif action == "unbind":
            result.setdefault("identity_bindings", {}).pop(_name(operation.get("role"), "role"), None)
        elif action == "set_ports":
            result["nodes"][node_index(str(operation.get("id", "")))]["ports"] = copy.deepcopy(operation.get("ports", {}))
        elif action == "set_permissions":
            if not isinstance(operation.get("permissions"), dict):
                raise EgoIRError("set_permissions requires permissions object")
            result["permissions"] = copy.deepcopy(operation["permissions"])
        elif action == "set_limits":
            limits = operation.get("limits") if isinstance(operation.get("limits"), dict) else {
                key: copy.deepcopy(value) for key, value in operation.items() if key != "op"
            }
            result.setdefault("limits", {}).update(copy.deepcopy(limits))
        elif action == "set_return":
            result["return_mode"] = str(operation.get("mode", ""))
        elif action == "set_prompt":
            result.setdefault("prompts", {})[_name(operation.get("id"), "prompt")] = copy.deepcopy(operation.get("value", ""))
        elif action == "remove_prompt":
            result.setdefault("prompts", {}).pop(_name(operation.get("id"), "prompt"), None)
        else:
            raise EgoIRError(f"unknown operation: {action!r}")
    validate_document(result)
    return result


def check_document(document: dict[str, Any], checks: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run deterministic pre-commit structural checks."""
    results = []
    node_ids = {node["id"] for node in document["nodes"]}
    for index, check in enumerate(checks or [], start=1):
        kind = str(check.get("type", ""))
        passed, evidence = False, ""
        if kind == "node_exists":
            passed = str(check.get("id")) in node_ids
            evidence = f"nodes={sorted(node_ids)}"
        elif kind == "edge_exists":
            passed = any(
                edge.get("from") == check.get("from") and edge.get("to") == check.get("to")
                and (check.get("condition") is None or edge.get("condition", "default") == check.get("condition"))
                for edge in document.get("edges", [])
            )
            evidence = f"edges={len(document.get('edges', []))}"
        elif kind == "no_python":
            values = [node["id"] for node in document["nodes"] if canonical_op(node["op"]) == "Python"]
            passed, evidence = not values, f"python_nodes={values}"
        elif kind == "max_nodes":
            passed = len(document["nodes"]) <= int(check.get("value", 0))
            evidence = f"nodes={len(document['nodes'])}"
        elif kind == "role_bound":
            role = str(check.get("role", ""))
            passed = bool(document.get("identity_bindings", {}).get(role))
            evidence = f"binding={document.get('identity_bindings', {}).get(role)}"
        else:
            evidence = f"unsupported check: {kind}"
        results.append({"id": str(check.get("id") or f"check_{index}"), "type": kind, "passed": passed, "evidence": evidence})
    return results


class EgoIRService:
    """Revision checked, transactional file boundary for EgoIR mutations."""

    def __init__(self, project_root: Path | str):
        self.root = Path(project_root).resolve()
        self.harness_root = self.root / "harness"
        self.transaction_root = self.root / "self_evolution" / "data" / "egoir_transactions"

    def _path(self, name: str) -> Path:
        path = (self.harness_root / _name(name, "Harness name") / "config.json").resolve()
        if path.parent.parent != self.harness_root.resolve():
            raise EgoIRError("Harness path escapes repository")
        return path

    def load(self, name: str) -> dict[str, Any]:
        path = self._path(name)
        if not path.is_file():
            raise EgoIRError(f"Harness not found: {name}")
        config = json.loads(path.read_text(encoding="utf-8"))
        document = decompile_config(config)
        return {"document": document, "text": dumps(document), "config": config, "revision": revision(config)}

    def create(self, text: str, *, dry_run: bool = False) -> dict[str, Any]:
        document = loads(text)
        config = compile_document(document)
        path = self._path(document["name"])
        if path.exists():
            raise EgoIRError(f"Harness already exists: {document['name']}")
        result = {"ok": True, "action": "create", "name": document["name"], "revision": revision(config), "config": config, "text": dumps(document), "dry_run": dry_run}
        if not dry_run:
            path.parent.mkdir(parents=True, exist_ok=False)
            self._write(path, config)
        return result

    def patch(self, name: str, operations: Iterable[dict[str, Any]], *, expected_revision: str | None = None, dry_run: bool = False, checks: Iterable[dict[str, Any]] = (), reason: str = "", actor: str = "agent") -> dict[str, Any]:
        loaded = self.load(name)
        if expected_revision and expected_revision != loaded["revision"]:
            raise EgoIRError(f"revision conflict: expected {expected_revision}, current {loaded['revision']}")
        operations = list(operations)
        updated = apply_operations(loaded["document"], operations)
        updated["name"] = name
        config = compile_document(updated)
        check_results = check_document(updated, checks)
        if any(not item["passed"] for item in check_results):
            raise EgoIRError("pre-commit checks failed: " + "; ".join(item["evidence"] for item in check_results if not item["passed"]))
        before_text = json.dumps(loaded["config"], ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        after_text = json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        diff = "".join(difflib.unified_diff(before_text.splitlines(True), after_text.splitlines(True), fromfile=f"{name}@{loaded['revision']}", tofile=f"{name}@{revision(config)}"))
        transaction_id = f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        transaction = {
            "format": "ego.ir-transaction.v1", "id": transaction_id, "harness": name,
            "timestamp": time.time(), "actor": actor, "reason": reason,
            "revision_before": loaded["revision"], "revision_after": revision(config),
            "operations": copy.deepcopy(operations), "checks": check_results,
            "before": loaded["config"], "after": config, "diff": diff,
        }
        if not dry_run:
            self.transaction_root.mkdir(parents=True, exist_ok=True)
            self._write(self.transaction_root / f"{transaction_id}.json", transaction)
            self._write(self._path(name), config)
        return {"ok": True, "action": "patch", "harness": name, "transaction_id": transaction_id, "revision_before": loaded["revision"], "revision": revision(config), "checks": check_results, "diff": diff, "text": dumps(updated), "config": config, "dry_run": dry_run}

    def rollback(self, transaction_id: str, *, expected_revision: str | None = None) -> dict[str, Any]:
        tx_id = _name(transaction_id, "transaction id")
        path = self.transaction_root / f"{tx_id}.json"
        if not path.is_file():
            raise EgoIRError(f"transaction not found: {tx_id}")
        transaction = json.loads(path.read_text(encoding="utf-8"))
        loaded = self.load(transaction["harness"])
        required = expected_revision or transaction["revision_after"]
        if loaded["revision"] != required:
            raise EgoIRError(f"rollback conflict: expected {required}, current {loaded['revision']}")
        compile_document(decompile_config(transaction["before"]))
        self._write(self._path(transaction["harness"]), transaction["before"])
        return {"ok": True, "action": "rollback", "harness": transaction["harness"], "transaction_id": tx_id, "revision": revision(transaction["before"])}

    @staticmethod
    def _write(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
