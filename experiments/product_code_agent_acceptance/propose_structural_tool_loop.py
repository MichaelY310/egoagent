"""Ask the Flow evolver for one evidence-grounded structural candidate.

The candidate is written as an internal experimental Harness for paired Task
Bench evaluation. This script never marks it promoted or changes a recommended
product Flow.
"""

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
from flow_variants import FlowVariantError, apply_flow_variant, flow_digest
from harness import Harness
from llm.env_config import load_local_env
from pipeline_engine import PipelineRunner


BASE_PATH = ROOT / "harness" / "experiment_structural_tool_loop_base" / "config.json"
CANDIDATE_PATH = ROOT / "harness" / "experiment_structural_tool_loop_evolved" / "config.json"
RESULTS_ROOT = Path(__file__).with_name("results")


def _measured_evidence(run_file: Path) -> dict:
    run = json.loads(run_file.read_text(encoding="utf-8"))
    traces = list(run.get("node_traces") or [])
    requested = sum(
        len(((trace.get("output") or {}).get("tool_calls") or []))
        for trace in traces
        if trace.get("node_id") == "infer"
    )
    executed = int((run.get("stats") or {}).get("tool_calls") or 0)
    score = float((run.get("evaluation") or {}).get("score") or 0.0)
    return {
        "source_kind": "Task Bench measured training trajectory",
        "source_run_id": run.get("id"),
        "official_outcome": {"task_score": score, "passed": run.get("status") == "passed"},
        "runtime": {
            "node_steps": int((run.get("stats") or {}).get("node_steps") or len(traces)),
            "model_calls": int((run.get("stats") or {}).get("model_calls") or 0),
            "tool_calls_requested": requested,
            "tool_calls_executed": executed,
        },
        "measured_failure": {
            "task_failed": run.get("status") != "passed",
            "model_requested_tools": requested > 0,
            "requested_tool_calls": requested,
            "executed_tool_calls": executed,
            "tool_feedback_steps": sum(trace.get("node_id") == "tools" for trace in traces),
            "terminated_immediately_after_tool_request": bool(requested and executed == 0 and traces[-1].get("node_id") == "done"),
        },
        "constraints": [
            "Do not encode file names, arithmetic, expected outputs, tests, or task-specific knowledge.",
            "The candidate must introduce a topology change; prompt-only or scalar-only changes are ineligible.",
            "The external paired gate evaluates two validation cases, two held-out cases, and a no-action poison check.",
        ],
    }


def _evidence_catalog(evidence: dict) -> list[dict]:
    rows = []
    for group in ("official_outcome", "runtime", "measured_failure"):
        for key, value in (evidence.get(group) or {}).items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                rows.append({"path": f"{group}.{key}", "type": type(value).__name__, "current": value})
    return rows


def propose(run_file: Path, output_dir: Path | None = None) -> Path:
    base = json.loads(BASE_PATH.read_text(encoding="utf-8"))
    evidence = _measured_evidence(run_file)
    factory = AgentFactory()
    agents = {"evolver": factory.create(ROOT / "identity" / "flow_evolver", name="evolver", workspace=ROOT)}
    harness = Harness(ROOT / "harness" / "component_flow_evolver", agents=agents, workspace=ROOT)
    harness._non_interactive = True
    harness.config["pipeline"]["context"].update(
        {
            "base_config": copy.deepcopy(base),
            "evaluation_evidence": evidence,
            "allowed_paths": ["pipeline.nodes"],
            "diversity_exclusions": [],
            "mutation_catalog": [],
            "available_evidence_paths": _evidence_catalog(evidence),
        }
    )
    result = PipelineRunner(harness).run()
    value = result.result if isinstance(result.result, dict) else {}
    proposal = value.get("proposal") if isinstance(value.get("proposal"), dict) else {}
    operations = list(proposal.get("operations") or [])
    structural = any(operation.get("op") in {"insert_node_on_edge", "remove_node_and_bypass", "redirect_edge"} for operation in operations if isinstance(operation, dict))
    if not structural:
        raise FlowVariantError("model proposal did not contain an eligible structural operation")
    # Reapply from the frozen base so candidate material never depends on an
    # opaque component payload and receives the same typed validator again.
    variant = apply_flow_variant(base, proposal, allowed_paths=["pipeline.nodes"], max_operations=3)
    candidate = copy.deepcopy(variant["config"])
    candidate["name"] = "experiment_structural_tool_loop_evolved"
    candidate["description"] = "Unpromoted structural-evolution candidate generated from a measured missing tool-feedback trajectory; retained only for paired validation and held-out evaluation."
    candidate["tags"] = ["experiment", "structural-evolution", "candidate", "do-not-recommend"]
    candidate["catalog"] = {"category": "experiment", "visibility": "internal", "display_name": "Structural Tool Loop Candidate (experiment)"}
    CANDIDATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CANDIDATE_PATH.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    output_dir = output_dir or (RESULTS_ROOT / f"{timestamp}_structural_evolution_proposal_r1")
    output_dir.mkdir(parents=True, exist_ok=False)
    report = {
        "schema": "ego.product-structural-evolution-proposal.v1",
        "created_at": time.time(),
        "source_run_file": str(run_file.resolve()),
        "base_path": str(BASE_PATH.resolve()),
        "candidate_path": str(CANDIDATE_PATH.resolve()),
        "base_digest": flow_digest(base),
        "candidate_digest": flow_digest(candidate),
        "measured_evidence": evidence,
        "proposal": proposal,
        "typed_operations": variant["operations"],
        "component_stats": vars(result.stats),
        "promotion": {"promoted": False, "reason": "unevaluated; requires paired validation, held-out and poison checks"},
    }
    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"report": str(report_path), "proposal": proposal, "typed_operations": variant["operations"]}, ensure_ascii=False, indent=2))
    return report_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    load_local_env(ROOT)
    propose(args.run_file.resolve(), args.output_dir.resolve() if args.output_dir else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
