"""Safe import/export adapters for Harbor and legacy Terminal-Bench tasks.

The adapter deliberately produces self-contained ``ego.task.v1`` files.  Text
and binary assets are embedded in the task specification, so importing a task
does not leave a later run dependent on an arbitrary source directory.
"""

from __future__ import annotations

import base64
import copy
import json
import re
import shutil
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

import yaml

from .engine import TASK_SPEC_VERSION, TaskBenchError, _safe_name, _validate_spec


HARBOR_SCHEMA_VERSION = "1.4"
MAX_ASSET_BYTES = 64 * 1024 * 1024
MAX_FILE_BYTES = 16 * 1024 * 1024
IGNORED_NAMES = {".git", "__pycache__", ".DS_Store"}


def detect_task_format(source: Path | str) -> str:
    root = Path(source)
    if root.is_file():
        root = root.parent
    if (root / "task.toml").is_file() and (root / "instruction.md").is_file():
        return "harbor"
    if (root / "task.yaml").is_file() or (root / "task.yml").is_file():
        return "terminal-bench"
    if root.suffix.lower() == ".json":
        return "ego"
    raise TaskBenchError(f"Unsupported task layout: {root}")


def _safe_relative(relative: str) -> str:
    value = str(relative).replace("\\", "/").lstrip("/")
    path = PurePosixPath(value)
    if not value or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise TaskBenchError(f"Unsafe imported task path: {relative}")
    return path.as_posix()


def _iter_assets(root: Path, prefixes: Iterable[str] | None = None) -> Iterable[tuple[str, Path]]:
    roots = [root / item for item in prefixes] if prefixes else [root]
    seen: set[str] = set()
    for asset_root in roots:
        if not asset_root.exists():
            continue
        candidates = [asset_root] if asset_root.is_file() else sorted(asset_root.rglob("*"))
        for path in candidates:
            if path.is_symlink():
                raise TaskBenchError(f"Symlinks are not accepted in imported tasks: {path}")
            if not path.is_file() or any(part in IGNORED_NAMES for part in path.parts):
                continue
            relative = _safe_relative(path.relative_to(root).as_posix())
            if relative not in seen:
                seen.add(relative)
                yield relative, path


def _embedded_files(root: Path, *, prefixes: Iterable[str] | None = None, target_prefix: str = ".external") -> dict[str, Any]:
    result: dict[str, Any] = {}
    total = 0
    for relative, path in _iter_assets(root, prefixes):
        raw = path.read_bytes()
        total += len(raw)
        if len(raw) > MAX_FILE_BYTES or total > MAX_ASSET_BYTES:
            raise TaskBenchError("Imported task assets exceed the 16 MiB/file or 64 MiB/task safety limit")
        target = _safe_relative(f"{target_prefix}/{relative}")
        try:
            result[target] = {"content": raw.decode("utf-8")}
        except UnicodeDecodeError:
            result[target] = {"content_base64": base64.b64encode(raw).decode("ascii"), "binary": True}
    return result


def _read_text(path: Path, *, required: bool = True) -> str:
    if not path.is_file():
        if required:
            raise TaskBenchError(f"Required task file is missing: {path.name}")
        return ""
    if path.stat().st_size > MAX_FILE_BYTES:
        raise TaskBenchError(f"Task file is too large: {path.name}")
    return path.read_text(encoding="utf-8")


def _authors(raw: Any) -> list[str]:
    values = raw if isinstance(raw, list) else ([] if raw is None else [raw])
    result = []
    for item in values:
        if isinstance(item, dict):
            name = str(item.get("name", "")).strip()
            email = str(item.get("email", "")).strip()
            result.append(f"{name} <{email}>" if name and email else name or email)
        elif str(item).strip():
            result.append(str(item).strip())
    return result


