"""User-defined dataset adapters for Task Bench.

The product deliberately stores a normalized, inspectable copy of every row
instead of letting an experiment runner interpret an arbitrary dataset at run
time.  This makes field mapping reviewable in the UI and keeps historical
experiments reproducible when the original CSV/JSONL later changes.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Mapping


DATASET_VERSION = "ego.dataset.v1"
SUPPORTED_FORMATS = {"json", "jsonl", "csv"}
MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_ROWS = 10_000


class DatasetError(ValueError):
    pass


def _safe_name(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", text) or text in {".", ".."}:
        raise DatasetError(f"Invalid {label}: {text!r}")
    return text


def _materialized_task_id(dataset_id: str, case_id: str) -> str:
    value = f"{dataset_id}__{case_id}"
    if len(value) <= 96:
        return _safe_name(value, "materialized task id")
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    # Preserve readable prefixes from both sides while making truncation
    # collision-resistant and staying inside ego.task.v1's identifier bound.
    value = f"{dataset_id[:38]}__{case_id[:38]}__{digest}"
    return _safe_name(value, "materialized task id")


def _field(row: Any, selector: object, default: Any = None) -> Any:
    """Read a dotted path or JSON Pointer from one source row."""
    path = str(selector or "").strip()
    if not path:
        return default
    current = row
    tokens = (
        [token.replace("~1", "/").replace("~0", "~") for token in path.strip("/").split("/")]
        if path.startswith("/")
        else path.split(".")
    )
    try:
        for token in tokens:
            if isinstance(current, list):
                current = current[int(token)]
            elif isinstance(current, Mapping):
                current = current[token]
            else:
                return default
    except (KeyError, IndexError, TypeError, ValueError):
        return default
    return current


def _parse_source(source_format: str, content: str) -> list[Any]:
    source_format = str(source_format or "").lower()
    if source_format not in SUPPORTED_FORMATS:
        raise DatasetError(f"Unsupported dataset format: {source_format!r}")
    encoded = str(content or "").encode("utf-8")
    if not encoded:
        raise DatasetError("Dataset content is empty")
    if len(encoded) > MAX_SOURCE_BYTES:
        raise DatasetError("Dataset source exceeds the 8 MiB limit")
    try:
        if source_format == "json":
            payload = json.loads(content)
            if isinstance(payload, dict):
                # Common dataset envelopes remain convenient without guessing
                # among every list-valued field in an arbitrary object.
                for key in ("rows", "records", "items", "data", "examples"):
                    if isinstance(payload.get(key), list):
                        payload = payload[key]
                        break
            if not isinstance(payload, list):
                raise DatasetError("JSON dataset must be an array or a rows/records/items/data/examples envelope")
            rows = payload
        elif source_format == "jsonl":
            rows = [json.loads(line) for line in content.splitlines() if line.strip()]
        else:
            rows = list(csv.DictReader(io.StringIO(content)))
    except (csv.Error, json.JSONDecodeError) as error:
        raise DatasetError(f"Cannot parse {source_format} dataset: {error}") from error
    if not rows:
        raise DatasetError("Dataset has no rows")
    if len(rows) > MAX_ROWS:
        raise DatasetError(f"Dataset has {len(rows)} rows; limit is {MAX_ROWS}")
    if not all(isinstance(row, Mapping) for row in rows):
        raise DatasetError("Every dataset row must be an object")
    return rows


def _workspace_files(value: Any, case_id: str) -> dict[str, Any]:
    if value in (None, ""):
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as error:
            raise DatasetError(f"Case {case_id} workspace mapping is not valid JSON") from error
    if not isinstance(value, Mapping):
        raise DatasetError(f"Case {case_id} workspace mapping must resolve to an object")
    result: dict[str, Any] = {}
    for raw_path, content in value.items():
        relative = Path(str(raw_path))
        if relative.is_absolute() or ".." in relative.parts or not str(relative):
            raise DatasetError(f"Case {case_id} has unsafe workspace path: {raw_path}")
        result[relative.as_posix()] = content
    return result


def normalize_rows(rows: list[Any], mapping: Mapping[str, Any]) -> list[dict[str, Any]]:
    prompt_field = mapping.get("prompt")
    if not prompt_field:
        raise DatasetError("Mapping must select a prompt field")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        raw_id = _field(row, mapping.get("id"), f"case-{index:04d}")
        case_id = _safe_name(raw_id, f"case id at row {index}")
        if case_id in seen:
            raise DatasetError(f"Duplicate case id: {case_id}")
        seen.add(case_id)
        prompt = str(_field(row, prompt_field, "") or "").strip()
        if not prompt:
            raise DatasetError(f"Case {case_id} has an empty prompt")
        title = str(_field(row, mapping.get("title"), case_id) or case_id).strip()
        expected = _field(row, mapping.get("expected"), None)
        workspace = _workspace_files(_field(row, mapping.get("workspace_files"), {}), case_id)
        metadata = _field(row, mapping.get("metadata"), {})
        normalized.append({
            "id": case_id,
            "title": title,
            "prompt": prompt,
            "expected": expected,
            "workspace_files": workspace,
            "metadata": metadata if isinstance(metadata, Mapping) else {"value": metadata},
            "source_index": index - 1,
            "source_sha256": hashlib.sha256(
                json.dumps(row, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest(),
        })
    return normalized


def _substitute(value: Any, case: Mapping[str, Any]) -> Any:
    """Expand exact placeholders without turning typed values into strings."""
    if isinstance(value, str):
        exact = re.fullmatch(r"\$\{([^}]+)\}", value)
        if exact:
            return _field(case, exact.group(1), value)
        return re.sub(
            r"\$\{([^}]+)\}",
            lambda match: str(_field(case, match.group(1), match.group(0))),
            value,
        )
    if isinstance(value, list):
        return [_substitute(item, case) for item in value]
    if isinstance(value, dict):
        return {key: _substitute(item, case) for key, item in value.items()}
    return value


class DatasetStore:
    def __init__(self, project_root: Path, *, dataset_dir: Path | None = None, task_dir: Path | None = None):
        self.project_root = Path(project_root).resolve()
        self.dataset_dir = Path(dataset_dir or self.project_root / ".egoagent" / "datasets").resolve()
        self.task_dir = Path(task_dir or self.project_root / "task_bench" / "tasks").resolve()
        self.dataset_dir.mkdir(parents=True, exist_ok=True)
        self.task_dir.mkdir(parents=True, exist_ok=True)

    def preview(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        source_format = str(payload.get("format", "jsonl")).lower()
        content = str(payload.get("content", ""))
        rows = _parse_source(source_format, content)
        cases = normalize_rows(rows, payload.get("mapping", {}) or {})
        fields = sorted({str(key) for row in rows[:100] for key in row.keys()})
        return {
            "version": DATASET_VERSION,
            "format": source_format,
            "row_count": len(rows),
            "fields": fields,
            "cases": cases[:20],
            "source_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        }

    def create(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        dataset_id = _safe_name(payload.get("id"), "dataset id")
        title = str(payload.get("title") or dataset_id).strip()
        source_format = str(payload.get("format", "jsonl")).lower()
        content = str(payload.get("content", ""))
        mapping = dict(payload.get("mapping", {}) or {})
        preview = self.preview({"format": source_format, "content": content, "mapping": mapping})
        root = self.dataset_dir / dataset_id
        if root.exists() and not payload.get("overwrite"):
            raise DatasetError(f"Dataset already exists: {dataset_id}; enable overwrite to replace it")
        suffix = {"json": "json", "jsonl": "jsonl", "csv": "csv"}[source_format]
        source_name = f"source.{suffix}"

        defaults = dict(payload.get("defaults", {}) or {})
        for key in ("selection", "environment", "execution", "evolution"):
            if key in defaults and not isinstance(defaults[key], Mapping):
                raise DatasetError(f"Dataset default {key} must be an object")
        raw_tags = defaults.get("tags", ["dataset", dataset_id])
        if not isinstance(raw_tags, list) or not all(isinstance(tag, str) for tag in raw_tags):
            raise DatasetError("Dataset default tags must be a list of strings")
        evaluation_template = payload.get("evaluation_template")
        if evaluation_template is not None and not isinstance(evaluation_template, Mapping):
            raise DatasetError("evaluation_template must be an object")
        tasks: list[str] = []
        task_payloads: dict[str, dict[str, Any]] = {}
        normalized_cases = normalize_rows(_parse_source(source_format, content), mapping)
        for case in normalized_cases:
            task_id = _materialized_task_id(dataset_id, case["id"])
            evaluation = _substitute(evaluation_template, case) if isinstance(evaluation_template, Mapping) else None
            if evaluation is None:
                checks = [] if case.get("expected") is None else [{
                    "id": "expected_response", "type": "response_contains", "value": str(case["expected"]),
                }]
                evaluation = {"pass_score": 1.0, "checks": checks}
            task = {
                "version": "ego.task.v1",
                "id": task_id,
                "title": case["title"],
                "description": str(defaults.get("description", f"Dataset case {case['id']} from {title}")),
                "category": str(defaults.get("category", "dataset")),
                "difficulty": str(defaults.get("difficulty", "research")),
                "tags": list(raw_tags),
                "prompt": case["prompt"],
                "workspace": {"files": case["workspace_files"]},
                "selection": dict(defaults.get("selection", {})),
                "environment": dict(defaults.get("environment", {"backend": "local", "network": "disabled"})),
                "execution": dict(defaults.get("execution", {"timeout_seconds": 900})),
                "evolution": dict(defaults.get("evolution", {"allowed": False})),
                "evaluation": evaluation,
                "dataset": {
                    "id": dataset_id, "case_id": case["id"], "source_index": case["source_index"],
                    "source_sha256": case["source_sha256"], "metadata": case["metadata"],
                },
            }
            task_payloads[task_id] = task
            tasks.append(task_id)

        manifest = {
            "version": DATASET_VERSION,
            "id": dataset_id,
            "title": title,
            "description": str(payload.get("description", "")),
            "format": source_format,
            "mapping": mapping,
            "defaults": defaults,
            "evaluation_template": evaluation_template,
            "row_count": len(normalized_cases),
            "fields": preview["fields"],
            "source": source_name,
            "source_sha256": preview["source_sha256"],
            "tasks": tasks,
            "cases": normalized_cases,
            "created_at": time.time(),
        }
        # Stage every byte before replacing either the dataset manifest or any
        # materialized task.  A malformed late row must never leave half a
        # dataset visible to Task Bench.
        transaction = uuid.uuid4().hex
        staged_root = self.dataset_dir / f".{dataset_id}.{transaction}.tmp"
        staged_tasks: dict[str, Path] = {}
        old_manifest: dict[str, Any] = {}
        if (root / "manifest.json").is_file():
            try:
                old_manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                old_manifest = {}
        try:
            staged_root.mkdir(parents=True, exist_ok=False)
            (staged_root / source_name).write_text(content, encoding="utf-8")
            (staged_root / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            for task_id, task in task_payloads.items():
                staged = self.task_dir / f".{task_id}.{transaction}.tmp"
                staged.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
                staged_tasks[task_id] = staged

            # Task files use atomic file replacement.  Keep the old bytes so a
            # rare filesystem failure during the multi-file commit can roll
            # back all task entries before the new manifest becomes visible.
            old_task_bytes: dict[str, bytes | None] = {}
            committed: list[str] = []
            try:
                for task_id, staged in staged_tasks.items():
                    destination = self.task_dir / f"{task_id}.json"
                    old_task_bytes[task_id] = destination.read_bytes() if destination.is_file() else None
                    staged.replace(destination)
                    committed.append(task_id)

                backup_root = self.dataset_dir / f".{dataset_id}.{transaction}.bak"
                if root.exists():
                    root.replace(backup_root)
                try:
                    staged_root.replace(root)
                except Exception:
                    if backup_root.exists() and not root.exists():
                        backup_root.replace(root)
                    raise
                # The replacement is already committed at this point.  Backup
                # cleanup must therefore be best-effort: a transient antivirus
                # or file-indexer lock must not enter the rollback path and
                # leave the dataset index and materialized task files out of
                # sync.
                if backup_root.exists():
                    shutil.rmtree(backup_root, ignore_errors=True)
            except Exception:
                for task_id in reversed(committed):
                    destination = self.task_dir / f"{task_id}.json"
                    previous = old_task_bytes.get(task_id)
                    if previous is None:
                        destination.unlink(missing_ok=True)
                    else:
                        destination.write_bytes(previous)
                raise

            # Removing cases on overwrite must not leave runnable ghost tasks.
            # Verify ownership before deleting in case a user manually reused
            # the same task id for a different source.
            stale = set(old_manifest.get("tasks", []) or []) - set(tasks)
            for task_id in stale:
                try:
                    path = self.task_dir / f"{_safe_name(task_id, 'old materialized task id')}.json"
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if (data.get("dataset") or {}).get("id") == dataset_id:
                        path.unlink(missing_ok=True)
                except (OSError, ValueError, json.JSONDecodeError, DatasetError):
                    continue
        finally:
            for staged in staged_tasks.values():
                staged.unlink(missing_ok=True)
            if staged_root.exists():
                shutil.rmtree(staged_root, ignore_errors=True)
        return manifest

    def list(self) -> list[dict[str, Any]]:
        result = []
        for path in sorted(self.dataset_dir.glob("*/manifest.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                result.append({key: data.get(key) for key in (
                    "version", "id", "title", "description", "format", "row_count", "fields",
                    "source_sha256", "created_at", "tasks",
                )})
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        return sorted(result, key=lambda item: float(item.get("created_at") or 0), reverse=True)

    def get(self, dataset_id: str) -> dict[str, Any]:
        safe_id = _safe_name(dataset_id, "dataset id")
        path = self.dataset_dir / safe_id / "manifest.json"
        if not path.is_file():
            raise DatasetError(f"Dataset not found: {safe_id}")
        return json.loads(path.read_text(encoding="utf-8"))
