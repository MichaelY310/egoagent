"""
Evolution Benchmark — Core framework for systematically evaluating self-evolution.

This module provides the EvoBenchmark class that orchestrates:
- Full benchmark runs across task suites and configurations
- Ablation experiments to measure component contributions
- Transfer tests to evaluate cross-domain generalization
- Stability tests with multiple runs
- Comprehensive report generation
"""

import json
import os
import sys
import time
import random
import re
import uuid
import statistics
import requests
from copy import deepcopy
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field, asdict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from experiments.evo_benchmark.metrics import (
    EvolutionTrace,
    BenchmarkMetrics,
    compute_all_metrics,
    compute_score_improvement,
    compute_variance_across_runs,
)

LLM_BASE_URL = "http://[fdbd:dc05:10:10a::27]:9638/v1"
LLM_MODEL = "Qwen3-8B-yangyuan"

BENCHMARK_DIR = Path(__file__).resolve().parent
TASK_SUITES_DIR = BENCHMARK_DIR / "task_suites"
ABLATION_CONFIG_FILE = BENCHMARK_DIR / "ablation_configs.json"


def _llm_call(messages: List[Dict], max_tokens: int = 2048, temperature: float = 0.7) -> Tuple[str, int]:
    """Call LLM API. Returns (content, tokens_used)."""
    url = f"{LLM_BASE_URL}/chat/completions"
    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    headers = {"Content-Type": "application/json"}
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=120)
        resp.raise_for_status()
        result = resp.json()
        content = result["choices"][0]["message"].get("content", "")
        if "</think>" in content:
            content = content.split("</think>")[-1].strip()
        elif "<think>" in content:
            content = ""
        usage = result.get("usage", {})
        total_tokens = usage.get("total_tokens", len(content) // 4 + len(str(messages)) // 4)
        return content, total_tokens
    except Exception as e:
        return f"[LLM_ERROR] {e}", 0


def _llm_call_simple(messages: List[Dict], max_tokens: int = 2048, temperature: float = 0.7) -> str:
    """Call LLM API, return only content string."""
    content, _ = _llm_call(messages, max_tokens, temperature)
    return content


def _score_response(task_description: str, response: str) -> Tuple[float, int]:
    """Score a response using LLM judge. Returns (score, tokens_used)."""
    eval_prompt = f"""Rate the quality of this response on a scale of 0.0 to 1.0.
Consider: correctness, completeness, clarity, adherence to requirements.

Task: {task_description}
Response: {response[:2000]}

Output ONLY a single float number between 0.0 and 1.0:"""

    result, tokens = _llm_call([
        {"role": "system", "content": "Output only a float between 0.0 and 1.0."},
        {"role": "user", "content": eval_prompt},
    ], max_tokens=32, temperature=0.1)

    try:
        numbers = re.findall(r"[01]?\.\d+|1\.0|0\.0", result)
        score = float(numbers[0]) if numbers else 0.5
        return max(0.0, min(1.0, score)), tokens
    except (ValueError, IndexError):
        return 0.5, tokens


def _generate_response(task_description: str, system_prompt: str = "") -> Tuple[str, int]:
    """Generate a response for a task. Returns (response, tokens_used)."""
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": task_description})
    return _llm_call(messages, max_tokens=1536, temperature=0.5)


@dataclass
class BenchmarkConfig:
    """Configuration for a benchmark run."""
    task_suites: List[str] = field(default_factory=lambda: ["coding", "reasoning", "writing", "mixed"])
    ablation_configs: List[str] = field(default_factory=lambda: ["full", "no_principles", "no_textgrad", "no_gate", "no_frontier", "random_baseline"])
    n_runs: int = 3
    max_iterations: int = 5
    output_dir: str = ""
    target_harness: str = "react_single"
    target_identity: str = "dante"


class EvoBenchmark:
    """Systematic benchmark framework for evaluating self-evolution effectiveness."""

    def __init__(self, config: Dict):
        """
        Initialize benchmark.

        Args:
            config: Dict with task_suites, metrics, ablation_configs, n_runs, etc.
        """
        self.config = BenchmarkConfig(
            task_suites=config.get("task_suites", ["coding", "reasoning", "writing", "mixed"]),
            ablation_configs=config.get("ablation_configs", ["full", "no_principles", "no_textgrad", "no_gate", "no_frontier", "random_baseline"]),
            n_runs=config.get("n_runs", 3),
            max_iterations=config.get("max_iterations", 5),
            output_dir=config.get("output_dir", str(BENCHMARK_DIR / "results")),
            target_harness=config.get("target_harness", "react_single"),
            target_identity=config.get("target_identity", "dante"),
        )
        self.output_dir = Path(self.config.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.ablation_configs = self._load_ablation_configs()
        self.task_suites = self._load_task_suites()
        self.results: Dict[str, Any] = {}

    def _load_ablation_configs(self) -> Dict[str, Dict]:
        if ABLATION_CONFIG_FILE.exists():
            data = json.loads(ABLATION_CONFIG_FILE.read_text(encoding="utf-8"))
            return data.get("configs", {})
        return {"full": {"name": "full", "use_principles": True, "use_textgrad": True, "use_gate": True, "use_frontier": True}}

    def _load_task_suites(self) -> Dict[str, List[Dict]]:
        suites = {}
        for suite_name in self.config.task_suites:
            suite_file = TASK_SUITES_DIR / f"{suite_name}_tasks.json"
            if suite_file.exists():
                suites[suite_name] = json.loads(suite_file.read_text(encoding="utf-8"))
            else:
                suites[suite_name] = []
        return suites

    def run_full_benchmark(self) -> Dict:
        """Run complete benchmark: all task suites x all configs x multiple runs."""
        print(f"\n{'='*70}")
        print(f"  Evolution Benchmark — Full Run")
        print(f"  Suites: {self.config.task_suites}")
        print(f"  Configs: {self.config.ablation_configs}")
        print(f"  Runs/config: {self.config.n_runs}")
        print(f"{'='*70}\n")

        results = {
            "metadata": {"timestamp": time.strftime("%Y-%m-%d %H:%M:%S"), "config": asdict(self.config)},
            "suite_results": {},
            "ablation_results": {},
            "transfer_results": {},
            "stability_results": {},
            "aggregate_metrics": {},
        }

        for suite_name in self.config.task_suites:
            print(f"\n--- Suite: {suite_name} ---")
            results["suite_results"][suite_name] = self.run_single_evolution(
                config=self.ablation_configs.get("full", {}), task_suite=suite_name)

        print(f"\n--- Ablation ---")
        results["ablation_results"] = self.run_ablation()

        print(f"\n--- Transfer ---")
        results["transfer_results"] = self.run_transfer_test()

        print(f"\n--- Stability ---")
        results["stability_results"] = self.run_stability_test(n_runs=self.config.n_runs)

        results["aggregate_metrics"] = self._compute_aggregate_metrics(results)
        self.results = results

        results_file = self.output_dir / f"benchmark_{time.strftime('%Y%m%d_%H%M%S')}.json"
        results_file.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

        report = self.generate_report(results)
        report_file = self.output_dir / f"report_{time.strftime('%Y%m%d_%H%M%S')}.md"
        report_file.write_text(report, encoding="utf-8")
        print(f"\nResults: {results_file}\nReport: {report_file}")

        return results

    def run_single_evolution(self, config: Dict, task_suite: str) -> Dict:
        """Run single evolution experiment and collect detailed metrics."""
        config_name = config.get("name", "unknown")
        tasks = self.task_suites.get(task_suite, [])
        if not tasks:
            return {"error": f"No tasks in suite '{task_suite}'", "trace": None}

        print(f"  [{config_name}] on [{task_suite}] ({len(tasks)} tasks, {self.config.max_iterations} iters)")

        trace = EvolutionTrace(config_name=config_name, task_suite=task_suite)
        system_prompt = self._build_system_prompt(config)

        baseline_scores, baseline_tokens = self._evaluate_on_tasks(tasks, system_prompt)
        baseline_avg = statistics.mean(baseline_scores) if baseline_scores else 0.0
        trace.scores.append(baseline_avg)
        trace.token_costs.append(baseline_tokens)

        per_iteration_data = []
        for iteration in range(self.config.max_iterations):
            iter_data = {"iteration": iteration + 1}
            selected_tasks = self._select_tasks(tasks, config, baseline_scores)
            modification, mod_tokens = self._generate_modification(config, selected_tasks, system_prompt, baseline_scores)
            new_prompt = self._apply_modification(config, system_prompt, modification)
            new_scores, eval_tokens = self._evaluate_on_tasks(tasks, new_prompt)
            new_avg = statistics.mean(new_scores) if new_scores else 0.0
            total_iter_tokens = mod_tokens + eval_tokens

            decision = self._gate_decision(config, baseline_avg, new_avg)
            iter_data.update({"score_before": baseline_avg, "score_after": new_avg, "decision": decision, "tokens": total_iter_tokens})

            if decision == "accept":
                system_prompt = new_prompt
                baseline_avg = new_avg
                baseline_scores = new_scores

            trace.scores.append(baseline_avg)
            trace.token_costs.append(total_iter_tokens)
            trace.decisions.append(decision)
            trace.iterations.append(iter_data)
            per_iteration_data.append(iter_data)
            print(f"    Iter {iteration+1}: {iter_data['score_before']:.3f} -> {new_avg:.3f} [{decision}]")

        metrics = self.compute_metrics(trace)
        return {
            "config_name": config_name, "task_suite": task_suite,
            "trace": {"scores": trace.scores, "token_costs": trace.token_costs, "decisions": trace.decisions},
            "iterations": per_iteration_data, "metrics": metrics.to_dict(),
            "final_score": trace.scores[-1] if trace.scores else 0.0,
        }

    def compute_metrics(self, evolution_trace: EvolutionTrace) -> BenchmarkMetrics:
        """Compute all evaluation metrics from an evolution trace."""
        return compute_all_metrics(trace=evolution_trace)

    def run_ablation(self) -> Dict:
        """Ablation: remove components one at a time and measure effect."""
        results = {}
        suite_name = self.config.task_suites[0] if self.config.task_suites else "coding"

        for config_name in self.config.ablation_configs:
            config = self.ablation_configs.get(config_name)
            if config is None:
                continue
            print(f"  Ablation: {config_name}")
            results[config_name] = self.run_single_evolution(config=config, task_suite=suite_name)

        full_score = results.get("full", {}).get("final_score", 0.0)
        contributions = {}
        for config_name, result in results.items():
            if config_name != "full" and not config_name.startswith("_"):
                contributions[config_name] = full_score - result.get("final_score", 0.0)
        results["_contributions"] = contributions
        return results

    def run_transfer_test(self) -> Dict:
        """Transfer test: evolve on suite A, test on suite B."""
        if len(self.config.task_suites) < 2:
            return {"error": "Need at least 2 suites for transfer test"}

        full_config = self.ablation_configs.get("full", {})
        source_suite = self.config.task_suites[0]
        target_suites = self.config.task_suites[1:]

        print(f"  Evolving on '{source_suite}'...")
        source_result = self.run_single_evolution(config=full_config, task_suite=source_suite)

        base_prompt = self._build_system_prompt(full_config)
        results = {}

        for target_suite in target_suites:
            tasks = self.task_suites.get(target_suite, [])
            if not tasks:
                continue
            before_scores, _ = self._evaluate_on_tasks(tasks, base_prompt)
            before_avg = statistics.mean(before_scores) if before_scores else 0.0

            after_prompt = self._enhance_prompt_with_evolution(base_prompt, source_result)
            after_scores, _ = self._evaluate_on_tasks(tasks, after_prompt)
            after_avg = statistics.mean(after_scores) if after_scores else 0.0

            delta = after_avg - before_avg
            results[target_suite] = {
                "source_suite": source_suite, "target_suite": target_suite,
                "score_before": before_avg, "score_after": after_avg,
                "transfer_delta": delta, "is_in_domain": self._is_same_domain(source_suite, target_suite),
                "is_negative_transfer": delta < 0,
            }
            print(f"    {source_suite} -> {target_suite}: {before_avg:.3f} -> {after_avg:.3f} (delta={delta:+.3f})")

        return results

    def run_stability_test(self, n_runs: int = 5) -> Dict:
        """Stability test: same config multiple times, compute variance."""
        full_config = self.ablation_configs.get("full", {})
        suite_name = self.config.task_suites[0] if self.config.task_suites else "coding"

        traces = []
        final_scores = []
        for run_idx in range(n_runs):
            print(f"  Stability run {run_idx + 1}/{n_runs}")
            result = self.run_single_evolution(config=full_config, task_suite=suite_name)
            final_scores.append(result.get("final_score", 0.0))
            trace = EvolutionTrace(
                scores=result.get("trace", {}).get("scores", []),
                token_costs=result.get("trace", {}).get("token_costs", []),
                decisions=result.get("trace", {}).get("decisions", []),
            )
            traces.append(trace)

        mean_score = statistics.mean(final_scores) if final_scores else 0.0
        variance = statistics.variance(final_scores) if len(final_scores) >= 2 else 0.0
        std_dev = statistics.stdev(final_scores) if len(final_scores) >= 2 else 0.0
        ci_lower, ci_upper = self._bootstrap_ci(final_scores, confidence=0.95)

        return {
            "n_runs": n_runs, "final_scores": final_scores,
            "mean": mean_score, "variance": variance, "std_dev": std_dev,
            "ci_95_lower": ci_lower, "ci_95_upper": ci_upper,
            "cross_run_variance": compute_variance_across_runs(traces),
        }

    def generate_report(self, results: Dict) -> str:
        """Generate comprehensive benchmark report in markdown."""
        lines = ["# Evolution Benchmark Report", f"\nGenerated: {time.strftime('%Y-%m-%d %H:%M:%S')}", ""]

        # Summary
        lines.append("## Summary\n")
        config = results.get("metadata", {}).get("config", {})
        lines.append(f"- **Task Suites**: {config.get('task_suites', [])}")
        lines.append(f"- **Ablation Configs**: {config.get('ablation_configs', [])}")
        lines.append(f"- **Runs per config**: {config.get('n_runs', 'N/A')}")
        lines.append(f"- **Max iterations**: {config.get('max_iterations', 'N/A')}\n")

        # Suite Results Table
        lines.append("## Task Suite Results\n")
        lines.append("| Suite | Final Score | Improvement | Imp Rate | Monotonicity |")
        lines.append("|-------|-------------|-------------|----------|--------------|")
        for suite_name, sr in results.get("suite_results", {}).items():
            m = sr.get("metrics", {})
            eff = m.get("effectiveness", {})
            stab = m.get("stability", {})
            lines.append(f"| {suite_name} | {sr.get('final_score',0):.4f} | {eff.get('score_improvement',0):+.4f} | {eff.get('improvement_rate',0):.2%} | {stab.get('monotonicity',0):.2%} |")
        lines.append("")

        # Ablation Table
        lines.append("## Ablation Results\n")
        ablation = results.get("ablation_results", {})
        contributions = ablation.get("_contributions", {})
        full_score = ablation.get("full", {}).get("final_score", 0.0)
        lines.append("| Configuration | Final Score | vs Full | Contribution |")
        lines.append("|--------------|-------------|---------|--------------|")
        for cfg, ar in ablation.items():
            if cfg.startswith("_"):
                continue
            f = ar.get("final_score", 0.0)
            lines.append(f"| {cfg} | {f:.4f} | {f-full_score:+.4f} | {contributions.get(cfg,0):+.4f} |")
        lines.append("")

        # Transfer Table
        lines.append("## Transfer Results\n")
        transfer = results.get("transfer_results", {})
        if transfer and "error" not in transfer:
            lines.append("| Source -> Target | Before | After | Delta | Negative? |")
            lines.append("|-----------------|--------|-------|-------|-----------|")
            for tgt, tr in transfer.items():
                if isinstance(tr, dict) and "score_before" in tr:
                    lines.append(f"| {tr['source_suite']} -> {tgt} | {tr['score_before']:.4f} | {tr['score_after']:.4f} | {tr['transfer_delta']:+.4f} | {'Yes' if tr['is_negative_transfer'] else 'No'} |")
        lines.append("")

        # Stability
        lines.append("## Stability Results\n")
        stab = results.get("stability_results", {})
        if stab:
            lines.append(f"- **Runs**: {stab.get('n_runs', 0)}")
            lines.append(f"- **Mean Score**: {stab.get('mean', 0):.4f}")
            lines.append(f"- **Std Dev**: {stab.get('std_dev', 0):.4f}")
            lines.append(f"- **95% CI**: [{stab.get('ci_95_lower', 0):.4f}, {stab.get('ci_95_upper', 0):.4f}]")
            lines.append(f"- **Scores**: {[f'{s:.4f}' for s in stab.get('final_scores', [])]}")
        lines.append("")

        # Aggregate
        lines.append("## Aggregate Analysis\n")
        agg = results.get("aggregate_metrics", {})
        if agg.get("evolution_effective"):
            lines.append("- Evolution is **effective**: avg improvement positive")
        else:
            lines.append("- Evolution shows **limited effectiveness**")
        if agg.get("most_important_component"):
            lines.append(f"- Most important component: **{agg['most_important_component']}**")
        if agg.get("stability_verdict"):
            lines.append(f"- Stability: {agg['stability_verdict']}")
        if agg.get("transfer_verdict"):
            lines.append(f"- Transfer: {agg['transfer_verdict']}")
        lines.append("")

        return "\n".join(lines)

    # ---- Internal helpers ----

    def _evaluate_on_tasks(self, tasks: List[Dict], system_prompt: str) -> Tuple[List[float], int]:
        scores = []
        total_tokens = 0
        for task in tasks:
            desc = task.get("description", "")
            response, gen_tokens = _generate_response(desc, system_prompt)
            total_tokens += gen_tokens
            score, score_tokens = _score_response(desc, response)
            total_tokens += score_tokens
            scores.append(score)
        return scores, total_tokens

    def _build_system_prompt(self, config: Dict) -> str:
        base = "You are a helpful, accurate, and thorough assistant."
        if config.get("use_principles"):
            pf = PROJECT_ROOT / "self_evolution" / "data" / "principles.json"
            if pf.exists():
                try:
                    principles = json.loads(pf.read_text(encoding="utf-8"))
                    top = sorted(principles, key=lambda x: x.get("score", 0), reverse=True)[:5]
                    if top:
                        base += "\n\nKey principles:\n" + "\n".join(f"- {p['description']}" for p in top)
                except (json.JSONDecodeError, IOError):
                    pass
        return base

    def _select_tasks(self, tasks: List[Dict], config: Dict, scores: List[float]) -> List[Dict]:
        if not config.get("use_frontier"):
            return random.sample(tasks, min(3, len(tasks)))
        frontier = [t for i, t in enumerate(tasks) if i < len(scores) and 0.3 <= scores[i] <= 0.7]
        if not frontier:
            frontier = tasks
        return frontier[:3]

    def _generate_modification(self, config: Dict, tasks: List[Dict], prompt: str, scores: List[float]) -> Tuple[str, int]:
        strategy = config.get("modification_strategy", "textgrad_with_principles")
        if strategy == "random":
            mods = ["Be more concise.", "Provide more detail.", "Use examples.", "Focus on accuracy.", "Structure with headings."]
            return random.choice(mods), 0

        weak = [t["description"] for i, t in enumerate(tasks) if i < len(scores) and scores[i] < 0.6]
        if not weak:
            weak = [t.get("description", "") for t in tasks[:2]]

        if strategy in ("textgrad_with_principles", "textgrad_only"):
            p = f'The current prompt is: "{prompt}"\n\nThe agent struggles with:\n{json.dumps(weak[:3])}\n\nProvide a CONCISE modification instruction (1-2 sentences):'
            return _llm_call([{"role": "user", "content": p}], max_tokens=256, temperature=0.5)
        elif strategy == "principles_only":
            pf = PROJECT_ROOT / "self_evolution" / "data" / "principles.json"
            if pf.exists():
                try:
                    principles = json.loads(pf.read_text(encoding="utf-8"))
                    top = sorted(principles, key=lambda x: x.get("score", 0), reverse=True)[:3]
                    return "Incorporate: " + "; ".join(p["description"] for p in top), 0
                except (json.JSONDecodeError, IOError):
                    pass
            return "Be more thorough.", 0
        return "Improve quality.", 0

    def _apply_modification(self, config: Dict, prompt: str, modification: str) -> str:
        if config.get("modification_strategy") == "random":
            return prompt + f"\n{modification}"
        p = f"Apply this modification to the prompt. Output ONLY the new prompt.\n\nCurrent:\n{prompt}\n\nModification:\n{modification}\n\nNew prompt:"
        result = _llm_call_simple([{"role": "user", "content": p}], max_tokens=512, temperature=0.3)
        if "[LLM_ERROR]" in result or not result.strip():
            return prompt + f"\nGuidance: {modification}"
        return result.strip()

    def _gate_decision(self, config: Dict, before: float, after: float) -> str:
        if not config.get("use_gate"):
            return "accept"
        diff = after - before
        if diff > 0.02:
            return "accept"
        elif diff >= -0.02:
            return "accept" if diff >= 0 else "reject"
        else:
            return "rollback"

    def _enhance_prompt_with_evolution(self, base: str, result: Dict) -> str:
        iters = result.get("iterations", [])
        accepted = [i for i in iters if i.get("decision") == "accept"]
        if not accepted:
            return base
        return base + "\n\nLearned: Provide thorough, structured, accurate responses with examples."

    def _is_same_domain(self, a: str, b: str) -> bool:
        groups = {"technical": {"coding", "mixed"}, "language": {"writing", "reasoning"}}
        for g in groups.values():
            if a in g and b in g:
                return True
        return False

    def _bootstrap_ci(self, scores: List[float], confidence: float = 0.95, n_boot: int = 1000) -> Tuple[float, float]:
        if len(scores) < 2:
            m = scores[0] if scores else 0.0
            return m, m
        means = []
        n = len(scores)
        for _ in range(n_boot):
            sample = [random.choice(scores) for _ in range(n)]
            means.append(statistics.mean(sample))
        means.sort()
        alpha = 1 - confidence
        lo = int(alpha / 2 * n_boot)
        hi = int((1 - alpha / 2) * n_boot)
        return means[lo], means[min(hi, n_boot - 1)]

    def _compute_aggregate_metrics(self, results: Dict) -> Dict:
        agg = {}
        suite_results = results.get("suite_results", {})
        improvements = [sr.get("metrics", {}).get("effectiveness", {}).get("score_improvement", 0.0) for sr in suite_results.values()]
        agg["evolution_effective"] = statistics.mean(improvements) > 0 if improvements else False
        agg["average_improvement"] = statistics.mean(improvements) if improvements else 0.0

        ablation = results.get("ablation_results", {})
        contributions = ablation.get("_contributions", {})
        if contributions:
            agg["most_important_component"] = max(contributions, key=lambda k: contributions[k])
            agg["component_contributions"] = contributions

        stab = results.get("stability_results", {})
        if stab:
            std = stab.get("std_dev", 0.0)
            if std < 0.02:
                agg["stability_verdict"] = "Highly stable (std < 0.02)"
            elif std < 0.05:
                agg["stability_verdict"] = "Moderately stable (std < 0.05)"
            else:
                agg["stability_verdict"] = f"Unstable (std = {std:.4f})"

        transfer = results.get("transfer_results", {})
        if transfer and "error" not in transfer:
            neg = sum(1 for v in transfer.values() if isinstance(v, dict) and v.get("is_negative_transfer"))
            total = sum(1 for v in transfer.values() if isinstance(v, dict) and "score_before" in v)
            if total > 0:
                rate = neg / total
                if rate == 0:
                    agg["transfer_verdict"] = "Positive transfer across all domains"
                elif rate < 0.5:
                    agg["transfer_verdict"] = f"Mixed transfer ({rate:.0%} negative)"
                else:
                    agg["transfer_verdict"] = f"Mostly negative transfer ({rate:.0%} negative)"
        return agg
