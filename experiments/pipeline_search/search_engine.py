"""
Pipeline Architecture Search (PAS) — 核心搜索引擎。

类比 NAS (Neural Architecture Search)，PAS 让 LLM 自动搜索最优的 Agent DAG 拓扑。

搜索策略：
1. Mutation-based: 从现有 harness 出发，LLM 提出结构变异
2. Generation-based: 给定任务描述，LLM 从零生成 DAG
3. Crossover: 组合两个 harness 的优势
"""

import json
import copy
import random
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

from .search_space import SearchSpace, NODE_TYPES
from .dag_validator import DAGValidator, validate_pipeline
from .population import Population, Individual


# ─── LLM 调用 ────────────────────────────────────────────────────────────────────

LLM_API_URL = "http://[fdbd:dc05:10:10a::27]:9638/v1/chat/completions"
LLM_MODEL = "Qwen3-8B-yangyuan"


def _llm_call(prompt: str, max_tokens: int = 4096, temperature: float = 0.7) -> str:
    """调用 LLM API"""
    try:
        resp = requests.post(
            LLM_API_URL,
            json={
                "model": LLM_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            timeout=120,
        )
        content = resp.json()["choices"][0]["message"].get("content", "")
        # 去除 think 标签
        if "</think>" in content:
            content = content.split("</think>")[-1].strip()
        elif "<think>" in content:
            content = ""
        return content
    except Exception as e:
        print(f"[PAS] LLM call failed: {e}")
        return ""


def _extract_json(text: str) -> Optional[Dict]:
    """从 LLM 输出中提取 JSON"""
    # 尝试找到 JSON 块
    import re
    # 尝试 ```json ... ``` 格式
    match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if match:
        text = match.group(1)

    # 尝试直接解析
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 尝试找到第一个 { 和最后一个 }
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    return None


# ─── 搜索引擎 ────────────────────────────────────────────────────────────────────

class PipelineArchitectureSearch:
    """
    Pipeline Architecture Search (PAS) — 自动搜索最优 Agent DAG 拓扑。

    搜索策略：
    1. Mutation-based: 从现有 harness 出发，LLM 提出结构变异
    2. Generation-based: 给定任务描述，LLM 从零生成 DAG
    3. Crossover: 组合两个 harness 的优势
    """

    def __init__(self, search_config: Dict):
        """
        search_config 包含：
        - search_strategy: "mutation" | "generation" | "crossover" | "hybrid"
        - population_size: 种群大小
        - max_generations: 最大代数
        - eval_tasks: 评估任务列表
        - mutation_rate: 变异率
        - crossover_rate: 交叉率
        - harness_dir: harness 模板目录
        - output_dir: 输出目录
        """
        self.config = search_config
        self.strategy = search_config.get("search_strategy", "mutation")
        self.population_size = search_config.get("population_size", 10)
        self.max_generations = search_config.get("max_generations", 5)
        self.eval_tasks = search_config.get("eval_tasks", [])
        self.mutation_rate = search_config.get("mutation_rate", 0.7)
        self.crossover_rate = search_config.get("crossover_rate", 0.3)
        self.harness_dir = search_config.get("harness_dir", "")
        self.output_dir = search_config.get("output_dir", "./pas_output")

        self.search_space = SearchSpace(search_config.get("constraints"))
        self.population = Population(
            size=self.population_size,
            elite_ratio=search_config.get("elite_ratio", 0.2),
        )
        self.validator = DAGValidator()
        self.search_trace: List[Dict] = []

    def mutate_pipeline(self, harness_config: Dict) -> Dict:
        """用 LLM 对现有 DAG 提出结构变异：
        - 添加节点
        - 删除节点
        - 修改连接
        - 更改节点类型
        - 修改条件边
        """
        pipeline_json = json.dumps(harness_config["pipeline"], ensure_ascii=False, indent=2)
        node_types_desc = "\n".join(
            f"  - {k}: {v['description']}" for k, v in NODE_TYPES.items()
        )

        prompt = f"""你是一个 Agent Pipeline 架构师。给你一个现有的 pipeline DAG 配置，请对它进行一次结构变异以提升性能。

可用节点类型：
{node_types_desc}

可用条件边：input, has_tool_calls, no_tool_calls, has_text, default, expr:..., loop_done, loop_continue

当前 pipeline 配置：
```json
{pipeline_json}
```

请选择以下一种变异操作并执行：
1. 添加节点 - 在适当位置插入新节点
2. 删除节点 - 移除不必要的节点（重连边）
3. 修改连接 - 改变边的目标
4. 更改节点类型 - 更换某个节点的操作类型
5. 修改条件边 - 调整触发条件

要求：
- 变异后的 pipeline 必须保持合法（所有节点可达，边目标存在）
- 必须有 "start" 字段指定起始节点
- 每个节点必须有 "op" 和 "edges" 字段
- 推理节点必须有 "agent" 字段

请直接输出完整的变异后 pipeline 配置（JSON 格式），包含完整的 harness config：
```json
{{完整配置}}
```"""

        response = _llm_call(prompt, max_tokens=4096, temperature=0.8)
        result = _extract_json(response)

        if result and "pipeline" in result:
            return result

        # 如果 LLM 只返回了 pipeline 部分
        if result and "nodes" in result:
            mutated = copy.deepcopy(harness_config)
            mutated["pipeline"] = result
            mutated["name"] = harness_config.get("name", "unknown") + "_mutated"
            return mutated

        # 回退：使用程序化变异
        return self._programmatic_mutate(harness_config)

    def generate_pipeline(self, task_description: str) -> Dict:
        """给定任务描述，LLM 从零生成完整的 DAG 配置"""
        node_types_desc = "\n".join(
            f"  - {k}: {v['description']}, 出边条件: {v['valid_out_conditions']}"
            for k, v in NODE_TYPES.items()
        )

        prompt = f"""你是一个 Agent Pipeline 架构师。根据任务描述，设计一个最优的 Agent DAG 拓扑。

任务描述：{task_description}

可用节点类型：
{node_types_desc}

可用条件边类型：input, has_tool_calls, no_tool_calls, has_text, default, expr:..., loop_done, loop_continue

配置格式示例（简单 ReAct 循环）：
```json
{{
    "name": "my_pipeline",
    "description": "描述",
    "slots": {{
        "agent": {{"description": "主要 agent", "required": true}}
    }},
    "return_mode": "last",
    "pipeline": {{
        "start": "wait_input",
        "max_steps": 100,
        "nodes": {{
            "wait_input": {{
                "op": "等待输入",
                "edges": [{{"condition": "input", "to": "infer"}}]
            }},
            "infer": {{
                "op": "推理",
                "agent": "agent",
                "edges": [
                    {{"condition": "has_tool_calls", "to": "exec_tools"}},
                    {{"condition": "has_text", "to": "wait_input"}}
                ]
            }},
            "exec_tools": {{
                "op": "执行工具",
                "agent": "agent",
                "edges": [{{"condition": "default", "to": "infer"}}]
            }}
        }}
    }}
}}
```

要求：
1. 根据任务类型设计合适的 pipeline 结构
2. 所有节点必须从 start 可达
3. 推理节点必须指定 agent（引用 slots 中定义的）
4. 确保边条件与节点类型匹配

请输出完整的 JSON 配置：
```json
{{你的设计}}
```"""

        response = _llm_call(prompt, max_tokens=4096, temperature=0.9)
        result = _extract_json(response)

        if result and "pipeline" in result:
            # 确保有名称
            if "name" not in result:
                result["name"] = f"generated_{int(time.time()) % 10000}"
            return result

        # 回退：返回基本 ReAct 结构
        return self.search_space.sample_random_pipeline()

    def crossover_pipelines(self, parent1: Dict, parent2: Dict) -> Dict:
        """交叉两个 pipeline 产生子代"""
        p1_json = json.dumps(parent1.get("pipeline", {}), ensure_ascii=False, indent=2)
        p2_json = json.dumps(parent2.get("pipeline", {}), ensure_ascii=False, indent=2)

        prompt = f"""你是一个 Agent Pipeline 架构师。请将两个 pipeline 的优势结合，产生一个新的子代 pipeline。

父代 1 (名称: {parent1.get('name', 'parent1')})：
```json
{p1_json}
```

父代 2 (名称: {parent2.get('name', 'parent2')})：
```json
{p2_json}
```

要求：
1. 组合两个父代的结构优势（如父代1的守卫机制 + 父代2的多轮推理）
2. 生成的子代必须是合法的 pipeline（所有节点可达，边目标存在）
3. 保持结构简洁，不要简单拼接
4. 确保有 slots 定义所有引用的 agent

请输出完整的子代 harness 配置（JSON）：
```json
{{子代配置}}
```"""

        response = _llm_call(prompt, max_tokens=4096, temperature=0.8)
        result = _extract_json(response)

        if result and "pipeline" in result:
            if "name" not in result:
                result["name"] = f"crossover_{int(time.time()) % 10000}"
            return result

        # 回退：程序化交叉
        return self._programmatic_crossover(parent1, parent2)

    def validate_pipeline(self, config: Dict) -> Tuple[bool, str]:
        """验证 DAG 配置的合法性"""
        return validate_pipeline(config)

    def evaluate_pipeline(self, config: Dict, tasks: List[str]) -> float:
        """在一组任务上评估 pipeline 的性能。

        评估维度：
        1. 结构合理性（验证通过 +0.3）
        2. 效率（节点数适中 +0.2）
        3. 鲁棒性（有错误处理路径 +0.2）
        4. LLM 评估（结构质量 +0.3）
        """
        score = 0.0

        # 1. 结构合理性
        valid, msg = self.validate_pipeline(config)
        if not valid:
            return 0.0
        score += 0.3

        pipeline = config.get("pipeline", {})
        nodes = pipeline.get("nodes", {})

        # 2. 效率 - 节点数适中（3-10 最优）
        num_nodes = len(nodes)
        if 3 <= num_nodes <= 10:
            score += 0.2
        elif num_nodes < 3:
            score += 0.1
        else:
            score += max(0.0, 0.2 - (num_nodes - 10) * 0.02)

        # 3. 鲁棒性 - 检查是否有 default 兜底
        has_default_paths = 0
        total_nodes_with_edges = 0
        for node in nodes.values():
            edges = node.get("edges", [])
            if edges:
                total_nodes_with_edges += 1
                conditions = [e.get("condition") for e in edges]
                if "default" in conditions or "has_text" in conditions:
                    has_default_paths += 1

        if total_nodes_with_edges > 0:
            robustness = has_default_paths / total_nodes_with_edges
            score += 0.2 * robustness

        # 4. LLM 评估结构质量
        if tasks:
            llm_score = self._llm_evaluate_structure(config, tasks)
            score += 0.3 * llm_score
        else:
            score += 0.15  # 无任务时给中间分

        return min(1.0, score)

    def run_search(self) -> Dict:
        """运行完整搜索过程，返回最优 pipeline 和搜索轨迹"""
        print(f"[PAS] Starting search: strategy={self.strategy}, "
              f"pop_size={self.population_size}, generations={self.max_generations}")

        # 初始化种群
        self._initialize_population()
        print(f"[PAS] Population initialized: {len(self.population.individuals)} individuals")

        # 评估初始种群
        self._evaluate_population()

        # 进化循环
        for gen in range(self.max_generations):
            print(f"\n[PAS] === Generation {gen + 1}/{self.max_generations} ===")

            # 生成后代
            offspring = self._generate_offspring()
            print(f"[PAS] Generated {len(offspring)} offspring")

            # 评估后代
            for ind in offspring:
                ind.fitness = self.evaluate_pipeline(ind.config, self.eval_tasks)
                ind.eval_history.append(ind.fitness)

            # 合并种群
            for ind in offspring:
                self.population.add_individual(ind)

            # 生存选择
            self.population.survive()
            self.population.advance_generation()

            # 记录轨迹
            stats = self.population.get_stats()
            self.search_trace.append(stats)
            print(f"[PAS] Gen {gen + 1} stats: best={stats['best_fitness']:.3f}, "
                  f"avg={stats['avg_fitness']:.3f}, diversity={stats['diversity']:.2f}")

        # 返回结果
        best = self.population.get_best()
        result = {
            "best_pipeline": best.config if best else None,
            "best_fitness": best.fitness if best else 0.0,
            "search_trace": self.search_trace,
            "population": self.population.get_population(),
            "config": self.config,
        }

        # 保存结果
        output_dir = Path(self.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        result_path = output_dir / "search_result.json"
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(f"\n[PAS] Search complete. Best fitness: {result['best_fitness']:.3f}")
        print(f"[PAS] Results saved to: {result_path}")

        return result

    def get_population(self) -> List[Dict]:
        """返回当前种群"""
        return self.population.get_population()

    def export_best(self, output_dir: str):
        """导出最优 pipeline 为 harness 目录"""
        best = self.population.get_best()
        if not best:
            print("[PAS] No individuals in population")
            return

        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        config = best.config
        config_path = out_path / "config.json"
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2))
        print(f"[PAS] Exported best pipeline to: {config_path}")
        print(f"[PAS] Fitness: {best.fitness:.3f}, Nodes: {best.num_nodes}, Edges: {best.num_edges}")

    # ─── 内部方法 ─────────────────────────────────────────────────────────────

    def _initialize_population(self):
        """初始化种群"""
        if self.harness_dir:
            loaded = self.population.initialize_from_harnesses(self.harness_dir)
            print(f"[PAS] Loaded {loaded} harnesses from {self.harness_dir}")

        # 补充到种群大小
        self.population.fill_to_size()

    def _evaluate_population(self):
        """评估整个种群"""
        for ind in self.population.individuals:
            if ind.fitness == 0.0:
                ind.fitness = self.evaluate_pipeline(ind.config, self.eval_tasks)
                ind.eval_history.append(ind.fitness)
        self.population.sort_by_fitness()

    def _generate_offspring(self) -> List[Individual]:
        """根据策略生成后代"""
        offspring = []
        target_count = max(2, self.population_size // 2)

        for _ in range(target_count):
            if self.strategy == "mutation" or (self.strategy == "hybrid" and random.random() < self.mutation_rate):
                child = self._mutation_offspring()
            elif self.strategy == "generation":
                child = self._generation_offspring()
            elif self.strategy == "crossover" or (self.strategy == "hybrid" and random.random() < self.crossover_rate):
                child = self._crossover_offspring()
            else:
                child = self._mutation_offspring()

            if child:
                offspring.append(child)

        return offspring

    def _mutation_offspring(self) -> Optional[Individual]:
        """通过变异产生后代"""
        parents = self.population.select_parents(count=1)
        if not parents:
            return None

        parent = parents[0]
        mutated_config = self.mutate_pipeline(parent.config)

        valid, msg = self.validate_pipeline(mutated_config)
        if not valid:
            # 尝试程序化变异作为后备
            mutated_config = self._programmatic_mutate(parent.config)
            valid, msg = self.validate_pipeline(mutated_config)
            if not valid:
                return None

        child = Individual(
            config=mutated_config,
            generation=self.population.generation + 1,
        )
        child.parent_ids = [parent.id]
        child.mutation_log.append("llm_mutation")
        return child

    def _generation_offspring(self) -> Optional[Individual]:
        """通过生成产生后代"""
        task_desc = random.choice(self.eval_tasks) if self.eval_tasks else "通用对话和工具使用"
        config = self.generate_pipeline(task_desc)

        valid, msg = self.validate_pipeline(config)
        if not valid:
            return None

        child = Individual(
            config=config,
            generation=self.population.generation + 1,
        )
        child.mutation_log.append("llm_generation")
        return child

    def _crossover_offspring(self) -> Optional[Individual]:
        """通过交叉产生后代"""
        parents = self.population.select_parents(count=2)
        if len(parents) < 2:
            return self._mutation_offspring()

        child_config = self.crossover_pipelines(parents[0].config, parents[1].config)

        valid, msg = self.validate_pipeline(child_config)
        if not valid:
            return None

        child = Individual(
            config=child_config,
            generation=self.population.generation + 1,
        )
        child.parent_ids = [parents[0].id, parents[1].id]
        child.mutation_log.append("llm_crossover")
        return child

    def _programmatic_mutate(self, config: Dict) -> Dict:
        """程序化变异（不依赖 LLM 的后备方案）"""
        mutated = copy.deepcopy(config)
        pipeline = mutated.get("pipeline", {})
        nodes = pipeline.get("nodes", {})

        if not nodes:
            return mutated

        operation = self.search_space.sample_mutation_operation()
        node_ids = list(nodes.keys())

        if operation == "add_node" and len(nodes) < self.search_space.max_nodes:
            # 在推理和执行之间插入审查节点
            new_id = self.search_space.random_node_id(node_ids)
            agent_slots = list(config.get("slots", {}).keys())
            agent = agent_slots[0] if agent_slots else "agent"

            nodes[new_id] = {
                "op": "处理工具",
                "agent": agent,
                "edges": [{"condition": "default", "to": random.choice(node_ids)}],
            }
            # 让某个已有节点指向新节点
            source = random.choice(node_ids)
            if nodes[source].get("edges"):
                edge_idx = random.randint(0, len(nodes[source]["edges"]) - 1)
                nodes[source]["edges"][edge_idx]["to"] = new_id

        elif operation == "remove_node" and len(nodes) > self.search_space.min_nodes:
            # 删除非起始节点
            start = pipeline.get("start", "")
            removable = [nid for nid in node_ids if nid != start]
            if removable:
                to_remove = random.choice(removable)
                # 重连指向该节点的边
                removed_edges = nodes[to_remove].get("edges", [])
                fallback_target = removed_edges[0]["to"] if removed_edges else start
                for nid, node in nodes.items():
                    for edge in node.get("edges", []):
                        if edge["to"] == to_remove:
                            edge["to"] = fallback_target
                del nodes[to_remove]

        elif operation == "change_edge_target":
            source = random.choice(node_ids)
            edges = nodes[source].get("edges", [])
            if edges:
                edge = random.choice(edges)
                targets = [nid for nid in node_ids if nid != source]
                if targets:
                    edge["to"] = random.choice(targets)

        elif operation == "swap_nodes":
            if len(node_ids) >= 2:
                n1, n2 = random.sample(node_ids, 2)
                # 只交换 op 和 agent
                op1, op2 = nodes[n1].get("op"), nodes[n2].get("op")
                if op1 == op2:
                    # 同类型节点交换 agent
                    a1, a2 = nodes[n1].get("agent"), nodes[n2].get("agent")
                    if a1:
                        nodes[n2]["agent"] = a1
                    if a2:
                        nodes[n1]["agent"] = a2

        mutated["name"] = config.get("name", "unknown") + "_mut"
        return mutated

    def _programmatic_crossover(self, parent1: Dict, parent2: Dict) -> Dict:
        """程序化交叉（不依赖 LLM 的后备方案）"""
        # 基于 parent1 的结构，替换部分节点为 parent2 的
        child = copy.deepcopy(parent1)
        p2_nodes = parent2.get("pipeline", {}).get("nodes", {})

        if not p2_nodes:
            return child

        child_nodes = child.get("pipeline", {}).get("nodes", {})
        # 合并 slots
        p2_slots = parent2.get("slots", {})
        child_slots = child.get("slots", {})
        child_slots.update(p2_slots)
        child["slots"] = child_slots

        # 从 parent2 取一个节点尝试插入
        p2_node_ids = list(p2_nodes.keys())
        candidate = random.choice(p2_node_ids)
        candidate_node = copy.deepcopy(p2_nodes[candidate])

        # 修正边引用
        child_node_ids = list(child_nodes.keys())
        for edge in candidate_node.get("edges", []):
            if edge["to"] not in child_node_ids:
                edge["to"] = random.choice(child_node_ids) if child_node_ids else None

        # 插入
        new_id = candidate if candidate not in child_nodes else f"{candidate}_x"
        child_nodes[new_id] = candidate_node

        child["name"] = f"cross_{parent1.get('name', 'p1')}_{parent2.get('name', 'p2')}"
        return child

    def _llm_evaluate_structure(self, config: Dict, tasks: List[str]) -> float:
        """用 LLM 评估 pipeline 结构质量"""
        pipeline_json = json.dumps(config.get("pipeline", {}), ensure_ascii=False, indent=2)
        tasks_str = "\n".join(f"  - {t}" for t in tasks[:3])

        prompt = f"""评估以下 Agent Pipeline 的结构质量（0.0-1.0）。

Pipeline 配置：
```json
{pipeline_json}
```

目标任务类型：
{tasks_str}

评估标准：
1. 结构是否适合目标任务
2. 是否有合理的错误处理和兜底路径
3. 效率（是否有不必要的节点）
4. 是否支持工具调用和文本响应的分流

请直接输出一个 0.0 到 1.0 之间的数字，不要任何解释："""

        response = _llm_call(prompt, max_tokens=32, temperature=0.3)
        try:
            score = float(response.strip())
            return max(0.0, min(1.0, score))
        except (ValueError, TypeError):
            return 0.5
