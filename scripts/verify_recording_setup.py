"""Preflight the local EgoAgent recording environment without exposing secrets.

The default run is offline apart from localhost checks.  ``--live`` also sends
one minimal provider probe and therefore may consume a small number of tokens.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.audit_harness_catalog import audit
from scripts.reset_video_demo import (
    EVOLUTION_ARTIFACTS,
    FLOW_DEMO_BASELINES,
    RECORDING_CREATED_ARTIFACTS,
    changed_flow_demos,
)


BACKEND = "http://127.0.0.1:8765"
IDE = "http://127.0.0.1:8880"
FIXTURE = ROOT / "tutorial_assets" / "video_demo_repo"


def request_json(method: str, path: str, body: dict | None = None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        BACKEND + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def require(condition, message: str):
    if not condition:
        raise AssertionError(message)


def check_local_services():
    with urllib.request.urlopen(IDE + "/", timeout=8) as response:
        require(response.status == 200, "IDE proxy on 8880 is not healthy")
    harnesses = request_json("GET", "/api/harnesses")
    require(isinstance(harnesses, list) and harnesses, "backend did not return Harnesses")
    print(f"PASS services: IDE 8880 + backend 8765; harnesses={len(harnesses)}")


def check_catalog():
    report = audit(ROOT)
    # The editor persists an untouched "new_harness" as a local draft before
    # it has any nodes.  It is intentionally not runnable and must not be
    # presented as a validated Catalog entry, but it also should not block a
    # recording preflight.  Every other invalid Harness remains a hard error.
    ignored_drafts = [
        item for item in report["harnesses"]
        if item["name"] == "new_harness"
        and item["nodes"] == 0
        and not item["description"]
        and not item["ok"]
    ]
    failures = [
        item for item in report["harnesses"]
        if not item["ok"] and item not in ignored_drafts
    ]
    require(
        not failures,
        "Harness audit failures: "
        + "; ".join(f"{item['name']}: {', '.join(item['errors'])}" for item in failures),
    )
    names = {item["name"] for item in report["harnesses"]}
    required = {
        "tutorial_full_stack_code_agent",
        "codex_flow",
        "deepseek_harness_replica",
        "arc_scientific_search",
        "component_context_compactor",
        "component_context_curator",
        "component_repeat_tool_guard",
        "component_tool_result_pruner",
        "flow_evolution_showcase",
        "demo_fragile_release_flow",
        "demo_noisy_research_flow",
    }
    require(required <= names, "recording Harnesses are missing: " + ", ".join(sorted(required - names)))
    validated = sum(1 for item in report["harnesses"] if item["ok"])
    draft_note = f", ignored empty drafts={len(ignored_drafts)}" if ignored_drafts else ""
    print(f"PASS harness catalog: {validated} runnable Harnesses validated{draft_note}")


def check_tutorial_assets():
    task_path = ROOT / "task_bench" / "tasks" / "video_code_agent_walkthrough.json"
    task = json.loads(task_path.read_text(encoding="utf-8"))
    expected = task["workspace"]["files"]
    drift = [
        relative for relative, content in expected.items()
        if not (FIXTURE / relative).is_file()
        or (FIXTURE / relative).read_text(encoding="utf-8") != content
    ]
    require(not drift, "recording fixture needs reset: " + ", ".join(drift))
    require(
        not changed_flow_demos(),
        "Flow evolution fixtures need reset: " + ", ".join(changed_flow_demos()),
    )
    namespace: dict = {}
    exec((FIXTURE / "garden.py").read_text(encoding="utf-8"), namespace)
    require(namespace["should_water"](20) is False, "fixture bug was already fixed; reset it")
    require(namespace["water_millilitres"](12, 5) == 17, "fixture arithmetic bug was already fixed; reset it")
    review_query = urllib.parse.urlencode({"workspace": str(FIXTURE)})
    require(
        request_json("GET", f"/api/session/changes?{review_query}") == [],
        "recording fixture has stale Agent Changes; run reset_video_demo.py again",
    )
    present_artifacts = [str(path.relative_to(ROOT)) for path in EVOLUTION_ARTIFACTS if path.is_dir()]
    require(
        not present_artifacts,
        "self-evolution recording is not fresh; run reset_video_demo.py --reset-evolution-artifact: "
        + ", ".join(present_artifacts),
    )
    present_created = [str(path.relative_to(ROOT)) for path in RECORDING_CREATED_ARTIFACTS if path.exists()]
    require(
        not present_created,
        "tutorial-created artifacts are not fresh; run reset_video_demo.py --reset-created-artifacts: "
        + ", ".join(present_created),
    )
    print(f"PASS tutorial fixture: {len(expected)} canonical files, intentional bugs present")


def check_product_apis():
    tasks = request_json("GET", "/api/task-bench/tasks")
    task_items = tasks.get("tasks", tasks) if isinstance(tasks, dict) else tasks
    task_ids = {item.get("id") for item in task_items}
    expected_tasks = {
        "video_code_agent_walkthrough",
        "video_capability_evolution_walkthrough",
        "video_context_governance_walkthrough",
        "video_self_evolution_walkthrough",
        "video_agent_factory_live",
        "video_flow_safety_evolution",
        "video_subflow_extraction_evolution",
    }
    require(expected_tasks <= task_ids, "recording Tasks are missing: " + ", ".join(sorted(expected_tasks - task_ids)))

    identities = request_json("GET", "/api/identities")
    identity_names = {item.get("name") for item in identities}
    required_identities = {"coder", "dante", "openmanus", "codex_operator", "deepseek_operator"}
    require(
        required_identities <= identity_names,
        "recording Identities are missing: " + ", ".join(sorted(required_identities - identity_names)),
    )
    environments = request_json("GET", "/api/environments")
    require(any(item.get("name") == "egoagent" for item in environments), "root egoagent Environment is missing")

    search = request_json("POST", "/api/capabilities/search", {
        "workspace": str(FIXTURE),
        "query": "压缩长上下文的可复用子 DAG",
        "kinds": ["harness"],
        "limit": 8,
        "mode": "hybrid",
    })
    items = search.get("results", search.get("items", [])) if isinstance(search, dict) else search
    reusable = [
        item for item in items
        if "typed_subdag" in ((item.get("reuse") or {}).get("modes") or [])
    ]
    require(reusable, "DAG search returned no typed SubDAG reuse contract")
    first = reusable[0]
    print(
        "PASS product APIs: seven recording Tasks + Identity/Environment visible; "
        f"DAG search reusable={first.get('name')}"
    )


def check_frontend_recording_contracts():
    """Catch source/bundle drift for interactions that are hard to see via HTTP."""
    extension = ROOT / "void_extension" / "egoagent-dag-chat"
    chat = (extension / "media" / "chat.js").read_text(encoding="utf-8")
    manifest = json.loads((extension / "package.json").read_text(encoding="utf-8"))
    app = (ROOT / "harness_editor" / "src" / "App.tsx").read_text(encoding="utf-8")
    session_ui = (ROOT / "harness_editor" / "src" / "components" / "SessionExplorer.tsx").read_text(encoding="utf-8")
    packaged_assets = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in (extension / "workbench" / "assets").glob("*")
        if path.suffix in {".css", ".js"}
    )

    require(
        "addEvent('system', 'error', '发送失败', detail)" in chat
        and "发送失败 · 请查看错误详情" in chat,
        "Chat bundle lacks actionable startup failure details",
    )
    require("[${kind}: ${title}]" in chat, "Chat bundle lacks in-message attachment references")
    require("pendingContextPastes: new Map()" in chat, "Chat bundle cannot guard unresolved attachment pastes")
    require("function syncComposerContexts()" in chat and ".inline-attachment[data-context-id]" in chat,
            "deleting an attachment chip would leave hidden context attached")
    require("function casualTurnText(text, pastedContexts = [])" in chat,
            "pasted casual text would be misclassified as a repository task")
    require("const requestText = casualText || text" in chat,
            "pasted casual text is not restored before entering the Harness")
    commands = {item.get("command") for item in manifest.get("contributes", {}).get("commands", [])}
    require({
        "egoagent.copyEditorContext", "egoagent.copyTerminalContext",
        "egoagent.attachFileToChat", "egoagent.attachSelectionToChat",
    } <= commands,
            "structured editor/terminal copy commands are missing")
    for label in ("Home", "Build", "Evaluate", "Library", "Improve", "Deploy", "Sessions", "Settings"):
        require(f"label: '{label}'" in app, f"Workbench route is missing: {label}")
    require('className="session-explorer-list"' in session_ui, "Sessions responsive layout hook is missing")
    require(".session-explorer-list" in packaged_assets, "packaged Workbench is stale; run npm run package:extension")
    require("LIVE ARCHITECTURE" in packaged_assets, "packaged Workbench lacks real-time Agent topology")
    require("Flow 版本变化" in packaged_assets, "packaged Workbench lacks structural mutation projection")
    print("PASS frontend contracts: attachment order, startup errors, copy commands, routes and narrow Sessions bundle")


def check_offline_task_bench():
    """Exercise the real Agent -> Tool -> Agent loop without spending API tokens."""
    created = request_json("POST", "/api/task-bench/runs", {
        "task_id": "offline_trace_smoke",
        "harness": "aider_review_worker",
        "identity": "test_bot",
        "slot_bindings": {"reviewer": "test_bot"},
        "environments": [],
        "debug_mode": "auto",
    })
    run_id = str(created.get("id", ""))
    require(run_id, "offline Task Bench smoke did not return a run id")
    deadline = time.monotonic() + 20
    state = created
    while state.get("running") and time.monotonic() < deadline:
        time.sleep(0.1)
        state = request_json("GET", f"/api/task-bench/runs/{run_id}")
    require(not state.get("running"), f"offline Task Bench smoke did not finish: {run_id}")
    evaluation = state.get("evaluation") or {}
    require(state.get("status") == "passed" and evaluation.get("passed"),
            f"offline Task Bench smoke failed: {run_id} ({state.get('error') or evaluation.get('score')})")
    stats = state.get("stats") or {}
    require(int(stats.get("model_calls", 0)) == 3, "offline Task Bench smoke did not execute all model rounds")
    require(int(stats.get("tool_calls", 0)) == 2, "offline Task Bench smoke did not execute both tools")
    print(f"PASS Task Bench runtime: {run_id}; Agent x3, Tool x2, score=100%")


def check_provider(live: bool):
    status = request_json("GET", "/api/ai/status")
    require(status.get("configured"), "AI provider is not configured")
    print(f"PASS provider config: {status.get('provider')} / {status.get('model')} (key not printed)")
    if live:
        result = request_json("POST", "/api/ai/probe", {})
        require(result.get("healthy"), f"live provider probe failed: {result.get('error') or 'unknown error'}")
        print("PASS live provider probe: one real model response received")


def check_live_chat_roundtrip():
    """Exercise startup plus several distinct casual turns in one live run."""
    run_id = ""
    try:
        started = request_json("POST", "/api/execution/start", {
            "harness": "adaptive_code_agent",
            "agents": {"agent": "identity/openmanus", "governor": "identity/dante"},
            "workspace": str(FIXTURE),
            "mode": "chat",
            "mutation_targets": [],
        })
        run_id = str(started.get("run_id", ""))
        require(run_id, "interactive Chat startup returned no run id")

        deadline = time.monotonic() + 20
        state = started
        while time.monotonic() < deadline:
            state = request_json("GET", f"/api/execution/state?run_id={urllib.parse.quote(run_id)}")
            if state.get("waiting_for_input"):
                break
            require(state.get("running"), f"Chat ended before input: {state.get('termination')}")
            time.sleep(0.15)
        require(state.get("waiting_for_input"), "Chat did not reach its input node")

        for turn, prompt in enumerate(("你好", "你好", "说话啊"), start=1):
            previous_steps = int(state.get("step_count", 0))
            request_json("POST", "/api/execution/input", {"run_id": run_id, "text": prompt})
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                state = request_json("GET", f"/api/execution/state?run_id={urllib.parse.quote(run_id)}")
                if state.get("waiting_for_input") and int(state.get("step_count", 0)) >= previous_steps + 4:
                    break
                require(state.get("running"), f"Chat ended during casual turn {turn}: {state.get('termination')}")
                time.sleep(0.2)
            outputs = [item for item in state.get("outputs", []) if str(item.get("text", "")).strip()]
            require(state.get("waiting_for_input"), f"Chat turn {turn} did not return to the input node")
            require(len(outputs) == turn, f"turn {turn} should have its own visible reply, got {len(outputs)} total")
            require(not outputs[-1].get("tools"), f"casual turn {turn} unexpectedly invoked a tool")
            require(outputs[-1].get("sealed"), f"casual turn {turn} was not closed at the model boundary")
        print(f"PASS live Chat roundtrip: {run_id}; three separate replies, zero tools, waiting for next input")
    finally:
        if run_id:
            try:
                request_json("POST", "/api/execution/stop", {"run_id": run_id})
            except (OSError, urllib.error.URLError):
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="spend a small number of tokens on a real provider probe")
    args = parser.parse_args()
    try:
        check_local_services()
        check_catalog()
        check_tutorial_assets()
        check_product_apis()
        check_frontend_recording_contracts()
        check_offline_task_bench()
        check_provider(args.live)
        if args.live:
            check_live_chat_roundtrip()
    except (AssertionError, OSError, urllib.error.URLError, ValueError) as exc:
        print(f"FAIL recording preflight: {exc}", file=sys.stderr)
        return 1
    print("RECORDING_SETUP_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
