"""
Evolution Benchmark Analyzer — statistical analysis of benchmark results.
"""

import json
import random
import statistics
import sys
from pathlib import Path
from typing import List, Dict, Tuple
from dataclasses import dataclass

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

BENCHMARK_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BENCHMARK_DIR / "results"


@dataclass
class ComparisonResult:
    """Result of comparing two configurations."""
    config_a: str
    config_b: str
    mean_a: float
    mean_b: float
    diff: float
    ci_lower: float
    ci_upper: float
    is_significant: bool
    p_value_approx: float


def load_results(results_path: str) -> Dict:
    """Load benchmark results from a JSON file."""
    path = Path(results_path)
    if not path.exists():
        raise FileNotFoundError(f"Results file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_latest_results() -> Dict:
    """Load the most recent benchmark results file."""
    if not RESULTS_DIR.exists():
        raise FileNotFoundError(f"No results directory: {RESULTS_DIR}")
    json_files = sorted(RESULTS_DIR.glob("benchmark_*.json"), reverse=True)
    if not json_files:
        json_files = sorted(RESULTS_DIR.glob("*.json"), reverse=True)
    if not json_files:
        raise FileNotFoundError("No result files found")
    return json.loads(json_files[0].read_text(encoding="utf-8"))


def bootstrap_confidence_interval(
    scores: List[float], confidence: float = 0.95,
    n_bootstrap: int = 10000, statistic: str = "mean",
) -> Tuple[float, float, float]:
    """Compute bootstrap CI. Returns (point_estimate, ci_lower, ci_upper)."""
    if not scores:
        return 0.0, 0.0, 0.0
    if len(scores) == 1:
        return scores[0], scores[0], scores[0]
    stat_fn = {"mean": statistics.mean, "median": statistics.median,
               "std": statistics.stdev}.get(statistic, statistics.mean)
    point_estimate = stat_fn(scores)
    boot = []
    n = len(scores)
    for _ in range(n_bootstrap):
        sample = [random.choice(scores) for _ in range(n)]
        try:
            boot.append(stat_fn(sample))
        except statistics.StatisticsError:
            boot.append(0.0)
    boot.sort()
    alpha = 1 - confidence
    lo = int(alpha / 2 * n_bootstrap)
    hi = int((1 - alpha / 2) * n_bootstrap)
    return point_estimate, boot[lo], boot[min(hi, n_bootstrap - 1)]


def paired_bootstrap_test(
    scores_a: List[float], scores_b: List[float],
    n_bootstrap: int = 10000,
) -> Tuple[float, float, float]:
    """Paired bootstrap test. Returns (mean_diff, ci_lower, ci_upper)."""
    min_len = min(len(scores_a), len(scores_b))
    sa, sb = scores_a[:min_len], scores_b[:min_len]
    if not sa:
        return 0.0, 0.0, 0.0
    diffs = [a - b for a, b in zip(sa, sb)]
    mean_diff = statistics.mean(diffs)
    boot = []
    n = len(diffs)
    for _ in range(n_bootstrap):
        sample = [random.choice(diffs) for _ in range(n)]
        boot.append(statistics.mean(sample))
    boot.sort()
    return mean_diff, boot[int(0.025 * n_bootstrap)], boot[int(0.975 * n_bootstrap)]


def compute_significance(
    scores_a: List[float], scores_b: List[float], alpha: float = 0.05,
) -> ComparisonResult:
    """Test statistical significance between two configurations."""
    mean_a = statistics.mean(scores_a) if scores_a else 0.0
    mean_b = statistics.mean(scores_b) if scores_b else 0.0
    _, ci_lower, ci_upper = paired_bootstrap_test(scores_a, scores_b)
    is_sig = (ci_lower > 0) or (ci_upper < 0)
    return ComparisonResult(
        config_a="A", config_b="B", mean_a=mean_a, mean_b=mean_b,
        diff=mean_a - mean_b, ci_lower=ci_lower, ci_upper=ci_upper,
        is_significant=is_sig, p_value_approx=alpha / 2 if is_sig else 0.5,
    )


def compute_marginal_contributions(results: Dict) -> Dict[str, float]:
    """Compute leave-one-out marginal contribution of each component."""
    ablation = results.get("ablation_results", {})
    full_score = ablation.get("full", {}).get("final_score", 0.0)
    component_map = {
        "no_principles": "Principle Library",
        "no_textgrad": "TextGrad Optimizer",
        "no_gate": "Gate Controller",
        "no_frontier": "Frontier Curriculum",
    }
    contributions = {}
    for cfg, name in component_map.items():
        ablated = ablation.get(cfg, {}).get("final_score", full_score)
        contributions[name] = full_score - ablated
    random_score = ablation.get("random_baseline", {}).get("final_score", 0.0)
    contributions["System vs Random"] = full_score - random_score
    return contributions


def generate_comparison_table(results: Dict) -> str:
    """Generate markdown comparison table."""
    ablation = results.get("ablation_results", {})
    lines = [
        "## Configuration Comparison Table", "",
        "| Config | Final Score | Improvement | Monotonicity | Rollback Rate |",
        "|--------|-------------|-------------|--------------|---------------|",
    ]
    for cfg, result in ablation.items():
        if cfg.startswith("_"):
            continue
        m = result.get("metrics", {})
        eff = m.get("effectiveness", {})
        stab = m.get("stability", {})
        lines.append(
            f"| {cfg} | {result.get('final_score', 0):.4f} | "
            f"{eff.get('score_improvement', 0):+.4f} | "
            f"{stab.get('monotonicity', 0):.2%} | "
            f"{stab.get('rollback_rate', 0):.2%} |"
        )
    lines.append("")
    return "\n".join(lines)


def analyze_results_file(filepath: str) -> str:
    """Complete analysis of a results file. Returns markdown report."""
    results = load_results(filepath)
    lines = ["# Evolution Benchmark Analysis Report",
             f"\nSource: {filepath}", ""]

    suite_results = results.get("suite_results", {})
    if suite_results:
        lines.append("## Overall Effectiveness\n")
        imps = []
        for suite, sr in suite_results.items():
            imp = sr.get("metrics", {}).get("effectiveness", {}).get(
                "score_improvement", 0.0)
            imps.append(imp)
            lines.append(f"- **{suite}**: improvement = {imp:+.4f}")
        if imps:
            avg = statistics.mean(imps)
            lines.append(f"\n**Average improvement**: {avg:+.4f}")
            if len(imps) >= 2:
                _, lo, hi = bootstrap_confidence_interval(imps)
                lines.append(f"**95% CI**: [{lo:+.4f}, {hi:+.4f}]")
        lines.append("")

    if "ablation_results" in results:
        lines.append("## Component Contributions\n")
        contribs = compute_marginal_contributions(results)
        for comp, val in sorted(contribs.items(), key=lambda x: -x[1]):
            lines.append(f"- **{comp}**: {val:+.4f}")
        lines.append("")
        lines.append(generate_comparison_table(results))

    stability = results.get("stability_results", {})
    if stability:
        lines.append("## Stability Analysis\n")
        scores = stability.get("final_scores", [])
        if len(scores) >= 2:
            pt, lo, hi = bootstrap_confidence_interval(scores)
            lines.append(f"- Point estimate: {pt:.4f}")
            lines.append(f"- 95% CI: [{lo:.4f}, {hi:.4f}]")
            lines.append(f"- Std dev: {statistics.stdev(scores):.4f}")
        lines.append("")

    transfer = results.get("transfer_results", {})
    if transfer and "error" not in transfer:
        lines.append("## Transfer Analysis\n")
        for tgt, tr in transfer.items():
            if isinstance(tr, dict) and "transfer_delta" in tr:
                d = tr["transfer_delta"]
                dom = "in-domain" if tr.get("is_in_domain") else "cross-domain"
                lines.append(
                    f"- {tr.get('source_suite','?')} -> {tgt} "
                    f"({dom}): {d:+.4f}")
        lines.append("")

    return "\n".join(lines)


def main():
    """CLI entry point."""
    import argparse
    parser = argparse.ArgumentParser(
        description="Analyze Evolution Benchmark results")
    parser.add_argument("results_file", type=str, nargs="?", default="")
    parser.add_argument("--output", type=str, default="")
    args = parser.parse_args()

    try:
        if args.results_file:
            report = analyze_results_file(args.results_file)
        else:
            results = load_latest_results()
            import tempfile
            tmp = Path(tempfile.mktemp(suffix=".json"))
            tmp.write_text(json.dumps(results, default=str), encoding="utf-8")
            report = analyze_results_file(str(tmp))
            tmp.unlink()
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        print(f"Analysis saved to: {args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()
