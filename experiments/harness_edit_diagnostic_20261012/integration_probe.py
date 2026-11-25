"""Exploratory upstream-fixture integration replay, separate from primary tests."""
from __future__ import annotations

import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent


def probe(cid: str):
    import yaml
    from minisweagent.exceptions import FormatError

    config = yaml.safe_load(Path("src/minisweagent/config/mini.yaml").read_text())
    if cid == "40fa3652":
        from minisweagent.agents.default import DefaultAgent
        from minisweagent.environments.local import LocalEnvironment
        from minisweagent.models.openrouter_model import OpenRouterModel
        fixture = runpy.run_path("tests/models/test_format_error_response_persistence.py")
        response = fixture["_bad_chat_completion_dict"]()
        model = OpenRouterModel(model_name="test/model")
        agent = DefaultAgent(model, LocalEnvironment(), **(config["agent"] | {"cost_limit": 2.5 * response["usage"]["cost"], "step_limit": 8, "max_consecutive_format_errors": 0}))
        with patch.object(OpenRouterModel, "_query", return_value=response):
            info = agent.run("Test billed format errors")
        return {"cost": agent.cost, "calls": agent.n_calls, "exit_status": info["exit_status"], "expected_calls": 3, "expected_cost": 0.03, "passed": agent.n_calls == 3 and abs(agent.cost - 0.03) < 1e-8}
    if cid == "147121ff":
        fixture = runpy.run_path("tests/models/test_truncation_finish_reason.py")
        from minisweagent.models.utils.actions_toolcall import parse_toolcall_actions
        try:
            parse_toolcall_actions([fixture["_toolcall"]("shell", '{"command": "ls"}')], format_error_template=config["model"]["format_error_template"], template_kwargs={"finish_reason": "tool_calls"})
        except FormatError as error:
            content = error.messages[0]["content"]
            return {"message": content, "passed": "Unknown tool 'shell'" in content and "cut off" not in content}
    elif cid == "640165a5":
        from minisweagent.models.openrouter_response_model import OpenRouterResponseModel
        model = OpenRouterResponseModel(model_name="test/model", format_error_template=config["model"]["format_error_template"])
        # Exact dict from TestFinishReasonFromResponsesApi; output defaults to []
        # in the production adapter. Invoke the parent/child adapter's own API,
        # not a new utility signature unavailable to the old implementation.
        response = {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}}
        try:
            model._parse_actions(response)
        except FormatError as error:
            content = error.messages[0]["content"][0]["text"]
            return {"message": content, "passed": "cut off" in content}
    return {"passed": False, "error": "Expected FormatError not raised"}


def main():
    manifest = json.loads((ROOT / "results/replay_manifest.json").read_text())
    result_path = ROOT / "results/integration_probes_v3.json"
    if result_path.exists():
        raise RuntimeError("Preserve recorded results; choose a new batch for a rerun")
    rows = []
    for case in manifest["cases"]:
        if case["id"] not in {"40fa3652", "147121ff", "640165a5"}:
            continue
        for cell in case["cells"]:
            tree = ROOT / cell["tree"]
            home = tree / ".probe-home"
            home.mkdir(exist_ok=True)
            env = {"PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin", "HOME": str(home), "LANG": "C.UTF-8", "MSWEA_GLOBAL_CONFIG_DIR": str(home / "config"), "MSWEA_SILENT_STARTUP": "1", "LITELLM_LOCAL_MODEL_COST_MAP": "True", "PYTHONPATH": str(ROOT / "safety") + ":" + str(tree / "src")}
            p = subprocess.run([sys.executable, str(Path(__file__).resolve()), case["id"]], cwd=tree, env=env, capture_output=True, text=True, timeout=30)
            try:
                payload = json.loads(p.stdout.strip().splitlines()[-1])
            except (ValueError, IndexError):
                payload = {"passed": False, "infrastructure_error": True, "stdout": p.stdout, "stderr": p.stderr}
            row = {"case": case["id"], "components": cell["components"], "label": cell["label"], **payload}
            rows.append(row)
            print(json.dumps(row), flush=True)
    result_path.write_text(json.dumps({"kind": "posthoc integration probes, not upstream test suite", "rows": rows}, indent=2) + "\n")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        main()
    else:
        try:
            print(json.dumps(probe(sys.argv[1])))
        except Exception as error:
            print(json.dumps({"passed": False, "exception": type(error).__name__, "message": str(error)}))