def _harbor_environment(task_toml: dict[str, Any]) -> dict[str, Any]:
    environment = task_toml.get("environment", {}) or {}
    task = task_toml.get("task", {}) or {}
    network = "required" if environment.get("allow_internet") or task.get("allow_internet") else "disabled"
    return {
        "backend": "container",
        "network": network,
        "container": {
            "dockerfile": ".external/environment/Dockerfile",
            "build_context": ".external/environment",
            "workdir": str(environment.get("workdir") or "/app"),
            "cpus": environment.get("cpus"),
            "memory_mb": environment.get("memory_mb"),
            "storage_mb": environment.get("storage_mb"),
        },
    }


def _harbor_evaluation(timeout: float, *, step_name: str | None = None, min_reward: float = 1.0) -> dict[str, Any]:
    prefix = f".external/steps/{step_name}/" if step_name else ".external/"
    return {
        "pass_score": float(min_reward),
        "checks": [{
            "id": f"harbor_verifier_{step_name or 'task'}",
            "type": "harbor_verifier",
            "script": f"{prefix}tests/test.sh",
            "timeout_seconds": max(1.0, float(timeout)),
            "reward_file": "/logs/verifier/reward.txt",
            "minimum_reward": float(min_reward),
            "weight": 1,
        }],
    }


def import_harbor_task(source: Path | str, destination: Path | str | None = None) -> dict[str, Any]:
    root = Path(source).resolve()
    if not root.is_dir():
        raise TaskBenchError(f"Harbor task directory not found: {root}")
    meta = tomllib.loads(_read_text(root / "task.toml"))
    task_meta = meta.get("task", {}) or {}
    name = _safe_name(task_meta.get("name") or root.name, "task id")
    instruction = _read_text(root / "instruction.md")
    verifier = meta.get("verifier", {}) or {}
    agent = meta.get("agent", {}) or {}
    assets = _embedded_files(root, target_prefix=".external")
    steps: list[dict[str, Any]] = []
    for index, raw_step in enumerate(meta.get("steps", []) or []):
        if not isinstance(raw_step, dict):
            raise TaskBenchError(f"Harbor step {index + 1} must be a table")
        step_name = _safe_name(raw_step.get("name") or f"step_{index + 1}", "step name")
        step_root = root / "steps" / step_name
        step_prompt = _read_text(step_root / "instruction.md")
        step_timeout = float(raw_step.get("verifier_timeout_sec") or verifier.get("timeout_sec") or 300)
        steps.append({
            "id": step_name,
            "title": str(raw_step.get("description") or step_name),
            "prompt": step_prompt,
            "resume_trajectory": bool(raw_step.get("resume_trajectory", False)),
            "workspace": {"files": {}},
            "evaluation": _harbor_evaluation(
                step_timeout,
                step_name=step_name,
                min_reward=float(raw_step.get("min_reward", 1.0)),
            ),
            "artifacts": list(raw_step.get("artifacts", []) or []),
        })

    timeout = float(agent.get("timeout_sec") or task_meta.get("timeout_sec") or 900)
    spec: dict[str, Any] = {
        "version": TASK_SPEC_VERSION,
        "id": name,
        "title": str(task_meta.get("description") or name),
        "description": str(task_meta.get("description") or "Imported Harbor task"),
        "category": "harbor",
        "difficulty": "research",
        "tags": [str(item) for item in task_meta.get("keywords", []) or []] + ["harbor"],
        "prompt": instruction,
        "workspace": {"files": assets},
        "selection": {},
        "environment": _harbor_environment(meta),
        "execution": {"timeout_seconds": timeout, "interactive": False},
        "evolution": {"allowed": False},
        "evaluation": _harbor_evaluation(float(verifier.get("timeout_sec") or 300)),
        "external_format": {
            "type": "harbor",
            "schema_version": str(meta.get("schema_version") or HARBOR_SCHEMA_VERSION),
            "source_name": root.name,
            "task_version": str(task_meta.get("version") or "1.0.0"),
            "authors": _authors(task_meta.get("authors")),
            "agent_timeout_sec": timeout,
            "verifier_timeout_sec": float(verifier.get("timeout_sec") or 300),
            "asset_root": ".external",
        },
    }
    if steps:
        spec["steps"] = steps
        spec["evaluation"] = {"pass_score": 1.0, "checks": []}
    validated = _validate_spec(spec, Path(destination or root / "task.toml"))
    validated.pop("source", None)
    if destination:
        path = Path(destination)
        if path.is_dir() or not path.suffix:
            path = path / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(validated, ensure_ascii=False, indent=2), encoding="utf-8")
    return validated


