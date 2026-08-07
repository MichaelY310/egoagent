"""
搜索空间定义：定义 PAS 可用的节点类型、条件边、结构约束及随机采样方法。
"""

import random
from typing import Dict, List, Optional, Tuple


# ─── 节点类型及其参数模板 ─────────────────────────────────────────────────────────

NODE_TYPES = {
    "等待输入": {
        "description": "等待用户输入",
        "required_fields": [],
        "optional_fields": [],
        "valid_out_conditions": ["input"],
    },
    "推理": {
        "description": "调用 agent 进行推理",
        "required_fields": ["agent"],
        "optional_fields": [],
        "valid_out_conditions": ["has_tool_calls", "has_text", "no_tool_calls", "default"],
    },
    "处理工具": {
        "description": "审查/过滤 tool_calls",
        "required_fields": ["agent"],
        "optional_fields": ["prompt"],
        "valid_out_conditions": ["has_tool_calls", "default"],
    },
    "处理文字": {
        "description": "处理推理输出的文本",
        "required_fields": ["agent"],
        "optional_fields": ["prompt"],
        "valid_out_conditions": ["has_tool_calls", "default"],
    },
    "执行工具": {
        "description": "执行当前的 tool_calls",
        "required_fields": [],
        "optional_fields": ["agent"],
        "valid_out_conditions": ["default"],
    },
    "脚本": {
        "description": "执行 Python 脚本",
        "required_fields": ["script"],
        "optional_fields": ["input_vars", "output_vars"],
        "valid_out_conditions": ["default"],
    },
    "llm_call": {
        "description": "独立 LLM 调用",
        "required_fields": ["prompt"],
        "optional_fields": ["input_vars", "output_var", "parse_as"],
        "valid_out_conditions": ["default"],
    },
    "循环": {
        "description": "遍历列表",
        "required_fields": ["list_var", "body_start"],
        "optional_fields": ["item_var", "counter_var", "max_count"],
        "valid_out_conditions": ["loop_done", "loop_continue"],
    },
    "子流程": {
        "description": "运行子 harness",
        "required_fields": ["harness", "identity_map"],
        "optional_fields": ["initial_message", "output_var"],
        "valid_out_conditions": ["default"],
    },
}

# ─── 条件边类型 ──────────────────────────────────────────────────────────────────

EDGE_CONDITIONS = [
    "input",           # 用户已输入
    "has_tool_calls",  # 上一步产生了 tool_calls
    "no_tool_calls",   # 上一步没有 tool_calls
    "has_text",        # 上一步产生了文本
    "default",         # 兜底（总是匹配）
    "loop_done",       # 循环结束
    "loop_continue",   # 循环体继续
    # "expr:..."      # 表达式条件，动态生成
]

# ─── 结构约束 ─────────────────────────────────────────────────────────────────────

DEFAULT_CONSTRAINTS = {
    "max_nodes": 20,
    "min_nodes": 2,
    "max_edges_per_node": 5,
    "max_depth": 10,
    "allowed_node_types": list(NODE_TYPES.keys()),
    "require_start_node": True,
    "require_wait_input": True,  # 至少一个等待输入节点
    "max_agents": 4,
}


