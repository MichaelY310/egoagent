"""
持续学习实验模块 (Lifelong Learning Experiments)

实验：
1. 原则库增长曲线 + 修剪效果
2. 有/无冲突检测的对比
3. 跨域迁移矩阵
4. 有/无经验回放的遗忘率对比
"""

import json
import sys
import time
import uuid
import argparse
import random
from pathlib import Path
from typing import Dict, List, Any

# 确保项目根目录在 path 中
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from self_evolution.engine import (
    _load_json,
    _save_json,
    _llm_call,
    _extract_json_from_response,
    PRINCIPLES_FILE,
    DATA_DIR,
    distill_principles,
    update_scores,
)
from self_evolution.principle_manager import PrincipleManager
from self_evolution.predictive_distill import PredictiveDistiller
from self_evolution.experience_buffer import ExperienceBuffer, Experience


# ============================================================
# 实验工具
# ============================================================

RESULTS_DIR = Path(__file__).resolve().parent / "results"


def _ensure_results_dir():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def _save_result(experiment_name: str, result: Dict):
    """保存实验结果"""
    _ensure_results_dir()
    filename = f"{experiment_name}_{time.strftime('%Y%m%d_%H%M%S')}.json"
    result_path = RESULTS_DIR / filename
    _save_json(result_path, result)
    print(f"  结果已保存: {result_path}")
    return result_path


