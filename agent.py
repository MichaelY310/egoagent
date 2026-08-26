from llm.llm import Identity
from typing import Union, List
from pathlib import Path
from config import CONFIG
from environment import (
    Environment,
    load_environment_from_dir,
    load_knowledge_from_dir,
    load_tool_from_dir,
)
import base64
import copy
import json
import mimetypes
import os
import sys
import time
import uuid
from message_protocol import compose_model_messages as _compose_model_messages

root_environment_path = CONFIG["root_environment_path"]

_WORKSPACE_PATH_ARGUMENTS = {
    "read_file": ("file_path",),
    "write_file": ("file_path",),
    "patch_file": ("file_path",),
    "multi_edit": ("file_path",),
    "search_files": ("path",),
    "glob_search": ("path",),
    "ls": ("path",),
    # A nested harness must not replace its inherited Task Bench workspace
    # with the repository root (or any other path outside the task sandbox).
    "create_harness": ("workspace",),
    "run_command": ("cwd",),
    "exec_command": ("workdir",),
}

_BUILTIN_ACTIVATED_CAPABILITIES = {
    "search_capabilities",
    "activate_capability",
    "read_file",
    "search_files",
    "glob_search",
    "ls",
    "write_file",
    "patch_file",
    "multi_edit",
    "run_command",
    "check_command_status",
    "stop_command",
    "apply_patch",
    "exec_command",
    "write_stdin",
    "update_plan",
}


def preserve_patch_line_endings(before: str, after: str) -> str:
    """Keep an existing file's newline convention for localized edit tools."""
    if not before or not after:
        return after
    crlf = before.count("\r\n")
    bare_lf = before.count("\n") - crlf
    bare_cr = before.count("\r") - crlf
    if crlf == bare_lf == bare_cr == 0:
        return after
    newline = "\r\n" if crlf >= max(bare_lf, bare_cr) and crlf > 0 else ("\r" if bare_cr > bare_lf else "\n")
    logical = after.replace("\r\n", "\n").replace("\r", "\n")
    return logical if newline == "\n" else logical.replace("\n", newline)


