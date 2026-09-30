"""
Harness = 控制中心，操作 agents，定义交互逻辑
Session = 运行记录器，存对话历史、状态，提供查询方法
"""
import json
import os
import time
import uuid
import contextvars
import threading
import copy
from contextlib import contextmanager
from pathlib import Path
from utils import load_script
from trajectory import SessionHealth, TrajectoryReader, TrajectoryRecorder, messages_sha256, payload_sha256


class EndSession(Exception):
    """skill 调用此异常来终止当前 session，回到父 harness"""
    pass

# Context-local state preserves the original API while isolating nested,
# parallel and server-side runs from each other.
_current_harness = contextvars.ContextVar("egoagent_current_harness", default=None)
_output_callback = contextvars.ContextVar("egoagent_output_callback", default=None)
_current_run_context = contextvars.ContextVar("egoagent_current_run_context", default=None)
_UNSET = object()


def get_current_harness():
    return _current_harness.get()


def set_current_harness(harness):
    return _current_harness.set(harness)


def reset_current_harness(token):
    _current_harness.reset(token)


def get_output_callback():
    """获取当前全局 output 回调（用于子 harness 推送事件）"""
    return _output_callback.get()


def set_output_callback(cb):
    """设置全局 output 回调"""
    return _output_callback.set(cb)


def reset_output_callback(token):
    _output_callback.reset(token)


def get_current_run_context():
    return _current_run_context.get()


def set_current_run_context(context):
    return _current_run_context.set(context)


def reset_current_run_context(token):
    _current_run_context.reset(token)


@contextmanager
def runtime_scope(*, harness=_UNSET, output_callback=_UNSET, run_context=_UNSET):
    """Bind run-local state and restore the exact previous ContextVar values."""
    tokens = []
    try:
        if harness is not _UNSET:
            tokens.append((_current_harness, _current_harness.set(harness)))
        if output_callback is not _UNSET:
            tokens.append((_output_callback, _output_callback.set(output_callback)))
        if run_context is not _UNSET:
            tokens.append((_current_run_context, _current_run_context.set(run_context)))
        yield
    finally:
        for variable, token in reversed(tokens):
            variable.reset(token)


