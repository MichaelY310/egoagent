"""Human feedback annotations and reproducible training-dataset export.

The native trajectory is an immutable account of what the runtime actually did.
Human judgements are intentionally stored in a separate, mutable sidecar so a
later rating edit never changes replay integrity or the source hashes recorded
by :mod:`trajectory`.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterable, Optional

from trajectory import TrajectoryReader, messages_sha256, payload_sha256, redact_sensitive_value


ANNOTATION_STORE_SCHEMA = "ego.training-annotations.v1"
ANNOTATION_SCHEMA = "ego.training-annotation.v1"
TRAINING_EXPORT_SCHEMA = "ego.training-export.v1"
DEFAULT_STORE_PATH = Path(__file__).resolve().parent / ".egoagent" / "training" / "annotations.json"
TARGET_TYPES = {"session", "message", "model_call", "event"}
RATINGS = {"up", "down", "neutral"}
EXPORT_FORMATS = {
    "conversation",
    "message_sft",
    "model_call_sft",
    "preference",
    "kto",
    "unary_feedback",
    "trajectory",
    "verl",
}
_STORE_LOCK = threading.RLock()


def _safe_json(value: Any) -> Any:
    redacted, _ = redact_sensitive_value(copy.deepcopy(value))
    return redacted


def _is_filesystem_root(path: Path) -> bool:
    resolved = path.resolve()
    return resolved == Path(resolved.anchor)


def _annotation_key(session: str, target_type: str, target_id: str) -> str:
    return f"{session}\u241f{target_type}\u241f{target_id}"


def message_target_id(index: int, message: dict[str, Any]) -> str:
    """Return a stable-enough ID that also detects changed message content."""

    return f"msg_{int(index)}_{payload_sha256(message)[:16]}"


def load_session_messages(session_dir: Path | str) -> list[dict[str, Any]]:
    session_dir = Path(session_dir)
    source = session_dir / "full_messages.json"
    if not source.is_file():
        source = session_dir / "messages.json"
    if not source.is_file():
        return []
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    return [copy.deepcopy(item) for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def annotated_session_messages(session_dir: Path | str) -> list[dict[str, Any]]:
    """Add UI-only stable target metadata without altering stored messages."""

    result = []
    for index, message in enumerate(load_session_messages(session_dir)):
        public = copy.deepcopy(message)
        public["_training"] = {
            "target_id": message_target_id(index, message),
            "source_hash": payload_sha256(message),
            "index": index,
        }
        result.append(public)
    return result


def session_source_hash(session_dir: Path | str) -> str:
    session_dir = Path(session_dir)
    trajectory = session_dir / "trajectory.jsonl"
    if trajectory.is_file():
        return hashlib.sha256(trajectory.read_bytes()).hexdigest()
    return messages_sha256(load_session_messages(session_dir))


class TrainingAnnotationStore:
    """Small atomic JSON store for user judgements.

    The server is threaded, so all read-modify-write operations share one lock.
    A temporary file + ``os.replace`` prevents partially written annotation
    files after a crash.
    """

    def __init__(self, path: Path | str = DEFAULT_STORE_PATH) -> None:
        self.path = Path(path)

    def _empty(self) -> dict[str, Any]:
        return {"schema": ANNOTATION_STORE_SCHEMA, "revision": 0, "annotations": {}}

    def _load_unlocked(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return self._empty()
        except (OSError, ValueError, TypeError) as error:
            raise ValueError(f"Training annotation store is unreadable: {error}") from error
        if not isinstance(payload, dict) or payload.get("schema") != ANNOTATION_STORE_SCHEMA:
            raise ValueError("Training annotation store has an unsupported schema")
        if not isinstance(payload.get("annotations"), dict):
            raise ValueError("Training annotation store has invalid annotations")
        return payload

    def _write_unlocked(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, self.path)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def list(
        self,
        *,
        session: Optional[str] = None,
        target_type: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        with _STORE_LOCK:
            payload = self._load_unlocked()
        annotations = [copy.deepcopy(value) for value in payload["annotations"].values()]
        if session is not None:
            annotations = [item for item in annotations if item.get("session") == str(session)]
        if target_type is not None:
            annotations = [item for item in annotations if item.get("target_type") == str(target_type)]
        annotations.sort(key=lambda item: (str(item.get("session")), float(item.get("updated_at", 0))), reverse=True)
        return annotations

    def get(self, session: str, target_type: str, target_id: str) -> Optional[dict[str, Any]]:
        key = _annotation_key(str(session), str(target_type), str(target_id))
        with _STORE_LOCK:
            value = self._load_unlocked()["annotations"].get(key)
        return copy.deepcopy(value) if isinstance(value, dict) else None

    def upsert(
        self,
        *,
        session: str,
        target_type: str,
        target_id: str,
        source_hash: str,
        rating: str = "neutral",
        important: bool = False,
        include_in_training: bool = False,
        tags: Optional[Iterable[str]] = None,
        note: str = "",
    ) -> dict[str, Any]:
        session = str(session or "").strip()
        target_type = str(target_type or "").strip()
        target_id = str(target_id or "").strip()
        source_hash = str(source_hash or "").strip()
        rating = str(rating or "neutral").strip().lower()
        if not session or not target_id or not source_hash:
            raise ValueError("session, target_id and source_hash are required")
        if target_type not in TARGET_TYPES:
            raise ValueError(f"target_type must be one of {sorted(TARGET_TYPES)}")
        if rating not in RATINGS:
            raise ValueError(f"rating must be one of {sorted(RATINGS)}")
        clean_tags = sorted({str(tag).strip()[:64] for tag in (tags or []) if str(tag).strip()})[:32]
        clean_note = str(note or "").strip()[:4000]
        key = _annotation_key(session, target_type, target_id)
        now = time.time()
        with _STORE_LOCK:
            payload = self._load_unlocked()
            previous = payload["annotations"].get(key) or {}
            annotation = {
                "schema": ANNOTATION_SCHEMA,
                "id": str(previous.get("id") or f"ann_{uuid.uuid4().hex}"),
                "session": session,
                "target_type": target_type,
                "target_id": target_id,
                "source_hash": source_hash,
                "rating": rating,
                "important": bool(important),
                "include_in_training": bool(include_in_training),
                "tags": clean_tags,
                "note": clean_note,
                "created_at": float(previous.get("created_at") or now),
                "updated_at": now,
            }
            payload["annotations"][key] = annotation
            payload["revision"] = int(payload.get("revision", 0) or 0) + 1
            payload["updated_at"] = now
            self._write_unlocked(payload)
        return copy.deepcopy(annotation)

    def summary(self) -> dict[str, Any]:
        annotations = self.list()
        return {
            "total": len(annotations),
            "ratings": {value: sum(item.get("rating") == value for item in annotations) for value in RATINGS},
            "important": sum(bool(item.get("important")) for item in annotations),
            "included": sum(bool(item.get("include_in_training")) for item in annotations),
            "sessions": len({str(item.get("session")) for item in annotations}),
        }


def resolve_target_source(
    session_name: str,
    session_dir: Path | str,
    target_type: str,
    target_id: str,
) -> tuple[Any, str]:
    """Resolve and hash a target server-side to reject stale/tampered IDs."""

    session_dir = Path(session_dir)
    if target_type == "session":
        return {"session": session_name}, session_source_hash(session_dir)
    if target_type == "message":
        for index, message in enumerate(load_session_messages(session_dir)):
            if message_target_id(index, message) == target_id:
                return message, payload_sha256(message)
        raise ValueError("The message target is stale or does not exist")
    trajectory_path = session_dir / "trajectory.jsonl"
    if not trajectory_path.is_file():
        raise ValueError("This session has no exact trajectory")
    reader = TrajectoryReader(trajectory_path)
    if target_type == "model_call":
        for call in reader.model_calls(include_incomplete=True):
            if call.get("model_call_id") == target_id:
                return call, payload_sha256(call)
        raise ValueError("The model call target does not exist")
    if target_type == "event":
        for event in reader.iter_events(strict=False) or []:
            if event.get("event_id") == target_id:
                return event, payload_sha256(event)
        raise ValueError("The trajectory event target does not exist")
    raise ValueError(f"Unsupported target type: {target_type}")


def _marked(annotation: Optional[dict[str, Any]]) -> bool:
    return bool(annotation and (
        annotation.get("include_in_training")
        or annotation.get("important")
        or annotation.get("rating") in {"up", "down"}
    ))


def _positive(annotation: Optional[dict[str, Any]]) -> bool:
    return not annotation or annotation.get("rating") != "down"


def _completion_message(call: dict[str, Any], *, include_reasoning: bool) -> dict[str, Any]:
    response = call.get("response") or {}
    content = str(response.get("content") or "")
    if include_reasoning and response.get("reasoning"):
        content = f"<think>{response['reasoning']}</think>\n{content}"
    result: dict[str, Any] = {"role": "assistant", "content": content}
    if response.get("tool_calls"):
        result["tool_calls"] = copy.deepcopy(response["tool_calls"])
    return result


def _preference_prompt_hash(messages: Any, tools: Any) -> str:
    """Hash semantic prompt content while ignoring EgoAgent UI bookkeeping."""

    def clean(value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): clean(child) for key, child in value.items() if not str(key).startswith("_")}
        if isinstance(value, list):
            return [clean(child) for child in value]
        return value

    return payload_sha256({"messages": clean(messages if isinstance(messages, list) else []), "tools": clean(tools if isinstance(tools, list) else [])})


def _sharegpt_messages(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, str]]]:
    systems: list[str] = []
    conversations: list[dict[str, str]] = []
    for message in messages:
        role = str(message.get("role") or "user")
        content = message.get("content", "")
        value = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, separators=(",", ":"))
        if message.get("tool_calls"):
            value = json.dumps({"content": value, "tool_calls": message["tool_calls"]}, ensure_ascii=False, separators=(",", ":"))
        if role == "system":
            systems.append(value)
        else:
            tag = "gpt" if role == "assistant" else "observation" if role == "tool" else "human"
            conversations.append({"from": tag, "value": value})
    return "\n\n".join(systems), conversations


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(_safe_json(row), ensure_ascii=False, separators=(",", ":")) + "\n")
            count += 1
    return count


def export_annotated_training_data(
    session_sources: Iterable[tuple[str, Path | str]],
    destination: Path | str,
    *,
    store: Optional[TrainingAnnotationStore] = None,
    selection: str = "marked",
    formats: Optional[Iterable[str]] = None,
    include_reasoning: bool = False,
) -> dict[str, Any]:
    """Export labelled sessions without collapsing distinct Agent identities.

    ``selection='marked'`` exports only targets that are liked, disliked,
    important, or explicitly added to the dataset.  ``selection='all'`` is an
    explicit escape hatch for exporting an entire Session.  Disliked targets
    are never used as positive SFT examples, but remain available in unary
    feedback, preference, and reward projections.
    """

    if selection not in {"marked", "all"}:
        raise ValueError("selection must be 'marked' or 'all'")
    selected_formats = set(formats or EXPORT_FORMATS)
    unknown = selected_formats - EXPORT_FORMATS
    if unknown:
        raise ValueError(f"Unsupported training export formats: {sorted(unknown)}")
    destination = Path(destination).expanduser().resolve()
    if _is_filesystem_root(destination):
        raise ValueError("Training export destination cannot be a filesystem root")
    destination.mkdir(parents=True, exist_ok=True)
    store = store or TrainingAnnotationStore()
    all_annotations = store.list()
    by_session: dict[str, list[dict[str, Any]]] = {}
    for annotation in all_annotations:
        by_session.setdefault(str(annotation.get("session")), []).append(annotation)

    conversation_rows: list[dict[str, Any]] = []
    message_rows: list[dict[str, Any]] = []
    call_rows: list[dict[str, Any]] = []
    sharegpt_rows: list[dict[str, Any]] = []
    unary_rows: list[dict[str, Any]] = []
    trajectory_rows: list[dict[str, Any]] = []
    verl_rows: list[dict[str, Any]] = []
    kto_rows: list[dict[str, Any]] = []
    preference_candidates: dict[str, dict[str, list[dict[str, Any]]]] = {}
    source_manifest: list[dict[str, Any]] = []

    for session_name, raw_dir in session_sources:
        session_dir = Path(raw_dir).resolve()
        annotations = by_session.get(str(session_name), [])
        annotation_map = {(str(item.get("target_type")), str(item.get("target_id"))): item for item in annotations}
        session_annotation = next((item for item in annotations if item.get("target_type") == "session"), None)
        messages = load_session_messages(session_dir)
        source_hash = session_source_hash(session_dir)
        session_selected = selection == "all" or _marked(session_annotation)
        source_manifest.append({
            "session": session_name,
            "path": str(session_dir),
            "source_hash": source_hash,
            "annotations": len(annotations),
            "selected": session_selected,
        })

        if session_selected and _positive(session_annotation) and messages:
            clean_messages = _safe_json(messages)
            conversation_rows.append({
                "messages": clean_messages,
            })

        for index, message in enumerate(messages):
            target_id = message_target_id(index, message)
            annotation = annotation_map.get(("message", target_id))
            if annotation:
                unary_rows.append({"annotation": annotation, "target": _safe_json(message), "context": _safe_json(messages[: index + 1])})
            if str(message.get("role")) != "assistant":
                continue
            chosen = selection == "all" and session_selected or _marked(annotation)
            effective = annotation or session_annotation
            if chosen and _positive(effective):
                message_rows.append({
                    "messages": _safe_json(messages[: index + 1]),
                })

        trajectory_path = session_dir / "trajectory.jsonl"
        if not trajectory_path.is_file():
            continue
        reader = TrajectoryReader(trajectory_path)
        validation = reader.validate()
        if not validation.get("valid"):
            raise ValueError(f"Cannot export invalid trajectory for {session_name}: {'; '.join(validation.get('errors', [])[:3])}")
        calls = reader.model_calls(include_incomplete=False)
        for call in calls:
            call_id = str(call.get("model_call_id") or "")
            annotation = annotation_map.get(("model_call", call_id))
            effective = annotation or session_annotation
            if annotation:
                unary_rows.append({"annotation": annotation, "target": _safe_json(call)})
            include_call = selection == "all" and session_selected or _marked(annotation) or (session_selected and annotation is None)
            response = call.get("response") or {}
            usable = not response.get("error") and bool(str(response.get("content") or "").strip() or response.get("tool_calls"))
            if include_call and usable and _positive(effective):
                row = _safe_json(call)
                row["training_annotation"] = copy.deepcopy(effective)
                call_rows.append(row)
                model_messages = copy.deepcopy(call.get("messages") or []) + [_completion_message(call, include_reasoning=include_reasoning)]
                system, conversations = _sharegpt_messages(model_messages)
                sharegpt_rows.append({
                    "system": system,
                    "conversations": conversations,
                    "tools": json.dumps(call.get("tools") or [], ensure_ascii=False, separators=(",", ":")),
                    "metadata": {**copy.deepcopy(call.get("metadata") or {}), "annotation": effective},
                })
            if include_call and usable:
                reward = 1.0 if effective and effective.get("rating") == "up" else -1.0 if effective and effective.get("rating") == "down" else None
                verl_rows.append({
                    "data_source": "egoagent_human_feedback",
                    "prompt": _safe_json(call.get("messages") or []),
                    "response": _safe_json(response),
                    "ability": (call.get("metadata") or {}).get("purpose") or "agent",
                    "reward": reward,
                    "reward_model": {"style": "human_feedback" if reward is not None else "unlabelled", "ground_truth": copy.deepcopy(effective)},
                    "extra_info": {**copy.deepcopy(call.get("metadata") or {}), "session": session_name, "tools": _safe_json(call.get("tools") or [])},
                })
            if annotation and annotation.get("rating") in {"up", "down"} and usable:
                kto_rows.append({
                    "prompt": _safe_json(call.get("messages") or []),
                    "completion": [_completion_message(call, include_reasoning=include_reasoning)],
                    "label": annotation.get("rating") == "up",
                    "tools": _safe_json(call.get("tools") or []),
                })
            # DPO requires two alternatives for the exact same prompt.  Only
            # direct call ratings are paired; a blanket Session rating is not
            # precise enough to claim one completion beats another.
            if annotation and annotation.get("rating") in {"up", "down"} and usable:
                prompt_hash = _preference_prompt_hash(call.get("messages") or [], call.get("tools") or [])
                bucket = preference_candidates.setdefault(prompt_hash, {"up": [], "down": []})
                bucket[str(annotation["rating"])].append({"call": call, "annotation": annotation, "session": session_name})

        if (session_selected or any(_marked(item) for item in annotations)) and "trajectory" in selected_formats:
            for event in reader.iter_events(strict=False) or []:
                trajectory_rows.append({"session": session_name, "source_hash": source_hash, "event": event})

        if session_annotation:
            unary_rows.append({
                "annotation": session_annotation,
                "target": {"session": session_name, "source_hash": source_hash},
            })

    preference_rows: list[dict[str, Any]] = []
    for prompt_hash, candidates in preference_candidates.items():
        if not candidates["up"] or not candidates["down"]:
            continue
        chosen = candidates["up"][-1]
        rejected = candidates["down"][-1]
        chosen_call, rejected_call = chosen["call"], rejected["call"]
        preference_rows.append({
            "prompt": _safe_json(chosen_call.get("messages") or []),
            "chosen": [_completion_message(chosen_call, include_reasoning=include_reasoning)],
            "rejected": [_completion_message(rejected_call, include_reasoning=include_reasoning)],
            "tools": _safe_json(chosen_call.get("tools") or []),
            "metadata": {
                "prompt_hash": prompt_hash,
                "chosen_session": chosen["session"],
                "rejected_session": rejected["session"],
                "chosen_annotation": chosen["annotation"],
                "rejected_annotation": rejected["annotation"],
            },
        })

    files: dict[str, Optional[str]] = {}
    counts: dict[str, int] = {}
    projections = {
        "conversation": ("conversations_openai.jsonl", conversation_rows),
        "message_sft": ("message_sft_openai.jsonl", message_rows),
        "model_call_sft": ("model_calls.jsonl", call_rows),
        "preference": ("preferences_trl.jsonl", preference_rows),
        "kto": ("kto_trl.jsonl", kto_rows),
        "unary_feedback": ("unary_feedback.jsonl", unary_rows),
        "trajectory": ("trajectories.jsonl", trajectory_rows),
        "verl": ("verl_rollouts.jsonl", verl_rows),
    }
    for format_name, (filename, rows) in projections.items():
        if format_name in selected_formats:
            path = destination / filename
            counts[format_name] = _write_jsonl(path, rows)
            files[format_name] = str(path)
        else:
            counts[format_name] = 0
            files[format_name] = None
    if "model_call_sft" in selected_formats:
        sharegpt_path = destination / "llamafactory_sharegpt.jsonl"
        counts["llamafactory_sharegpt"] = _write_jsonl(sharegpt_path, sharegpt_rows)
        files["llamafactory_sharegpt"] = str(sharegpt_path)
        dataset_info = {
            "egoagent_sft": {
                "file_name": sharegpt_path.name,
                "formatting": "sharegpt",
                "columns": {"messages": "conversations", "system": "system", "tools": "tools"},
                "tags": {"role_tag": "from", "content_tag": "value", "user_tag": "human", "assistant_tag": "gpt", "observation_tag": "observation"},
            }
        }
        dataset_info_path = destination / "dataset_info.json"
        dataset_info_path.write_text(json.dumps(dataset_info, ensure_ascii=False, indent=2), encoding="utf-8")
        files["llamafactory_dataset_info"] = str(dataset_info_path)

    manifest = {
        "schema": TRAINING_EXPORT_SCHEMA,
        "created_at": time.time(),
        "destination": str(destination),
        "selection": selection,
        "formats": sorted(selected_formats),
        "include_reasoning": bool(include_reasoning),
        "sources": source_manifest,
        "counts": counts,
        "files": files,
        "annotation_store": str(store.path.resolve()),
        "annotation_store_sha256": hashlib.sha256(store.path.read_bytes()).hexdigest() if store.path.is_file() else None,
        "quality_rules": [
            "Down-rated examples are excluded from positive SFT projections.",
            "TRL preference rows require directly rated chosen/rejected model calls with identical prompt hashes.",
            "Agent, identity, harness, node and model-call identities remain explicit in exact-call and trajectory projections.",
            "Secret-like values are redacted again at the export boundary.",
        ],
    }
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["manifest_path"] = str(manifest_path)
    return manifest
