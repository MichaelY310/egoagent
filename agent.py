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
        self.meilisearch = None
        self._runtime_context = {
            "running_commands": self._running_commands,
            "agent_name": self.name,
            "meilisearch": None,
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

        # 从 ID 读取身份和性格
        id_config = self.identity.ID
        if id_config.get("role"):
            parts.append(f"You are {self.name}, a {id_config['role']}.")
        else:
            parts.append(f"You are {self.name}.")
        if id_config.get("description"):
            parts.append(id_config["description"])
        personality = id_config.get("personality", {})
        if personality.get("language"):
            parts.append(f"Respond in: {personality['language']}.")

        # 从 SEGO 读取任务和约束
        if self.identity.SEGO:
            sego_config, _ = self.identity.SEGO
            if sego_config.get("task_prompt"):
                parts.append(f"\n{sego_config['task_prompt']}")

        # 通用行为约束
        parts.append("\nRules:")
        parts.append("- Only use the tools provided via function calling. Do not invent tool names.")
        parts.append("- After a tool succeeds, respond to the user. Do not re-call the same tool with same arguments.")
        parts.append("- If a tool errors, try a different approach or explain the issue to the user.")

        return "\n".join(parts)

    def get_tools_desc(self):
        """获取所有 tools + knowledges 的 desc 列表（传给 LLM），已按权限过滤。
        传给 LLM 的 function.name 使用短名字（不含 IDENTITY<...>:TOOL: 前缀），节省 token。
        """
        descs = []
        for t in self.tools.values():
            if self._check_tool_access(t.name) is None:
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
        for k in self.knowledges.values():
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

        # 插入 system prompt
        system_prompt = self.build_system_prompt()
        if system_prompt:
            messages = [{"role": "system", "content": system_prompt}] + messages

        result = self.llm.chat(messages)
        reply = result["choices"][0]["message"].get("content", "").strip()
        # Strip <think> blocks from reply
        if "<think>" in reply and "</think>" in reply:
            reply = reply.split("</think>", 1)[-1].strip()

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

        # 插入 system prompt
        system_prompt = self.build_system_prompt()
        if system_prompt:
            messages = [{"role": "system", "content": system_prompt}] + messages

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
        pending_tool_ids = []  # [(tool_call_id, tool_name), ...]

        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", "")

            if role == "assistant":
                # Check if this message has tool_calls embedded as XML
                if "<tool_call>" in content:
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
                            pending_tool_ids.append((tc_id, tc_name))
                        except (json.JSONDecodeError, Exception):
                            continue

                    new_msg = {"role": "assistant"}
                    if clean_content:
                        new_msg["content"] = clean_content
                    else:
                        new_msg["content"] = None
                    if tool_calls_list:
                        new_msg["tool_calls"] = tool_calls_list
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
                        tc_id = None
                        for pid, pname in pending_tool_ids:
                            if pname == tool_name:
                                tc_id = pid
                                pending_tool_ids.remove((pid, pname))
                                break

                        converted.append({
                            "role": "tool",
                            "tool_call_id": tc_id or f"unknown_{tool_name}",
                            "content": tool_content if isinstance(tool_content, str) else json.dumps(tool_content, ensure_ascii=False)
                        })
                    else:
                        converted.append({"role": "user", "content": content})
                except (json.JSONDecodeError, Exception):
                    converted.append({"role": "user", "content": content})
            else:
                # Regular user message
                converted.append({"role": role, "content": content})

        return converted

    def step(self, messages, tools_desc=None, on_token=None):
        """调用一次 LLM（流式），返回 (response, tool_calls)
        自动插入 system prompt，自动记录到全局 session
        on_token: 可选回调，每收到一个 token 时调用 on_token(token_text)
        """
        if tools_desc is None:
            tools_desc = self.get_tools_desc()

        # 将 session 消息转换为标准 OpenAI 格式
        llm_messages = self._convert_messages_for_llm(messages)

        # 插入 system prompt 作为第一条 system message
        system_prompt = self.build_system_prompt()
        if system_prompt:
            system_msg = {"role": "system", "content": system_prompt}
            full_messages = [system_msg] + llm_messages
        else:
            full_messages = llm_messages

        # pre_llm_hook: 在调用 LLM 之前触发
        if self.hooks["pre_llm_hook"]:
            self.hooks["pre_llm_hook"](agent=self, messages=full_messages, tools_desc=tools_desc)

        # 调用 LLM
        response = ""
        tool_calls = []
        _in_think = False
        try:
            for delta in self.llm.chat_stream(full_messages, tools=tools_desc):
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
                        print(filtered, end="", flush=True)
                        if on_token:
                            on_token(filtered)
                        response += filtered
                if delta.get("tool_calls"):
                    tool_calls = delta["tool_calls"]
        except StopIteration:
            pass
        except InterruptedError:
            print("\n[agent] LLM 调用被中断")
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

        # post_llm_hook: 在 LLM 返回后触发
        if self.hooks["post_llm_hook"]:
            self.hooks["post_llm_hook"](agent=self, response=response, tool_calls=tool_calls)

        # 自动记录到全局 session
        from harness import get_current_harness
        harness = get_current_harness()
        if harness:
            session = harness.session

            # 构建 session 中的 assistant 消息：tool_calls 转为 <tool_call> 文本标签
            session_content = response
            if tool_calls:
                tc_parts = []
                for tc in tool_calls:
                    tc_parts.append(
                        f'<tool_call>{{"name": "{tc["function"]["name"]}", '
                        f'"arguments": {tc["function"]["arguments"]}}}</tool_call>'
                    )
                session_content = (session_content + "\n" + "\n".join(tc_parts)).strip() if session_content else "\n".join(tc_parts)

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

                # 在 workspace 目录下执行工具（让相对路径和默认 path="." 生效）
                import os
                old_cwd = os.getcwd()
                if self.workspace:
                    os.chdir(str(self.workspace))
                try:
                    result = tool.func(**arguments)
                finally:
                    os.chdir(old_cwd)
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