def import_terminal_bench_task(source: Path | str, destination: Path | str | None = None) -> dict[str, Any]:
    root = Path(source).resolve()
    yaml_path = root / "task.yaml"
    if not yaml_path.is_file():
        yaml_path = root / "task.yml"
    raw = yaml.safe_load(_read_text(yaml_path)) or {}
    if not isinstance(raw, dict):
        raise TaskBenchError("Terminal-Bench task.yaml must contain a mapping")
    task_id = _safe_name(raw.get("name") or root.name, "task id")
    prompt = str(raw.get("instruction") or raw.get("description") or "").strip()
    if not prompt:
        raise TaskBenchError("Terminal-Bench task has no instruction")
    assets = _embedded_files(root, target_prefix=".external")
    spec = {
        "version": TASK_SPEC_VERSION,
        "id": task_id,
        "title": str(raw.get("description") or task_id).splitlines()[0][:160],
        "description": str(raw.get("description") or "Imported Terminal-Bench task"),
        "category": "terminal-bench",
        "difficulty": str(raw.get("difficulty") or "research") if str(raw.get("difficulty") or "research") in {"starter", "easy", "medium", "hard", "research"} else "research",
        "tags": [str(item) for item in raw.get("tags", []) or []] + ["terminal-bench"],
        "prompt": prompt,
        "workspace": {"files": assets},
        "selection": {},
        "environment": {
            "backend": "container",
            "network": "required" if raw.get("allow_internet") else "disabled",
            "container": {
                "dockerfile": ".external/Dockerfile",
                "build_context": ".external",
                "compose_file": ".external/docker-compose.yaml" if (root / "docker-compose.yaml").is_file() else None,
                "workdir": "/app",
            },
        },
        "execution": {"timeout_seconds": float(raw.get("max_agent_timeout_sec") or 900), "interactive": False},
        "evolution": {"allowed": False},
        "evaluation": {
            "pass_score": 1.0,
            "checks": [{
                "id": "terminal_bench_verifier",
                "type": "harbor_verifier",
                "script": ".external/run-tests.sh",
                "timeout_seconds": float(raw.get("max_test_timeout_sec") or 300),
                "reward_file": "/logs/verifier/reward.txt",
                "legacy_terminal_bench": True,
            }],
        },
        "external_format": {
            "type": "terminal-bench",
            "source_name": root.name,
            "authors": _authors(raw.get("author_name") or raw.get("authors")),
            "asset_root": ".external",
        },
    }
    validated = _validate_spec(spec, Path(destination or yaml_path))
    validated.pop("source", None)
    if destination:
        path = Path(destination)
        if path.is_dir() or not path.suffix:
            path = path / f"{task_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(validated, ensure_ascii=False, indent=2), encoding="utf-8")
    return validated


def import_external_task(source: Path | str, destination: Path | str | None = None) -> dict[str, Any]:
    kind = detect_task_format(source)
    if kind == "harbor":
        return import_harbor_task(source, destination)
    if kind == "terminal-bench":
        return import_terminal_bench_task(source, destination)
    path = Path(source)
    raw = json.loads(path.read_text(encoding="utf-8"))
    validated = _validate_spec(raw, path)
    validated.pop("source", None)
    return validated


