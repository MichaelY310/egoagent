"""Persistent, model-free context handoff for the optional Heart Flow demo."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterable, Optional


SCHEMA = "ego.heart-flow.v1"
_FILE = re.compile(r"(?<![\w:/])(?:[\w.@-]+[\\/])*[\w.@-]+\.[A-Za-z0-9]{1,10}(?::\d+(?:-\d+)?)?")
_BLOCKER = re.compile(r"(?:阻塞|卡住|无法|失败|报错|error|failed|blocked|waiting for approval|需要.{0,8}(?:允许|确认))", re.I)
_NEXT = re.compile(r"(?:下一步|接下来|next(?: step)?|todo)\s*[:：-]?\s*(.+)", re.I)
_TEST = re.compile(r"(?:pytest|unittest|npm test|npm run|测试|tests?|passed|failed|通过|失败)", re.I)
_PROTOCOL_BLOCK = re.compile(r"<(?:tool_call|tool_response|think)>.*?</(?:tool_call|tool_response|think)>", re.I | re.S)
_ATTACHMENT_REF = re.compile(r"\[(?:代码|文本|图片|文件)附件:[^\]]+\]\s*", re.I)


def enabled() -> bool:
    return str(os.environ.get("EGOAGENT_HEART_FLOW_ENABLED", "1")).strip().lower() not in {
        "0", "false", "no", "off",
    }


def _read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return fallback


def _compact(value: object, limit: int = 360) -> str:
    return " ".join(str(value or "").split())[:limit]


def _lines(value: object) -> list[str]:
    return [line.strip(" \t-*•#") for line in str(value or "").splitlines() if line.strip(" \t-*•#")]


def _visible_assistant_text(value: object) -> str:
    return _PROTOCOL_BLOCK.sub("", str(value or "")).strip()


def _is_real_user_message(message: dict[str, Any]) -> bool:
    if message.get("role") != "user":
        return False
    content = str(message.get("content") or "").lstrip()
    return bool(content) and not content.startswith(("<tool_response>", "[System]"))


def _clean_user_text(value: object) -> str:
    text = str(value or "").split("[EgoAgent planned context]", 1)[0]
    return _ATTACHMENT_REF.sub("", text).strip()


class FlowRelayService:
    """Create re-entry capsules and route background events at breakpoints.

    The service intentionally has no LLM dependency.  Its output is a compact,
    editable first draft derived from persisted Session facts.  This makes the
    experiment useful offline and prevents a context switch from itself causing
    an expensive, slow model call.
    """

    def __init__(self, state_path: Path | str):
        self.state_path = Path(state_path)
        self._lock = threading.RLock()

    @staticmethod
    def empty_state() -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "settings": {
                "focus_minutes": 50,
                "wip_limit": 2,
                "notification_policy": "natural_breakpoints",
            },
            "focus": {"project_id": "", "started_at": 0.0, "ends_at": 0.0},
            "capsules": {},
            "inbox": [],
            "run_states": {},
            "updated_at": 0.0,
        }

    def _load(self) -> dict[str, Any]:
        state = _read_json(self.state_path, {})
        if not isinstance(state, dict) or state.get("schema") != SCHEMA:
            return self.empty_state()
        base = self.empty_state()
        base.update(state)
        base["settings"].update(state.get("settings") if isinstance(state.get("settings"), dict) else {})
        base["focus"].update(state.get("focus") if isinstance(state.get("focus"), dict) else {})
        base["capsules"] = state.get("capsules") if isinstance(state.get("capsules"), dict) else {}
        base["inbox"] = state.get("inbox") if isinstance(state.get("inbox"), list) else []
        base["run_states"] = state.get("run_states") if isinstance(state.get("run_states"), dict) else {}
        return base

    def _save(self, state: dict[str, Any]) -> None:
        state["schema"] = SCHEMA
        state["updated_at"] = time.time()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.state_path)

    @staticmethod
    def _messages(session_dir: Path) -> list[dict[str, Any]]:
        for filename in ("full_messages.json", "messages.json"):
            value = _read_json(session_dir / filename, [])
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return []

    @classmethod
    def draft_capsule(
        cls,
        *,
        project: dict[str, Any],
        session: Optional[dict[str, Any]] = None,
        overrides: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        overrides = overrides if isinstance(overrides, dict) else {}
        messages = cls._messages(Path(str(session.get("path")))) if session and session.get("path") else []
        user_text = [
            cleaned for item in messages if _is_real_user_message(item)
            for cleaned in [_clean_user_text(item.get("content"))] if cleaned
        ]
        assistant_text = [
            visible for item in messages if item.get("role") == "assistant"
            for visible in [_visible_assistant_text(item.get("content"))] if visible
        ]
        latest_user = next((_compact(item, 500) for item in reversed(user_text) if _compact(item)), "")
        latest_assistant = next((item for item in reversed(assistant_text) if _compact(item)), "")
        assistant_lines = _lines(latest_assistant)

        next_action = ""
        for text in reversed(assistant_text[-4:]):
            matches = _NEXT.findall(text)
            if matches:
                next_action = _compact(matches[-1], 360)
                break

        blockers: list[str] = []
        tests: list[str] = []
        evidence_text = "\n".join((user_text + assistant_text)[-8:])
        for line in _lines(evidence_text):
            if _BLOCKER.search(line) and line not in blockers:
                blockers.append(_compact(line, 260))
            if _TEST.search(line) and line not in tests:
                tests.append(_compact(line, 260))

        files: list[str] = []
        for match in _FILE.findall(evidence_text):
            if match.lower().startswith(("http.", "https.")) or match in files:
                continue
            files.append(match)

        if not next_action:
            next_action = (
                f"打开 {files[-1]}，核对最后一次修改和验证状态。"
                if files else "回到来源 Session，核对最后结果并确定一个可执行的下一步。"
            )

        progress = []
        for line in assistant_lines[-8:]:
            if line and line not in progress:
                progress.append(_compact(line, 260))

        now = time.time()
        capsule = {
            "id": f"capsule_{uuid.uuid4().hex[:12]}",
            "project_id": str(project.get("id") or ""),
            "project_title": str(project.get("title") or ""),
            "workspace": str(project.get("workspace") or ""),
            "session": str((session or {}).get("name") or ""),
            "goal": latest_user or str((session or {}).get("summary") or project.get("description") or ""),
            "progress": progress[-5:],
            "next_action": next_action,
            "blockers": blockers[-4:],
            "files": files[-10:],
            "tests": tests[-4:],
            "message_count": int((session or {}).get("message_count") or len(messages)),
            "created_at": now,
            "updated_at": now,
        }
        for key in ("goal", "next_action"):
            if key in overrides:
                capsule[key] = _compact(overrides[key], 1000)
        for key in ("progress", "blockers", "files", "tests"):
            if key in overrides and isinstance(overrides[key], list):
                capsule[key] = [_compact(item, 500) for item in overrides[key] if _compact(item)][:20]
        return capsule

    def park(
        self,
        *,
        project: dict[str, Any],
        session: Optional[dict[str, Any]] = None,
        overrides: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        capsule = self.draft_capsule(project=project, session=session, overrides=overrides)
        with self._lock:
            state = self._load()
            state["capsules"][capsule["project_id"]] = capsule
            self._save(state)
        return capsule

    def focus(self, project_id: str, *, minutes: Optional[int] = None) -> dict[str, Any]:
        with self._lock:
            state = self._load()
            duration = max(5, min(int(minutes or state["settings"].get("focus_minutes") or 50), 240))
            now = time.time()
            state["focus"] = {
                "project_id": str(project_id or ""),
                "started_at": now if project_id else 0.0,
                "ends_at": now + duration * 60 if project_id else 0.0,
            }
            self._save(state)
            return dict(state["focus"])

    def update_settings(self, changes: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            state = self._load()
            settings = state["settings"]
            if "focus_minutes" in changes:
                settings["focus_minutes"] = max(5, min(int(changes["focus_minutes"]), 240))
            if "wip_limit" in changes:
                settings["wip_limit"] = max(1, min(int(changes["wip_limit"]), 8))
            if "notification_policy" in changes:
                value = str(changes["notification_policy"])
                if value not in {"natural_breakpoints", "focus_end", "immediate"}:
                    raise ValueError("Unsupported notification policy")
                settings["notification_policy"] = value
            self._save(state)
            return dict(settings)

    @staticmethod
    def _run_phase(run: dict[str, Any]) -> str:
        if run.get("pending_approval"):
            return "approval"
        if run.get("waiting_for_input"):
            return "waiting"
        if run.get("running"):
            return "running"
        termination = str(run.get("termination") or run.get("status") or "completed").lower()
        return "failed" if any(word in termination for word in ("error", "fail", "abort")) else "completed"

    def observe_runs(self, runs: Iterable[dict[str, Any]]) -> None:
        """Store only meaningful state transitions, never token-level noise."""

        with self._lock:
            state = self._load()
            changed = False
            for run in runs:
                run_id = str(run.get("run_id") or "")
                if not run_id:
                    continue
                phase = self._run_phase(run)
                previous = state["run_states"].get(run_id)
                state["run_states"][run_id] = phase
                if phase == previous or phase == "running":
                    continue
                project_id = str(run.get("project_id") or "")
                urgent = phase == "approval"
                state["inbox"].append({
                    "id": f"event_{uuid.uuid4().hex[:12]}",
                    "run_id": run_id,
                    "project_id": project_id,
                    "session": str(run.get("session_name") or ""),
                    "harness": str(run.get("harness") or ""),
                    "phase": phase,
                    "urgent": urgent,
                    "created_at": time.time(),
                    "acknowledged": False,
                    "summary": {
                        "approval": "Agent 需要你的允许",
                        "waiting": "Agent 已到达自然断点，等待输入",
                        "failed": "后台 Agent 运行失败",
                        "completed": "后台 Agent 已完成",
                    }.get(phase, phase),
                })
                changed = True
            if len(state["inbox"]) > 300:
                state["inbox"] = state["inbox"][-300:]
                changed = True
            if changed:
                self._save(state)

    def acknowledge(self, event_ids: Iterable[object]) -> int:
        requested = {str(item) for item in event_ids if str(item)}
        count = 0
        with self._lock:
            state = self._load()
            for item in state["inbox"]:
                if not requested or str(item.get("id")) in requested:
                    if not item.get("acknowledged"):
                        item["acknowledged"] = True
                        count += 1
            self._save(state)
        return count

    def snapshot(self, *, projects: list[dict[str, Any]], runs: Iterable[dict[str, Any]]) -> dict[str, Any]:
        self.observe_runs(runs)
        with self._lock:
            state = self._load()
        project_by_id = {str(item.get("id")): item for item in projects}
        active = str(state["focus"].get("project_id") or "")
        inbox = [item for item in state["inbox"] if not item.get("acknowledged")]
        policy = str(state["settings"].get("notification_policy") or "natural_breakpoints")
        now = time.time()
        focus_ended = bool(active and float(state["focus"].get("ends_at") or 0) <= now)
        for item in inbox:
            is_foreground = bool(active and item.get("project_id") == active)
            item["delivery"] = "now" if (
                item.get("urgent") or is_foreground or policy == "immediate" or focus_ended
            ) else "batched"
            item["project_title"] = str(project_by_id.get(str(item.get("project_id")), {}).get("title") or "Unknown")
        capsule = state["capsules"].get(active) if active else None
        return {
            "schema": SCHEMA,
            "enabled": enabled(),
            "projects": projects,
            "settings": state["settings"],
            "focus": state["focus"],
            "focus_ended": focus_ended,
            "focused_project": project_by_id.get(active),
            "reentry_capsule": capsule,
            "capsules": state["capsules"],
            "inbox": sorted(inbox, key=lambda item: float(item.get("created_at") or 0), reverse=True),
            "batched_count": sum(item.get("delivery") == "batched" for item in inbox),
            "immediate_count": sum(item.get("delivery") == "now" for item in inbox),
        }


__all__ = ["FlowRelayService", "SCHEMA", "enabled"]
