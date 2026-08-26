"""Safe, shared authoring primitives for reusable Identity capabilities.

EgoAgent stores executable Skills below ``identity/<name>/ego/skills`` and
exposes each Skill to a model as a function tool.  The distinction is useful:
the directory is the reusable/versionable Skill package, while the function is
its runtime interface.  Creation tools call this module instead of duplicating
filesystem and validation logic in every Identity.
"""

from __future__ import annotations

import ast
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


_SAFE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,79}$")
_JSON_TYPES = {"array", "boolean", "integer", "null", "number", "object", "string"}


class CapabilityAuthoringError(ValueError):
    """Raised when a generated capability is unsafe or cannot be loaded."""


def parse_parameters_schema(value: Any) -> dict[str, Any]:
    """Normalize a JSON Schema or the compact ``name:type:description`` form."""

    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("{"):
            try:
                decoded = json.loads(stripped)
            except json.JSONDecodeError as error:
                raise CapabilityAuthoringError(
                    f"parameters_schema looks like JSON but is invalid: {error.msg}"
                ) from error
            return parse_parameters_schema(decoded)
        schema: dict[str, Any] = {"type": "object", "properties": {}, "required": []}
        for raw_part in value.split(","):
            part = raw_part.strip()
            if not part:
                continue
            fields = [field.strip() for field in part.split(":", 2)]
            name = fields[0]
            if not _SAFE_NAME.fullmatch(name):
                raise CapabilityAuthoringError(f"invalid parameter name: {name!r}")
            parameter_type = fields[1] if len(fields) > 1 and fields[1] else "string"
            if parameter_type not in _JSON_TYPES:
                raise CapabilityAuthoringError(f"invalid JSON Schema type for {name}: {parameter_type}")
            description = fields[2] if len(fields) > 2 else ""
            schema["properties"][name] = {"type": parameter_type, "description": description}
            schema["required"].append(name)
        return schema

    if not isinstance(value, dict):
        raise CapabilityAuthoringError("parameters_schema must be an object or compact schema string")
    schema = dict(value)
    if "type" not in schema:
        schema = {"type": "object", "properties": schema, "required": list(schema)}
    if schema.get("type") != "object" or not isinstance(schema.get("properties", {}), dict):
        raise CapabilityAuthoringError("parameters_schema must describe a JSON object")
    for name, definition in schema.get("properties", {}).items():
        if not _SAFE_NAME.fullmatch(str(name)):
            raise CapabilityAuthoringError(f"invalid parameter name: {name!r}")
        if not isinstance(definition, dict) or definition.get("type", "string") not in _JSON_TYPES:
            raise CapabilityAuthoringError(f"invalid JSON Schema definition for {name!r}")
    required = schema.get("required", [])
    if not isinstance(required, list) or any(name not in schema.get("properties", {}) for name in required):
        raise CapabilityAuthoringError("parameters_schema.required must reference declared properties")
    return schema


def _validate_function(source: str, function_name: str, schema: dict[str, Any]) -> None:
    try:
        module = ast.parse(source)
    except SyntaxError as error:
        raise CapabilityAuthoringError(f"function_code is not valid Python: {error.msg}") from error
    definition = next((
        node for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name
    ), None)
    if definition is None:
        raise CapabilityAuthoringError(
            f"function_code must define a top-level function named {function_name!r}"
        )
    positional = [argument.arg for argument in (*definition.args.posonlyargs, *definition.args.args)]
    keyword_only = [argument.arg for argument in definition.args.kwonlyargs]
    if "_context" not in positional and "_context" not in keyword_only:
        loads_runtime_context = any(
            isinstance(node, ast.Name) and node.id == "_context" and isinstance(node.ctx, ast.Load)
            for node in ast.walk(definition)
        )
        if loads_runtime_context:
            raise CapabilityAuthoringError(
                f"{function_name} reads _context but does not accept _context=None"
            )
    accepted = set(positional + keyword_only) - {"_context"}
    # ``_context`` is injected by the trusted runtime.  It is valid for the
    # Python function to accept it, but it is never a model-facing argument.
    properties = set(schema.get("properties", {})) - {"_context"}
    if definition.args.kwarg is None:
        missing_in_function = sorted(properties - accepted)
        if missing_in_function:
            raise CapabilityAuthoringError(
                f"parameters_schema declares arguments not accepted by {function_name}: {missing_in_function}"
            )

    positional_defaults = len(definition.args.defaults)
    required_positional = set(positional[: len(positional) - positional_defaults] if positional_defaults else positional)
    required_keyword = {
        argument.arg for argument, default in zip(definition.args.kwonlyargs, definition.args.kw_defaults)
        if default is None
    }
    undeclared_required = sorted((required_positional | required_keyword) - {"_context"} - properties)
    if undeclared_required:
        raise CapabilityAuthoringError(
            f"function requires arguments missing from parameters_schema: {undeclared_required}"
        )


