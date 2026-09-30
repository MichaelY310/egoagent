"""Schema helpers for EgoAgent's declarative DAG format.

The runtime intentionally accepts both the original Chinese operation names and
the smaller user-facing vocabulary introduced by the v2 editor.  Harness files
therefore remain backwards compatible while new graphs can use explicit data
ports and safe conditions.
"""

from __future__ import annotations

import ast
import copy
import json
import operator
import re
from collections.abc import Mapping, Sequence
from typing import Any

from node_registry import NODE_ALIASES, SUPPORTED_NODE_OPS, canonical_node_op


OP_ALIASES = NODE_ALIASES
SUPPORTED_OPS = set(SUPPORTED_NODE_OPS)


def canonical_op(op: str) -> str:
    return canonical_node_op(op)


_PATH_TOKEN = re.compile(r"([^.[\]]+)|\[(\d+)\]")
_TEMPLATE_REF = re.compile(r"\$\{([^}]+)\}")


def _path_parts(path: str) -> list[Any]:
    parts: list[Any] = []
    for match in _PATH_TOKEN.finditer(path or ""):
        name, index = match.groups()
        parts.append(int(index) if index is not None else name)
    return parts


def get_path(root: Any, path: str, default: Any = None) -> Any:
    value = root
    for part in _path_parts(path):
        try:
            if isinstance(part, int):
                value = value[part]
            elif isinstance(value, Mapping):
                value = value[part]
            else:
                value = getattr(value, part)
        except (KeyError, IndexError, TypeError, AttributeError):
            return default
    return value


def set_path(root: dict, path: str, value: Any) -> None:
    parts = _path_parts(path)
    if not parts:
        raise ValueError("data path cannot be empty")
    current: Any = root
    for index, part in enumerate(parts[:-1]):
        following = parts[index + 1]
        if isinstance(part, int):
            while len(current) <= part:
                current.append({} if not isinstance(following, int) else [])
            current = current[part]
        else:
            if part not in current or current[part] is None:
                current[part] = [] if isinstance(following, int) else {}
            current = current[part]
    last = parts[-1]
    if isinstance(last, int):
        while len(current) <= last:
            current.append(None)
        current[last] = value
    else:
        current[last] = value


def delete_path(root: dict, path: str) -> bool:
    parts = _path_parts(path)
    if not parts:
        return False
    parent = get_path(root, ".".join(str(p) for p in parts[:-1]), None) if len(parts) > 1 else root
    if isinstance(parent, dict):
        sentinel = object()
        return parent.pop(parts[-1], sentinel) is not sentinel
    if isinstance(parent, list) and isinstance(parts[-1], int) and parts[-1] < len(parent):
        parent.pop(parts[-1])
        return True
    return False


def _reference_root(runtime: Any, name: str) -> Any:
    if name in {"ctx", "data"}:
        return runtime.data
    if name in {"node", "nodes"}:
        return runtime.node_outputs
    if name == "last":
        return runtime.last_output
    if name == "session":
        return {
            "messages": runtime.harness.session.messages,
            "full_messages": runtime.harness.session.full_messages,
            "state": runtime.harness.session.state,
        }
    if name == "stats":
        return runtime.stats.as_dict()
    if name == "input":
        return runtime.last_input
    return None


def resolve_reference(value: Any, runtime: Any, default: Any = None) -> Any:
    """Resolve explicit DAG references while preserving literal values.

    Exact references (``$ctx.foo``) preserve the source type. Embedded
    references (``hello ${ctx.name}``) are rendered as strings.
    """
    if isinstance(value, dict):
        return {key: resolve_reference(item, runtime, default) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_reference(item, runtime, default) for item in value]
    if not isinstance(value, str):
        return copy.deepcopy(value)

    exact = re.fullmatch(r"\$([A-Za-z_][\w]*)(?:\.(.*))?", value)
    if exact:
        root = _reference_root(runtime, exact.group(1))
        return get_path(root, exact.group(2) or "", root if exact.group(2) is None else default)

    def replace(match: re.Match) -> str:
        raw = match.group(1)
        root_name, _, path = raw.partition(".")
        root = _reference_root(runtime, root_name)
        resolved = get_path(root, path, default) if path else root
        if isinstance(resolved, (dict, list)):
            return json.dumps(resolved, ensure_ascii=False)
        return "" if resolved is None else str(resolved)

    return _TEMPLATE_REF.sub(replace, value)


_BINARY = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}
_COMPARE = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda left, right: left in right,
    ast.NotIn: lambda left, right: left not in right,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
}


class SafeExpressionError(ValueError):
    pass