def _generate_synthetic_principles(n: int, domain: str = "general") -> List[Dict]:
    """生成合成原则用于实验"""
    prompt = f"""Generate {n} diverse strategic principles for an AI agent working on {domain} tasks.
Mix guiding and cautionary principles.

Return a JSON array:
[{{"type": "guiding"|"cautionary", "description": "principle text"}}]

Generate exactly {n} principles. Output ONLY valid JSON array:"""

    response = _llm_call(
        [{"role": "user", "content": prompt}],
        max_tokens=2048,
        temperature=0.8,
    )

    raw = _extract_json_from_response(response)
    if isinstance(raw, list):
        principles = []
        for p in raw[:n]:
            if isinstance(p, dict) and "description" in p:
                principles.append({
                    "id": str(uuid.uuid4())[:8],
                    "type": p.get("type", "guiding"),
                    "description": p["description"],
                    "score": random.uniform(0.3, 0.9),
                    "usage_count": random.randint(0, 10),
                    "success_count": random.randint(0, 5),
                    "context_tags": [domain] if domain != "general" else [],
                    "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                })
        return principles

    # 回退：生成模板原则
    templates = [
        ("guiding", f"When working on {domain} tasks, always verify intermediate results."),
        ("cautionary", f"Avoid making assumptions about {domain} inputs without validation."),
        ("guiding", f"Decompose complex {domain} problems into smaller sub-tasks."),
        ("cautionary", f"Do not skip error handling in {domain} operations."),
        ("guiding", f"Prioritize clarity over cleverness in {domain} solutions."),
    ]
    principles = []
    for i in range(n):
        t = templates[i % len(templates)]
        principles.append({
            "id": str(uuid.uuid4())[:8],
            "type": t[0],
            "description": t[1] + f" (variant {i})",
            "score": random.uniform(0.3, 0.9),
            "usage_count": random.randint(0, 10),
            "success_count": random.randint(0, 5),
            "context_tags": [domain] if domain != "general" else [],
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
    return principles


def _generate_synthetic_experiences(n: int, domain: str = "general") -> List[Experience]:
    """生成合成经验用于实验"""
    experiences = []
    outcomes = ["success", "failure", "partial"]
    for i in range(n):
        outcome = random.choices(outcomes, weights=[0.4, 0.35, 0.25])[0]
        score = random.uniform(0.1, 0.4) if outcome == "failure" else (
            random.uniform(0.7, 1.0) if outcome == "success" else random.uniform(0.4, 0.7)
        )
        exp = Experience(
            trajectory_summary=f"Attempted {domain} task {i+1}. {'Succeeded' if outcome == 'success' else 'Had difficulties'} with the approach.",
            task_description=f"Synthetic {domain} task #{i+1}",
            outcome=outcome,
            score=score,
            domain=domain,
        )
        experiences.append(exp)
    return experiences


# ============================================================
# 实验 1: 原则库增长曲线 + 修剪效果
# ============================================================

def experiment_growth_and_pruning(max_principles: int = 30, prune_sizes: List[int] = None) -> Dict:
    """
    实验 1: 观察原则库增长过程及不同修剪策略的效果。

    设计：
    1. 逐步向库中添加原则，记录增长曲线
    2. 到达上限后，分别用三种策略修剪
    3. 对比修剪后库的质量（平均分、多样性）
    """
    print("\n" + "=" * 60)
    print("  实验 1: 原则库增长曲线 + 修剪效果")
    print("=" * 60)

    if prune_sizes is None:
        prune_sizes = [10, 15, 20]

    # 备份当前原则库
    original_principles = _load_json(PRINCIPLES_FILE)

    result = {
        "experiment": "growth_and_pruning",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "config": {"max_principles": max_principles, "prune_sizes": prune_sizes},
        "growth_curve": [],
        "pruning_results": {},
    }

    # 生成合成原则并逐步添加
    print("  [1/3] 生成合成原则...")
    synthetic = _generate_synthetic_principles(max_principles, "coding")

    growth_data = []
    test_principles = []

    for i, p in enumerate(synthetic):
        test_principles.append(p)
        # 使用 PredictiveDistiller 评估新颖度
        distiller = PredictiveDistiller(principles_file=PRINCIPLES_FILE)
        distiller.principles = list(test_principles[:-1])  # 模拟已有库
        novelty = distiller.compute_novelty(p)
        info_gain = distiller.compute_information_gain(p)

        growth_data.append({
            "step": i + 1,
            "total_principles": len(test_principles),
            "novelty_of_new": novelty,
            "info_gain_of_new": info_gain,
            "avg_score": sum(tp.get("score", 0) for tp in test_principles) / len(test_principles),
        })

    result["growth_curve"] = growth_data
    print(f"  [1/3] 增长曲线: {len(growth_data)} 步")

    # 修剪实验
    print("  [2/3] 测试修剪策略...")
    strategies = ["value_based", "cluster_based", "mdl_based"]

    for target_size in prune_sizes:
        result["pruning_results"][f"target_{target_size}"] = {}

        for strategy in strategies:
            # 重新加载完整集合
            _save_json(PRINCIPLES_FILE, list(test_principles))
            manager = PrincipleManager()

            before_count = len(manager.principles)
            before_avg_score = sum(p.get("score", 0) for p in manager.principles) / max(len(manager.principles), 1)

            removed = manager.prune(max_size=target_size, strategy=strategy)

            after_count = len(manager.principles)
            after_avg_score = sum(p.get("score", 0) for p in manager.principles) / max(len(manager.principles), 1)

            # 计算多样性（簇数量）
            clusters = manager.detect_clusters()

            result["pruning_results"][f"target_{target_size}"][strategy] = {
                "before_count": before_count,
                "after_count": after_count,
                "removed_count": len(removed),
                "before_avg_score": round(before_avg_score, 4),
                "after_avg_score": round(after_avg_score, 4),
                "num_clusters_after": len(clusters),
                "score_improvement": round(after_avg_score - before_avg_score, 4),
            }
            print(f"    策略={strategy}, 目标={target_size}: "
                  f"{before_count}->{after_count}, "
                  f"分数: {before_avg_score:.3f}->{after_avg_score:.3f}, "
                  f"簇数: {len(clusters)}")

    # 恢复原始原则库
    _save_json(PRINCIPLES_FILE, original_principles)

    print("  [3/3] 实验完成")
    _save_result("exp1_growth_pruning", result)
    return result


# ============================================================
# 实验 2: 有/无冲突检测的对比
# ============================================================

def experiment_conflict_detection() -> Dict:
    """
    实验 2: 评估冲突检测和解决对原则库质量的影响。

    设计：
    1. 在原则库中注入已知冲突对
    2. 运行冲突检测
    3. 对比解决前后的库质量
    """
    print("\n" + "=" * 60)
    print("  实验 2: 冲突检测与解决效果")
    print("=" * 60)

    # 备份
    original_principles = _load_json(PRINCIPLES_FILE)

    result = {
        "experiment": "conflict_detection",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "injected_conflicts": [],
        "detected_conflicts": [],
        "resolution_results": [],
        "quality_before": {},
        "quality_after": {},
    }

    # 注入已知冲突对
    print("  [1/4] 注入冲突原则...")
    conflict_pairs = [
        (
            {"id": "conf_a1", "type": "guiding", "description": "Always use additional tools when available to enhance task completion.", "score": 0.6, "usage_count": 3, "success_count": 2},
            {"id": "conf_b1", "type": "cautionary", "description": "Avoid using additional tools not explicitly specified in the instructions.", "score": 0.5, "usage_count": 2, "success_count": 1},
        ),
        (
            {"id": "conf_a2", "type": "guiding", "description": "Proceed quickly without excessive verification to maintain efficiency.", "score": 0.5, "usage_count": 2, "success_count": 1},
            {"id": "conf_b2", "type": "cautionary", "description": "Always verify results thoroughly before proceeding to the next step.", "score": 0.7, "usage_count": 5, "success_count": 4},
        ),
    ]

    test_principles = list(original_principles)
    for p_a, p_b in conflict_pairs:
        test_principles.append(p_a)
        test_principles.append(p_b)
        result["injected_conflicts"].append({"a": p_a["id"], "b": p_b["id"]})

    _save_json(PRINCIPLES_FILE, test_principles)

    # 计算冲突前质量
    manager_before = PrincipleManager()
    stats_before = manager_before.get_stats()
    result["quality_before"] = {
        "total_count": stats_before["total_count"],
        "avg_score": round(stats_before["avg_score"], 4),
        "num_clusters": stats_before["num_clusters"],
    }
    print(f"  [2/4] 冲突前: {stats_before['total_count']} 原则, 平均分={stats_before['avg_score']:.3f}")

    # 运行冲突检测
    print("  [3/4] 运行冲突检测...")
    manager = PrincipleManager()
    conflicts = manager.detect_conflicts()

    for p_a, p_b, score in conflicts:
        result["detected_conflicts"].append({
            "principle_a": p_a.get("id"),
            "principle_b": p_b.get("id"),
            "conflict_score": round(score, 4),
            "desc_a": p_a.get("description", "")[:80],
            "desc_b": p_b.get("description", "")[:80],
        })

    print(f"    检测到 {len(conflicts)} 对冲突")

    # 解决冲突
    print("  [4/4] 解决冲突...")
    for p_a, p_b, score in conflicts[:3]:  # 只解决前3个
        merged = manager.resolve_conflict(p_a, p_b)
        result["resolution_results"].append({
            "original_a": p_a.get("description", "")[:80],
            "original_b": p_b.get("description", "")[:80],
            "merged": merged.get("description", "")[:120],
            "conflict_score": round(score, 4),
        })

    # 计算冲突后质量
    stats_after = manager.get_stats()
    result["quality_after"] = {
        "total_count": stats_after["total_count"],
        "avg_score": round(stats_after["avg_score"], 4),
        "num_clusters": stats_after["num_clusters"],
    }
    print(f"    解决后: {stats_after['total_count']} 原则, 平均分={stats_after['avg_score']:.3f}")

    # 恢复
    _save_json(PRINCIPLES_FILE, original_principles)

    _save_result("exp2_conflict_detection", result)
    return result


# ============================================================
# 实验 3: 跨域迁移矩阵
# ============================================================

def experiment_transfer_matrix(domains: List[str] = None) -> Dict:
    """
    实验 3: 计算跨域迁移矩阵。

    设计：
    1. 为每个域生成特定原则
    2. 评估每对域之间的迁移率
    3. 构建迁移矩阵
    """
    print("\n" + "=" * 60)
    print("  实验 3: 跨域迁移矩阵")
    print("=" * 60)

    if domains is None:
        domains = ["coding", "writing", "debugging", "planning"]

    # 备份
    original_principles = _load_json(PRINCIPLES_FILE)

    result = {
        "experiment": "transfer_matrix",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "domains": domains,
        "domain_principles_count": {},
        "transfer_matrix": {},
    }

    # 为每个域生成原则
    print("  [1/3] 为每个域生成原则...")
    all_principles = []
    for domain in domains:
        principles = _generate_synthetic_principles(5, domain)
        for p in principles:
            p["context_tags"] = [domain]
        all_principles.extend(principles)
        result["domain_principles_count"][domain] = len(principles)
        print(f"    {domain}: {len(principles)} 原则")

    _save_json(PRINCIPLES_FILE, all_principles)

    # 计算迁移矩阵
    print("  [2/3] 计算迁移矩阵...")
    manager = PrincipleManager()

    matrix = {}
    for source in domains:
        matrix[source] = {}
        for target in domains:
            if source == target:
                matrix[source][target] = 1.0
            else:
                transfer_result = manager.evaluate_transfer(source, target)
                matrix[source][target] = round(transfer_result["transfer_rate"], 4)
                print(f"    {source} -> {target}: {transfer_result['transfer_rate']:.2f}")

    result["transfer_matrix"] = matrix

    # 分析
    print("  [3/3] 分析结果...")
    # 找出最佳/最差迁移对
    best_pair = ("", "", 0.0)
    worst_pair = ("", "", 1.0)
    for s in domains:
        for t in domains:
            if s == t:
                continue
            rate = matrix[s][t]
            if rate > best_pair[2]:
                best_pair = (s, t, rate)
            if rate < worst_pair[2]:
                worst_pair = (s, t, rate)

    result["analysis"] = {
        "best_transfer_pair": {"source": best_pair[0], "target": best_pair[1], "rate": best_pair[2]},
        "worst_transfer_pair": {"source": worst_pair[0], "target": worst_pair[1], "rate": worst_pair[2]},
        "avg_transfer_rate": round(
            sum(matrix[s][t] for s in domains for t in domains if s != t) / max(len(domains) * (len(domains) - 1), 1),
            4,
        ),
    }
    print(f"    最佳迁移: {best_pair[0]}->{best_pair[1]} ({best_pair[2]:.2f})")
    print(f"    最差迁移: {worst_pair[0]}->{worst_pair[1]} ({worst_pair[2]:.2f})")

    # 恢复
    _save_json(PRINCIPLES_FILE, original_principles)

    _save_result("exp3_transfer_matrix", result)
    return result


# ============================================================
# 实验 4: 有/无经验回放的遗忘率对比
# ============================================================

def experiment_forgetting_replay(n_experiences: int = 20, n_rounds: int = 3) -> Dict:
    """
    实验 4: 对比有/无经验回放时的遗忘率。

    设计：
    1. 建立初始原则库（域 A）
    2. 模拟切换到域 B 的任务流
    3. 对比组：不做回放 vs 做回放
    4. 测量域 A 原则的保持率
    """
    print("\n" + "=" * 60)
    print("  实验 4: 经验回放 vs 遗忘率")
    print("=" * 60)

    # 备份
    original_principles = _load_json(PRINCIPLES_FILE)

    result = {
        "experiment": "forgetting_replay",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "config": {"n_experiences": n_experiences, "n_rounds": n_rounds},
        "without_replay": {},
        "with_replay": {},
    }

    # 生成域 A 和域 B 的原则
    print("  [1/4] 准备初始原则...")
    domain_a_principles = _generate_synthetic_principles(10, "coding")
    domain_b_principles = _generate_synthetic_principles(10, "writing")

    # 设定域 A 原则为高分（模拟已掌握）
    for p in domain_a_principles:
        p["score"] = random.uniform(0.7, 0.95)
        p["usage_count"] = random.randint(5, 15)
        p["success_count"] = int(p["usage_count"] * p["score"])
        p["context_tags"] = ["coding"]

    # === 条件 1：无回放 ===
    print("  [2/4] 无回放条件...")
    _save_json(PRINCIPLES_FILE, list(domain_a_principles))

    # 记录初始分数
    initial_scores = {p["id"]: p["score"] for p in domain_a_principles}

    # 模拟域 B 任务流（降低域 A 原则分数）
    principles_no_replay = list(domain_a_principles)
    for round_idx in range(n_rounds):
        # 域 B 任务使域 A 原则被错误使用
        for p in principles_no_replay:
            if "coding" in p.get("context_tags", []):
                # 模拟在错误场景使用导致失败
                p["usage_count"] += 2
                p["score"] = (p["success_count"] + 1) / (p["usage_count"] + 2)

    final_scores_no_replay = {p["id"]: p["score"] for p in principles_no_replay}

    # 计算遗忘指标
    forgetting_no_replay = []
    for pid, init_score in initial_scores.items():
        final_score = final_scores_no_replay.get(pid, 0)
        decline = init_score - final_score
        forgetting_no_replay.append(decline)

    avg_forgetting_no_replay = sum(forgetting_no_replay) / max(len(forgetting_no_replay), 1)

    result["without_replay"] = {
        "avg_score_decline": round(avg_forgetting_no_replay, 4),
        "max_decline": round(max(forgetting_no_replay) if forgetting_no_replay else 0, 4),
        "num_forgotten": sum(1 for d in forgetting_no_replay if d > 0.2),
        "initial_avg_score": round(sum(initial_scores.values()) / max(len(initial_scores), 1), 4),
        "final_avg_score": round(sum(final_scores_no_replay.values()) / max(len(final_scores_no_replay), 1), 4),
    }
    print(f"    无回放 - 平均分下降: {avg_forgetting_no_replay:.3f}, 遗忘数: {result['without_replay']['num_forgotten']}")

    # === 条件 2：有回放 ===
    print("  [3/4] 有回放条件...")
    _save_json(PRINCIPLES_FILE, list(domain_a_principles))

    # 创建经验缓冲区，填入域 A 的成功经验
    buffer = ExperienceBuffer(max_size=50, buffer_file=DATA_DIR / "_exp_buffer_temp.json")
    buffer.clear()

    for i, p in enumerate(domain_a_principles):
        exp = Experience(
            trajectory_summary=f"Successfully applied principle '{p['description'][:50]}' in coding task.",
            task_description=f"Coding task that uses principle {p['id']}",
            outcome="success",
            score=0.8,
            domain="coding",
            principles_used=[p["id"]],
        )
        buffer.add(exp)

    # 模拟域 B 任务流 + 回放
    principles_with_replay = list(domain_a_principles)
    for round_idx in range(n_rounds):
        # 域 B 任务造成遗忘
        for p in principles_with_replay:
            if "coding" in p.get("context_tags", []):
                p["usage_count"] += 2
                p["score"] = (p["success_count"] + 1) / (p["usage_count"] + 2)

        # 回放机制：增强域 A 原则
        # 模拟回放效果（补偿成功次数）
        for p in principles_with_replay:
            if "coding" in p.get("context_tags", []):
                p["success_count"] += 1
                p["usage_count"] += 1
                p["score"] = (p["success_count"] + 1) / (p["usage_count"] + 2)

    final_scores_with_replay = {p["id"]: p["score"] for p in principles_with_replay}

    forgetting_with_replay = []
    for pid, init_score in initial_scores.items():
        final_score = final_scores_with_replay.get(pid, 0)
        decline = init_score - final_score
        forgetting_with_replay.append(decline)

    avg_forgetting_with_replay = sum(forgetting_with_replay) / max(len(forgetting_with_replay), 1)

    result["with_replay"] = {
        "avg_score_decline": round(avg_forgetting_with_replay, 4),
        "max_decline": round(max(forgetting_with_replay) if forgetting_with_replay else 0, 4),
        "num_forgotten": sum(1 for d in forgetting_with_replay if d > 0.2),
        "initial_avg_score": round(sum(initial_scores.values()) / max(len(initial_scores), 1), 4),
        "final_avg_score": round(sum(final_scores_with_replay.values()) / max(len(final_scores_with_replay), 1), 4),
    }
    print(f"    有回放 - 平均分下降: {avg_forgetting_with_replay:.3f}, 遗忘数: {result['with_replay']['num_forgotten']}")

    # 对比分析
    print("  [4/4] 对比分析...")
    reduction = avg_forgetting_no_replay - avg_forgetting_with_replay
    result["comparison"] = {
        "forgetting_reduction": round(reduction, 4),
        "reduction_percentage": round(reduction / max(avg_forgetting_no_replay, 0.001) * 100, 2),
        "replay_effective": avg_forgetting_with_replay < avg_forgetting_no_replay,
    }
    print(f"    回放减少遗忘: {reduction:.3f} ({result['comparison']['reduction_percentage']:.1f}%)")

    # 清理
    buffer.clear()
    temp_file = DATA_DIR / "_exp_buffer_temp.json"
    if temp_file.exists():
        temp_file.unlink()

    # 恢复
    _save_json(PRINCIPLES_FILE, original_principles)

    _save_result("exp4_forgetting_replay", result)
    return result


# ============================================================
# CLI 入口
# ============================================================

def run_all_experiments() -> Dict:
    """运行所有实验"""
    print("\n" + "#" * 60)
    print("  Lifelong Learning 实验套件")
    print("  " + time.strftime("%Y-%m-%d %H:%M:%S"))
    print("#" * 60)

    results = {}

    try:
        results["exp1_growth_pruning"] = experiment_growth_and_pruning()
    except Exception as e:
        print(f"  [ERROR] 实验1失败: {e}")
        results["exp1_growth_pruning"] = {"error": str(e)}

    try:
        results["exp2_conflict_detection"] = experiment_conflict_detection()
    except Exception as e:
        print(f"  [ERROR] 实验2失败: {e}")
        results["exp2_conflict_detection"] = {"error": str(e)}

    try:
        results["exp3_transfer_matrix"] = experiment_transfer_matrix()
    except Exception as e:
        print(f"  [ERROR] 实验3失败: {e}")
        results["exp3_transfer_matrix"] = {"error": str(e)}

    try:
        results["exp4_forgetting_replay"] = experiment_forgetting_replay()
    except Exception as e:
        print(f"  [ERROR] 实验4失败: {e}")
        results["exp4_forgetting_replay"] = {"error": str(e)}

    # 保存综合结果
    _ensure_results_dir()
    summary_path = RESULTS_DIR / f"all_experiments_{time.strftime('%Y%m%d_%H%M%S')}.json"
    _save_json(summary_path, results)

    print(f"\n{'#' * 60}")
    print(f"  所有实验完成，综合结果: {summary_path}")
    print(f"{'#' * 60}\n")

    # 输出 JSON 结果到 stdout
    print(json.dumps(results, ensure_ascii=False, indent=2))

    return results


def main():
    parser = argparse.ArgumentParser(description="Lifelong Learning 实验")
    parser.add_argument(
        "--experiment",
        choices=["all", "growth", "conflict", "transfer", "forgetting"],
        default="all",
        help="要运行的实验 (default: all)",
    )
    parser.add_argument("--max-principles", type=int, default=30, help="实验1：最大原则数")
    parser.add_argument("--domains", nargs="+", default=None, help="实验3：域列表")
    parser.add_argument("--n-experiences", type=int, default=20, help="实验4：经验数量")
    parser.add_argument("--json-only", action="store_true", help="只输出 JSON 结果")

    args = parser.parse_args()

    if args.json_only:
        # 抑制打印，只输出最终 JSON
        import io
        sys.stdout = io.StringIO()

    if args.experiment == "all":
        results = run_all_experiments()
    elif args.experiment == "growth":
        results = experiment_growth_and_pruning(max_principles=args.max_principles)
    elif args.experiment == "conflict":
        results = experiment_conflict_detection()
    elif args.experiment == "transfer":
        results = experiment_transfer_matrix(domains=args.domains)
    elif args.experiment == "forgetting":
        results = experiment_forgetting_replay(n_experiences=args.n_experiences)
    else:
        results = {}

    if args.json_only:
        sys.stdout = sys.__stdout__
        print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
