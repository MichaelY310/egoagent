"""Use the Flow-evolver component to produce an isolated ARC solver candidate."""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_factory import AgentFactory
from flow_variants import build_flow_variant_population, write_flow_variant
from harness import Harness
from llm.env_config import load_local_env
from pipeline_engine import PipelineRunner


def _leaf_catalog(value, *, prefix="", allowed_prefixes=(), max_items=180):
    """Reflect compact, real scalar paths for weak-model structured editing."""

    items = []

    def visit(child, path):
        if len(items) >= max(1, int(max_items)):
            return
        if isinstance(child, dict):
            for key, nested in child.items():
                visit(nested, f"{path}.{key}" if path else str(key))
            return
        if isinstance(child, list):
            return
        if allowed_prefixes and not any(
            path == allowed or path.startswith(allowed + ".")
            for allowed in allowed_prefixes
        ):
            return
        if path.endswith((".id", ".op")):
            return
        preview = child
        if isinstance(preview, str) and len(preview) > 220:
            preview = preview[:217] + "..."
        suffix = path.rsplit(".", 1)[-1]
        semantics = {
            "max_tokens": "maximum generated OUTPUT tokens for this model call; not context length or call count",
            "max_chars": "maximum selected characters passed through this context view",
            "last_n": "number of recent messages retained by this context view",
            "condition": "safe routing/cadence expression evaluated at runtime",
            "max_model_calls": "hard run-budget ceiling; raising it does not improve policy",
            "max_tool_calls": "hard tool-budget ceiling; raising it does not improve policy",
            "repetition_ngram_size": "token n-gram length used only for generated-text repetition detection",
            "repetition_ratio_threshold": "generated-text repetition detector threshold",
            "repetition_min_tokens": "minimum generated tokens before text repetition detection",
        }.get(suffix)
        item = {"path": path, "type": type(child).__name__, "current": preview}
        if semantics:
            item["semantics"] = semantics
        items.append(item)

    visit(value, prefix)
    return items


def _compact_evidence(result_path: Path) -> dict:
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    actions = []
    action_signatures = []
    invalid_actions = 0
    unique_states = set()
    revisited_states = 0
    no_change_actions = 0
    for item in payload.get("trajectory", []):
        raw = item.get("observation")
        try:
            observation = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except ValueError:
            observation = {}
        if item.get("action") == "arc_act":
            arguments = item.get("arguments") or {}
            action = observation.get("action") or {}
            name = str(action.get("name") or arguments.get("action") or "UNKNOWN")
            actions.append(name)
            signature = json.dumps(
                {key: arguments.get(key) for key in ("action", "x", "y") if arguments.get(key) is not None},
                ensure_ascii=False,
                sort_keys=True,
            )
            action_signatures.append(signature)
            invalid_actions += not bool(observation.get("ok", item.get("ok", False)))
            grid_hash = observation.get("grid_hash")
            if grid_hash:
                revisited_states += grid_hash in unique_states
                unique_states.add(grid_hash)
            no_change_actions += int(observation.get("changed_cells", 1) == 0)
    memories = []
    result = payload.get("result") or {}
    if isinstance(result, dict):
        for memory in (result.get("memory") or [])[-4:]:
            memories.append([str(keyword) for keyword in memory.get("keywords", [])])
    histogram = {name: actions.count(name) for name in sorted(set(actions))}
    longest_streak = 0
    current_streak = 0
    previous = None
    for name in actions:
        current_streak = current_streak + 1 if name == previous else 1
        longest_streak = max(longest_streak, current_streak)
        previous = name
    longest_signature_streak = 0
    current_signature_streak = 0
    previous_signature = None
    for signature in action_signatures:
        current_signature_streak = current_signature_streak + 1 if signature == previous_signature else 1
        longest_signature_streak = max(longest_signature_streak, current_signature_streak)
        previous_signature = signature
    official = payload.get("official_outcome") or {}
    result_data = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    ledger = result_data.get("ledger") if isinstance(result_data, dict) else None
    measured = {
        "environment_actions_attempted": len(actions),
        "environment_action_budget": int(payload.get("action_budget") or 0),
        "action_budget_completed": len(actions) >= int(payload.get("action_budget") or 0),
        "premature_termination_observed": len(actions) < int(payload.get("action_budget") or 0),
        "invalid_action_calls": int(invalid_actions),
        "distinct_action_classes": len(histogram),
        "longest_identical_action_class_streak": longest_streak,
        "longest_identical_action_signature_streak": longest_signature_streak,
        "unique_observed_states": len(unique_states),
        "revisited_state_actions": int(revisited_states),
        "no_change_actions": int(no_change_actions),
        "levels_completed": official.get("total_levels_completed", 0),
        "score": official.get("score", 0),
    }
    return {
        "source_kind": "official unknown interactive environment",
        "budget": {"environment_actions": payload.get("action_budget")},
        "official_outcome": official,
        "runtime": {
            key: (payload.get("stats") or {}).get(key)
            for key in ("model_calls", "tool_calls", "input_tokens_actual", "output_tokens_actual")
        },
        "behavioral_aggregates": {
            **measured,
            "action_histogram": histogram,
            "supervision_events": len(memories),
            "supervisor_keyword_sets": memories,
            "final_belief_ledger": ledger or {},
        },
        "measured_failure": measured,
        "optimization_order": [
            "increase official score or completed levels",
            "when the primary outcome ties, reduce actual model input/output tokens or model calls",
        ],
        "constraints": [
            "No game ID, coordinate, action sequence, discovered rule or environment-specific tool may enter the candidate Flow.",
            "Official outcome is the primary promotion metric.",
            "Use paired validation and at least two independent held-out cases before promotion.",
            "No no-op mutation may consume evaluation budget.",
        ],
    }


