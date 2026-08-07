"""
种群管理：管理 PAS 的种群生命周期。

功能：
- 种群初始化（从现有 harness 或随机生成）
- 适应度排序
- 精英保留
- 多样性维护（避免种群坍缩）
"""

import json
import copy
import random
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .search_space import SearchSpace
from .dag_validator import validate_pipeline


class Individual:
    """种群中的个体：一个 pipeline 配置及其适应度。"""

    def __init__(self, config: Dict, fitness: float = 0.0, generation: int = 0):
        self.config = config
        self.fitness = fitness
        self.generation = generation
        self.eval_history: List[float] = []
        self.parent_ids: List[str] = []
        self.mutation_log: List[str] = []

    @property
    def id(self) -> str:
        """基于配置内容的唯一标识"""
        content = json.dumps(self.config.get("pipeline", {}).get("nodes", {}), sort_keys=True)
        return hashlib.md5(content.encode()).hexdigest()[:8]

    @property
    def name(self) -> str:
        return self.config.get("name", f"individual_{self.id}")

    @property
    def num_nodes(self) -> int:
        return len(self.config.get("pipeline", {}).get("nodes", {}))

    @property
    def num_edges(self) -> int:
        total = 0
        for node in self.config.get("pipeline", {}).get("nodes", {}).values():
            total += len(node.get("edges", []))
        return total

    def structural_signature(self) -> str:
        """生成结构签名用于多样性比较"""
        nodes = self.config.get("pipeline", {}).get("nodes", {})
        ops = sorted([n.get("op", "") for n in nodes.values()])
        return "|".join(ops)

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "config": self.config,
            "fitness": self.fitness,
            "generation": self.generation,
            "eval_history": self.eval_history,
            "parent_ids": self.parent_ids,
            "mutation_log": self.mutation_log,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "Individual":
        ind = cls(
            config=data["config"],
            fitness=data.get("fitness", 0.0),
            generation=data.get("generation", 0),
        )
        ind.eval_history = data.get("eval_history", [])
        ind.parent_ids = data.get("parent_ids", [])
        ind.mutation_log = data.get("mutation_log", [])
        return ind


