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
        self.init_environment()
        self.load_environments(environments)

        self.hooks = {
            "pre_llm_hooks": [],      # 调 LLM 前
            "post_llm_hooks": [],     # LLM 返回后
            "pre_tool_hooks": [],     # 执行 tool 前
            "post_tool_hooks": [],    # tool 执行后
            "pre_loop_hooks": [],     # 每轮 loop 开始
            "post_loop_hooks": [],    # 每轮 loop 结束
        }

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

        # 可用工具和知识库说明
        if self.tools:
            tool_lines = [f"- `{t.name}`: {t.desc['function'].get('description', '')}" for t in self.tools.values()]
            parts.append("\n[Available Tools]\n" + "\n".join(tool_lines))
        if self.knowledges:
            knowledge_lines = [f"- `{k.name}`: {k.desc['function'].get('description', '')}" for k in self.knowledges.values()]
            parts.append("\n[Available Knowledge]\nCall these to retrieve knowledge content, they are NOT tools:\n" + "\n".join(knowledge_lines))

        return "\n".join(parts)

    def get_tools_desc(self):
        """获取所有 tools + knowledges 的 desc 列表（传给 LLM）"""
        descs = [t.desc for t in self.tools.values()]
        descs += [k.desc for k in self.knowledges.values()]
        return descs

    def step(self, messages, tools_desc=None):
        """调用一次 LLM（流式），返回 (response, tool_calls)
        自动插入 system prompt，自动记录到全局 session
        """
        if tools_desc is None:
            tools_desc = self.get_tools_desc()

        # 插入 system prompt
        # 如果最后一条是 user，放在它前面；否则放在末尾
        system_prompt = self.build_system_prompt()
        if system_prompt and messages:
            last_msg = messages[-1]
            if last_msg.get("role") in ("user",):
                full_messages = messages[:-1] + [{"role": "system", "content": system_prompt}] + [last_msg]
            else:
                full_messages = messages + [{"role": "system", "content": system_prompt}]
        elif system_prompt:
            full_messages = [{"role": "system", "content": system_prompt}]
        else:
            full_messages = messages

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

        # 自动记录到全局 session
        from harness import get_current_harness
        harness = get_current_harness()
        if harness:
            session = harness.session
            # full_messages 版本（含 system prompt）
            if system_prompt:
                session.record_full({"role": "system", "name": self.name, "content": system_prompt})
            msg = {"role": "assistant", "name": self.name, "content": response}
            if tool_calls:
                msg["tool_calls"] = tool_calls
            session.record(msg)
            session.record_full(msg)

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

    def execute_tool_call(self, tool_call):
        """执行单个 tool_call，返回结果字符串，自动记录到全局 session"""
        from harness import EndSession, get_current_harness
        tool_name = tool_call["function"]["name"]
        found = self._find_tool_or_knowledge(tool_name)
        if found and found[0] == "tool":
            tool = found[1]
            arguments = json.loads(tool_call["function"]["arguments"])
            try:
                result = tool.func(**arguments)
            except EndSession:
                raise
            except Exception as e:
                result = f"Tool {tool_name} error: {str(e)}"
        elif found and found[0] == "knowledge":
            result = found[1].render()
        else:
            result = f"Tool not found: {tool_name}"

        # 自动记录 tool 结果到全局 session
        harness = get_current_harness()
        if harness:
            tool_msg = {
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": result
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