class _SafeEvaluator(ast.NodeVisitor):
    """A deliberately small expression evaluator used by If nodes and edges."""

    def __init__(self, variables: dict[str, Any]):
        self.variables = variables

    def generic_visit(self, node):
        raise SafeExpressionError(f"unsupported expression element: {type(node).__name__}")

    def visit_Expression(self, node):
        return self.visit(node.body)

    def visit_Constant(self, node):
        return node.value

    def visit_Name(self, node):
        literals = {"true": True, "false": False, "null": None}
        if node.id in literals:
            return literals[node.id]
        if node.id not in self.variables:
            raise SafeExpressionError(f"unknown name: {node.id}")
        return self.variables[node.id]

    def visit_List(self, node):
        return [self.visit(item) for item in node.elts]

    def visit_Tuple(self, node):
        return tuple(self.visit(item) for item in node.elts)

    def visit_Dict(self, node):
        return {self.visit(k): self.visit(v) for k, v in zip(node.keys, node.values)}

    def visit_Attribute(self, node):
        value = self.visit(node.value)
        if isinstance(value, Mapping):
            return value.get(node.attr)
        raise SafeExpressionError("attribute access is only allowed on DAG mappings")

    def visit_Subscript(self, node):
        value = self.visit(node.value)
        key = self.visit(node.slice)
        try:
            return value[key]
        except (KeyError, IndexError, TypeError) as error:
            raise SafeExpressionError(str(error)) from error

    def visit_Slice(self, node):
        return slice(
            self.visit(node.lower) if node.lower is not None else None,
            self.visit(node.upper) if node.upper is not None else None,
            self.visit(node.step) if node.step is not None else None,
        )

    def visit_IfExp(self, node):
        return self.visit(node.body) if self.visit(node.test) else self.visit(node.orelse)

    def visit_UnaryOp(self, node):
        value = self.visit(node.operand)
        if isinstance(node.op, ast.Not):
            return not value
        if isinstance(node.op, ast.USub):
            return -value
        if isinstance(node.op, ast.UAdd):
            return +value
        raise SafeExpressionError("unsupported unary operator")

    def visit_BoolOp(self, node):
        if isinstance(node.op, ast.And):
            result = True
            for item in node.values:
                result = self.visit(item)
                if not result:
                    return result
            return result
        if isinstance(node.op, ast.Or):
            result = False
            for item in node.values:
                result = self.visit(item)
                if result:
                    return result
            return result
        raise SafeExpressionError("unsupported boolean operator")

    def visit_BinOp(self, node):
        operation = _BINARY.get(type(node.op))
        if not operation:
            raise SafeExpressionError("unsupported binary operator")
        return operation(self.visit(node.left), self.visit(node.right))

    def visit_Compare(self, node):
        left = self.visit(node.left)
        for op_node, comparator in zip(node.ops, node.comparators):
            operation = _COMPARE.get(type(op_node))
            if not operation:
                raise SafeExpressionError("unsupported comparison")
            right = self.visit(comparator)
            if not operation(left, right):
                return False
            left = right
        return True

    def visit_Call(self, node):
        args = [self.visit(arg) for arg in node.args]
        kwargs = {kw.arg: self.visit(kw.value) for kw in node.keywords}
        if isinstance(node.func, ast.Name):
            name = node.func.id
            functions = {
                "exists": lambda value: value is not None,
                "empty": lambda value: value is None or len(value) == 0,
                "len": len,
                "contains": lambda value, item: item in value,
                "starts_with": lambda value, prefix: str(value).startswith(str(prefix)),
                "ends_with": lambda value, suffix: str(value).endswith(str(suffix)),
                "lower": lambda value: str(value).lower(),
                "upper": lambda value: str(value).upper(),
                "strip": lambda value: str(value).strip(),
                "is_string": lambda value: isinstance(value, str),
                "is_number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
                "is_list": lambda value: isinstance(value, list),
                "is_object": lambda value: isinstance(value, dict),
                "bool": bool,
                "str": str,
                "int": int,
                "float": float,
                "min": min,
                "max": max,
            }
            if name not in functions:
                raise SafeExpressionError(f"function is not allowed: {name}")
            return functions[name](*args, **kwargs)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "get":
            target = self.visit(node.func.value)
            if not isinstance(target, Mapping):
                raise SafeExpressionError(".get() is only allowed on mappings")
            return target.get(*args, **kwargs)
        raise SafeExpressionError("only safe DAG helper functions are allowed")


def evaluate_expression(expression: str, variables: dict[str, Any]) -> Any:
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as error:
        raise SafeExpressionError(str(error)) from error
    return _SafeEvaluator(variables).visit(tree)


