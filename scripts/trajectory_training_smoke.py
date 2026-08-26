"""Create a deterministic multi-Agent trajectory for replay/training smoke tests.

No model API is called.  The fixture intentionally includes a context
replacement between model calls and a child Agent with a separate Session so
that exporters and trainers can prove they do not flatten distinct model
surfaces into one synthetic conversation.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from harness import Session, runtime_scope
from subagent_lifecycle import finish_subagent, link_subagent
from trajectory import TrajectoryReader, export_training_data


DEFAULT_OUTPUT = PROJECT_ROOT / ".egoagent" / "research" / "trajectory_training_smoke_v5"


def _identity(root: Path, name: str) -> SimpleNamespace:
    return SimpleNamespace(identity_path=root / "identity" / name)


def _run_context(harness, *, run_id: str, node_id: str, parent_run_id: str | None = None):
    return SimpleNamespace(
        harness=harness,
        run_id=run_id,
        parent_run_id=parent_run_id,
        current_node=node_id,
        graph={"nodes": {node_id: {"op": "Agent", "agent": next(iter(harness.agents))}}},
        secret_view=None,
    )


def _call(
    session: Session,
    harness,
    *,
    run_id: str,
    node_id: str,
    agent: str,
    messages: list[dict],
    response: str,
    parent_run_id: str | None = None,
) -> str:
    context = _run_context(harness, run_id=run_id, node_id=node_id, parent_run_id=parent_run_id)
    with runtime_scope(harness=harness, run_context=context):
        call_id = session.begin_model_call(
            messages=messages,
            tools=[],
            agent=agent,
            model="hmellor/tiny-random-LlamaForCausalLM",
            provider="deterministic-fixture",
            parameters={"stream": False, "max_tokens": 128},
            purpose="trajectory_training_smoke",
        )
        session.finish_model_call(
            call_id,
            agent=agent,
            content=response,
            finish_reason="stop",
            usage={"prompt_tokens": 16, "completion_tokens": 8},
            metadata={"fixture": True},
        )
    return call_id


def build_fixture(output: Path) -> dict:
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(
            f"Refusing to replace a non-empty experiment directory: {output}. "
            "Choose a new --output path."
        )
    session_dir = output / "session"
    export_dir = output / "export"
    root_session = Session(workspace=PROJECT_ROOT, save_dir=session_dir)
    planner = SimpleNamespace(name="planner", identity=_identity(PROJECT_ROOT, "coder"))
    parent = SimpleNamespace(
        name="trajectory_training_parent",
        workspace=PROJECT_ROOT,
        children=[],
        agents={"planner": planner},
        session=root_session,
    )

    original = {"role": "user", "content": "Inspect three modules and propose a safe refactor."}
    root_session.record(dict(original))
    root_session.record_full(dict(original))
    _call(
        root_session,
        parent,
        run_id="run_planner",
        node_id="plan",
        agent="planner",
        messages=[
            {"role": "system", "content": "You are the planning Agent."},
            dict(original),
        ],
        response="I will delegate repository evidence collection before editing.",
    )

    summary = {
        "role": "system",
        "name": "context_summary",
        "content": "Goal: propose a safe refactor. Evidence collection is delegated; no files changed yet.",
    }
    root_session.apply_context_result(
        {
            "messages": [summary],
            "full_messages": list(root_session.full_messages),
            "ledger": [{"action": "summarize", "reason": "token budget smoke"}],
            "stats": {"before_tokens_estimated": 96, "after_tokens_estimated": 24},
        }
    )

    child_session = Session(workspace=PROJECT_ROOT, save_dir=None)
    researcher = SimpleNamespace(name="researcher", identity=_identity(PROJECT_ROOT, "searcher"))
    child = SimpleNamespace(
        name="repository_research_subdag",
        workspace=PROJECT_ROOT,
        children=[],
        agents={"researcher": researcher},
        session=child_session,
        parent=None,
    )
    invocation = link_subagent(parent, child, purpose="training_smoke")
    child_prompt = {"role": "user", "content": "Return only the three most relevant module names."}
    child_session.record(dict(child_prompt))
    child_session.record_full(dict(child_prompt))
    _call(
        child_session,
        child,
        run_id="run_researcher",
        parent_run_id="run_planner",
        node_id="search",
        agent="researcher",
        messages=[
            {"role": "system", "content": "You are an isolated evidence-gathering Agent."},
            dict(child_prompt),
        ],
        response="trajectory.py, harness.py, pipeline_engine.py",
    )
    finish_subagent(child, status="completed", result={"modules": 3})

    final_messages = [
        {
            "role": "system",
            "content": (
                "You are the planning Agent.\n\n[context_summary]\n"
                "Goal: propose a safe refactor. Evidence collection is delegated; no files changed yet."
            ),
        },
        {"role": "user", "content": "Use the child result and finish the proposal."},
    ]
    final_call = _call(
        root_session,
        parent,
        run_id="run_final",
        parent_run_id="run_planner",
        node_id="finalize",
        agent="planner",
        messages=final_messages,
        response="Unify trajectory recording around Session and keep pipeline events as projections.",
    )
    final_context = _run_context(parent, run_id="run_final", node_id="finalize", parent_run_id="run_planner")
    with runtime_scope(harness=parent, run_context=final_context):
        root_session.trace(
            "evaluation.completed",
            {
                "score": 1.0,
                "reward_style": "egoagent_exact_match",
                "ground_truth": "Unify trajectory recording around Session and keep pipeline events as projections.",
                "checks": [{"name": "deterministic_fixture", "passed": True}],
                "reward_source": "deterministic_smoke_checker",
                "terminal_model_call_id": final_call,
            },
            agent="planner",
        )
    root_session.save()

    trajectory_path = session_dir / "trajectory.jsonl"
    manifest = export_training_data(trajectory_path, export_dir)
    reader = TrajectoryReader(trajectory_path)
    calls = reader.model_calls()
    by_agent = {}
    for call in calls:
        agent = str((call.get("metadata") or {}).get("agent") or "unknown")
        by_agent[agent] = by_agent.get(agent, 0) + 1
    result = {
        "trajectory": str(trajectory_path),
        "export": str(export_dir),
        "validation": reader.validate(),
        "model_calls_by_agent": by_agent,
        "final_request_messages": next(
            call["messages"] for call in calls if call["model_call_id"] == final_call
        ),
        "manifest": manifest,
    }
    (output / "smoke_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = build_fixture(args.output.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["validation"]["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