def _atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def create_executable_skill(
    project_root: str | Path,
    *,
    identity_name: str,
    skill_name: str,
    description: str,
    parameters_schema: Any,
    function_code: str,
) -> dict[str, Any]:
    """Create one validated executable Skill without overwriting user data."""

    root = Path(project_root).resolve()
    if not _SAFE_NAME.fullmatch(str(identity_name or "")):
        raise CapabilityAuthoringError("identity_name must be a safe ASCII identifier")
    normalized_name = str(skill_name or "").strip().replace("-", "_").replace(" ", "_")
    if not _SAFE_NAME.fullmatch(normalized_name):
        raise CapabilityAuthoringError("skill_name must be snake_case and start with a letter or underscore")
    clean_description = str(description or "").strip()
    if not clean_description:
        raise CapabilityAuthoringError("description cannot be empty")

    identity_root = (root / "identity").resolve()
    identity_dir = (identity_root / identity_name).resolve()
    if identity_root not in identity_dir.parents or not (identity_dir / "id.json").is_file():
        raise CapabilityAuthoringError(f"identity {identity_name!r} does not exist")
    skill_dir = (identity_dir / "ego" / "skills" / normalized_name).resolve()
    if identity_dir not in skill_dir.parents:
        raise CapabilityAuthoringError("skill path escaped the target identity")
    if skill_dir.exists():
        raise CapabilityAuthoringError(f"skill {normalized_name!r} already exists for {identity_name!r}")

    schema = parse_parameters_schema(parameters_schema)
    # Weak models sometimes copy the optional runtime-only ``_context``
    # parameter into JSON Schema despite the tool description telling them not
    # to. Accept that harmless redundancy, then remove it from the public tool
    # contract so callers cannot forge trusted runtime context.
    schema = json.loads(json.dumps(schema))
    schema.setdefault("properties", {}).pop("_context", None)
    schema["required"] = [name for name in schema.get("required", []) if name != "_context"]
    _validate_function(str(function_code or ""), normalized_name, schema)
    meta = {
        "type": "tool",
        "name": normalized_name,
        "description": clean_description,
        "parameters": schema,
        "authoring": {"kind": "executable_skill", "version": 1},
    }
    script_path = skill_dir / "scripts" / f"{normalized_name}.py"
    try:
        _atomic_text(skill_dir / "meta.json", json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
        _atomic_text(script_path, str(function_code).rstrip() + "\n")
    except BaseException:
        # Only remove the just-created target. Existing directories are rejected
        # above, so cleanup can never delete user-owned capability data.
        import shutil

        shutil.rmtree(skill_dir, ignore_errors=True)
        raise

    return {
        "ok": True,
        "kind": "skill",
        "identity": identity_name,
        "name": normalized_name,
        "path": str(skill_dir),
        "runtime_interface": normalized_name,
        "reload_required": True,
        "message": "The Skill is persisted and will be available after the Identity is reloaded.",
    }
