"""
Harness = 控制中心，操作 agents，定义交互逻辑
Session = 运行记录器，存对话历史、状态，提供查询方法
"""
import json
import os
import time
from pathlib import Path
from utils import load_script


class EndSession(Exception):
    """skill 调用此异常来终止当前 session，回到父 harness"""
    pass

# 全局 harness 栈，支持嵌套子 harness
_current_harness: "Harness" = None


def get_current_harness():
    return _current_harness


def set_current_harness(harness):
    global _current_harness
    _current_harness = harness


class Session:
    """纯记录器，不控制任何 agent"""

    def __init__(self, workspace: Path = None, save_dir: Path = None):
        self.messages = []
        self.full_messages = []  # 包含 system prompt 的完整版本
        self.workspace = workspace
        self.state = {}
        self.save_dir = save_dir

    def record(self, msg):
        """记录一条消息"""
        self.messages.append(msg)

    def record_full(self, msg):
        """记录一条含 system prompt 的消息到 full log"""
        self.full_messages.append(msg)

    def get_history(self, agent_name=None):
        """查看对话记录，可选按 agent 过滤"""
        if agent_name is None:
            return self.messages
        return [m for m in self.messages if m.get("name") == agent_name]

    def save(self, path=None):
        """持久化到文件"""
        save_dir = Path(path) if path else self.save_dir
        if not save_dir:
            return
        os.makedirs(save_dir, exist_ok=True)
        with open(save_dir / "messages.json", "w", encoding="utf-8") as f:
            json.dump(self.messages, f, ensure_ascii=False, indent=2)
        with open(save_dir / "full_messages.json", "w", encoding="utf-8") as f:
            json.dump(self.full_messages, f, ensure_ascii=False, indent=2)
        with open(save_dir / "state.json", "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)

    def load(self, path):
        """从文件恢复"""
        path = Path(path)
        if (path / "messages.json").exists():
            self.messages = json.load(open(path / "messages.json"))
        if (path / "state.json").exists():
            self.state = json.load(open(path / "state.json"))

    def get_result(self, mode="last"):
        """
        获取 session 结果，用于返回给父 harness。
        mode:
          - "all": 返回所有 messages
          - "last": 只返回最后一条 role 不为 tool 的 message
        """
        if mode == "all":
            return self.messages
        else:
            # 从后往前找第一条 role 不为 tool 的消息
            for msg in reversed(self.messages):
                if msg.get("role") != "tool":
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
        self.config = json.load(open(self.dir / "config.json"))
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

        # 加载 protocol
        protocol_file = self.dir / "protocol.py"
        assert protocol_file.exists(), f"Harness {self.dir} 缺少 protocol.py"
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
        session_dir = Path("sessions") / f"{self.name}_{time.strftime('%Y%m%d_%H%M%S')}"
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

        # 栈式保存 parent，设置 self 为 current
        parent = get_current_harness()
        if parent:
            self.parent = parent
            parent.children.append(self)
        set_current_harness(self)

        self.fire_hook("pre_session")
        try:
            self.run_func(self)
        except EndSession as e:
            # EndSession 只终止当前 harness，不向上传播
            if str(e):
                print(f"\n[EndSession] {e}")
        finally:
            self.fire_hook("post_session")
            self.session.save()
            # 恢复 parent
            set_current_harness(parent)

        # 返回 session 结果
        return self.session.get_result(self.return_mode)

    def fire_hook(self, hook_name, **kwargs):
        """触发 harness 级 hook"""
        if hook_name in self.hooks:
            return self.hooks[hook_name](harness=self, **kwargs)
        return None

    def get_prompt(self, name):
        """获取模板 prompt"""
        return self.prompts.get(name, "")
