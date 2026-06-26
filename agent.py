from llm.llm import Identity
from typing import Union, List
from pathlib import Path
from config import CONFIG
from environment import Environment, load_environment_from_dir
import json

root_environment_path = CONFIG["root_environment_path"]


class Agent:
    def __init__(self, identity: Union[Path, str, Identity], name: str = None, workspace: Path = None, environments: List[Union[Path, str, Environment]] = None):
        self.set_identity(identity)
        self.name = name or self.identity.ID.get("name", "agent")
        self.llm = self.identity.get_llm()
        self.environments = set()
        self.tools = {}
        self.knowledges = {}
        self.workspace = workspace

        # 共享运行时状态，所有 tool 通过 _context 参数访问
        self._running_commands = {}
        self._runtime_context = {
            "running_commands": self._running_commands,
            "agent_name": self.name,
        }

        self.init_environment()
        self.load_environments(environments)

        self.hooks = self._load_hooks()

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
        self.load_environment(self.identity.EGO)
        self.load_environment(root_environment_path)
        # workspace: 优先加载 .environment 子目录
        if self.workspace:
            env_dir = Path(self.workspace) / ".environment"
            if env_dir.is_dir():
                self.load_environment(env_dir)
            else:
                self.load_environment(self.workspace)

    def build_system_prompt(self):
        """从 ID（性格）和 SEGO（任务/约束）组装 system prompt"""
        parts = []

        # 注入 agent 名字
        parts.append(f"Your name is {self.name}.")

        # 从 ID 读取身份和性格
        id_config = self.identity.ID
        if id_config.get("role"):
            parts.append(f"You are a {id_config['role']}.")
        if id_config.get("description"):
            parts.append(id_config["description"])
        personality = id_config.get("personality", {})
        if personality.get("traits"):
            parts.append(f"Your personality traits: {', '.join(personality['traits'])}.")
        if personality.get("tone"):
            parts.append(f"Your tone: {personality['tone']}.")
        if personality.get("language"):
            parts.append(f"Respond in: {personality['language']}.")

        # 从 SEGO 读取任务和约束
        if self.identity.SEGO:
            sego_config, _ = self.identity.SEGO
            if sego_config.get("task_prompt"):
                parts.append(f"\n[Current Task]\n{sego_config['task_prompt']}")
            # 权限约束提示
            constraints = []
            if not sego_config.get("allow_create_agent", True):
                constraints.append("You cannot create other agents.")
            if not sego_config.get("allow_modify_identity", True):
                constraints.append("You cannot modify your own identity.")
            if constraints:
                parts.append("\n[Constraints]\n" + "\n".join(constraints))

        # 可用工具和知识库说明（已按权限过滤，限制显示数量）
        max_tools = CONFIG.get("max_prompt_tools", 10)
        max_knowledges = CONFIG.get("max_prompt_knowledges", 5)

        if self.tools:
            tool_lines = []
            for t in self.tools.values():
                if self._check_tool_access(t.name) is None:
                    tool_lines.append(f"- `{t.name}`: {t.desc['function'].get('description', '')}")
            if tool_lines:
                shown = tool_lines[:max_tools]
                remaining = len(tool_lines) - len(shown)
                header = "\n[Available Tools]\n"
                parts.append(header + "\n".join(shown))
                if remaining > 0:
                    parts.append(f"(... and {remaining} more tools. Use `list_all_resources` or search to find them.)")

        if self.knowledges:
            knowledge_lines = [f"- `{k.name}`: {k.desc['function'].get('description', '')}" for k in self.knowledges.values()]
            shown = knowledge_lines[:max_knowledges]
            remaining = len(knowledge_lines) - len(shown)
            header = "\n[Available Knowledge]\nCall these to retrieve knowledge content, they are NOT tools:\n"
            parts.append(header + "\n".join(shown))
            if remaining > 0:
                parts.append(f"(... and {remaining} more knowledge items. Use `list_all_resources` or search to find them.)")

        return "\n".join(parts)

    def get_tools_desc(self):
        """获取所有 tools + knowledges 的 desc 列表（传给 LLM），已按权限过滤"""
        descs = []
        for t in self.tools.values():
            if self._check_tool_access(t.name) is None:
                descs.append(t.desc)
        for k in self.knowledges.values():
            descs.append(k.desc)
        return descs

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

        # 构造带 system_instructions 的消息
        system_prompt = self.build_system_prompt()
        if system_prompt:
            wrapped = f"<system_instructions>\n{system_prompt}\n</system_instructions>"
            messages = [{"role": "user", "content": wrapped}] + messages

        result = self.llm.chat(messages)
        reply = result["choices"][0]["message"].get("content", "").strip()

        # 记录到 session
        from harness import get_current_harness
        harness = get_current_harness()
        if harness:
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

        # 构造带 system_instructions 的消息
        system_prompt = self.build_system_prompt()
        if system_prompt:
            wrapped = f"<system_instructions>\n{system_prompt}\n</system_instructions>"
            messages = [{"role": "user", "content": wrapped}] + messages

        try:
            result = self.llm.chat(messages)
            reply = result["choices"][0]["message"].get("content", "").strip()
            # 如果 reply 被 <think>...</think> 包裹，提取实际内容
            if "<think>" in reply and "</think>" in reply:
                reply = reply.split("</think>", 1)[-1].strip()

            # 去掉可能的 markdown 代码块
            if reply.startswith("```"):
                reply = reply.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            verdicts = json.loads(reply)
            print(f"  [{self.name}] 审查回复: {reply}")
        except (json.JSONDecodeError, KeyError, Exception) as e:
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
        from harness import get_current_harness
        harness = get_current_harness()
        if harness:
            harness.session.record_full({
                "role": "assistant", "name": self.name, "_op": "process_tool_calls",
                "content": reply
            })

        return allowed, blocked

    def step(self, messages, tools_desc=None):
        """调用一次 LLM（流式），返回 (response, tool_calls)
        自动插入 system prompt，自动记录到全局 session
        """
        if tools_desc is None:
            tools_desc = self.get_tools_desc()

        # 插入 system prompt（作为 user 消息 + XML 标签包裹）
        # 如果最后一条是 user，放在它前面；否则放在末尾
        system_prompt = self.build_system_prompt()
        if system_prompt:
            wrapped = f"<system_instructions>\n{system_prompt}\n</system_instructions>"
            system_msg = {"role": "user", "content": wrapped}
        else:
            system_msg = None

        if system_msg and messages:
            last_msg = messages[-1]
            if last_msg.get("role") in ("user",):
                full_messages = messages[:-1] + [system_msg] + [last_msg]
            else:
                full_messages = messages + [system_msg]
        elif system_msg:
            full_messages = [system_msg]
        else:
            full_messages = messages

        # pre_llm_hook: 在调用 LLM 之前触发
        if self.hooks["pre_llm_hook"]:
            self.hooks["pre_llm_hook"](agent=self, messages=full_messages, tools_desc=tools_desc)

        # 调用 LLM
        response = ""
        tool_calls = []
        for delta in self.llm.chat_stream(full_messages, tools=tools_desc):
            content = delta.get("content", "")
            if content:
                print(content, end="", flush=True)
                response += content
            if delta.get("tool_calls"):
                tool_calls = delta["tool_calls"]
        print()

        # post_llm_hook: 在 LLM 返回后触发
        if self.hooks["post_llm_hook"]:
            self.hooks["post_llm_hook"](agent=self, response=response, tool_calls=tool_calls)

        # 自动记录到全局 session
        from harness import get_current_harness
        harness = get_current_harness()
        if harness:
            session = harness.session
            # full_messages 版本（含 system prompt）
            if system_prompt:
                session.record_full({"role": "user", "name": self.name, "content": wrapped})

            # 构建 session 中的 assistant 消息：tool_calls 转为 <tool_call> 文本标签
            session_content = response
            if tool_calls:
                tc_parts = []
                for tc in tool_calls:
                    tc_parts.append(
                        f'<tool_call>{{"name": "{tc["function"]["name"]}", '
                        f'"arguments": {tc["function"]["arguments"]}}}</tool_call>'
                    )
                session_content = session_content + "\n" + "\n".join(tc_parts) if session_content else "\n".join(tc_parts)

            msg = {"role": "assistant", "name": self.name, "content": session_content}
            if tool_calls:
                # 保留原始 tool_calls 用于 full_messages（调试/回溯）
                full_msg = {"role": "assistant", "name": self.name, "content": session_content, "tool_calls": tool_calls}
            else:
                full_msg = msg
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

    def _check_tool_access(self, tool_name: str) -> str:
        """检查 tool 是否被权限规则允许。返回 None 表示允许，返回字符串表示拒绝原因。"""
        if not self.identity.SEGO:
            return None
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

        return None

    def execute_tool_call(self, tool_call):
        """执行单个 tool_call，返回结果字符串，自动记录到全局 session"""
        from harness import EndSession, get_current_harness
        tool_name = tool_call["function"]["name"]
        arguments = json.loads(tool_call["function"]["arguments"])

        # 权限检查
        denied = self._check_tool_access(tool_name)
        if denied:
            result = f"Permission denied: {denied}"
            harness = get_current_harness()
            if harness:
                tool_msg = {"role": "user", "content": f'<tool_response>{{"tool": "{tool_name}", "status": "denied", "content": "{denied}"}}</tool_response>'}
                harness.session.record(tool_msg)
                harness.session.record_full(tool_msg)
            return result

        # pre_tool_hook: 在执行 tool 之前触发
        if self.hooks["pre_tool_hook"]:
            self.hooks["pre_tool_hook"](agent=self, tool_name=tool_name, arguments=arguments)

        found = self._find_tool_or_knowledge(tool_name)
        if found and found[0] == "tool":
            tool = found[1]
            try:
                # 如果 tool 函数签名中有 _context 参数，自动注入运行时上下文
                import inspect
                sig = inspect.signature(tool.func)
                if "_context" in sig.parameters:
                    arguments["_context"] = self._runtime_context
                result = tool.func(**arguments)
            except EndSession:
                raise
            except Exception as e:
                result = f"Tool {tool_name} error: {str(e)}"
        elif found and found[0] == "knowledge":
            result = found[1].render()
        else:
            result = f"Tool not found: {tool_name}"

        # post_tool_hook: 在 tool 执行后触发
        if self.hooks["post_tool_hook"]:
            self.hooks["post_tool_hook"](agent=self, tool_name=tool_name, arguments=arguments, result=result)

        # 自动记录 tool 结果到全局 session（文本化 <tool_response> 标签）
        harness = get_current_harness()
        if harness:
            result_str = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
            tool_msg = {
                "role": "user",
                "content": f'<tool_response>{{"tool": "{tool_name}", "content": {json.dumps(result_str, ensure_ascii=False)}}}</tool_response>'
            }
            harness.session.record(tool_msg)
            harness.session.record_full(tool_msg)

        return result

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


