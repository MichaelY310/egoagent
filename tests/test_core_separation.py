"""Enforce the dependency boundary and test actual frontend-free source exports."""
import ast
import importlib
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.export_core import CORE_PACKAGES, export_core


ROOT = Path(__file__).resolve().parents[1]
UI_PACKAGES = {"harness_editor", "void_extension", "desktop", "heart_flow", "egoagent_server"}


def test_core_and_executable_capabilities_never_import_ui_or_server():
    files = list(ROOT.glob("*.py"))
    for directory in CORE_PACKAGES | {"identity", ".environment", "capability_packs"}:
        files.extend((ROOT / directory).rglob("*.py"))
    violations = []
    for file in files:
        if file.name == "start-all.py" or any(part in {"__pycache__", ".versions", "snapshots", "data"} for part in file.relative_to(ROOT).parts):
            continue
        source = file.read_text(encoding="utf-8-sig")
        for node in ast.walk(ast.parse(source, filename=str(file))):
            if isinstance(node, ast.Import):
                modules = [item.name for item in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            elif (isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant)
                  and isinstance(node.args[0].value, str)
                  and ((isinstance(node.func, ast.Name) and node.func.id == "__import__")
                       or (isinstance(node.func, ast.Attribute) and node.func.attr == "import_module"))):
                modules = [node.args[0].value]
            else:
                continue
            for module in modules:
                if module.split(".", 1)[0] in UI_PACKAGES:
                    violations.append(f"{file.relative_to(ROOT)}:{node.lineno}: {module}")
    assert not violations, "Reverse dependencies:\n" + "\n".join(violations)


@pytest.mark.parametrize("name", [
    "agent_creator", "ai_service", "background_workspace", "change_tracker",
    "checkpoint_manager", "context_engine", "model_router", "project_rules",
])
def test_legacy_modules_are_aliases_not_separate_state_stores(name):
    legacy = importlib.import_module("harness_editor." + name)
    canonical = importlib.import_module("egoagent_core." + name)
    assert legacy is canonical


def clean_environment():
    return {name: value for name, value in os.environ.items()
            if not name.startswith(("EGOAGENT_", "EGO_", "DEEPSEEK_", "OPENAI_", "SILICONFLOW_", "PYTHONPATH"))
            and not name.endswith(("_API_KEY", "_TOKEN"))}


def test_pure_export_runs_actual_flow_without_ui_or_server(tmp_path):
    output = tmp_path / "headless"
    exported = export_core(ROOT, output)
    assert exported["files"] > 100
    for name in UI_PACKAGES | {"void-web", ".env.local", ".egoagent", "sessions"}:
        assert not (output / name).exists(), name
    result = subprocess.run([sys.executable, "-I", str(output / "scripts/verify_headless.py")],
                            cwd=tmp_path, capture_output=True, text=True, encoding="utf-8",
                            env=clean_environment(), timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: all public core exports" in result.stdout
    assert "EgoAgent core is running without a frontend." in result.stdout
    with pytest.raises(ValueError, match="new directory"):
        export_core(ROOT, output)


def test_optional_api_serves_without_any_frontend(tmp_path):
    output = tmp_path / "api-only"
    export_core(ROOT, output, with_server=True)
    code = r'''
import json, sys, threading, urllib.request
sys.path.insert(0, sys.argv[1])
from egoagent_server import server
httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.APIHandler)
worker = threading.Thread(target=httpd.serve_forever, daemon=True)
worker.start()
try:
    base = "http://127.0.0.1:" + str(httpd.server_port)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(base + "/", timeout=10) as response:
        assert json.load(response)["frontend"] == "not_installed"
    with opener.open(base + "/api/harnesses", timeout=10) as response:
        assert response.status == 200 and json.load(response)
    with opener.open(base + "/api/execution/state", timeout=10) as response:
        assert response.status == 200
    print("PASS: API without frontend")
finally:
    httpd.shutdown()
    httpd.server_close()
    worker.join(timeout=2)
'''
    result = subprocess.run([sys.executable, "-I", "-c", code, str(output)], cwd=tmp_path,
                            capture_output=True, text=True, encoding="utf-8", env=clean_environment(), timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: API without frontend" in result.stdout


def test_cli_accepts_agentless_flows_but_still_parses_identity_slots():
    from run_harness import build_parser
    assert build_parser().parse_args(["--harness-dir", "examples/headless/hello_flow"]).agents == []
    args = build_parser().parse_args(["--harness-dir", "harness/code_agent_fast", "--agents",
                                     "agent:identity/dante", "governor:identity/dante"])
    assert [name for name, _ in args.agents] == ["agent", "governor"]


def test_remote_bundle_includes_new_core_and_api_packages():
    from remote_workspaces import product_files
    paths = {relative for _path, relative in product_files(ROOT)}
    assert {"egoagent_core/change_tracker.py", "egoagent_core/model_router.py",
            "egoagent_server/server.py", "egoagent_server/api_extensions.py"} <= paths
