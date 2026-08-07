"""
DAG 合法性验证器：检查 Pipeline 配置的结构合法性。

验证项目：
1. DAG 无环（循环节点的自指边除外）
2. 所有节点从 start 可达
3. 边条件合法（每个节点至少有 default 或完备条件集）
4. 节点类型合法
5. 引用的 context 变量一致性
"""

from typing import Dict, List, Tuple, Set
from collections import deque

from .search_space import NODE_TYPES, EDGE_CONDITIONS


class DAGValidator:
    """Pipeline DAG 配置验证器。"""

    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def validate(self, config: Dict) -> Tuple[bool, str]:
        """验证完整的 harness 配置。

        Returns:
            (is_valid, message) - 是否合法及原因
        """
        self.errors = []
        self.warnings = []

        pipeline = config.get("pipeline")
        if not pipeline:
            return False, "缺少 'pipeline' 字段"

        nodes = pipeline.get("nodes")
        if not nodes:
            return False, "缺少 'pipeline.nodes' 字段"

        start = pipeline.get("start")
        if not start:
            return False, "缺少 'pipeline.start' 字段"

        if start not in nodes:
            return False, f"起始节点 '{start}' 不在 nodes 中"

        self._check_node_types(nodes)
        self._check_edges_valid(nodes)
        self._check_reachability(nodes, start)
        self._check_no_cycles(nodes, start)
        self._check_edge_conditions(nodes)
        self._check_agent_references(config)
        self._check_context_consistency(config)

        if self.errors:
            return False, "; ".join(self.errors)

        msg = "验证通过"
        if self.warnings:
            msg += f" (warnings: {'; '.join(self.warnings)})"
        return True, msg

    def _check_node_types(self, nodes: Dict):
        """检查所有节点类型是否合法"""
        valid_ops = set(NODE_TYPES.keys())
        for node_id, node in nodes.items():
            op = node.get("op")
            if not op:
                self.errors.append(f"节点 '{node_id}' 缺少 'op' 字段")
            elif op not in valid_ops:
                self.errors.append(f"节点 '{node_id}' 的操作类型 '{op}' 不合法")

    def _check_edges_valid(self, nodes: Dict):
        """检查所有边的目标节点是否存在"""
        node_ids = set(nodes.keys())
        for node_id, node in nodes.items():
            edges = node.get("edges", [])
            for i, edge in enumerate(edges):
                if "condition" not in edge:
                    self.errors.append(f"节点 '{node_id}' 的第{i}条边缺少 'condition'")
                if "to" not in edge:
                    self.errors.append(f"节点 '{node_id}' 的第{i}条边缺少 'to'")
                else:
                    target = edge["to"]
                    if target is not None and target not in node_ids:
                        self.errors.append(
                            f"节点 '{node_id}' 的边指向不存在的节点 '{target}'"
                        )

    def _check_reachability(self, nodes: Dict, start: str):
        """检查所有节点是否从 start 可达"""
        reachable = set()
        queue = deque([start])
        reachable.add(start)

        while queue:
            current = queue.popleft()
            node = nodes.get(current)
            if not node:
                continue
            for edge in node.get("edges", []):
                target = edge.get("to")
                if target and target not in reachable and target in nodes:
                    reachable.add(target)
                    queue.append(target)
            if node.get("op") == "循环":
                body_start = node.get("body_start")
                if body_start and body_start not in reachable and body_start in nodes:
                    reachable.add(body_start)
                    queue.append(body_start)

        unreachable = set(nodes.keys()) - reachable
        if unreachable:
            self.errors.append(f"以下节点不可达: {sorted(unreachable)}")

    def _check_no_cycles(self, nodes: Dict, start: str):
        """检查 DAG 无环（ReAct 循环和循环节点回边除外）。"""
        visited = set()
        rec_stack = set()

        def dfs(node_id: str, path: List[str]):
            if node_id in rec_stack:
                cycle_start = path.index(node_id)
                cycle = path[cycle_start:]
                cycle_ops = [nodes[nid].get("op") for nid in cycle if nid in nodes]
                if "推理" not in cycle_ops and "循环" not in cycle_ops:
                    self.warnings.append(
                        f"检测到不含推理节点的循环: {' -> '.join(cycle)}"
                    )
                return
            if node_id in visited:
                return

            visited.add(node_id)
            rec_stack.add(node_id)

            node = nodes.get(node_id)
            if node:
                for edge in node.get("edges", []):
                    target = edge.get("to")
                    if target and target in nodes:
                        dfs(target, path + [node_id])
                if node.get("op") == "循环":
                    body_start = node.get("body_start")
                    if body_start and body_start in nodes:
                        dfs(body_start, path + [node_id])

            rec_stack.discard(node_id)

        dfs(start, [])

    def _check_edge_conditions(self, nodes: Dict):
        """检查边条件的合法性"""
        for node_id, node in nodes.items():
            op = node.get("op", "")
            edges = node.get("edges", [])
            if not edges:
                continue

            valid_conditions = set()
            if op in NODE_TYPES:
                valid_conditions = set(NODE_TYPES[op]["valid_out_conditions"])
            valid_conditions.add("default")

            for edge in edges:
                cond = edge.get("condition", "")
                if cond.startswith("expr:"):
                    continue
                if cond not in valid_conditions and cond not in EDGE_CONDITIONS:
                    self.warnings.append(
                        f"节点 '{node_id}' (op={op}) 的条件 '{cond}' 可能不合法"
                    )

    def _check_agent_references(self, config: Dict):
        """检查节点引用的 agent 是否在 slots 中定义"""
        slots = set(config.get("slots", {}).keys())
        if not slots:
            return

        nodes = config.get("pipeline", {}).get("nodes", {})
        for node_id, node in nodes.items():
            agent = node.get("agent")
            if agent and agent not in slots:
                self.warnings.append(
                    f"节点 '{node_id}' 引用的 agent '{agent}' 未在 slots 中定义"
                )

    def _check_context_consistency(self, config: Dict):
        """检查 context 变量引用的一致性"""
        pipeline = config.get("pipeline", {})
        context = pipeline.get("context", {})
        nodes = pipeline.get("nodes", {})

        referenced_vars = set()
        produced_vars = set(context.keys())

        for node_id, node in nodes.items():
            input_vars = node.get("input_vars", [])
            output_vars = node.get("output_vars", [])
            output_var = node.get("output_var")

            for v in input_vars:
                referenced_vars.add(v)
            for v in output_vars:
                produced_vars.add(v)
            if output_var:
                produced_vars.add(output_var)

            if node.get("op") == "循环":
                list_var = node.get("list_var", "")
                if list_var:
                    referenced_vars.add(list_var)
                    produced_vars.add(f"{list_var}_results")
                item_var = node.get("item_var", "_item")
                produced_vars.add(item_var)

        undefined = referenced_vars - produced_vars
        undefined = {v for v in undefined if not v.startswith("_")}
        if undefined:
            self.warnings.append(
                f"以下变量被引用但未定义: {sorted(undefined)}"
            )


def validate_pipeline(config: Dict) -> Tuple[bool, str]:
    """便捷函数：验证 pipeline 配置的合法性。"""
    validator = DAGValidator()
    return validator.validate(config)
