"""
Self-Evolution Engine for EgoAgent.

综合自进化引擎，融合 EvolveR（原则库）、ADAS（进化归档）、
Agent0（前沿课程）、EvoAgentX（TextGrad优化）等思想，
为 egoagent 系统提供自动化的持续改进能力。
"""

from self_evolution.engine import (
    # Principle Library
    distill_principles,
    retrieve_principles,
    update_scores,
    # Evolution Archive
    record_attempt,
    get_history,
    get_best_configs,
    # Frontier Curriculum
    assess_difficulty,
    generate_frontier_tasks,
    get_task_pool,
    # TextGrad Optimizer
    compute_text_gradient,
    apply_gradient,
    # Gated Evolution Controller
    snapshot,
    evaluate,
    gate_decision,
    rollback,
    # Main Loop
    run_evolution_cycle,
)

__all__ = [
    "distill_principles",
    "retrieve_principles",
    "update_scores",
    "record_attempt",
    "get_history",
    "get_best_configs",
    "assess_difficulty",
    "generate_frontier_tasks",
    "get_task_pool",
    "compute_text_gradient",
    "apply_gradient",
    "snapshot",
    "evaluate",
    "gate_decision",
    "rollback",
    "run_evolution_cycle",
]
