"""Export a source-only, headless distribution without deleting the product UI.

Only allowlisted Git-tracked sources/assets are copied. New core-package Python
files are included as well so this command can validate an uncommitted refactor.
Runtime data, credentials and untracked user-created capabilities stay behind.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess


CORE_PACKAGES = {"egoagent_core", "llm", "self_evolution", "task_bench", "tabletop"}
ASSET_ROOTS = {"identity", "harness", ".environment", "environment", "capability_packs"}
EXCLUDED_PARTS = {
    "__pycache__", "node_modules", ".git", ".versions", ".egoagent", "sessions",
    "data", "_runs", "snapshots", ".env", ".env.local", ".runtime", ".quarantine",
}
HEADLESS_TESTS = (
    "test_agent_creator", "test_ai_service", "test_background_workspace",
    "test_change_tracker", "test_checkpoint_manager", "test_model_router",
    "test_project_rules", "test_context_engine", "test_capability_registry", "test_capability_evolution",
    "test_capability_authoring", "test_capability_references", "test_context_policy",
    "test_dag_components", "test_dag_contracts", "test_flow_observation",
    "test_harness_blueprint", "test_harness_versions", "test_identity_composition",
    "test_node_registry", "test_pipeline_runtime", "test_port_graph",
    "test_runtime_factories", "test_session_branching", "test_subagent_lifecycle",
    "test_task_bench", "test_training_data", "test_trajectory", "test_permissions",
    "test_superego_governance", "test_codex_runtime_capabilities", "test_config_portability",
)
EXTRA_FILES = {
    "config.yaml", "LICENSE", ".env.example", "requirements-core.txt",
    "requirements.txt", "requirements-dev.txt", "docs/HEADLESS_CORE_ZH.md",
    "examples/headless/hello_flow/config.json", "scripts/export_core.py",
    "scripts/verify_headless.py",
    "scripts/prepare_verl_trajectory.py", "scripts/trajectory_training_smoke.py",
}


def _allowed(path: PurePosixPath, *, with_server: bool, with_tests: bool) -> bool:
    if path.is_absolute() or ".." in path.parts or EXCLUDED_PARTS.intersection(path.parts):
        return False
    if path.name.startswith(".env") and str(path) != ".env.example":
        return False
    if str(path) in EXTRA_FILES:
        return True
    if len(path.parts) == 1:
        return path.suffix == ".py" and path.name != "start-all.py"
    if path.parts[0] in CORE_PACKAGES | ASSET_ROOTS:
        return path.suffix in {".py", ".json", ".yaml", ".yml", ".md", ".txt", ".sh"}
    if with_server and path.parts[0] == "egoagent_server":
        return path.suffix == ".py"
    return with_tests and str(path) in {f"tests/{name}.py" for name in HEADLESS_TESTS}


def export_core(source: Path, output: Path, *, with_server=False, with_tests=False) -> dict:
    source, output = source.resolve(), output.resolve()
    # No overwrite, no cleanup of an existing path, and never export into a source package.
    if output.exists():
        raise ValueError(f"Output must be a new directory: {output}")
    if output == source or source.is_relative_to(output):
        raise ValueError("Output cannot contain the source repository")
    if output.is_relative_to(source) and output.relative_to(source).parts[0] not in {"tmp", "dist"}:
        raise ValueError("Use a directory outside the repository, or a fresh tmp/dist child")
    tracked = subprocess.run(
        ["git", "-C", str(source), "ls-files", "-z"], check=True, capture_output=True,
    ).stdout.decode("utf-8").split("\0")
    candidates = {PurePosixPath(name) for name in tracked if name}
    candidates.update(PurePosixPath(name) for name in EXTRA_FILES)
    for package in ("egoagent_core", "egoagent_server"):
        candidates.update(PurePosixPath(p.relative_to(source).as_posix())
                          for p in (source / package).rglob("*.py"))
    selected = []
    for relative in sorted(candidates):
        if not _allowed(relative, with_server=with_server, with_tests=with_tests):
            continue
        file = source / str(relative)
        if not file.is_file():  # Deleted tracked files are not resurrected.
            continue
        if file.is_symlink() or not file.resolve().is_relative_to(source):
            raise ValueError(f"Refusing to export a link outside the source tree: {relative}")
        selected.append((relative, file))
    required = {"agent.py", "pipeline_engine.py", "egoagent_core/__init__.py", "config.yaml"}
    if not required.issubset({str(relative) for relative, _ in selected}):
        raise ValueError("Source is not a complete EgoAgent checkout")
    output.mkdir(parents=True, exist_ok=False)
    entries = []
    for relative, source_file in selected:
        destination = output / str(relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_file, destination)
        entries.append({"path": str(relative), "sha256": hashlib.sha256(destination.read_bytes()).hexdigest()})
    guide = output / "docs/HEADLESS_CORE_ZH.md"
    if guide.is_file():
        shutil.copyfile(guide, output / "README.md")
    # Several legacy deterministic tests use a repository-local temporary root.
    (output / "tmp").mkdir(exist_ok=True)
    manifest = {"format": "egoagent.core-source.v1", "server": with_server,
                "tests": with_tests, "files": entries}
    (output / "core-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"output": str(output), "files": len(entries), "server": with_server, "tests": with_tests}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--with-server", action="store_true", help="Include optional HTTP/WebSocket API, no frontend")
    parser.add_argument("--with-tests", action="store_true", help="Include offline core regression tests")
    args = parser.parse_args(argv)
    result = export_core(Path(__file__).resolve().parents[1], args.output,
                         with_server=args.with_server, with_tests=args.with_tests)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
