"""Executable source-to-replica conformance contracts.

The suite deliberately separates what can be proven offline from parity that
depends on a real model, website, game or hosted service.  A passing structural
check is never presented as proof that an external adapter worked.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable

from pipeline_schema import validate_pipeline


ROOT = Path(__file__).resolve().parent
DEFAULT_MANIFEST = ROOT / "research_specs" / "harness_conformance.json"


class ConformanceError(ValueError):
    pass


def load_manifest(path: str | Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    source = Path(path).resolve()
    data = json.loads(source.read_text(encoding="utf-8"))
    if data.get("schema") != "ego.harness-conformance.v1":
        raise ConformanceError("unsupported conformance manifest schema")
    contracts = data.get("contracts")
    if not isinstance(contracts, list) or not contracts:
        raise ConformanceError("manifest must contain contracts")
    ids = [str(item.get("id", "")) for item in contracts]
    if any(not value for value in ids) or len(ids) != len(set(ids)):
        raise ConformanceError("contract ids must be non-empty and unique")
    return data


def contract_by_id(contract_id: str, manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    for contract in (manifest or load_manifest())["contracts"]:
        if contract["id"] == contract_id:
            return contract
    raise ConformanceError(f"unknown contract: {contract_id}")


def inspect_config(config: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    pipeline = config.get("pipeline")
    if not isinstance(pipeline, dict):
        raise ConformanceError("config has no pipeline")
    nodes = pipeline.get("nodes", {})
    if not isinstance(nodes, dict):
        raise ConformanceError("pipeline.nodes must be an object")
    node_ids = set(nodes)
    operations = {str(node.get("op", "")) for node in nodes.values() if isinstance(node, dict)}
    checks: list[dict[str, Any]] = []

    def record(check: str, passed: bool, detail: Any) -> None:
        checks.append({"check": check, "passed": bool(passed), "detail": detail})

    schema_errors = validate_pipeline(pipeline)
    record("schema", not schema_errors, schema_errors or "valid")
    record("start_exists", pipeline.get("start") in node_ids, pipeline.get("start"))
    record("bounded_steps", isinstance(pipeline.get("max_steps"), int) and pipeline["max_steps"] > 0, pipeline.get("max_steps"))
    missing_nodes = sorted(set(contract.get("required_nodes", [])) - node_ids)
    record("required_nodes", not missing_nodes, missing_nodes or "all present")
    missing_ops = sorted(set(contract.get("required_ops", [])) - operations)
    record("required_ops", not missing_ops, missing_ops or "all present")
    forbidden = sorted(set(contract.get("forbidden_ops", ["Python", "python", "代码"])) & operations)
    record("forbidden_ops", not forbidden, forbidden or "none")

    dangling: list[str] = []
    edge_count = 0
    for source, node in nodes.items():
        for edge in node.get("edges", []) or []:
            edge_count += 1
            target = edge.get("to")
            # A null target is an intentional suspension edge (for example an
            # Input node waiting for user data), not a dangling graph edge.
            if target is not None and target not in node_ids:
                dangling.append(f"{source}->{target}")
    record("edge_targets", not dangling, dangling or f"{edge_count} valid edges")
    record("source_pin", bool(contract.get("repository") and contract.get("revision")), f"{contract.get('repository')}@{contract.get('revision')}")
    record("behavioral_evidence_declared", bool(contract.get("behavioral_tests")), contract.get("behavioral_tests", []))
    return {
        "contract_id": contract["id"],
        "harness": contract["harness"],
        "passed": all(item["passed"] for item in checks),
        "checks": checks,
        "graph": {"nodes": len(nodes), "edges": edge_count, "operations": sorted(operations)},
    }


def inspect_contract(contract: dict[str, Any], root: str | Path = ROOT) -> dict[str, Any]:
    source = Path(root).resolve() / "harness" / contract["harness"] / "config.json"
    if not source.is_file():
        return {
            "contract_id": contract["id"],
            "harness": contract["harness"],
            "passed": False,
            "checks": [{"check": "config_exists", "passed": False, "detail": str(source)}],
        }
    return inspect_config(json.loads(source.read_text(encoding="utf-8")), contract)


def _run_behavioral_tests(test_names: Iterable[str], root: Path, timeout: float) -> dict[str, Any]:
    names = list(test_names)
    if not names:
        return {"passed": False, "tests": [], "output": "no behavioral tests declared"}
    # tests/ is intentionally not a Python package.  It is placed directly on
    # PYTHONPATH below, so use its importable module name rather than the
    # package-style path (which fails on a clean Windows checkout).
    targets = [f"test_harness_replicas.HarnessReplicaTests.{name}" for name in names]
    started = time.monotonic()
    try:
        environment = os.environ.copy()
        search_paths = [str(root / "tests"), str(root)]
        if environment.get("PYTHONPATH"):
            search_paths.append(environment["PYTHONPATH"])
        environment["PYTHONPATH"] = os.pathsep.join(search_paths)
        process = subprocess.run(
            [sys.executable, "-m", "unittest", *targets],
            cwd=root,
            capture_output=True,
            text=True,
            env=environment,
            timeout=timeout,
            check=False,
        )
        output = (process.stdout + "\n" + process.stderr).strip()
        return {
            "passed": process.returncode == 0,
            "tests": names,
            "returncode": process.returncode,
            "duration_seconds": round(time.monotonic() - started, 3),
            "output": output[-12000:],
        }
    except subprocess.TimeoutExpired as error:
        return {
            "passed": False,
            "tests": names,
            "duration_seconds": round(time.monotonic() - started, 3),
            "output": f"timed out after {timeout}s: {error}",
        }


def run_contract(
    contract: dict[str, Any],
    *,
    root: str | Path = ROOT,
    behavioral: bool = False,
    timeout: float = 180.0,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    structural = inspect_contract(contract, root_path)
    behavior = (
        _run_behavioral_tests(contract.get("behavioral_tests", []), root_path, timeout)
        if behavioral and structural["passed"]
        else {"passed": None, "tests": contract.get("behavioral_tests", []), "output": "not executed"}
    )
    core_passed = structural["passed"] and (behavior["passed"] is not False)
    blockers = list(contract.get("external_blockers", []))
    return {
        "contract_id": contract["id"],
        "project": contract["project"],
        "source": {"repository": contract["repository"], "revision": contract["revision"]},
        "source_contract": contract["source_contract"],
        "structural": structural,
        "behavioral": behavior,
        "core_passed": core_passed,
        "external_blockers": blockers,
        "parity_status": "core_verified_external_blocked" if core_passed and blockers else ("verified" if core_passed else "failed"),
    }


def run_suite(
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST,
    root: str | Path = ROOT,
    behavioral: bool = False,
    only: Iterable[str] | None = None,
    timeout: float = 180.0,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    selected = set(only or [])
    contracts = [item for item in manifest["contracts"] if not selected or item["id"] in selected]
    reports = [run_contract(item, root=root, behavioral=behavioral, timeout=timeout) for item in contracts]
    return {
        "schema": "ego.harness-conformance-report.v1",
        "generated_at": int(time.time()),
        "behavioral_executed": behavioral,
        "summary": {
            "contracts": len(reports),
            "core_passed": sum(bool(item["core_passed"]) for item in reports),
            "failed": sum(not bool(item["core_passed"]) for item in reports),
            "external_blocked": sum(bool(item["external_blockers"]) for item in reports),
        },
        "contracts": reports,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    parser = argparse.ArgumentParser(description="Run EgoAgent open-source Harness conformance contracts")
    parser.add_argument("--behavioral", action="store_true", help="execute declared offline behavioral tests")
    parser.add_argument("--only", action="append", default=[], help="contract id (repeatable)")
    parser.add_argument("--output", help="write the JSON report to this path")
    parser.add_argument("--timeout", type=float, default=180.0, help="per-contract behavioral timeout")
    args = parser.parse_args(argv)
    report = run_suite(behavioral=args.behavioral, only=args.only, timeout=args.timeout)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        destination = Path(args.output).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