def validate_json_schema(value: Any, schema: dict, path: str = "$output") -> list[str]:
    """Validate the useful JSON Schema subset without adding a dependency."""
    errors: list[str] = []
    if not schema:
        return errors
    expected = schema.get("type")
    expected_types = expected if isinstance(expected, list) else [expected]

    def matches_type(type_name: Any) -> bool:
        if type_name == "object":
            return isinstance(value, dict)
        if type_name == "array":
            return isinstance(value, list)
        if type_name == "string":
            return isinstance(value, str)
        if type_name == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if type_name == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if type_name == "boolean":
            return isinstance(value, bool)
        if type_name == "null":
            return value is None
        return True

    recognized_types = {"object", "array", "string", "number", "integer", "boolean", "null"}
    constrained_types = [type_name for type_name in expected_types if type_name in recognized_types]
    if constrained_types and not any(matches_type(type_name) for type_name in constrained_types):
        label = " or ".join(str(type_name) for type_name in constrained_types)
        errors.append(f"{path} must be {label}, got {type(value).__name__}")
        return errors
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path} must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path} must be one of {schema['enum']!r}")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}.{key} is required")
        for key, child_schema in schema.get("properties", {}).items():
            if key in value:
                errors.extend(validate_json_schema(value[key], child_schema, f"{path}.{key}"))
        if schema.get("additionalProperties") is False:
            extras = sorted(set(value) - set(schema.get("properties", {})))
            for key in extras:
                errors.append(f"{path}.{key} is not allowed")
        if "minProperties" in schema and len(value) < schema["minProperties"]:
            errors.append(f"{path} has fewer than minProperties")
        if "maxProperties" in schema and len(value) > schema["maxProperties"]:
            errors.append(f"{path} has more than maxProperties")
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            errors.extend(validate_json_schema(item, schema["items"], f"{path}[{index}]"))
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path} has fewer than minItems")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path} has more than maxItems")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path} is less than minimum")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path} is greater than maximum")
    if isinstance(value, (str, list)):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path} is shorter than minLength")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path} is longer than maxLength")
    return errors