class Population:
    """种群管理器。"""

    def __init__(self, size: int = 10, elite_ratio: float = 0.2,
                 diversity_threshold: float = 0.3):
        self.max_size = size
        self.elite_ratio = elite_ratio
        self.diversity_threshold = diversity_threshold
        self.individuals: List[Individual] = []
        self.generation = 0
        self.history: List[Dict] = []  # 每代统计
        self.search_space = SearchSpace()

    def initialize_from_harnesses(self, harness_dir: str) -> int:
        """从现有 harness 模板初始化种群。

        Returns:
            加载的个体数量
        """
        harness_path = Path(harness_dir)
        loaded = 0

        if not harness_path.exists():
            return 0

        for config_file in harness_path.glob("*/config.json"):
            try:
                config = json.loads(config_file.read_text(encoding="utf-8"))
                # 只加载有 pipeline 的配置
                if "pipeline" in config and "nodes" in config.get("pipeline", {}):
                    valid, _ = validate_pipeline(config)
                    if valid:
                        ind = Individual(config=config, generation=0)
                        self.individuals.append(ind)
                        loaded += 1
            except (json.JSONDecodeError, IOError):
                continue

        return loaded

    def initialize_random(self, count: int, num_agents: int = 1):
        """随机初始化种群"""
        for _ in range(count):
            config = self.search_space.sample_random_pipeline(num_agents=num_agents)
            valid, msg = validate_pipeline(config)
            if valid:
                ind = Individual(config=config, generation=0)
                self.individuals.append(ind)

    def fill_to_size(self, num_agents: int = 1):
        """补充种群至最大规模"""
        attempts = 0
        while len(self.individuals) < self.max_size and attempts < self.max_size * 3:
            config = self.search_space.sample_random_pipeline(num_agents=num_agents)
            valid, _ = validate_pipeline(config)
            if valid:
                ind = Individual(config=config, generation=self.generation)
                self.individuals.append(ind)
            attempts += 1

    def sort_by_fitness(self):
        """按适应度降序排列"""
        self.individuals.sort(key=lambda x: x.fitness, reverse=True)

    def get_elites(self) -> List[Individual]:
        """获取精英个体"""
        self.sort_by_fitness()
        elite_count = max(1, int(len(self.individuals) * self.elite_ratio))
        return self.individuals[:elite_count]

    def select_parents(self, count: int = 2) -> List[Individual]:
        """锦标赛选择"""
        if len(self.individuals) < count:
            return list(self.individuals)

        parents = []
        for _ in range(count):
            # 锦标赛大小为 3
            tournament_size = min(3, len(self.individuals))
            contestants = random.sample(self.individuals, tournament_size)
            winner = max(contestants, key=lambda x: x.fitness)
            parents.append(winner)
        return parents

    def add_individual(self, individual: Individual) -> bool:
        """添加新个体，检查多样性。

        Returns:
            是否成功添加
        """
        # 检查是否与现有个体过于相似
        new_sig = individual.structural_signature()
        for existing in self.individuals:
            if existing.structural_signature() == new_sig:
                # 结构完全相同，只保留适应度更高的
                if individual.fitness > existing.fitness:
                    self.individuals.remove(existing)
                    self.individuals.append(individual)
                    return True
                return False

        self.individuals.append(individual)
        return True

    def survive(self):
        """生存选择：保留种群到最大规模。

        策略：精英保留 + 多样性维护
        """
        if len(self.individuals) <= self.max_size:
            return

        self.sort_by_fitness()

        # 精英保留
        elite_count = max(1, int(self.max_size * self.elite_ratio))
        elites = self.individuals[:elite_count]

        # 从剩余中按多样性选择
        remaining = self.individuals[elite_count:]
        survivors = list(elites)
        used_signatures = {ind.structural_signature() for ind in elites}

        # 优先选择不同结构的个体
        for ind in remaining:
            if len(survivors) >= self.max_size:
                break
            sig = ind.structural_signature()
            if sig not in used_signatures:
                survivors.append(ind)
                used_signatures.add(sig)

        # 如果还不够，按适应度填充
        for ind in remaining:
            if len(survivors) >= self.max_size:
                break
            if ind not in survivors:
                survivors.append(ind)

        self.individuals = survivors[:self.max_size]

    def advance_generation(self):
        """推进到下一代，记录统计信息"""
        self.generation += 1
        stats = self.get_stats()
        self.history.append(stats)

    def get_stats(self) -> Dict:
        """获取当前种群统计"""
        if not self.individuals:
            return {"generation": self.generation, "size": 0}

        fitnesses = [ind.fitness for ind in self.individuals]
        signatures = {ind.structural_signature() for ind in self.individuals}

        return {
            "generation": self.generation,
            "size": len(self.individuals),
            "best_fitness": max(fitnesses),
            "avg_fitness": sum(fitnesses) / len(fitnesses),
            "worst_fitness": min(fitnesses),
            "diversity": len(signatures) / len(self.individuals),
            "best_individual": self.individuals[0].name if self.individuals else None,
        }

    def get_best(self) -> Optional[Individual]:
        """获取最优个体"""
        if not self.individuals:
            return None
        self.sort_by_fitness()
        return self.individuals[0]

    def get_population(self) -> List[Dict]:
        """返回种群数据"""
        return [ind.to_dict() for ind in self.individuals]

    def save(self, filepath: str):
        """保存种群到文件"""
        data = {
            "generation": self.generation,
            "max_size": self.max_size,
            "individuals": [ind.to_dict() for ind in self.individuals],
            "history": self.history,
        }
        Path(filepath).write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def load(self, filepath: str):
        """从文件加载种群"""
        data = json.loads(Path(filepath).read_text(encoding="utf-8"))
        self.generation = data.get("generation", 0)
        self.max_size = data.get("max_size", self.max_size)
        self.individuals = [Individual.from_dict(d) for d in data.get("individuals", [])]
        self.history = data.get("history", [])