def _toml_quote(value: Any) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _write_embedded_assets(spec: dict[str, Any], destination: Path) -> None:
    for relative, raw in spec.get("workspace", {}).get("files", {}).items():
        if not str(relative).startswith(".external/"):
            continue
        target_relative = _safe_relative(str(relative)[len(".external/"):])
        target = destination / target_relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(raw, dict) and "content_base64" in raw:
            target.write_bytes(base64.b64decode(str(raw["content_base64"]), validate=True))
        else:
            target.write_text(str(raw.get("content", "") if isinstance(raw, dict) else raw), encoding="utf-8")


def export_harbor_task(spec_or_path: dict[str, Any] | Path | str, destination: Path | str) -> Path:
    if isinstance(spec_or_path, dict):
        spec = copy.deepcopy(spec_or_path)
        source = Path("<memory>")
    else:
        source = Path(spec_or_path)
        spec = json.loads(source.read_text(encoding="utf-8"))
    spec = _validate_spec(spec, source)
    root = Path(destination).resolve()
    if root.exists() and any(root.iterdir()):
        raise TaskBenchError(f"Harbor export destination must be empty: {root}")
    root.mkdir(parents=True, exist_ok=True)
    _write_embedded_assets(spec, root)
    (root / "instruction.md").write_text(str(spec["prompt"]).rstrip() + "\n", encoding="utf-8")
    environment = spec.get("environment", {}).get("container", {}) or {}
    dockerfile = root / "environment" / "Dockerfile"
    if not dockerfile.exists():
        dockerfile.parent.mkdir(parents=True, exist_ok=True)
        dockerfile.write_text("FROM ubuntu:24.04\nWORKDIR /app\n", encoding="utf-8")
    tests = root / "tests" / "test.sh"
    if not tests.exists():
        tests.parent.mkdir(parents=True, exist_ok=True)
        tests.write_text(
            "#!/bin/sh\nset -eu\nmkdir -p /logs/verifier\n"
            "echo 0 > /logs/verifier/reward.txt\n"
            "echo 'Replace this verifier before publishing the task.' >&2\n",
            encoding="utf-8",
        )
    lines = [
        f"schema_version = {_toml_quote(HARBOR_SCHEMA_VERSION)}",
        "",
        "[task]",
        f"name = {_toml_quote(spec['id'])}",
        f"version = {_toml_quote(spec.get('external_format', {}).get('task_version', '1.0.0'))}",
        f"description = {_toml_quote(spec.get('description') or spec.get('title'))}",
    ]
    tags = spec.get("tags", [])
    lines.append("keywords = [" + ", ".join(_toml_quote(item) for item in tags) + "]")
    lines.extend([
        "",
        "[agent]",
        f"timeout_sec = {float(spec.get('execution', {}).get('timeout_seconds', 900)):g}",
        "",
        "[verifier]",
        f"timeout_sec = {float(spec.get('external_format', {}).get('verifier_timeout_sec', 300)):g}",
        "",
        "[environment]",
        f"allow_internet = {'true' if spec.get('environment', {}).get('network') == 'required' else 'false'}",
        f"workdir = {_toml_quote(environment.get('workdir', '/app'))}",
    ])
    for step in spec.get("steps", []) or []:
        name = _safe_name(step.get("id", ""), "step name")
        step_root = root / "steps" / name
        step_root.mkdir(parents=True, exist_ok=True)
        (step_root / "instruction.md").write_text(str(step.get("prompt", "")).rstrip() + "\n", encoding="utf-8")
        lines.extend([
            "",
            "[[steps]]",
            f"name = {_toml_quote(name)}",
            f"description = {_toml_quote(step.get('title', name))}",
            f"min_reward = {float(step.get('evaluation', {}).get('pass_score', 1.0)):g}",
            f"resume_trajectory = {'true' if step.get('resume_trajectory') else 'false'}",
        ])
    (root / "task.toml").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return root
