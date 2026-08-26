"""Run comparable direct and AVO-inspired EgoAgent Flows on official ARC."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "tmp" / "matplotlib"))

from agent_factory import AgentFactory
from arc_agi3_runtime import _SESSIONS, finish_arc_session
from harness import Harness
from llm.env_config import load_local_env
from pipeline_engine import PipelineRunner


def _score_from_finish(payload):
    scorecard = (payload or {}).get("scorecard") or {}
    return {
        "score": scorecard.get("score"),
        "total_levels_completed": scorecard.get("total_levels_completed"),
        "total_actions": scorecard.get("total_actions"),
        "state": (payload or {}).get("state"),
    }


def run_flow(
    flow: str,
    game: str,
    action_budget: int,
    seed: int,
    *,
    token_budget: int | None = None,
    config_path: str | Path | None = None,
) -> dict:
    factory = AgentFactory()
    agents = {"explorer": factory.create(ROOT / "identity" / "arc_explorer", name="explorer", workspace=ROOT)}
    flow_dir = Path(config_path).resolve().parent if config_path else ROOT / "harness" / flow
    raw_config = json.loads((flow_dir / "config.json").read_text(encoding="utf-8"))
    flow = str(raw_config.get("name") or flow)
    declared_slots = set((raw_config.get("slots") or {}).keys())
    if "supervisor" in declared_slots:
        agents["supervisor"] = factory.create(ROOT / "identity" / "arc_supervisor", name="supervisor", workspace=ROOT)
    if "scientist" in declared_slots:
        agents["scientist"] = factory.create(ROOT / "identity" / "arc_supervisor", name="scientist", workspace=ROOT)
    if "compactor" in declared_slots:
        agents["compactor"] = factory.create(ROOT / "identity" / "arc_supervisor", name="compactor", workspace=ROOT)
    harness = Harness(flow_dir, agents=agents, workspace=ROOT)
    harness._non_interactive = True
    graph = harness.config["pipeline"]
    memory_namespace = f"arc_run_{uuid.uuid4().hex[:16]}"
    graph.setdefault("context", {})["memory_namespace"] = memory_namespace
    graph["budget"]["max_tool_calls"] = action_budget + 3
    graph["budget"]["max_model_calls"] = action_budget * 2 + 12
    # ARC's exact 64x64 text observation is intentionally token-heavy.  This
    # is an experiment guard, not a model output limit: allow the requested
    # environment-action budget to finish while still bounding runaway loops.
    graph["budget"]["max_tokens"] = int(token_budget or max(600000, action_budget * 50000))
    request = (
        f"Play the official ARC-AGI-3 game {game} with seed {seed}. Start with arc_start. "
        f"You have at most {action_budget} environment actions, excluding start and finish. "
        "Use no game-specific prior solution. If you reach WIN, or cannot win within the budget, call arc_finish exactly once."
    )
    message = {"role": "user", "content": request}
    harness.session.record(message)
    harness.session.record_full(message.copy())
    started = time.time()
    error = None
    result = None
    try:
        result = PipelineRunner(harness).run()
    except Exception as caught:
        error = f"{type(caught).__name__}: {caught}"
    # A runtime budget can terminate before the model gets one last tool call.
    # Deterministically close any remaining official scorecard without adding
    # an environment action so the experiment is still auditable.
    forced_finishes = []
    for session_id in list(_SESSIONS):
        forced_finishes.append(finish_arc_session(session_id))
    trajectory = result.data.get("_trajectory", []) if result is not None else []
    finish_observation = None
    for item in reversed(trajectory):
        if item.get("action") == "arc_finish":
            raw = item.get("observation")
            try:
                finish_observation = json.loads(raw) if isinstance(raw, str) else raw
            except ValueError:
                finish_observation = None
            break
    if finish_observation is None and forced_finishes:
        finish_observation = forced_finishes[-1]
    payload = {
        "run_id": f"{int(started)}-{flow}-{game}-{uuid.uuid4().hex[:6]}",
        "flow": flow,
        "game": game,
        "seed": seed,
        "action_budget": action_budget,
        "elapsed_seconds": round(time.time() - started, 3),
        "error": error,
        "result": result.result if result is not None else None,
        "stats": vars(result.stats) if result is not None else None,
        "trajectory": trajectory,
        "forced_finishes": forced_finishes,
        "official_outcome": _score_from_finish(finish_observation),
        "session_dir": str(harness.session.save_dir),
        "memory_namespace": memory_namespace,
    }
    output = ROOT / "experiments" / "arc_agi3" / "results" / f"{payload['run_id']}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    payload["result_path"] = str(output.resolve())
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--flow", default="arc_long_horizon")
    parser.add_argument("--config", help="Optional candidate config.json; its parent directory is used as the Flow")
    parser.add_argument("--game", default="ls20")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--actions", type=int, default=24)
    parser.add_argument("--token-budget", type=int)
    args = parser.parse_args()
    load_local_env(ROOT)
    payload = run_flow(
        args.flow,
        args.game,
        max(1, args.actions),
        args.seed,
        token_budget=args.token_budget,
        config_path=args.config,
    )
    print(json.dumps({
        "run_id": payload["run_id"],
        "flow": payload["flow"],
        "game": payload["game"],
        "elapsed_seconds": payload["elapsed_seconds"],
        "error": payload["error"],
        "stats": payload["stats"],
        "official_outcome": payload["official_outcome"],
        "actions": [item.get("action") for item in payload["trajectory"]],
    }, ensure_ascii=False, indent=2, default=str))
    return 0 if payload["error"] is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
