"""
Evolution Benchmark Metrics — 6 dimensions, 24 metrics for evaluating self-evolution.

Dimensions:
1. Effectiveness — Does evolution actually improve performance?
2. Efficiency — How much does improvement cost?
3. Stability — Is the evolution process reliable?
4. Transferability — Do improvements generalize?
5. Component Attribution — What contributes to improvement?
6. Sustainability — Does improvement last over time?
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
import math
import statistics


@dataclass
class EvolutionTrace:
    """A trace of one evolution run, containing per-iteration scores and metadata."""
    scores: List[float] = field(default_factory=list)
    token_costs: List[int] = field(default_factory=list)
    decisions: List[str] = field(default_factory=list)
    iterations: List[Dict] = field(default_factory=list)
    config_name: str = ""
    task_suite: str = ""


@dataclass
class MetricResult:
    """Result of a single metric computation."""
    name: str
    value: float
    dimension: str
    description: str = ""


@dataclass
class BenchmarkMetrics:
    """Full set of benchmark metrics across all dimensions."""
    effectiveness: Dict[str, float] = field(default_factory=dict)
    efficiency: Dict[str, float] = field(default_factory=dict)
    stability: Dict[str, float] = field(default_factory=dict)
    transferability: Dict[str, float] = field(default_factory=dict)
    component_attribution: Dict[str, float] = field(default_factory=dict)
    sustainability: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "effectiveness": self.effectiveness,
            "efficiency": self.efficiency,
            "stability": self.stability,
            "transferability": self.transferability,
            "component_attribution": self.component_attribution,
            "sustainability": self.sustainability,
        }

    def flat_dict(self) -> Dict[str, float]:
        result = {}
        for dim_name, dim_dict in self.to_dict().items():
            for k, v in dim_dict.items():
                result[f"{dim_name}.{k}"] = v
        return result


# Dimension 1: Effectiveness

def compute_score_improvement(trace: EvolutionTrace) -> float:
    """Absolute score improvement from start to end."""
    if len(trace.scores) < 2:
        return 0.0
    return trace.scores[-1] - trace.scores[0]


def compute_improvement_rate(trace: EvolutionTrace) -> float:
    """Fraction of iterations that resulted in score improvement."""
    if len(trace.scores) < 2:
        return 0.0
    improvements = sum(1 for i in range(1, len(trace.scores)) if trace.scores[i] > trace.scores[i-1])
    return improvements / (len(trace.scores) - 1)


def compute_convergence_score(trace: EvolutionTrace) -> float:
    """Final converged score (average of last 3 scores)."""
    if not trace.scores:
        return 0.0
    tail = trace.scores[-3:] if len(trace.scores) >= 3 else trace.scores
    return statistics.mean(tail)


# Dimension 2: Efficiency

def compute_token_cost(trace: EvolutionTrace) -> int:
    """Total token cost across all iterations."""
    return sum(trace.token_costs) if trace.token_costs else 0


def compute_iterations_to_threshold(trace: EvolutionTrace, threshold: float = 0.7) -> int:
    """Number of iterations to reach threshold. -1 if never reached."""
    for i, score in enumerate(trace.scores):
        if score >= threshold:
            return i
    return -1


def compute_cost_per_point(trace: EvolutionTrace) -> float:
    """Token cost per point of improvement. inf if no improvement."""
    improvement = compute_score_improvement(trace)
    total_cost = compute_token_cost(trace)
    if improvement <= 0:
        return float("inf")
    return total_cost / improvement if total_cost > 0 else 0.0


# Dimension 3: Stability

def compute_monotonicity(trace: EvolutionTrace) -> float:
    """Fraction of steps where score is non-decreasing."""
    if len(trace.scores) < 2:
        return 1.0
    nd = sum(1 for i in range(1, len(trace.scores)) if trace.scores[i] >= trace.scores[i-1])
    return nd / (len(trace.scores) - 1)


def compute_rollback_rate(trace: EvolutionTrace) -> float:
    """Fraction of iterations that resulted in rollback."""
    if not trace.decisions:
        return 0.0
    return sum(1 for d in trace.decisions if d == "rollback") / len(trace.decisions)


def compute_variance_across_runs(traces: List[EvolutionTrace]) -> float:
    """Variance of final scores across multiple runs."""
    if len(traces) < 2:
        return 0.0
    final_scores = [t.scores[-1] for t in traces if t.scores]
    if len(final_scores) < 2:
        return 0.0
    return statistics.variance(final_scores)


def compute_worst_case_regression(trace: EvolutionTrace) -> float:
    """Largest single-step score decrease."""
    if len(trace.scores) < 2:
        return 0.0
    return max(trace.scores[i-1] - trace.scores[i] for i in range(1, len(trace.scores)))


# Dimension 4: Transferability

def compute_in_domain_transfer(source_trace: EvolutionTrace, before: float, after: float) -> float:
    """In-domain transfer improvement."""
    return after - before


def compute_out_of_domain_transfer(source_trace: EvolutionTrace, before: float, after: float) -> float:
    """Out-of-domain transfer improvement."""
    return after - before


def compute_negative_transfer_rate(transfer_results: List[float]) -> float:
    """Fraction of transfer tests showing negative transfer."""
    if not transfer_results:
        return 0.0
    return sum(1 for r in transfer_results if r < 0) / len(transfer_results)


# Dimension 5: Component Attribution

def compute_component_contribution(full_score: float, ablated_score: float) -> float:
    """Marginal contribution = full_score - ablated_score."""
    return full_score - ablated_score


def compute_principle_contribution(full: float, without: float) -> float:
    return compute_component_contribution(full, without)


def compute_textgrad_contribution(full: float, without: float) -> float:
    return compute_component_contribution(full, without)


def compute_frontier_contribution(full: float, without: float) -> float:
    return compute_component_contribution(full, without)


def compute_gate_contribution(full: float, without: float) -> float:
    return compute_component_contribution(full, without)


# Dimension 6: Sustainability

def compute_forgetting_rate(before: List[float], after: List[float]) -> float:
    """Average performance drop on old tasks (positive = forgetting)."""
    if not before or not after:
        return 0.0
    n = min(len(before), len(after))
    drops = [before[i] - after[i] for i in range(n)]
    return max(0.0, statistics.mean(drops))


def compute_principle_saturation(count: int, max_useful: int = 50) -> float:
    """Ratio of current principles to estimated max useful."""
    return min(1.0, count / max_useful)


def compute_improvement_decay(trace: EvolutionTrace, window: int = 3) -> float:
    """Ratio of late improvements to early improvements."""
    if len(trace.scores) < 2 * window + 1:
        return 1.0
    early = [trace.scores[i] - trace.scores[i-1] for i in range(1, window+1)]
    n = len(trace.scores)
    late = [trace.scores[i] - trace.scores[i-1] for i in range(n-window, n)]
    early_avg = statistics.mean(early)
    late_avg = statistics.mean(late)
    if abs(early_avg) < 1e-9:
        return 1.0 if abs(late_avg) < 1e-9 else 0.0
    return late_avg / early_avg


# Aggregate

def compute_all_metrics(
    trace: EvolutionTrace,
    multi_run_traces: Optional[List[EvolutionTrace]] = None,
    ablation_scores: Optional[Dict[str, float]] = None,
    transfer_results: Optional[Dict[str, Tuple[float, float]]] = None,
    old_task_scores: Optional[Tuple[List[float], List[float]]] = None,
    principles_count: int = 0,
) -> BenchmarkMetrics:
    """Compute all 24 metrics from available data."""
    m = BenchmarkMetrics()
    m.effectiveness = {
        "score_improvement": compute_score_improvement(trace),
        "improvement_rate": compute_improvement_rate(trace),
        "convergence_score": compute_convergence_score(trace),
    }
    m.efficiency = {
        "token_cost": float(compute_token_cost(trace)),
        "iterations_to_threshold": float(compute_iterations_to_threshold(trace)),
        "cost_per_point": compute_cost_per_point(trace),
    }
    m.stability = {
        "monotonicity": compute_monotonicity(trace),
        "rollback_rate": compute_rollback_rate(trace),
        "variance_across_runs": compute_variance_across_runs(multi_run_traces or []),
        "worst_case_regression": compute_worst_case_regression(trace),
    }
    if transfer_results:
        ind = transfer_results.get("in_domain", (0.0, 0.0))
        ood = transfer_results.get("out_of_domain", (0.0, 0.0))
        all_t = [v[1] - v[0] for v in transfer_results.values()]
        m.transferability = {
            "in_domain_transfer": ind[1] - ind[0],
            "out_of_domain_transfer": ood[1] - ood[0],
            "negative_transfer_rate": compute_negative_transfer_rate(all_t),
        }
    else:
        m.transferability = {"in_domain_transfer": 0.0, "out_of_domain_transfer": 0.0, "negative_transfer_rate": 0.0}
    if ablation_scores:
        fs = trace.scores[-1] if trace.scores else 0.0
        m.component_attribution = {
            "principle_contribution": compute_principle_contribution(fs, ablation_scores.get("no_principles", fs)),
            "textgrad_contribution": compute_textgrad_contribution(fs, ablation_scores.get("no_textgrad", fs)),
            "frontier_contribution": compute_frontier_contribution(fs, ablation_scores.get("no_frontier", fs)),
            "gate_contribution": compute_gate_contribution(fs, ablation_scores.get("no_gate", fs)),
        }
    else:
        m.component_attribution = {"principle_contribution": 0.0, "textgrad_contribution": 0.0, "frontier_contribution": 0.0, "gate_contribution": 0.0}
    forgetting = compute_forgetting_rate(old_task_scores[0], old_task_scores[1]) if old_task_scores else 0.0
    m.sustainability = {
        "forgetting_rate": forgetting,
        "principle_saturation": compute_principle_saturation(principles_count),
        "improvement_decay": compute_improvement_decay(trace),
    }
    return m