def validate_pipeline(graph: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(graph, dict):
        return ["pipeline must be an object"]
    nodes = graph.get("nodes")
    if not isinstance(nodes, dict) or not nodes:
        return ["pipeline.nodes must be a non-empty object"]
    start = graph.get("start")
    if start not in nodes:
        errors.append(f"pipeline.start points to missing node: {start!r}")
    for field in ("budget_exceeded_to", "limit_exceeded_to"):
        target = graph.get(field)
        if target is not None and target not in nodes:
            errors.append(f"pipeline.{field} points to missing node: {target!r}")
    data_links = graph.get("data_links", [])
    if not isinstance(data_links, list):
        errors.append("pipeline.data_links must be an array")
        data_links = []
    occupied_inputs: set[tuple[str, str]] = set()
    for index, link in enumerate(data_links):
        path = f"pipeline.data_links[{index}]"
        if not isinstance(link, dict):
            errors.append(f"{path} must be an object")
            continue
        source = link.get("source")
        target = link.get("target")
        source_port = link.get("source_port")
        target_port = link.get("target_port")
        if source not in nodes:
            errors.append(f"{path}.source points to missing node {source!r}")
        if target not in nodes:
            errors.append(f"{path}.target points to missing node {target!r}")
        if not isinstance(source_port, str) or not source_port:
            errors.append(f"{path}.source_port must be a non-empty string")
        if not isinstance(target_port, str) or not target_port:
            errors.append(f"{path}.target_port must be a non-empty string")
        if isinstance(target, str) and isinstance(target_port, str):
            key = (target, target_port)
            if key in occupied_inputs:
                errors.append(f"{path} duplicates single input socket {target}.{target_port}")
            occupied_inputs.add(key)
        reroutes = link.get("reroutes", [])
        if not isinstance(reroutes, list):
            errors.append(f"{path}.reroutes must be an array")
        else:
            for route_index, reroute in enumerate(reroutes):
                if not isinstance(reroute, dict) or not all(isinstance(reroute.get(axis), (int, float)) for axis in ("x", "y")):
                    errors.append(f"{path}.reroutes[{route_index}] must contain numeric x/y")
                    continue
                for spline_field in ("angle", "in_length", "out_length"):
                    if spline_field in reroute and not isinstance(reroute[spline_field], (int, float)):
                        errors.append(f"{path}.reroutes[{route_index}].{spline_field} must be numeric")
        for handle_field in ("source_handle", "target_handle"):
            if handle_field in link and not isinstance(link[handle_field], (int, float)):
                errors.append(f"{path}.{handle_field} must be numeric")
    for node_id, node in nodes.items():
        if not isinstance(node, dict):
            errors.append(f"node {node_id!r} must be an object")
            continue
        op = canonical_op(node.get("op", ""))
        if op not in SUPPORTED_OPS:
            errors.append(f"node {node_id!r} has unsupported op: {node.get('op')!r}")
        if "inputs" in node and not isinstance(node["inputs"], dict):
            errors.append(f"node {node_id!r}.inputs must be an object")
        if "outputs" in node and not isinstance(node["outputs"], dict):
            errors.append(f"node {node_id!r}.outputs must be an object")
        editor_position = node.get("editor_position")
        if editor_position is not None and (
            not isinstance(editor_position, dict)
            or not all(isinstance(editor_position.get(axis), (int, float)) for axis in ("x", "y"))
        ):
            errors.append(f"node {node_id!r}.editor_position must contain numeric x/y")
        for field in (
            "error_to",
            "empty_response_to",
            "tool_call_count_error_to",
            "stuck_to",
            "end_session_to",
            "auto_continue_to",
        ):
            target = node.get(field)
            if target is not None and target not in nodes:
                errors.append(f"node {node_id!r}.{field} points to missing node {target!r}")
        for edge in node.get("edges", []):
            if not isinstance(edge, dict) or "condition" not in edge or "to" not in edge:
                errors.append(f"node {node_id!r} contains an invalid edge")
            elif edge["to"] is not None and edge["to"] not in nodes:
                errors.append(f"node {node_id!r} points to missing node {edge['to']!r}")
            if isinstance(edge, dict):
                for port_field in ("source_port", "target_port"):
                    if port_field in edge and (not isinstance(edge[port_field], str) or not edge[port_field]):
                        errors.append(f"node {node_id!r} edge {port_field} must be a non-empty string")
                reroutes = edge.get("reroutes", [])
                if not isinstance(reroutes, list):
                    errors.append(f"node {node_id!r} edge reroutes must be an array")
                else:
                    for route_index, reroute in enumerate(reroutes):
                        if not isinstance(reroute, dict) or not all(isinstance(reroute.get(axis), (int, float)) for axis in ("x", "y")):
                            errors.append(f"node {node_id!r} edge reroutes[{route_index}] must contain numeric x/y")
                            continue
                        for spline_field in ("angle", "in_length", "out_length"):
                            if spline_field in reroute and not isinstance(reroute[spline_field], (int, float)):
                                errors.append(f"node {node_id!r} edge reroutes[{route_index}].{spline_field} must be numeric")
                for handle_field in ("source_handle", "target_handle"):
                    if handle_field in edge and not isinstance(edge[handle_field], (int, float)):
                        errors.append(f"node {node_id!r} edge {handle_field} must be numeric")
        if op == "并行":
            for branch in node.get("branches", []):
                branch_start = branch.get("start") if isinstance(branch, dict) else branch
                if branch_start not in nodes:
                    errors.append(f"parallel node {node_id!r} has missing branch {branch_start!r}")
            join = node.get("join")
            if join and join not in nodes:
                errors.append(f"parallel node {node_id!r} has missing join node {join!r}")
        if op == "映射":
            body_start = node.get("body_start") or node.get("start")
            if body_start not in nodes:
                errors.append(f"map node {node_id!r} has missing body_start {body_start!r}")
            join = node.get("join")
            if join and join not in nodes:
                errors.append(f"map node {node_id!r} has missing join node {join!r}")
    return errors


def validate_component_manifest(component: Any) -> list[str]:
    """Validate the typed public contract of a reusable Harness SubDAG."""

    if component in (None, {}):
        return []
    if not isinstance(component, dict):
        return ["component must be an object"]
    errors: list[str] = []
    for field in ("name", "display_name", "category", "description", "icon"):
        if field in component and not isinstance(component[field], str):
            errors.append(f"component.{field} must be a string")
    if "share_session" in component and not isinstance(component["share_session"], bool):
        errors.append("component.share_session must be a boolean")
    for section in ("inputs", "outputs"):
        ports = component.get(section, {})
        if not isinstance(ports, dict):
            errors.append(f"component.{section} must be an object")
            continue
        for name, spec in ports.items():
            if not isinstance(name, str) or not name:
                errors.append(f"component.{section} contains an invalid port name")
            if not isinstance(spec, dict):
                errors.append(f"component.{section}.{name} must be an object")
                continue
            if section == "inputs" and "required" in spec and not isinstance(spec["required"], bool):
                errors.append(f"component.inputs.{name}.required must be a boolean")
            if section == "inputs" and "schema" in spec and not isinstance(spec["schema"], dict):
                errors.append(f"component.inputs.{name}.schema must be an object")
            if section == "outputs" and "schema" in spec and not isinstance(spec["schema"], dict):
                errors.append(f"component.outputs.{name}.schema must be an object")
            if section == "outputs" and "path" in spec and not isinstance(spec["path"], str):
                errors.append(f"component.outputs.{name}.path must be a string")
    return errors


def assert_valid_pipeline(graph: dict) -> None:
    errors = validate_pipeline(graph)
    if errors:
        raise ValueError("Invalid pipeline:\n- " + "\n- ".join(errors))