def _propose_candidate(base: dict, evidence: dict, exclusions: list[dict]) -> tuple[dict, dict]:
    factory = AgentFactory()
    agents = {
        "evolver": factory.create(ROOT / "identity" / "flow_evolver", name="evolver", workspace=ROOT),
    }
    harness = Harness(ROOT / "harness" / "component_flow_evolver", agents=agents, workspace=ROOT)
    harness._non_interactive = True
    context = harness.config["pipeline"].setdefault("context", {})
    context.update({
        "base_config": base,
        "evaluation_evidence": evidence,
        "allowed_paths": ["pipeline.nodes", "prompts.supervise"],
        "diversity_exclusions": copy.deepcopy(exclusions),
        "mutation_catalog": _leaf_catalog(
            base,
            allowed_prefixes=("pipeline.nodes", "prompts.supervise"),
        ),
        "available_evidence_paths": _leaf_catalog(
            evidence,
            allowed_prefixes=("measured_failure", "runtime", "official_outcome", "behavioral_aggregates"),
        ),
    })
    result = PipelineRunner(harness).run()
    value = result.result if isinstance(result.result, dict) else {}
    return value, vars(result.stats)


def evolve(
    result_path: Path,
    generation: int,
    *,
    population_size: int = 3,
    base_flow: str = "arc_scientific_search",
) -> dict:
    base_path = ROOT / "harness" / base_flow / "config.json"
    base = json.loads(base_path.read_text(encoding="utf-8"))
    evidence = _compact_evidence(result_path)
    attempts = []
    exclusions: list[dict] = []
    proposals: list[dict] = []
    runtime_stats = []
    # Ask for extra attempts because invalid/no-op/duplicate candidates are
    # expected outputs of a weak model and should not collapse a generation.
    for attempt in range(max(1, int(population_size)) * 2):
        value, stats = _propose_candidate(base, evidence, exclusions)
        proposal = value.get("proposal") if isinstance(value.get("proposal"), dict) else {}
        proposals.append(proposal)
        runtime_stats.append(stats)
        attempts.append({
            "attempt": attempt + 1,
            "proposal": proposal,
            "component_variant": {
                key: child for key, child in (value.get("variant") or {}).items() if key != "config"
            },
        })
        exclusions.append({
            "hypothesis": proposal.get("hypothesis"),
            "failure_mechanism": proposal.get("failure_mechanism"),
            "operations": proposal.get("operations", []),
        })
        population = build_flow_variant_population(
            base,
            proposals,
            allowed_paths=["pipeline.nodes", "prompts.supervise"],
            max_operations=8,
            max_candidates=population_size,
            min_novelty=0.12,
            evaluation_evidence=evidence,
        )
        if len(population["accepted"]) >= max(1, int(population_size)):
            break
    population = build_flow_variant_population(
        base,
        proposals,
        allowed_paths=["pipeline.nodes", "prompts.supervise"],
        max_operations=8,
        max_candidates=population_size,
        min_novelty=0.12,
        evaluation_evidence=evidence,
    )
    output_dir = ROOT / "experiments" / "arc_agi3" / "candidates" / f"generation_{generation:03d}"
    output_dir.mkdir(parents=True, exist_ok=True)
    candidates = []
    for index, variant in enumerate(population["accepted"], start=1):
        candidate = copy.deepcopy(variant)
        candidate["config"]["name"] = f"{base_flow}_candidate_g{generation:03d}_c{index:03d}"
        candidate_path = (
            output_dir / "config.json"
            if index == 1
            else output_dir / f"candidate_{index:03d}" / "config.json"
        )
        written = write_flow_variant(candidate, candidate_path)
        candidates.append({
            "candidate_id": f"g{generation:03d}_c{index:03d}",
            "path": str(written.resolve()),
            "candidate_digest": variant["candidate_digest"],
            "proposal_signature": variant["proposal_signature"],
            "novelty": variant["novelty"],
            "verified_evidence": variant["verified_evidence"],
            "operations": variant["operations"],
            "proposal": variant["proposal"],
            "evaluation_status": "unevaluated",
        })
    report = {
        "format": "ego.flow-evolution.v2",
        "created_at": time.time(),
        "source_result": str(result_path.resolve()),
        "base_flow": base_flow,
        "base_digest": population["accepted"][0]["base_digest"] if population["accepted"] else None,
        "generation": generation,
        "evidence": evidence,
        "requested_population": int(population_size),
        "attempts": attempts,
        "candidates": candidates,
        "population_rejections": population["rejected"],
        "proposal": candidates[0]["proposal"] if candidates else None,
        "candidate_path": candidates[0]["path"] if candidates else None,
        "promoted": False,
        "promotion_reason": "unevaluated population; promotion requires paired validation and held-out result files",
        "runtime_stats": runtime_stats,
    }
    report_path = output_dir / "evolution_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", "--source-result", dest="result", type=Path, required=True)
    parser.add_argument("--generation", type=int, default=1)
    parser.add_argument("--population", type=int, default=3)
    parser.add_argument("--base-flow", default="arc_scientific_search")
    args = parser.parse_args()
    load_local_env(ROOT)
    report = evolve(
        args.result,
        max(1, args.generation),
        population_size=max(1, min(args.population, 8)),
        base_flow=args.base_flow,
    )
    # Windows consoles are not guaranteed to use UTF-8.  Escaping only the
    # diagnostic stdout keeps the UTF-8 report artifact fully human-readable.
    print(json.dumps(report, ensure_ascii=True, indent=2, default=str))
    return 0 if report.get("candidate_path") else 2


if __name__ == "__main__":
    raise SystemExit(main())