def _console_write(value: str, end: str = "") -> None:
    """Best-effort progress output that can never abort an Agent run.

    Windows pipes frequently advertise cp1252 even when the provider returns
    Chinese. The complete Unicode response is still stored in the session;
    only an incapable console receives escaped characters.
    """
    text = str(value) + end
    try:
        sys.stdout.write(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        sys.stdout.write(text.encode(encoding, errors="backslashreplace").decode(encoding))
    try:
        sys.stdout.flush()
    except (AttributeError, OSError):
        pass


def build_tool_image_message(result, tool_name, workspace, max_bytes=8_000_000):
    """Build an OpenAI-compatible vision message for a safe local tool image."""
    if not isinstance(result, dict) or not result.get("path") or not workspace:
        return None
    root = Path(workspace).resolve()
    candidate = Path(str(result["path"]))
    path = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    if path != root and root not in path.parents:
        return None
    mime, _ = mimetypes.guess_type(path.name)
    if not path.is_file() or not mime or not mime.startswith("image/"):
        return None
    if path.stat().st_size > max(1, int(max_bytes)):
        return None
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return {
        "role": "user",
        "name": "tool_image",
        "content": [
            {"type": "text", "text": f"Image observation produced by tool {tool_name}. Use it as evidence together with the textual tool response."},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
        ],
    }


class Agent:
    def __init__(self, identity: Union[Path, str, Identity], name: str = None, workspace: Path = None, environments: List[Union[Path, str, Environment]] = None, model_provider=None):
        self.set_identity(identity)
        self.name = name or self.identity.ID.get("name", "agent")
        self._model_provider_override = model_provider
        self.llm = model_provider or self.identity.get_llm()
        if model_provider is not None:
            self._validate_model_provider(self.llm)
        self.environments = set()
        self.tools = {}
        self.knowledges = {}
        self.workspace = workspace
        self._extra_environment_inputs = list(environments or [])
        self._activated_capabilities = set(_BUILTIN_ACTIVATED_CAPABILITIES)
        self._activated_capability_refs = {}
        self._capability_snapshot_cache = None
        # Instruction-only skills (for example a workspace ``SKILL.md``)
        # become visible only after capability activation.  Keeping them out
        # of the default prompt is the main token-saving reason for the local
        # catalog, while this separate map avoids pretending every Skill is an
        # executable function.
        self._activated_skill_instructions = {}
        # Runtime context injected by the IDE (project rules, AGENTS.md and
        # cross-session memory). It is deliberately separate from Identity so
        # reusable identities are not mutated by one workspace.
        self.context_instructions = ""
        self.scoped_context_instructions = ""

        # 共享运行时状态，所有 tool 通过 _context 参数访问
        self._running_commands = {}
        self._plan_state = {"items": [], "explanation": "", "updated_at": None}
        self._runtime_context = {
            "running_commands": self._running_commands,
            "plan_state": self._plan_state,
            "agent_name": self.name,
            "workspace": str(Path(self.workspace).resolve()) if self.workspace else None,
            "identity_path": str(self.identity.identity_path),
            "project_root": str(Path(__file__).resolve().parent),
            "agent": self,
        }

        self.init_environment()
        self.load_environments(environments)
        self._load_pinned_capabilities()

        self.hooks = self._load_hooks()
        from tool_pipeline import AgentToolExecutor
        self.tool_executor = AgentToolExecutor(self)

    def reload_identity(self):
        """Reload a persistent Identity and its EGO without replacing the Agent.

        Tabletop Keeper transactions use this after changing a reusable
        character sheet or its generated item tools.  It is also useful for
        safe self-evolution runs: the next model call sees the committed ID,
        tools and policies while the current harness slot remains stable.
        """
        identity_path = self.identity.identity_path
        self.set_identity(identity_path)
        self.llm = self._model_provider_override or self.identity.get_llm()
        if self._model_provider_override is not None:
            self._validate_model_provider(self.llm)
        self.environments = set()
        self.tools = {}
        self.knowledges = {}
        self._activated_capabilities = set(_BUILTIN_ACTIVATED_CAPABILITIES)
        self._activated_capability_refs = {}
        self._capability_snapshot_cache = None
        self._activated_skill_instructions = {}
        self.scoped_context_instructions = ""
        self._runtime_context["identity_path"] = str(self.identity.identity_path)
        self.init_environment()
        self.load_environments(self._extra_environment_inputs)
        self._load_pinned_capabilities()
        self.hooks = self._load_hooks()
        return self

    @staticmethod
    def _validate_model_provider(provider):
        from model_gateway import DEFAULT_MODEL_GATEWAY
        DEFAULT_MODEL_GATEWAY.validate(provider)

    def set_model_provider(self, provider):
        """Replace only the model capability; DAG/Identity behavior is unchanged."""
        self._validate_model_provider(provider)
        self._model_provider_override = provider
        self.llm = provider
        return self

    def _load_pinned_capabilities(self):
        """Activate workspace choices without copying their schemas into ID."""
        if not self.workspace:
            return
        pins_path = Path(self.workspace) / ".egoagent" / "pinned_capabilities.json"
        if not pins_path.is_file():
            return
        try:
            payload = json.loads(pins_path.read_text(encoding="utf-8"))
            capability_ids = payload.get("capabilities", []) if isinstance(payload, dict) else []
            if not isinstance(capability_ids, list):
                return
            from capability_registry import CapabilityRegistry

            registry = CapabilityRegistry(Path(__file__).resolve().parent, workspace=self.workspace)
            registry.reindex()
            for capability_id in capability_ids[:100]:
                result = self.activate_capability(str(capability_id), registry=registry)
                if result.get("ok") and result.get("kind") in {"skill", "tool", "knowledge"}:
                    registry.record_event(str(capability_id), "activate")
        except (OSError, ValueError, json.JSONDecodeError):
            # A malformed optional preference must not prevent the Agent from
            # opening the workspace. The Library UI can overwrite it safely.
            return

    def _load_hooks(self):
        """从 identity SEGO 中加载 hooks"""
        hooks = {
            "pre_llm_hook": None,
            "post_llm_hook": None,
            "pre_tool_hook": None,
            "post_tool_hook": None,
        }
        if self.identity.SEGO:
            _, sego_hooks = self.identity.SEGO
            for hook_name in hooks:
                if hook_name in sego_hooks and sego_hooks[hook_name]:
                    hooks[hook_name] = sego_hooks[hook_name]
        return hooks

    def set_identity(self, identity: Union[Path, str, Identity]):
        if isinstance(identity, Identity):
            self.identity = identity
        else:
            self.identity = Identity(identity)

    def load_environments(self, environments: List[Union[Path, str, Environment]] = None):
        """加载额外指定的环境列表"""
        if environments:
            for env in environments:
                self.load_environment(env)

    def load_environment(self, environment: Union[Path, str, Environment], no_tool_override=False):
        """加载单个环境的 tools 和 knowledges 到 agent
        no_tool_override: 如果为 True，当短名字已存在时不覆盖
        """
        if not environment:
            return
        if isinstance(environment, (str, Path)):
            environment = load_environment_from_dir(environment)
        if not environment:
            return
        self.environments.add(environment)

        if no_tool_override:
            # 不覆盖：按短名字判断，已存在则跳过
            existing_short_tools = {self._short_name(k) for k in self.tools}
            for k, v in environment.tools.items():
                if self._short_name(k) not in existing_short_tools:
                    self.tools[k] = v
            existing_short_knowledges = {self._short_name(k) for k in self.knowledges}
            for k, v in environment.knowledges.items():
                if self._short_name(k) not in existing_short_knowledges:
                    self.knowledges[k] = v
        else:
            # 默认覆盖：按短名字判断，先删除同短名的旧条目再添加新的
            for k, v in environment.tools.items():
                short = self._short_name(k)
                # 删除已有的同短名 tool
                to_remove = [existing_k for existing_k in self.tools if self._short_name(existing_k) == short]
                for old_k in to_remove:
                    del self.tools[old_k]
                self.tools[k] = v
            for k, v in environment.knowledges.items():
                short = self._short_name(k)
                to_remove = [existing_k for existing_k in self.knowledges if self._short_name(existing_k) == short]
                for old_k in to_remove:
                    del self.knowledges[old_k]
                self.knowledges[k] = v

    @staticmethod
    def _short_name(full_name: str) -> str:
        """从带前缀的全名中提取短名字。如 'IDENTITY<...>:TOOL:read_file' -> 'read_file'"""
        if ":" in full_name:
            return full_name.rsplit(":", 1)[-1]
        return full_name

    def init_environment(self):
        """初始化环境"""
        self._runtime_context["workspace"] = str(Path(self.workspace).resolve()) if self.workspace else None
        # A composite Identity can reuse EGO capability packs from other
        # identities while keeping its own ID/personality and SEGO policy.
        # Parents load first; the local EGO remains authoritative on conflicts.
        for inherited_ego in getattr(self.identity, "EGO_INHERITS", []):
            self.load_environment(inherited_ego, no_tool_override=True)
        self.load_environment(self.identity.EGO)
        self.load_environment(root_environment_path)
        # workspace: 优先加载 .environment 子目录
        if self.workspace:
            env_dir = Path(self.workspace) / ".environment"
            if env_dir.is_dir():
                self.load_environment(env_dir)
            else:
                self.load_environment(self.workspace)

    def build_system_prompt(self, has_tools=True):
        """从 ID（性格）和 SEGO（任务/约束）组装 system prompt"""
        parts = []

        # 从 ID 读取身份和性格
        id_config = self.identity.ID
        if id_config.get("role"):
            parts.append(f"You are {self.name}, a {id_config['role']}.")
        else:
            parts.append(f"You are {self.name}.")
        identity_name = str(id_config.get("name", "")).strip()
        if identity_name and identity_name != self.name:
            parts.append(f"Your bound Identity profile is `{identity_name}`.")
        if id_config.get("description"):
            parts.append(id_config["description"])
        personality = id_config.get("personality", {})
        if personality.get("language"):
            parts.append(f"Respond in: {personality['language']}.")
        game_profiles = id_config.get("game_profiles")
        if isinstance(game_profiles, dict) and game_profiles:
            # Game profiles are authoritative Identity state, not prose copied
            # into a scenario session.  Supplying the exact JSON prevents a
            # model from hallucinating restored HP, ammunition or equipment.
            parts.append("\nAuthoritative persistent character profile (read-only; only the harness/Keeper transaction may change it):")
            parts.append(json.dumps(game_profiles, ensure_ascii=False, sort_keys=True))

        # 从 SEGO 读取任务和约束
        if self.identity.SEGO:
            sego_config, _ = self.identity.SEGO
            if sego_config.get("task_prompt"):
                parts.append(f"\n{sego_config['task_prompt']}")

        if self.context_instructions:
            parts.append("\nWorkspace context:")
            parts.append(self.context_instructions)

        if self.scoped_context_instructions:
            parts.append("\nPath-scoped workspace context (applies to the files currently being inspected):")
            parts.append(self.scoped_context_instructions)

        if self._activated_skill_instructions:
            parts.append("\nActivated on-demand Skills:")
            for skill_name, instructions in self._activated_skill_instructions.items():
                parts.append(f"\n### {skill_name}\n{instructions}")

        # 通用行为约束
        if has_tools:
            parts.append("\nRules:")
            parts.append("- Only use the tools provided via function calling. Do not invent tool names.")
            parts.append("- For a casual greeting or conversation that needs no workspace evidence, answer directly without calling tools or discussing the workspace unless the user asks.")
            parts.append("- Before a tool call, keep user-visible progress to one brief sentence. After the tool result, continue the same turn without repeating greetings, plans, or prose already emitted.")
            parts.append("- After a tool succeeds, respond to the user. Do not re-call the same tool with same arguments.")
            parts.append("- If a tool errors, try a different approach or explain the issue to the user.")
            if any(self._short_name(name) == "search_capabilities" for name in self.tools):
                parts.append(
                    "- If the visible tools are insufficient, search_capabilities before inventing a new skill, "
                    "tool, knowledge item, identity, or harness. Activate a strong match and create a new capability "
                    "only when the search result explicitly recommends creation."
                )
        else:
            parts.append("\nRules:")
            parts.append("- Respond directly to the user with text. Do NOT output any tool calls or XML tags.")
            parts.append("- Be concise and helpful in your response.")

        return "\n".join(parts)

    def get_tools_desc(self):
        """获取所有 tools + knowledges 的 desc 列表（传给 LLM），已按权限过滤。
        传给 LLM 的 function.name 使用短名字（不含 IDENTITY<...>:TOOL: 前缀），节省 token。
        """
        descs = []
        tool_limit = max(2, int(CONFIG.get("max_prompt_tools", 20)))
        knowledge_limit = max(0, int(CONFIG.get("max_prompt_knowledges", 10)))
        preferred_tools = self.identity.ID.get("preferred_tools", [])
        if not isinstance(preferred_tools, list):
            preferred_tools = []
        preferred_order = {
            str(name).strip(): index
            for index, name in enumerate(preferred_tools)
            if str(name).strip()
        }

        def tool_priority(tool):
            short = self._short_name(tool.name)
            if short in {"search_capabilities", "activate_capability"}:
                return (0, short)
            # Explicit completion/control tools must remain visible even when
            # an Identity inherits more tools than the prompt budget permits.
            # Hiding ``finish`` can strand an otherwise-complete agent loop;
            # hiding ``submit_result`` can force a bounded worker to time out.
            if short.casefold() in {
                "finish", "finishtool", "submit_result", "terminate", "done", "end_session"
            }:
                return (1, short)
            # Composite Identities can expose many capability packs.  A small,
            # explicit preference list keeps task-critical tools visible under
            # the global prompt-schema budget without globally increasing
            # tokens or marking every inherited tool as active.
            if short in preferred_order:
                return (2, preferred_order[short], short)
            if short in self._activated_capabilities:
                return (3, short)
            return (4, short)

        visible_tools = sorted(self.tools.values(), key=tool_priority)[:tool_limit]
        for t in visible_tools:
            if self._check_tool_access(t.name, for_schema=True) is None:
                # 复制 desc，用短名字替换 function.name
                short = self._short_name(t.name)
                desc_copy = {
                    "type": "function",
                    "function": {
                        "name": short,
                        "description": t.desc["function"].get("description", ""),
                        "parameters": t.desc["function"].get("parameters", {}),
                    }
                }
                descs.append(desc_copy)
        visible_knowledge = sorted(
            self.knowledges.values(),
            key=lambda item: (
                0 if self._short_name(item.name) in self._activated_capabilities else 1,
                self._short_name(item.name),
            ),
        )[:knowledge_limit]
        for k in visible_knowledge:
            short = self._short_name(k.name)
            desc_copy = {
                "type": "function",
                "function": {
                    "name": short,
                    "description": k.desc["function"].get("description", ""),
                    "parameters": k.desc["function"].get("parameters", {}),
                }
            }
            descs.append(desc_copy)
        return descs

    def _remember_capability_ref(self, item):
        from capability_reference import CapabilityRef

        ref = CapabilityRef.from_mapping(item)
        if not hasattr(self, "_activated_capability_refs"):
            self._activated_capability_refs = {}
        self._activated_capability_refs[ref.id] = ref
        self._capability_snapshot_cache = None
        try:
            from harness import get_current_harness

            harness = get_current_harness()
            if harness is not None:
                harness.session.trace(
                    "capability.activated",
                    {"ref": ref.as_dict(), "agent": getattr(self, "name", "Agent")},
                    agent=getattr(self, "name", "Agent"),
                )
        except (AttributeError, OSError, ValueError):
            # Activation must remain usable for standalone Agents without a
            # durable Session; the following model-call snapshot is canonical.
            pass
        return ref.as_dict()

    def capability_snapshot(self):
        """Return the exact Identity/tool/knowledge revisions visible now."""

        if self._capability_snapshot_cache is not None:
            return copy.deepcopy(self._capability_snapshot_cache)

        from capability_reference import build_capability_snapshot, source_reference

        identity_path = Path(self.identity.identity_path).resolve()
        identity_ref = source_reference(
            kind="identity",
            name=identity_path.name,
            path=identity_path,
            version=str(self.identity.ID.get("version") or "local"),
            scope="identity",
        )
        refs = list(self._activated_capability_refs.values())
        seen_sources = {str(ref.source).casefold() for ref in refs if ref.source}
        for kind, values in (("tool", self.tools), ("knowledge", self.knowledges)):
            for runtime_name, value in sorted(values.items()):
                source = getattr(value, "source_path", None)
                if not source or str(source).casefold() in seen_sources:
                    continue
                metadata = getattr(value, "meta", {}) or {}
                refs.append(source_reference(
                    kind=kind,
                    name=self._short_name(runtime_name),
                    path=source,
                    version=str(metadata.get("version") or "local"),
                    scope="runtime",
                ))
                seen_sources.add(str(source).casefold())
        self._capability_snapshot_cache = build_capability_snapshot(
            agent=self.name,
            identity=identity_ref,
            capabilities=refs,
        )
        return copy.deepcopy(self._capability_snapshot_cache)

    def activate_capability(self, capability_id: str, registry=None):
        """Load one catalog result into this Agent for the next model step.

        Identity and Harness activation is intentionally advisory: changing the
        running topology or personality behind the user's back would make runs
        irreproducible. Executable skills/tools and knowledge can be added
        safely and are still checked by the normal permission policy.
        """
        if registry is None:
            from capability_registry import CapabilityRegistry

            registry = CapabilityRegistry(Path(__file__).resolve().parent, workspace=self.workspace)
        item = registry.get(str(capability_id))
        if not item:
            return {"ok": False, "error": f"Unknown capability: {capability_id}"}
        kind = item["kind"]
        path = Path(item["path"])
        if kind in {"skill", "tool"}:
            has_tool_metadata = (path / "meta.json").is_file() or (path / "description.json").is_file()
            has_tool_script = (path / "scripts").is_dir() and any((path / "scripts").glob("*.py"))
            loaded = (
                load_tool_from_dir(path, prefix=f"CATALOG<{capability_id}>:TOOL:")
                if kind == "tool" or (has_tool_metadata and has_tool_script)
                else None
            )
            if loaded is None:
                skill_path = path / "SKILL.md"
                if kind == "skill" and skill_path.is_file():
                    instructions = skill_path.read_text(encoding="utf-8", errors="replace")[:12_000].strip()
                    if not instructions:
                        return {"ok": False, "error": f"Skill instructions are empty: {skill_path}"}
                    short = str(item.get("name") or path.name)
                    self._activated_skill_instructions[short] = instructions
                    self._activated_capabilities.add(short)
                    ref = self._remember_capability_ref(item)
                    return {
                        "ok": True,
                        "id": capability_id,
                        "kind": kind,
                        "name": short,
                        "action": "apply_instructions",
                        "source": str(skill_path),
                        "instructions": instructions,
                        "ref": ref,
                        "message": (
                            f"Instruction Skill {short} is active in the next model step. "
                            "Follow its workflow using the tools already exposed by the parent Agent."
                        ),
                    }
                return {"ok": False, "error": f"Capability is not executable and has no SKILL.md instructions: {path}"}
            short = self._short_name(loaded.name)
            for existing_name in list(self.tools):
                if self._short_name(existing_name) == short:
                    del self.tools[existing_name]
            self.tools[loaded.name] = loaded
            self._activated_capabilities.add(short)
            ref = self._remember_capability_ref(item)
            return {
                "ok": True,
                "id": capability_id,
                "kind": kind,
                "name": short,
                "ref": ref,
                "message": f"{short} is available on the next model step.",
            }
        if kind == "knowledge":
            loaded = load_knowledge_from_dir(path, prefix=f"CATALOG<{capability_id}>:KNOWLEDGE:")
            if loaded is None:
                return {"ok": False, "error": f"Knowledge could not be loaded: {path}"}
            short = self._short_name(loaded.name)
            for existing_name in list(self.knowledges):
                if self._short_name(existing_name) == short:
                    del self.knowledges[existing_name]
            self.knowledges[loaded.name] = loaded
            self._activated_capabilities.add(short)
            ref = self._remember_capability_ref(item)
            return {
                "ok": True,
                "id": capability_id,
                "kind": kind,
                "name": short,
                "ref": ref,
                "message": f"{short} is available as a knowledge tool on the next model step.",
            }
        if kind == "identity":
            return {
                "ok": True,
                "id": capability_id,
                "kind": kind,
                "name": item["name"],
                "action": "select_identity",
                "path": item["path"],
                "reuse": item.get("reuse"),
                "ref": item.get("ref"),
                "message": "Select this Identity in the Workbench or bind it to a Harness slot.",
            }
        if kind == "harness":
            reuse = item.get("reuse") or {}
            modes = reuse.get("modes") or []
            preferred = "typed SubDAG" if "typed_subdag" in modes else "sub-agent Harness"
            return {
                "ok": True,
                "id": capability_id,
                "kind": kind,
                "name": item["name"],
                "action": "invoke_subdag",
                "path": item["path"],
                "reuse": reuse,
                "ref": item.get("ref"),
                "message": (
                    f"Reuse this as a {preferred}. For a live child Agent, call create_harness with the "
                    "provided invoke arguments. In a visual DAG, add a Subflow node using the provided "
                    "subflow contract. Do not recreate the Harness."
                ),
            }
        return {"ok": False, "error": f"Unsupported capability kind: {kind}"}

    def _record_capability_execution(self, found, result, runtime_ms):
        if not found:
            return
        source_path = getattr(found[1], "source_path", None)
        if not source_path:
            return
        failed = (
            isinstance(result, dict) and (result.get("ok") is False or bool(result.get("error")))
        ) or (
            isinstance(result, str)
            and (result.startswith("Tool ") and " error:" in result or result.startswith("Permission denied:"))
        )
        try:
            from capability_registry import CapabilityRegistry

            CapabilityRegistry(Path(__file__).resolve().parent, workspace=self.workspace).record_path_execution(
                source_path,
                success=not failed,
                runtime_ms=runtime_ms,
            )
        except (OSError, ValueError):
            # Metrics must never make a real tool call fail.
            return

    def process_text(self, text, context_messages=None, prompt_template=None):
        """处理文字：输入 text，输出处理后的 text
        用于审查或改写另一个 agent 的文本输出。
        prompt_template 中用 {text} 占位符代表待处理的文本。
        """
        if not prompt_template:
            prompt_template = "Review and process the following text. Return the processed text only.\n\n{text}"

        prompt = prompt_template.replace("{text}", text)

        messages = []
        if context_messages:
            recent = context_messages[-4:] if len(context_messages) > 4 else context_messages
            messages = list(recent)
        messages.append({"role": "user", "content": prompt})

        messages = _compose_model_messages(self.build_system_prompt(), messages)

        from harness import get_current_harness
        harness = get_current_harness()
        call_id = None
        if harness:
            config = getattr(self.llm, "config", {}) or {}
            call_id = harness.session.begin_model_call(
                messages=messages,
                tools=[],
                agent=self.name,
                model=getattr(self.llm, "model", None),
                provider=config.get("provider") or type(self.llm).__name__,
                parameters={"stream": False},
                purpose="text_process",
            )
        try:
            result = self.llm.chat(messages)
        except BaseException as error:
            if harness and call_id:
                harness.session.fail_model_call(call_id, agent=self.name, error=error)
            raise
        reply = result["choices"][0]["message"].get("content", "").strip()
        # Strip <think> blocks from reply
        if "<think>" in reply and "</think>" in reply:
            reply = reply.split("</think>", 1)[-1].strip()

        # 记录到 session
        if harness:
            metadata = dict(getattr(self.llm, "last_response_metadata", {}) or {})
            harness.session.finish_model_call(
                call_id,
                agent=self.name,
                content=reply,
                finish_reason=metadata.get("finish_reason"),
                usage=metadata.get("usage"),
                metadata=metadata,
            )
            harness.session.record_full({"role": "assistant", "name": self.name, "content": reply, "_op": "process_text"})

        return reply

    def process_tool_calls(self, tool_calls, context_messages=None, prompt_template=None):
        """处理工具调用：输入 tool_calls 列表，输出 (allowed_tool_calls, blocked_with_reasons)
        用于审查另一个 agent 的工具调用。
        prompt_template 中用 {tool_calls} 占位符代表待审查的工具调用。
        返回: (allowed: list, blocked: list of (tool_call, reason))
        """
        if not tool_calls:
            return tool_calls, []

        if not prompt_template:
            prompt_template = (
                "Review the following tool calls. For each, decide if it should be allowed.\n"
                "Respond with a JSON array. Each element: {{\"id\": \"...\", \"allow\": true/false, \"reason\": \"...\"}}\n\n"
                "{tool_calls}"
            )

        # 序列化 tool_calls 为可读格式
        tc_readable = []
        for tc in tool_calls:
            tc_readable.append({
                "id": tc["id"],
                "tool": tc["function"]["name"],
                "arguments": tc["function"]["arguments"]
            })
        tc_str = json.dumps(tc_readable, ensure_ascii=False, indent=2)
        prompt = prompt_template.replace("{tool_calls}", tc_str)

        messages = []
        if context_messages:
            # 过滤掉含 tool_calls 和 role=tool 的消息，避免干扰审查 LLM
            filtered = [m for m in context_messages if m.get("role") in ("user", "assistant") and "tool_calls" not in m]
            recent = filtered[-4:] if len(filtered) > 4 else filtered
            messages = list(recent)
        messages.append({"role": "user", "content": prompt})

        messages = _compose_model_messages(self.build_system_prompt(), messages)

        from harness import get_current_harness
        harness = get_current_harness()
        call_id = None
        if harness:
            config = getattr(self.llm, "config", {}) or {}
            call_id = harness.session.begin_model_call(
                messages=messages,
                tools=[],
                agent=self.name,
                model=getattr(self.llm, "model", None),
                provider=config.get("provider") or type(self.llm).__name__,
                parameters={"stream": False, "response_format": "json"},
                purpose="tool_review",
            )
        try:
            result = self.llm.chat(messages)
            raw_reply = result["choices"][0]["message"].get("content", "").strip()
        except BaseException as error:
            if harness and call_id:
                harness.session.fail_model_call(call_id, agent=self.name, error=error)
            raise

        if harness and call_id:
            metadata = dict(getattr(self.llm, "last_response_metadata", {}) or {})
            harness.session.finish_model_call(
                call_id,
                agent=self.name,
                content=raw_reply,
                finish_reason=metadata.get("finish_reason"),
                usage=metadata.get("usage"),
                metadata=metadata,
            )

        reply = raw_reply
        try:
            # 如果 reply 被 <think>...</think> 包裹，提取实际内容
            if "<think>" in reply and "</think>" in reply:
                reply = reply.split("</think>", 1)[-1].strip()

            # 去掉可能的 markdown 代码块
            if reply.startswith("```"):
                reply = reply.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            verdicts = json.loads(reply)
            print(f"  [{self.name}] 审查回复: {reply}")
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            if harness and call_id:
                harness.session.trace(
                    "model.output_parse_error",
                    {"error": str(e), "raw_content": raw_reply, "fallback": "allow"},
                    agent=self.name,
                    model_call_id=call_id,
                )
            print(f"  [{self.name}] 审查结果解析失败，默认放行: {e}")
            print(f"  [{self.name}] 原始回复: {reply if 'reply' in dir() else '(empty)'}")
            return tool_calls, []

        # 构建 id -> verdict 映射
        verdict_map = {}
        if isinstance(verdicts, list):
            for v in verdicts:
                verdict_map[v.get("id", "")] = v
        elif isinstance(verdicts, dict):
            # 兼容单个 tool_call 的情况
            verdict_map[verdicts.get("id", tool_calls[0]["id"] if tool_calls else "")] = verdicts

        allowed = []
        blocked = []
        for tc in tool_calls:
            v = verdict_map.get(tc["id"], {"allow": True})
            if v.get("allow", True):
                allowed.append(tc)
                print(f"  [{self.name}] ✓ {tc['function']['name']} - 通过")
            else:
                reason = v.get("reason", "rejected by reviewer")
                blocked.append((tc, reason))
                print(f"  [{self.name}] ✗ {tc['function']['name']} - 拦截: {reason}")

        # 记录到 session
        if harness:
            harness.session.record_full({
                "role": "assistant", "name": self.name, "_op": "process_tool_calls",
                "content": reply
            })

        return allowed, blocked

    @staticmethod
    def _sanitize_tool_protocol(messages):
        """Return an OpenAI-compatible message sequence with complete tool batches.

        Strict providers reject both orphan ``role=tool`` messages and assistant
        tool-call batches that are not followed immediately by one result for
        every advertised call. Shared sessions, context curation, and legacy
        transcripts can all leave either half behind. Preserve that information
        as ordinary context instead of sending an invalid provider transcript.
        """
        sanitized = []
        index = 0
        while index < len(messages):
            message = messages[index]
            if message.get("role") == "assistant" and message.get("tool_calls"):
                calls = message.get("tool_calls") or []
                expected = [str(call.get("id") or "") for call in calls if isinstance(call, dict)]
                following = []
                cursor = index + 1
                while cursor < len(messages) and messages[cursor].get("role") == "tool":
                    following.append(messages[cursor])
                    cursor += 1
                observed = [str(item.get("tool_call_id") or "") for item in following]
                complete = (
                    bool(expected)
                    and len(expected) == len(following)
                    and len(set(expected)) == len(expected)
                    and set(observed) == set(expected)
                )
                if complete:
                    sanitized.append(message)
                    sanitized.extend(following)
                else:
                    names = [
                        str((call.get("function") or {}).get("name") or "unknown")
                        for call in calls if isinstance(call, dict)
                    ]
                    content = str(message.get("content") or "").strip()
                    if not content:
                        content = (
                            "[Historical tool request had incomplete results and was not replayed: "
                            + ", ".join(names)
                            + "]"
                        )
                    sanitized.append({"role": "assistant", "content": content})
                    for result in following:
                        sanitized.append({
                            "role": "user",
                            "content": (
                                "[Unpaired historical tool result "
                                f"{result.get('tool_call_id') or 'unknown'}]\n"
                                f"{result.get('content', '')}"
                            ),
                        })
                index = cursor
                continue
            if message.get("role") == "tool":
                sanitized.append({
                    "role": "user",
                    "content": (
                        "[Unpaired historical tool result "
                        f"{message.get('tool_call_id') or 'unknown'}]\n"
                        f"{message.get('content', '')}"
                    ),
                })
            else:
                sanitized.append(message)
            index += 1
        return sanitized

    def _convert_messages_for_llm(self, messages):
        """将 session 格式的消息转换为标准 OpenAI function calling 格式。

        Session 格式:
          - assistant 带 <tool_call> XML 标签
          - tool response 是 role=user + <tool_response> XML

        OpenAI 格式:
          - assistant 带 tool_calls 数组, content 为纯文本或 null
          - tool response 是 role=tool + tool_call_id
        """
        import re
        converted = []
        # Track tool_call IDs for matching tool responses
        pending_tool_ids = []  # [{id, name, synthetic}, ...] for this Agent
        foreign_tool_ids = []  # [{id, name, agent}, ...] from shared SubDAGs

        def pop_pending(pending, tool_call_id, tool_name, *, allow_synthetic=False):
            if tool_call_id:
                for item in pending:
                    if item.get("id") == tool_call_id:
                        pending.remove(item)
                        return item
            if tool_name and (not tool_call_id or allow_synthetic):
                for item in pending:
                    if item.get("name") == tool_name and (
                        not tool_call_id or item.get("synthetic") or not item.get("id")
                    ):
                        pending.remove(item)
                        return item
            return None

        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", "")

            if role == "assistant":
                source_name = msg.get("name")
                if source_name and source_name != self.name:
                    # Another Agent's output is context for this Agent, not a
                    # previous answer authored by the same assistant. Keeping
                    # consecutive cross-Agent messages as `assistant` causes
                    # small OpenAI-compatible models to return empty content.
                    structured_calls = msg.get("tool_calls")
                    if isinstance(structured_calls, list):
                        for raw_call in structured_calls:
                            if not isinstance(raw_call, dict):
                                continue
                            function = raw_call.get("function") or {}
                            foreign_tool_ids.append({
                                "id": str(raw_call.get("id") or ""),
                                "name": str(function.get("name") or ""),
                                "agent": str(source_name),
                                "synthetic": not bool(raw_call.get("id")),
                            })
                    elif "<tool_call>" in str(content or ""):
                        for tc_json in re.findall(r'<tool_call>\s*(\{.*?\})\s*</tool_call>', str(content), re.DOTALL):
                            try:
                                tc_data = json.loads(tc_json)
                            except (json.JSONDecodeError, TypeError):
                                continue
                            foreign_tool_ids.append({
                                "id": "",
                                "name": str(tc_data.get("name") or ""),
                                "agent": str(source_name),
                                "synthetic": True,
                            })
                    converted.append({
                        "role": "user",
                        "content": f"[Output from agent {source_name}]\n{content}",
                    })
                    continue
                structured_calls = msg.get("tool_calls")
                if isinstance(structured_calls, list) and structured_calls:
                    tool_calls_list = []
                    for i, raw_call in enumerate(structured_calls):
                        function = raw_call.get("function", {}) if isinstance(raw_call, dict) else {}
                        synthetic_id = not bool(raw_call.get("id"))
                        tc_id = str(raw_call.get("id") or f"call_{len(converted)}_{i}")
                        tc_name = str(function.get("name") or "")
                        tc_args = function.get("arguments", "{}")
                        if not isinstance(tc_args, str):
                            tc_args = json.dumps(tc_args, ensure_ascii=False)
                        tool_calls_list.append({
                            "id": tc_id,
                            "type": raw_call.get("type", "function"),
                            "function": {"name": tc_name, "arguments": tc_args},
                        })
                        pending_tool_ids.append({"id": tc_id, "name": tc_name, "synthetic": synthetic_id})
                    clean_content = re.sub(
                        r'\s*<tool_call>.*?</tool_call>', '', str(content or ''), flags=re.DOTALL
                    ).strip()
                    new_msg = {
                        "role": "assistant",
                        "content": clean_content or None,
                        "tool_calls": tool_calls_list,
                    }
                    if msg.get("reasoning_content"):
                        new_msg["reasoning_content"] = msg["reasoning_content"]
                    converted.append(new_msg)
                # Check if this message has tool_calls embedded as XML
                elif "<tool_call>" in content:
                    # Extract tool calls
                    tc_matches = re.findall(r'<tool_call>\s*(\{.*?\})\s*</tool_call>', content, re.DOTALL)
                    # Clean content (remove tool_call tags)
                    clean_content = re.sub(r'\s*<tool_call>.*?</tool_call>', '', content, flags=re.DOTALL).strip()

                    tool_calls_list = []
                    for i, tc_json in enumerate(tc_matches):
                        try:
                            tc_data = json.loads(tc_json)
                            tc_id = f"call_{len(converted)}_{i}"
                            tc_name = tc_data.get("name", "")
                            tc_args = tc_data.get("arguments", {})
                            if isinstance(tc_args, dict):
                                tc_args = json.dumps(tc_args, ensure_ascii=False)
                            tool_calls_list.append({
                                "id": tc_id,
                                "type": "function",
                                "function": {"name": tc_name, "arguments": tc_args}
                            })
                            pending_tool_ids.append({"id": tc_id, "name": tc_name, "synthetic": True})
                        except (json.JSONDecodeError, Exception):
                            continue

                    new_msg = {"role": "assistant"}
                    if clean_content:
                        new_msg["content"] = clean_content
                    else:
                        new_msg["content"] = None
                    if tool_calls_list:
                        new_msg["tool_calls"] = tool_calls_list
                    if msg.get("reasoning_content"):
                        new_msg["reasoning_content"] = msg["reasoning_content"]
                    converted.append(new_msg)
                else:
                    # Plain assistant message
                    converted.append({"role": "assistant", "content": content.strip() if content else content})

            elif role == "user" and "<tool_response>" in content:
                # Convert tool_response to role=tool
                try:
                    # Extract JSON from <tool_response>...</tool_response>
                    tr_match = re.search(r'<tool_response>(.*?)</tool_response>', content, re.DOTALL)
                    if tr_match:
                        tr_data = json.loads(tr_match.group(1))
                        tool_name = tr_data.get("tool", "")
                        tool_content = tr_data.get("content", "")

                        # Find matching tool_call_id
                        tc_id = str(tr_data.get("tool_call_id") or "")
                        foreign_match = pop_pending(
                            foreign_tool_ids, tc_id, tool_name, allow_synthetic=True
                        )
                        own_match = None if foreign_match else pop_pending(
                            pending_tool_ids, tc_id, tool_name, allow_synthetic=True
                        )
                        normalized_content = (
                            tool_content if isinstance(tool_content, str)
                            else json.dumps(tool_content, ensure_ascii=False)
                        )
                        if foreign_match:
                            converted.append({
                                "role": "user",
                                "content": (
                                    f"[Tool result for agent {foreign_match.get('agent')}: "
                                    f"{tool_name or foreign_match.get('name') or 'unknown'}]\n"
                                    f"{normalized_content}"
                                ),
                            })
                        elif own_match:
                            converted.append({
                                "role": "tool",
                                "tool_call_id": own_match["id"],
                                "content": normalized_content,
                            })
                        else:
                            # Never invent a tool_call_id. A role=tool message
                            # without its exact assistant call makes the entire
                            # request invalid on DeepSeek and OpenAI.
                            converted.append({
                                "role": "user",
                                "content": (
                                    f"[Unpaired tool observation: {tool_name or 'unknown'}]\n"
                                    f"{normalized_content}"
                                ),
                            })
                    else:
                        converted.append({"role": "user", "content": content})
                except (json.JSONDecodeError, Exception):
                    converted.append({"role": "user", "content": content})
            else:
                # Preserve names on runtime-authored system sections until
                # compose_model_messages merges them into the single provider
                # system prefix.  The provider never sees a ``name`` field,
                # but the section labels keep Identity, DAG policy, context
                # summaries and transient runtime policy unambiguous.
                converted_message = {"role": role, "content": content}
                if role == "system" and msg.get("name"):
                    converted_message["name"] = str(msg["name"])
                converted.append(converted_message)

        return self._sanitize_tool_protocol(converted)

    def step(self, messages, tools_desc=None, on_token=None, max_tokens=None, temperature=None):
        """调用一次 LLM（流式），返回 (response, tool_calls)
        自动插入 system prompt，自动记录到全局 session
        on_token: 可选回调，每收到一个 token 时调用 on_token(token_text)
        """
        if tools_desc is None:
            tools_desc = self.get_tools_desc()

        # 将 session 消息转换为标准 OpenAI 格式
        llm_messages = self._convert_messages_for_llm(messages)

        # 插入 system prompt 作为第一条 system message
        system_prompt = self.build_system_prompt(has_tools=bool(tools_desc))
        full_messages = _compose_model_messages(system_prompt, llm_messages)

        # pre_llm_hook: 在调用 LLM 之前触发
        if self.hooks["pre_llm_hook"]:
            self.hooks["pre_llm_hook"](agent=self, messages=full_messages, tools_desc=tools_desc)

        # 调用 LLM
        from harness import get_current_harness
        harness = get_current_harness()
        model_call_id = None
        if harness:
            llm_config = getattr(self.llm, "config", {}) or {}
            parameters = {"stream": True}
            if max_tokens is not None:
                parameters["max_tokens"] = max_tokens
            if temperature is not None:
                parameters["temperature"] = temperature
            model_call_id = harness.session.begin_model_call(
                messages=full_messages,
                tools=tools_desc or [],
                agent=self.name,
                model=getattr(self.llm, "model", None),
                provider=llm_config.get("provider") or type(self.llm).__name__,
                parameters=parameters,
                purpose="agent_step",
            )
        response = ""
        reasoning_content = ""
        tool_calls = []
        metadata_before = dict(getattr(self.llm, "last_response_metadata", {}) or {})
        _in_think = False
        try:
            stream_options = {"tools": tools_desc}
            # Keep lightweight/custom LLM adapters source-compatible: optional
            # per-call overrides are only forwarded when the caller set them.
            # Provider implementations still receive explicit limits from
            # their own configuration when these values are absent.
            if max_tokens is not None:
                stream_options["max_tokens"] = max_tokens
            if temperature is not None:
                stream_options["temperature"] = temperature
            for delta in self.llm.chat_stream(full_messages, **stream_options):
                if delta.get("reasoning_content"):
                    reasoning_content += str(delta["reasoning_content"])
                content = delta.get("content", "")
                if content:
                    # Filter out <think>...</think> blocks from response and token callback
                    filtered = ""
                    i = 0
                    while i < len(content):
                        if not _in_think:
                            think_start = content.find("<think>", i)
                            if think_start == -1:
                                filtered += content[i:]
                                break
                            else:
                                filtered += content[i:think_start]
                                _in_think = True
                                i = think_start + len("<think>")
                        else:
                            think_end = content.find("</think>", i)
                            if think_end == -1:
                                break  # still in think block, discard rest
                            else:
                                _in_think = False
                                i = think_end + len("</think>")

                    if filtered:
                        # Preserve the model response before any optional
                        # console rendering; terminal encoding is not part of
                        # the Agent protocol and must not lose a model turn.
                        response += filtered
                        _console_write(filtered)
                        if on_token:
                            on_token(filtered)
                if delta.get("tool_calls"):
                    tool_calls = delta["tool_calls"]
        except StopIteration:
            pass
        except InterruptedError:
            print("\n[agent] LLM 调用被中断")
            if harness and model_call_id:
                harness.session.fail_model_call(
                    model_call_id,
                    agent=self.name,
                    error="LLM call was interrupted",
                    error_type="InterruptedError",
                )
            model_call_id = None
        except BaseException as error:
            if harness and model_call_id:
                harness.session.fail_model_call(model_call_id, agent=self.name, error=error)
            raise
        print()

        # Fallback: if no tool_calls from API but response contains <tool_call> XML tags, parse them
        if not tool_calls and "<tool_call>" in response:
            import re
            tc_matches = re.findall(r'<tool_call>\s*(\{.*?\})\s*</tool_call>', response, re.DOTALL)
            if tc_matches:
                parsed_tcs = []
                for i, tc_json in enumerate(tc_matches):
                    try:
                        tc_data = json.loads(tc_json)
                        tc_name = tc_data.get("name", "")
                        tc_args = tc_data.get("arguments", {})
                        if isinstance(tc_args, str):
                            tc_args_str = tc_args
                        else:
                            tc_args_str = json.dumps(tc_args, ensure_ascii=False)
                        parsed_tcs.append({
                            "id": f"fallback_{i}",
                            "function": {
                                "name": tc_name,
                                "arguments": tc_args_str,
                            }
                        })
                    except (json.JSONDecodeError, Exception) as e:
                        print(f"[agent] Failed to parse text tool_call: {e}")
                if parsed_tcs:
                    tool_calls = parsed_tcs
                    # Remove tool_call tags from response text
                    response = re.sub(r'<tool_call>.*?</tool_call>', '', response, flags=re.DOTALL).strip()
                    print(f"[agent] Parsed {len(parsed_tcs)} tool_call(s) from response text (fallback)")

        # Strip leading/trailing whitespace from response
        response = response.strip()

        provider_metadata = dict(getattr(self.llm, "last_response_metadata", {}) or {})
        metadata_is_fresh = (
            provider_metadata.get("sequence") != metadata_before.get("sequence")
            or not metadata_before
        )
        finish_reason = provider_metadata.get("finish_reason") if metadata_is_fresh else None
        output_truncated = bool(
            provider_metadata.get("output_truncated")
            or finish_reason in {"length", "max_tokens", "max_output_tokens"}
        ) if metadata_is_fresh else False
        if output_truncated:
            # A partially emitted tool call must never be executed. Preserve
            # visible prose, close the turn, and tell the user exactly why the
            # sentence stopped instead of silently treating it as completion.
            tool_calls = []
            notice = "\n\n> ⚠️ 模型达到输出长度上限，本次回复已被截断。请发送“继续”，我会从中断处续写。"
            response = f"{response}{notice}" if response else notice.strip()
            _console_write(notice)
            if on_token:
                on_token(notice)

        # post_llm_hook: 在 LLM 返回后触发
        if self.hooks["post_llm_hook"]:
            self.hooks["post_llm_hook"](agent=self, response=response, tool_calls=tool_calls)

        if harness and model_call_id:
            harness.session.finish_model_call(
                model_call_id,
                agent=self.name,
                content=response,
                reasoning=reasoning_content,
                tool_calls=tool_calls,
                finish_reason=finish_reason,
                usage=provider_metadata.get("usage"),
                metadata=provider_metadata,
            )

        # 自动记录到全局 session
        if harness:
            session = harness.session

            # 构建 session 中的 assistant 消息：tool_calls 转为 <tool_call> 文本标签
            session_content = response
            if tool_calls:
                tc_parts = []
                for tc in tool_calls:
                    raw_arguments = tc.get("function", {}).get("arguments", "{}")
                    try:
                        serialized_arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
                    except (json.JSONDecodeError, TypeError):
                        # Preserve malformed provider output as a JSON string so
                        # the session itself remains valid and the next turn can
                        # receive an explicit tool error and retry.
                        serialized_arguments = str(raw_arguments)
                    serialized_call = json.dumps({
                        "name": tc.get("function", {}).get("name", ""),
                        "arguments": serialized_arguments,
                    }, ensure_ascii=False)
                    tc_parts.append(f'<tool_call>{serialized_call}</tool_call>')
                session_content = (session_content + "\n" + "\n".join(tc_parts)).strip() if session_content else "\n".join(tc_parts)

            msg = {"role": "assistant", "name": self.name, "content": session_content}
            if tool_calls and reasoning_content:
                # Required by DeepSeek thinking-mode multi-round tool calls.
                # This field is protocol state and is never mirrored as text.
                msg["reasoning_content"] = reasoning_content
            if tool_calls:
                # The compact working transcript must retain provider ids too.
                # Reconstructing calls from XML creates synthetic ids, while
                # tool responses carry the original ids; strict providers then
                # reject the next turn as an unpaired tool call.
                msg["tool_calls"] = tool_calls
            full_msg = dict(msg)
            session.record(msg)
            session.record_full(full_msg)

        return response, tool_calls

    def _find_tool_or_knowledge(self, name):
        """按全名或短名字查找 tool/knowledge，返回 (type, obj) 或 None"""
        if name in self.tools:
            return ("tool", self.tools[name])
        if name in self.knowledges:
            return ("knowledge", self.knowledges[name])
        # fallback: 用短名字匹配
        short = self._short_name(name) if ":" in name else name
        for k, v in self.tools.items():
            if self._short_name(k) == short:
                return ("tool", v)
        for k, v in self.knowledges.items():
            if self._short_name(k) == short:
                return ("knowledge", v)
        return None

    def _check_tool_access(
        self,
        tool_name: str,
        arguments: dict = None,
        *,
        for_schema: bool = False,
        policy_approved: bool = False,
    ) -> str:
        """检查 tool 是否被权限规则允许。返回 None 表示允许，返回字符串表示拒绝原因。"""
        if self.identity.SEGO:
            sego_config, _ = self.identity.SEGO
            tool_access = sego_config.get("tool_access", {})
            whitelist = tool_access.get("whitelist", [])
            blacklist = tool_access.get("blacklist", [])

            short = self._short_name(tool_name)

            # 如果 whitelist 非空，只有匹配的 tool 才允许
            if whitelist:
                for pattern in whitelist:
                    if pattern == tool_name or pattern == short or self._short_name(pattern) == short:
                        break
                else:
                    return f"Tool '{tool_name}' is not in the allowed whitelist."

            # blacklist 检查
            if blacklist:
                for pattern in blacklist:
                    if pattern == tool_name or pattern == short or self._short_name(pattern) == short:
                        return f"Tool '{tool_name}' is blocked by blacklist."

        from harness import get_current_run_context
        current_run = get_current_run_context()
        policy = getattr(current_run, "permission_policy", None)
        if policy is not None and not policy_approved:
            found = self._find_tool_or_knowledge(tool_name)
            metadata = getattr(found[1], "meta", {}) if found else {}
            decision = policy.evaluate_tool(
                tool_name, arguments or {}, metadata, schema_only=for_schema
            )
            if decision.decision.value == "ask" and for_schema:
                return None
            if not decision.allowed:
                prefix = "Approval required" if decision.decision.value == "ask" else "Permission denied"
                return f"{prefix}: {decision.reason}"

        return None

    def _check_workspace_path_access(self, tool_name: str, arguments: dict) -> str:
        """Reject filesystem paths that escape a Task Bench workspace.

        Normal IDE agents intentionally retain access to their configured
        project. The stricter boundary is activated only for workspaces with
        Task Bench's `.egoagent/environment.json` marker, and therefore also
        applies automatically to agents created inside nested harnesses.
        """
        if not self.workspace:
            return None
        root = Path(self.workspace).resolve()
        if not (root / ".egoagent" / "environment.json").is_file():
            return None
        short = self._short_name(tool_name)
        for key in _WORKSPACE_PATH_ARGUMENTS.get(short, ()):
            raw_value = arguments.get(key)
            if raw_value in (None, ""):
                continue
            try:
                candidate = Path(str(raw_value))
                resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
                resolved.relative_to(root)
            except (OSError, RuntimeError, ValueError):
                return (
                    f"Tool '{short}' argument '{key}' must stay inside the Task Bench "
                    f"workspace '{root}'. Requested path was '{raw_value}'."
                )
        return None

    def _resolve_workspace_path_arguments(self, tool_name: str, arguments: dict) -> None:
        """Resolve file-tool paths against this Agent's workspace.

        Tool execution historically relied on process-wide ``os.chdir``.
        Nested harnesses and concurrent runs can change it underneath each
        other, so path-bearing arguments must be made absolute first.
        """
        if not self.workspace:
            return
        root = Path(self.workspace).resolve()
        short = self._short_name(tool_name)
        for key in _WORKSPACE_PATH_ARGUMENTS.get(short, ()):
            raw_value = arguments.get(key)
            if raw_value in (None, ""):
                if short in {"search_files", "glob_search", "create_harness", "run_command"} and key in {"path", "workspace", "cwd"}:
                    arguments[key] = str(root)
                continue
            candidate = Path(str(raw_value))
            if not candidate.is_absolute():
                arguments[key] = str((root / candidate).resolve())

    def _refresh_scoped_workspace_instructions(self, tool_name: str, arguments: dict) -> None:
        """Activate nested ``AGENTS.md`` policy after a path enters the turn.

        The global workspace prompt is assembled by the product runtime.  This
        method adds only nested instruction files, so reading a file in a
        specialized subtree affects the *next* model step without duplicating
        root policy or cross-session memory.
        """

        if not self.workspace:
            return
        short = self._short_name(tool_name)
        path_keys = _WORKSPACE_PATH_ARGUMENTS.get(short, ())
        target = next((arguments.get(key) for key in path_keys if arguments.get(key)), None)
        if not target:
            return
        try:
            from harness_editor.project_rules import get_scoped_agents_prompt

            self.scoped_context_instructions = get_scoped_agents_prompt(
                str(Path(self.workspace).resolve()),
                str(target),
                include_root=False,
            )
        except (ImportError, OSError, ValueError):
            # Scoped instructions improve correctness but must never make an
            # otherwise safe file read fail.
            self.scoped_context_instructions = ""

    def execute_tool_call(
        self,
        tool_call,
        attach_images=False,
        max_image_bytes=8_000_000,
        max_result_chars=None,
    ):
        """执行单个 tool_call，返回结果字符串，自动记录到全局 session"""
        from harness import EndSession, get_current_harness
        tool_name = tool_call["function"]["name"]
        tool_call_id = str(tool_call.get("id") or f"tool_{uuid.uuid4().hex}")
        harness = get_current_harness()
        raw_arguments = tool_call["function"].get("arguments", "{}")
        try:
            arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
            if not isinstance(arguments, dict):
                raise ValueError("tool arguments must be a JSON object")
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            result = (
                f"Tool {tool_name} error: invalid JSON arguments ({error}). "
                "Retry the tool call with valid JSON and escape quotes inside string values."
            )
            if harness:
                harness.session.trace(
                    "tool.request",
                    {"name": tool_name, "arguments_raw": raw_arguments, "arguments_valid": False},
                    agent=self.name,
                    tool_call_id=tool_call_id,
                )
                harness.session.trace(
                    "tool.result",
                    {"name": tool_name, "status": "invalid_arguments", "result": result},
                    agent=self.name,
                    tool_call_id=tool_call_id,
                )
                tool_msg = {
                    "role": "user",
                    "content": f'<tool_response>{json.dumps({"tool": tool_name, "tool_call_id": tool_call.get("id"), "content": result}, ensure_ascii=False)}</tool_response>',
                }
                harness.session.record(tool_msg)
                harness.session.record_full(tool_msg)
            return result

        original_arguments = copy.deepcopy(arguments)
        if harness:
            harness.session.trace(
                "tool.request",
                {"name": tool_name, "arguments": original_arguments, "arguments_valid": True},
                agent=self.name,
                tool_call_id=tool_call_id,
            )

        # 权限检查
        from harness import get_current_run_context
        current_run = get_current_run_context()
        policy_approved = bool(
            current_run is not None
            and tool_call.get("id")
            and str(tool_call.get("id")) in current_run.approved_tool_call_ids
        )
        denied = self._check_tool_access(tool_name, arguments, policy_approved=policy_approved)
        if not denied:
            denied = self._check_workspace_path_access(tool_name, arguments)
        if denied:
            result = f"Permission denied: {denied}"
            if harness:
                harness.session.trace(
                    "tool.result",
                    {"name": tool_name, "status": "denied", "result": result},
                    agent=self.name,
                    tool_call_id=tool_call_id,
                )
                payload = {
                    "tool": tool_name,
                    "tool_call_id": tool_call.get("id"),
                    "status": "denied",
                    "content": denied,
                }
                tool_msg = {
                    "role": "user",
                    "content": f'<tool_response>{json.dumps(payload, ensure_ascii=False)}</tool_response>',
                }
                harness.session.record(tool_msg)
                harness.session.record_full(tool_msg)
            return result

        self._resolve_workspace_path_arguments(tool_name, arguments)
        self._refresh_scoped_workspace_instructions(tool_name, arguments)
        if harness and arguments != original_arguments:
            harness.session.trace(
                "tool.arguments.resolved",
                {"name": tool_name, "arguments": copy.deepcopy(arguments)},
                agent=self.name,
                tool_call_id=tool_call_id,
            )

        # pre_tool_hook: 在执行 tool 之前触发
        if self.hooks["pre_tool_hook"]:
            self.hooks["pre_tool_hook"](agent=self, tool_name=tool_name, arguments=arguments)

        found = self._find_tool_or_knowledge(tool_name)
        capability_started = time.perf_counter()
        if found and found[0] == "tool":
            tool = found[1]
            try:
                # 如果 tool 函数签名中有 _context 参数，自动注入运行时上下文
                import inspect
                sig = inspect.signature(tool.func)
                if "_context" in sig.parameters:
                    from harness import get_current_run_context
                    tool_context = dict(self._runtime_context)
                    current_run = get_current_run_context()
                    if current_run is not None:
                        tool_context.update({
                            "run_id": current_run.run_id,
                            "parent_run_id": current_run.parent_run_id,
                            "workspace": str(Path(current_run.harness.workspace).resolve())
                            if current_run.harness.workspace else tool_context.get("workspace"),
                            "is_running": lambda: not current_run.cancelled(),
                            "cancel_event": current_run.cancel_event,
                        })
                        runtime_policy = getattr(current_run, "permission_policy", None)
                        if runtime_policy is not None:
                            tool_context["security_policy"] = runtime_policy.public()
                            tool_context["sandbox"] = dict(getattr(runtime_policy, "sandbox", {}) or {})
                    arguments["_context"] = tool_context
                
                # 变更追踪: 在文件修改工具执行前读取旧内容
                _track_file_path = None
                _track_old_content = None
                if tool_name in ('patch_file', 'write_file', 'multi_edit'):
                    _fp = arguments.get('file_path', '')
                    if _fp:
                        _track_file_path = os.path.abspath(_fp)
                        try:
                            with open(_track_file_path, 'r', encoding='utf-8', newline='') as _f:
                                _track_old_content = _f.read()
                        except (FileNotFoundError, OSError):
                            _track_old_content = None  # 新建文件
                
                try:
                    result = tool.func(**arguments)
                finally:
                    # 变更追踪: 执行后记录变更
                    if _track_file_path is not None:
                        try:
                            from harness_editor.change_tracker import record_change
                            try:
                                with open(_track_file_path, 'r', encoding='utf-8', newline='') as _f:
                                    _track_new_content = _f.read()
                            except (FileNotFoundError, OSError):
                                _track_new_content = None
                            if (
                                tool_name in ('patch_file', 'multi_edit')
                                and _track_old_content is not None
                                and _track_new_content is not None
                            ):
                                normalized_content = preserve_patch_line_endings(
                                    _track_old_content, _track_new_content
                                )
                                if normalized_content != _track_new_content:
                                    with open(_track_file_path, 'w', encoding='utf-8', newline='') as _f:
                                        _f.write(normalized_content)
                                    _track_new_content = normalized_content
                            if _track_old_content != _track_new_content:
                                from harness import get_current_run_context
                                active_run = get_current_run_context()
                                record_change(
                                    _track_file_path,
                                    _track_old_content,
                                    _track_new_content,
                                    tool_name,
                                    transaction_id=getattr(active_run, "change_transaction_id", None),
                                )
                        except ImportError:
                            pass  # change_tracker not available
            except EndSession as error:
                if harness:
                    harness.session.trace(
                        "tool.result",
                        {"name": tool_name, "status": "end_session", "result": str(error)},
                        agent=self.name,
                        tool_call_id=tool_call_id,
                    )
                raise
            except Exception as e:
                result = f"Tool {tool_name} error: {str(e)}"
        elif found and found[0] == "knowledge":
            result = found[1].render()
        else:
            result = f"Tool not found: {tool_name}"

        self._record_capability_execution(
            found,
            result,
            runtime_ms=(time.perf_counter() - capability_started) * 1000,
        )

        # post_tool_hook: 在 tool 执行后触发
        if self.hooks["post_tool_hook"]:
            self.hooks["post_tool_hook"](agent=self, tool_name=tool_name, arguments=arguments, result=result)

        raw_result = copy.deepcopy(result)
        if max_result_chars is not None:
            limit = max(1, int(max_result_chars))
            serialized = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
            if len(serialized) > limit:
                omitted = len(serialized) - limit
                result = f"{serialized[:limit]}\n...[tool observation truncated; {omitted} characters omitted]"

        if harness:
            harness.session.trace(
                "tool.result",
                {
                    "name": tool_name,
                    "status": "ok" if not (
                        isinstance(raw_result, str)
                        and (raw_result.startswith("Tool ") and " error:" in raw_result)
                    ) else "error",
                    "result": raw_result,
                    "model_observation": result,
                    "observation_truncated": raw_result != result,
                },
                agent=self.name,
                tool_call_id=tool_call_id,
            )

        from harness import get_current_run_context
        active_run = get_current_run_context()
        if active_run is not None:
            result = active_run.secret_view.redact_value(result)

        # 自动记录 tool 结果到全局 session（文本化 <tool_response> 标签）
        harness = get_current_harness()
        if harness:
            result_str = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
            payload = {"tool": tool_name, "tool_call_id": tool_call.get("id"), "content": result_str}
            tool_msg = {
                "role": "user",
                "content": f'<tool_response>{json.dumps(payload, ensure_ascii=False)}</tool_response>'
            }
            harness.session.record(tool_msg)
            harness.session.record_full(tool_msg)
            if attach_images:
                image_msg = build_tool_image_message(result, tool_name, self.workspace, max_bytes=max_image_bytes)
                if image_msg is not None:
                    harness.session.record(image_msg)
                    harness.session.record_full(image_msg.copy())

        # Tool execution is also used directly by tests, the capability
        # library and nested runtimes that intentionally have no active
        # Harness.  The result must not depend on whether session recording is
        # enabled.
        return result

    def close_runtime_resources(self):
        """Best-effort cleanup for run-scoped sessions such as browsers."""
        closed = []
        for key, value in list(self._runtime_context.items()):
            if not key.endswith("_session") or value is None or not callable(getattr(value, "close", None)):
                continue
            try:
                result = value.close()
                closed.append({"resource": key, "result": result})
            except Exception as error:
                closed.append({"resource": key, "error": str(error)})
            finally:
                self._runtime_context.pop(key, None)
        return closed

    def _log_llm_io(self, data, tools_desc, direction):
        """记录 LLM 的输入输出到文件"""
        log_file = Path("llm_io.log")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"[{direction.upper()}] agent={self.identity.ID.get('name', '?')}\n")
            f.write(f"{'='*60}\n")
            if direction == "input":
                f.write(json.dumps({"messages": data, "tools": tools_desc}, ensure_ascii=False, indent=2))
            else:
                f.write(json.dumps(data, ensure_ascii=False, indent=2))
            f.write("\n")