class Session:
    """纯记录器，不控制任何 agent"""

    def __init__(self, workspace: Path = None, save_dir: Path = None, session_id: str = None):
        self.messages = []
        self.full_messages = []  # 包含 system prompt 的完整版本
        self.workspace = workspace
        self.state = {}
        # The graph does not define a complete Agent by itself.  Persist the
        # per-Session assembly (Harness, slot -> Identity bindings and mode) so
        # Session switching/replay never depends on the last global UI choice.
        self.agent_config = {}
        self.save_dir = Path(save_dir) if save_dir else None
        self.session_id = str(session_id or f"session_{uuid.uuid4().hex}")
        self._lock = threading.RLock()
        self.trajectory = TrajectoryRecorder(
            self.save_dir / "trajectory.jsonl" if self.save_dir else None,
            project_name=(Path(workspace).resolve().name if workspace else None),
        )
        self._context_generation = 0

    def attach_trajectory(self, recorder: TrajectoryRecorder) -> None:
        """Join a parent root trace while retaining this Session's own surface."""
        if recorder is not None:
            self.trajectory = recorder

    def set_save_dir(self, save_dir, *, preserve_trace_id=True) -> None:
        """Relocate an unstarted Session and keep its recorder aligned.

        Task Bench used to assign ``save_dir`` directly after construction,
        which left the native trajectory writing to the old default Session.
        """
        target = Path(save_dir) if save_dir else None
        if target == self.save_dir:
            return
        old_path = self.trajectory.native_path
        if old_path is not None and old_path.is_file() and old_path.stat().st_size:
            raise RuntimeError("Cannot relocate a Session after trajectory events have been written")
        trace_id = self.trajectory.trace_id if preserve_trace_id else None
        self.save_dir = target
        self.trajectory = TrajectoryRecorder(
            target / "trajectory.jsonl" if target else None,
            trace_id=trace_id,
            project_name=(Path(self.workspace).resolve().name if self.workspace else None),
        )

    def _trajectory_context(self, *, agent_name=None):
        run_context = get_current_run_context()
        harness = get_current_harness()
        if run_context is not None:
            harness = run_context.harness
        node_id = getattr(run_context, "current_node", None)
        node_op = None
        if run_context is not None and node_id:
            node = (getattr(run_context, "graph", {}) or {}).get("nodes", {}).get(node_id, {})
            node_op = node.get("op") if isinstance(node, dict) else None
        identity_name = None
        if harness is not None:
            requested_agent = agent_name
            if not requested_agent and node_id:
                node = (getattr(run_context, "graph", {}) or {}).get("nodes", {}).get(node_id, {})
                requested_agent = node.get("agent") if isinstance(node, dict) else None
            agent = getattr(harness, "agents", {}).get(str(requested_agent or ""))
            identity = getattr(agent, "identity", None)
            identity_path = getattr(identity, "identity_path", None)
            if identity_path:
                identity_name = Path(identity_path).name
        return {
            "run_id": getattr(run_context, "run_id", None),
            "parent_run_id": getattr(run_context, "parent_run_id", None),
            "harness": getattr(harness, "name", None),
            "harness_version": getattr(harness, "flow_version", None),
            "node_id": node_id,
            "node_op": node_op,
            "agent": agent_name,
            "identity": identity_name,
        }

    def active_agent_config(self):
        """Return the compact configuration that produced the next message.

        ``agent_config`` also contains the Session-wide revision history.  That
        history belongs in session.json, not on every message.  A compact copy
        makes mixed-Flow conversations independently auditable without
        needlessly inflating the model context.
        """
        config = self.agent_config if isinstance(self.agent_config, dict) else {}
        return copy.deepcopy({
            key: config.get(key)
            for key in (
                "revision", "harness", "harness_version", "agents", "mode", "debug_mode",
                "mutation_targets", "run_id", "activated_at",
            )
            if config.get(key) is not None
        })

    def set_agent_config(self, config, *, run_id=None):
        """Activate a new configuration revision while preserving its history."""
        next_config = copy.deepcopy(config if isinstance(config, dict) else {})
        previous = self.active_agent_config()
        history = copy.deepcopy(
            self.agent_config.get("history", [])
            if isinstance(self.agent_config, dict) and isinstance(self.agent_config.get("history"), list)
            else []
        )
        comparable_keys = ("harness", "harness_version", "agents", "mode", "debug_mode", "mutation_targets")
        changed = bool(previous) and any(previous.get(key) != next_config.get(key) for key in comparable_keys)
        if changed:
            history.append({**previous, "deactivated_at": time.time()})
        revision = int(previous.get("revision") or len(history) or 0) + (1 if changed or not previous else 0)
        next_config.update({
            "revision": max(1, revision),
            "run_id": str(run_id or next_config.get("run_id") or ""),
            "activated_at": time.time(),
            "history": history,
        })
        self.agent_config = next_config
        if changed:
            self.trace(
                "runtime.configuration.changed",
                {"previous": previous, "current": self.active_agent_config()},
            )
        return self.active_agent_config()

    def _annotate_message(self, msg):
        if not isinstance(msg, dict):
            return msg
        config = self.active_agent_config()
        if config:
            msg.setdefault("_agent_config", config)
        role = str(msg.get("role") or "")
        name = str(msg.get("name") or "")
        if name:
            speaker = {"kind": "agent", "agent": name}
            context = self._trajectory_context(agent_name=name)
            if context.get("identity"):
                speaker["identity"] = context["identity"]
        elif role == "user" and "<tool_response>" not in str(msg.get("content") or ""):
            speaker = {"kind": "user", "agent": "user"}
        elif role == "tool" or "<tool_response>" in str(msg.get("content") or ""):
            speaker = {"kind": "tool", "agent": "tool"}
        else:
            speaker = {"kind": role or "message", "agent": name or role or "unknown"}
        msg.setdefault("_speaker", speaker)
        return msg

    @staticmethod
    def _resolve_runtime_agent(agent_name):
        run_context = get_current_run_context()
        harness = run_context.harness if run_context is not None else get_current_harness()
        agents = getattr(harness, "agents", {}) if harness is not None else {}
        instance = agents.get(str(agent_name or ""))
        if instance is None and len(agents) == 1:
            instance = next(iter(agents.values()))
        return harness, instance

    def trace(self, event_type, data=None, **metadata):
        """Append an exact, secret-redacted event to the root trajectory."""
        context = self._trajectory_context(agent_name=metadata.get("agent"))
        context.update({key: value for key, value in metadata.items() if value is not None})
        run_context = get_current_run_context()
        safe_data = copy.deepcopy(data if data is not None else {})
        secret_view = getattr(run_context, "secret_view", None)
        if secret_view is not None:
            safe_data = secret_view.redact_value(safe_data)
        return self.trajectory.append(
            event_type,
            safe_data,
            session_id=self.session_id,
            **context,
        )

    def begin_model_call(
        self,
        *,
        messages,
        tools,
        agent,
        model=None,
        provider=None,
        parameters=None,
        purpose="agent",
    ):
        model_call_id = f"call_{uuid.uuid4().hex}"
        exact_messages = copy.deepcopy(messages or [])
        harness, agent_instance = self._resolve_runtime_agent(agent)
        capability_snapshot_id = None
        if agent_instance is not None and callable(getattr(agent_instance, "capability_snapshot", None)):
            snapshot = agent_instance.capability_snapshot()
            capability_snapshot_id = snapshot.get("snapshot_id")
            context = self._trajectory_context(agent_name=agent)
            self.trajectory.register_capability_snapshot(
                snapshot,
                session_id=self.session_id,
                run_id=context.get("run_id"),
                harness=getattr(harness, "name", None),
                agent=str(agent or getattr(agent_instance, "name", "Agent")),
                identity=context.get("identity"),
            )
        self.trace(
            "model.request",
            {
                "messages": exact_messages,
                "tools": copy.deepcopy(tools or []),
                "parameters": copy.deepcopy(parameters or {}),
                "model": model,
                "provider": provider,
                "purpose": str(purpose or "agent"),
                "messages_sha256": messages_sha256(exact_messages),
                "tools_sha256": payload_sha256(tools or []),
                "context_generation": self._context_generation,
                "capability_snapshot_id": capability_snapshot_id,
            },
            agent=agent,
            model_call_id=model_call_id,
        )
        return model_call_id

    def finish_model_call(
        self,
        model_call_id,
        *,
        agent,
        content="",
        reasoning="",
        tool_calls=None,
        finish_reason=None,
        usage=None,
        metadata=None,
    ):
        return self.trace(
            "model.response",
            {
                "content": content,
                "reasoning": reasoning,
                "tool_calls": copy.deepcopy(tool_calls or []),
                "finish_reason": finish_reason,
                "usage": copy.deepcopy(usage or {}),
                "provider_metadata": copy.deepcopy(metadata or {}),
            },
            agent=agent,
            model_call_id=model_call_id,
        )

    def fail_model_call(self, model_call_id, *, agent, error, error_type=None):
        return self.trace(
            "model.error",
            {"error": str(error), "error_type": str(error_type or type(error).__name__)},
            agent=agent,
            model_call_id=model_call_id,
        )

    def record(self, msg):
        """记录一条消息"""
        with self._lock:
            self._annotate_message(msg)
            msg.setdefault("_message_id", f"msg_{uuid.uuid4().hex}")
            self.messages.append(msg)
            self._context_generation += 1
            self.trace(
                "conversation.working.append",
                {"message": copy.deepcopy(msg), "context_generation": self._context_generation},
                agent=msg.get("name"),
            )

    def record_full(self, msg):
        """记录一条含 system prompt 的消息到 full log"""
        with self._lock:
            self._annotate_message(msg)
            msg.setdefault("_message_id", f"msg_{uuid.uuid4().hex}")
            self.full_messages.append(msg)
            self.trace(
                "conversation.audit.append",
                {"message": copy.deepcopy(msg), "context_generation": self._context_generation},
                agent=msg.get("name"),
            )

    def get_history(self, agent_name=None):
        """查看对话记录，可选按 agent 过滤"""
        with self._lock:
            if agent_name is None:
                return list(self.messages)
            return [m for m in self.messages if m.get("name") == agent_name]

    def get_full_history(self, agent_name=None):
        """Return the UI/audit transcript, including context-elided turns."""
        with self._lock:
            source = self.full_messages or self.messages
            if agent_name is None:
                return copy.deepcopy(source)
            return [copy.deepcopy(message) for message in source if message.get("name") == agent_name]

    def apply_context_result(self, result):
        """Commit an auditable context-policy result atomically."""
        if not isinstance(result, dict) or not isinstance(result.get("messages"), list):
            raise ValueError("Invalid context policy result")
        with self._lock:
            before_messages = copy.deepcopy(self.messages)
            before_full_messages = copy.deepcopy(self.full_messages)
            if isinstance(result.get("full_messages"), list):
                self.full_messages = copy.deepcopy(result["full_messages"])
            self.messages = copy.deepcopy(result["messages"])
            self._context_generation += 1
            governance = self.state.setdefault("context_governance", {})
            governance["ledger"] = copy.deepcopy(result.get("ledger", []))
            governance["stats"] = copy.deepcopy(result.get("stats", {}))
            governance["last_updated_at"] = time.time()
            self.trace(
                "conversation.surface.replace",
                {
                    "before_messages_sha256": messages_sha256(before_messages),
                    "before_full_messages_sha256": messages_sha256(before_full_messages),
                    "after_messages": copy.deepcopy(self.messages),
                    "after_full_messages": copy.deepcopy(self.full_messages),
                    "after_full_messages_sha256": messages_sha256(self.full_messages),
                    "after_messages_sha256": messages_sha256(self.messages),
                    "ledger": copy.deepcopy(result.get("ledger", [])),
                    "stats": copy.deepcopy(result.get("stats", {})),
                    "context_generation": self._context_generation,
                },
            )

    def health(self) -> SessionHealth:
        """Return an explicit replay/training readiness assessment."""

        path = self.trajectory.native_path
        if path is not None and path.is_file():
            return TrajectoryReader(path).health(
                durability_error=self.trajectory.last_error,
                mirror_error=self.trajectory.mirror_error,
            )
        status = "invalid" if self.trajectory.last_error else "empty"
        blockers = (
            (f"trajectory persistence failed: {self.trajectory.last_error}",)
            if self.trajectory.last_error else ()
        )
        return SessionHealth(
            status=status,
            replayable=False,
            training_ready=False,
            event_count=self.trajectory.event_count,
            model_calls=0,
            tool_calls=0,
            blockers=blockers,
            durability_error=self.trajectory.last_error,
            mirror_error=self.trajectory.mirror_error,
        )

    def save(self, path=None):
        """持久化到文件"""
        save_dir = Path(path) if path else self.save_dir
        if not save_dir:
            return
        with self._lock:
            messages = list(self.messages)
            full_messages = list(self.full_messages)
            state = dict(self.state)
        os.makedirs(save_dir, exist_ok=True)
        with open(save_dir / "messages.json", "w", encoding="utf-8") as f:
            json.dump(messages, f, ensure_ascii=False, indent=2)
        with open(save_dir / "full_messages.json", "w", encoding="utf-8") as f:
            json.dump(full_messages, f, ensure_ascii=False, indent=2)
        with open(save_dir / "state.json", "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        health = self.health()
        metadata = {
            "schema": "ego.session.v2",
            "session_id": self.session_id,
            "trace_id": self.trajectory.trace_id,
            # Workspace attribution is a first-class part of Session identity.
            # Older builds only emitted it in ``trace.started``, forcing every
            # project/session view to parse a potentially large trajectory.
            "workspace": str(Path(self.workspace).expanduser().resolve()) if self.workspace else "",
            "project_name": Path(self.workspace).expanduser().resolve().name if self.workspace else "",
            "context_generation": self._context_generation,
            "trajectory": str(self.trajectory.native_path) if self.trajectory.native_path else None,
            "trajectory_error": self.trajectory.last_error,
            "mirror": str(self.trajectory.location.mirror_path) if self.trajectory.location.mirror_path else None,
            "mirror_error": self.trajectory.mirror_error,
            "trajectory_events": self.trajectory.event_count,
            "trajectory_agents": list(self.trajectory.agents),
            "capability_snapshots": list(self.trajectory.capability_snapshot_ids),
            "health": health.as_dict(),
            "agent_config": dict(self.agent_config),
        }
        with open(save_dir / "session.json", "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

    def load(self, path):
        """Restore a Session, preferring a validated event projection."""
        path = Path(path)
        self.save_dir = path
        metadata_file = path / "session.json"
        metadata = {}
        local_trajectory_path = path / "trajectory.jsonl"
        trajectory_path = local_trajectory_path
        if metadata_file.is_file():
            try:
                metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
                self.session_id = str(metadata.get("session_id") or self.session_id)
                self._context_generation = int(metadata.get("context_generation", 0))
                raw_agent_config = metadata.get("agent_config")
                self.agent_config = dict(raw_agent_config) if isinstance(raw_agent_config, dict) else {}
                recorded_path = str(metadata.get("trajectory") or "").strip()
                recorded_trajectory = Path(recorded_path) if recorded_path else None
                # A session directory may have been copied or moved. Prefer the
                # recorded location only while it still exists; the colocated
                # immutable log is otherwise the portable source of truth.
                if recorded_trajectory is not None and recorded_trajectory.is_file():
                    trajectory_path = recorded_trajectory
            except (OSError, ValueError, TypeError):
                pass
        if (path / "messages.json").exists():
            with open(path / "messages.json", encoding="utf-8") as stream:
                self.messages = json.load(stream)
        if (path / "full_messages.json").exists():
            with open(path / "full_messages.json", encoding="utf-8") as stream:
                self.full_messages = json.load(stream)
        elif self.messages:
            # Legacy sessions predate the append-only audit transcript.
            self.full_messages = copy.deepcopy(self.messages)
        if (path / "state.json").exists():
            with open(path / "state.json", encoding="utf-8") as stream:
                self.state = json.load(stream)
        if trajectory_path.is_file():
            reader = TrajectoryReader(trajectory_path)
            validation = reader.validate()
            if validation.get("valid"):
                events = reader.read_all(strict=False)
                if not metadata.get("session_id"):
                    inferred_session_id = next(
                        (
                            str(event.get("session_id"))
                            for event in events
                            if event.get("session_id")
                            and event.get("type") in {
                                "conversation.working.append",
                                "conversation.audit.append",
                                "conversation.surface.replace",
                            }
                        ),
                        None,
                    )
                    if inferred_session_id:
                        self.session_id = inferred_session_id
                self.trajectory = TrajectoryRecorder(
                    trajectory_path,
                    trace_id=validation.get("trace_id") or metadata.get("trace_id"),
                    project_name=(Path(self.workspace).resolve().name if self.workspace else None),
                )
                projection = reader.reconstruct_session(self.session_id)
                if projection.get("applied_events", 0):
                    self.messages = projection["messages"]
                    self.full_messages = projection["full_messages"]
                    self._context_generation = max(
                        self._context_generation,
                        int(projection.get("context_generation", 0)),
                    )

    def get_result(self, mode="last"):
        """
        获取 session 结果，用于返回给父 harness。
        mode:
          - "all": 返回所有 messages
          - "last": 只返回最后一条非 tool_response 的 assistant message
        """
        if mode == "all":
            return self.messages
        else:
            # 从后往前找第一条 assistant 消息（不含 <tool_response> 的）
            for msg in reversed(self.messages):
                if msg.get("role") == "assistant" and "<tool_call>" not in msg.get("content", ""):
                    return [msg]
                if msg.get("role") == "assistant":
                    return [msg]
            return []


class Harness:
    """控制中心，操作 agents"""

    def __init__(self, harness_dir, agents: dict = None, workspace: Path = None, prompts: dict = None, return_mode: str = None):
        """
        agents: dict[slot_name -> Agent]，按 config 中定义的 slots 分配
        prompts: dict[prompt_name -> str]，传入的 prompt 覆盖 config 中的 default
        return_mode: "all" 返回所有消息 / "last" 只返回最后一条非 tool 消息，覆盖 config 默认值
        """
        self.dir = Path(harness_dir)
        with open(self.dir / "config.json", encoding="utf-8") as config_stream:
            self.config = json.load(config_stream)
        from pipeline_schema import validate_component_manifest
        component_errors = validate_component_manifest(self.config.get("component"))
        if component_errors:
            raise ValueError("Invalid component manifest:\n- " + "\n- ".join(component_errors))
        self.name = self.config["name"]
        self.agents = {}  # {slot_name: Agent}
        self.workspace = workspace
        self.parent = None  # 父 harness
        self.children = []  # 子 harness 列表

        # return_mode: 传入参数优先，否则用 config 默认值，最后兜底 "last"
        self.return_mode = return_mode or self.config.get("return_mode", "last")

        # 解析 slots 定义
        self.slots = self.config.get("slots", {})

        # 加载 prompts：先从 config 取 default，再用传入参数覆盖
        self.prompts = {}
        prompts_config = self.config.get("prompts", {})
        for name, prompt_def in prompts_config.items():
            if isinstance(prompt_def, dict):
                self.prompts[name] = prompt_def.get("default", "")
            else:
                self.prompts[name] = prompt_def
        if prompts:
            self.prompts.update(prompts)

        # 加载 protocol：优先使用 pipeline 声明式编排，否则回退到 protocol.py
        if "pipeline" in self.config:
            from pipeline_engine import run_pipeline
            self.run_func = run_pipeline
        else:
            protocol_file = self.dir / "protocol.py"
            assert protocol_file.exists(), f"Harness {self.dir} 缺少 pipeline 定义或 protocol.py"
            self.run_func = load_script(str(protocol_file), "run")

        # 加载 hooks
        self.hooks = {}
        hooks_dir = self.dir / "hooks"
        if hooks_dir.is_dir():
            for f in hooks_dir.glob("*.py"):
                hook_func = load_script(str(f), f.stem)
                if hook_func:
                    self.hooks[f.stem] = hook_func

        # 创建 session（harness 私有属性）
        # Session storage must not depend on the caller's current working
        # directory. The HTTP backend runs from `harness_editor/` while the CLI
        # normally runs from the repository root; a relative path split their
        # histories into two invisible catalogs.
        session_root = Path(__file__).resolve().parent / "sessions"
        session_dir = session_root / f"{self.name}_{time.strftime('%Y%m%d_%H%M%S')}"
        self.session = Session(workspace=workspace, save_dir=session_dir)

        # 如果初始化时传了 agents，直接设置
        if agents:
            self.set_agents(agents)

    def set_agents(self, agents: dict):
        """设置 agents 字典 {slot_name: Agent}，校验 slots、同步名字、初始化环境"""
        self.agents = agents

        # 同步 slot name 到 agent.name
        for slot_name, agent in self.agents.items():
            agent.name = slot_name

        # 校验 required slots
        for slot_name, slot_def in self.slots.items():
            if slot_def.get("required", False):
                assert slot_name in self.agents, \
                    f"Harness {self.name} 缺少必填 slot: {slot_name}"

        # 校验 agent 不超出定义的 slots
        if self.slots:
            for slot_name in self.agents:
                assert slot_name in self.slots, \
                    f"Harness {self.name} 不存在 slot: {slot_name}，可用: {list(self.slots.keys())}"

        # 初始化 agent environment
        if self.workspace:
            for agent in self.agents.values():
                agent.workspace = self.workspace
                agent.init_environment()

    def assign_agent(self, slot_name, agent):
        """动态分配单个 agent 到指定 slot"""
        if self.slots:
            assert slot_name in self.slots, \
                f"Harness {self.name} 不存在 slot: {slot_name}，可用: {list(self.slots.keys())}"
        agent.name = slot_name
        self.agents[slot_name] = agent
        if self.workspace:
            agent.workspace = self.workspace
            agent.init_environment()

    def get_slots_info(self):
        """返回 slots 状态（哪些已填、哪些未填）"""
        info = {}
        for slot_name, slot_def in self.slots.items():
            info[slot_name] = {
                "description": slot_def.get("description", ""),
                "required": slot_def.get("required", False),
                "filled": slot_name in self.agents
            }
        return info

    def run(self):
        """
        执行 protocol，支持嵌套（栈式保存/恢复 parent harness）。
        返回值: 根据 return_mode 返回 session 结果（messages 列表）
        """
        # 启动前校验 required slots
        for slot_name, slot_def in self.slots.items():
            if slot_def.get("required", False):
                assert slot_name in self.agents, \
                    f"Harness {self.name} 启动失败，缺少必填 slot: {slot_name}"

        # ContextVar token restoration keeps nested and concurrent runs isolated.
        parent = get_current_harness()
        if parent:
            from subagent_lifecycle import link_subagent
            if self.parent is None:
                link_subagent(parent, self, share_session=self.session is parent.session, purpose="harness_run")
            elif self not in parent.children:
                parent.children.append(self)
        failure = None
        with runtime_scope(harness=self):
            self.fire_hook("pre_session")
            try:
                self.run_func(self)
            except EndSession as e:
                # EndSession 只终止当前 harness，不向上传播
                if str(e):
                    print(f"\n[EndSession] {e}")
            except Exception as error:
                failure = error
                if parent:
                    from subagent_lifecycle import finish_subagent
                    finish_subagent(self, status="failed", error=error)
                raise
            finally:
                self.fire_hook("post_session")
                self.session.save()

        # 返回 session 结果
        result = self.session.get_result(self.return_mode)
        if parent:
            from subagent_lifecycle import finish_subagent
            finish_subagent(self, status="failed" if failure else "completed", result=result, error=failure)
        return result

    def fire_hook(self, hook_name, **kwargs):
        """触发 harness 级 hook"""
        if hook_name in self.hooks:
            return self.hooks[hook_name](harness=self, **kwargs)
        return None

    def get_prompt(self, name):
        """获取模板 prompt"""
        return self.prompts.get(name, "")


def parse_user_tool_call(user_input: str):
    """
    解析用户直接调用工具的语法: \\tool_name(arg1=value1, arg2=value2)
    返回 (tool_name, arguments_dict) 或 None（如果不是工具调用格式）
    """
    import re
    # 匹配 \tool_name(...) 格式
    match = re.match(r'^\\(\w+)\((.*)\)$', user_input.strip(), re.DOTALL)
    if not match:
        return None
    tool_name = match.group(1)
    args_str = match.group(2).strip()

    # 解析参数
    if not args_str:
        return tool_name, {}

    # 尝试用 JSON 解析 (如果用户传的是 JSON 格式)
    try:
        args = json.loads("{" + args_str + "}")
        return tool_name, args
    except (json.JSONDecodeError, ValueError):
        pass

    # 用简单的 key=value 解析
    arguments = {}
    # 匹配 key="value" 或 key=value 模式
    pattern = r'(\w+)\s*=\s*(?:"([^"]*?)"|\'([^\']*?)\'|([^,\s]+))'
    for m in re.finditer(pattern, args_str):
        key = m.group(1)
        value = m.group(2) if m.group(2) is not None else (m.group(3) if m.group(3) is not None else m.group(4))
        arguments[key] = value

    # 如果没有 key=value 格式，尝试作为单个位置参数
    if not arguments and args_str:
        # 去掉首尾引号
        if (args_str.startswith('"') and args_str.endswith('"')) or \
           (args_str.startswith("'") and args_str.endswith("'")):
            args_str = args_str[1:-1]
        arguments["_positional"] = args_str

    return tool_name, arguments


def execute_user_tool_call(harness, agent, tool_name: str, arguments: dict):
    """
    用户直接调用工具，执行并记录到 session。
    返回结果字符串。
    """
    # 查找 tool
    found = agent._find_tool_or_knowledge(tool_name)
    if not found:
        result = f"Tool not found: {tool_name}"
    elif found[0] == "knowledge":
        result = found[1].render()
    else:
        tool = found[1]
        try:
            import inspect
            sig = inspect.signature(tool.func)
            # 如果有 _positional 参数且函数只有一个必填参数，把它映射过去
            if "_positional" in arguments and len(arguments) == 1:
                params = [p for p in sig.parameters.values() if p.name != "_context" and p.default is inspect.Parameter.empty]
                if params:
                    arguments = {params[0].name: arguments["_positional"]}
            if "_context" in sig.parameters:
                arguments["_context"] = agent._runtime_context
            # 移除 _positional 如果还在
            arguments.pop("_positional", None)
            result = tool.func(**arguments)
        except Exception as e:
            result = f"Tool {tool_name} error: {str(e)}"

    # 记录到 session：user 发起的 tool 调用（使用 <tool_response> 格式）
    result_str = result if isinstance(result, str) else str(result)
    user_tool_msg = {
        "role": "user",
        "content": f'<tool_response>{{"tool": "{tool_name}", "content": {json.dumps(result_str, ensure_ascii=False)}, "_user_invoked": true}}</tool_response>',
    }
    harness.session.record(user_tool_msg)
    harness.session.record_full(user_tool_msg)

    return result