class SearchSpace:
    """搜索空间管理器：定义并约束 Pipeline DAG 的可能结构。"""

    def __init__(self, constraints: Optional[Dict] = None):
        self.constraints = {**DEFAULT_CONSTRAINTS, **(constraints or {})}

    @property
    def allowed_node_types(self) -> List[str]:
        return self.constraints["allowed_node_types"]

    @property
    def max_nodes(self) -> int:
        return self.constraints["max_nodes"]

    @property
    def min_nodes(self) -> int:
        return self.constraints["min_nodes"]

    def get_node_template(self, node_type: str) -> Dict:
        """获取指定节点类型的参数模板"""
        if node_type not in NODE_TYPES:
            raise ValueError(f"Unknown node type: {node_type}")
        info = NODE_TYPES[node_type]
        template = {"op": node_type, "edges": []}
        for field in info["required_fields"]:
            template[field] = ""  # 占位符
        return template

    def get_valid_conditions(self, node_type: str) -> List[str]:
        """获取节点类型的合法出边条件"""
        if node_type not in NODE_TYPES:
            return ["default"]
        return NODE_TYPES[node_type]["valid_out_conditions"]

    def random_node_type(self, exclude: Optional[List[str]] = None) -> str:
        """随机采样一个节点类型"""
        allowed = [t for t in self.allowed_node_types if t not in (exclude or [])]
        return random.choice(allowed)

    def random_condition(self, node_type: str) -> str:
        """随机采样节点的一个合法出边条件"""
        conditions = self.get_valid_conditions(node_type)
        return random.choice(conditions)

    def random_node_id(self, existing_ids: List[str]) -> str:
        """生成唯一的节点ID"""
        prefixes = ["node", "step", "proc", "check", "act"]
        for _ in range(100):
            prefix = random.choice(prefixes)
            nid = f"{prefix}_{random.randint(0, 999):03d}"
            if nid not in existing_ids:
                return nid
        return f"node_{random.randint(1000, 9999)}"

    def sample_random_pipeline(self, num_agents: int = 1) -> Dict:
        """随机采样一个完整的 pipeline 配置。

        生成一个基本的 ReAct 结构变体。
        """
        agent_slots = [f"agent_{i}" if i > 0 else "agent" for i in range(num_agents)]
        num_nodes = random.randint(self.min_nodes, min(7, self.max_nodes))

        # 始终包含基本结构：等待输入 → 推理 → 执行工具
        nodes = {}
        node_ids = []

        # 必须有的起始节点
        nodes["wait_input"] = {
            "op": "等待输入",
            "edges": [{"condition": "input", "to": "infer"}]
        }
        node_ids.append("wait_input")

        # 推理节点
        agent = random.choice(agent_slots)
        nodes["infer"] = {
            "op": "推理",
            "agent": agent,
            "edges": [
                {"condition": "has_tool_calls", "to": "exec_tools"},
                {"condition": "has_text", "to": "wait_input"},
            ]
        }
        node_ids.append("infer")

        # 执行工具节点
        nodes["exec_tools"] = {
            "op": "执行工具",
            "agent": agent,
            "edges": [{"condition": "default", "to": "infer"}]
        }
        node_ids.append("exec_tools")

        # 添加额外节点（链式插入确保可达）
        # 追踪当前 infer→exec_tools 路径上的中间节点
        last_before_exec = "infer"  # 当前指向 exec_tools 的节点
        last_after_exec = "infer"   # exec_tools 当前指向的节点

        extra_types = ["处理工具", "处理文字", "llm_call"]
        for i in range(num_nodes - 3):
            node_type = random.choice(extra_types)
            nid = self.random_node_id(node_ids)
            node_ids.append(nid)

            if node_type in ("处理工具", "处理文字"):
                # 插入在当前 has_tool_calls 目标和 exec_tools 之间
                review_agent = random.choice(agent_slots)
                # 找到当前 infer 的 has_tool_calls 边指向
                current_target = "exec_tools"
                for edge in nodes["infer"]["edges"]:
                    if edge["condition"] == "has_tool_calls":
                        current_target = edge["to"]
                        break
                # 新节点指向原来的目标
                nodes[nid] = {
                    "op": node_type,
                    "agent": review_agent,
                    "edges": [{"condition": "default", "to": current_target}]
                }
                # infer 指向新节点
                for edge in nodes["infer"]["edges"]:
                    if edge["condition"] == "has_tool_calls":
                        edge["to"] = nid
                        break
            elif node_type == "llm_call":
                # 插入在 exec_tools 之后
                # 找到 exec_tools 当前指向的目标
                current_target = nodes["exec_tools"]["edges"][0]["to"]
                nodes[nid] = {
                    "op": "llm_call",
                    "prompt": "default_prompt",
                    "input_vars": [],
                    "output_var": f"_llm_{i}",
                    "parse_as": "text",
                    "edges": [{"condition": "default", "to": current_target}]
                }
                # exec_tools 指向这个 llm_call 节点
                nodes["exec_tools"]["edges"] = [{"condition": "default", "to": nid}]

        # 构建 slots
        slots = {}
        for s in agent_slots:
            slots[s] = {"description": f"Agent slot: {s}", "required": True}

        config = {
            "name": f"generated_{random.randint(0, 9999):04d}",
            "description": "Auto-generated pipeline",
            "slots": slots,
            "return_mode": "last",
            "pipeline": {
                "start": "wait_input",
                "max_steps": 100,
                "nodes": nodes,
            }
        }
        return config

    def sample_mutation_operation(self) -> str:
        """随机选择一种变异操作"""
        operations = [
            "add_node",
            "remove_node",
            "change_edge_target",
            "change_node_type",
            "add_edge",
            "swap_nodes",
        ]
        return random.choice(operations)

    def get_insertable_node_types(self) -> List[str]:
        """获取可插入到图中的节点类型（排除循环和子流程等复杂类型）"""
        simple_types = ["推理", "处理工具", "处理文字", "执行工具", "llm_call"]
        return [t for t in simple_types if t in self.allowed_node_types]
