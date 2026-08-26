"""Audit every installed Harness as a catalog, not just isolated JSON files."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline_schema import canonical_op, validate_component_manifest, validate_pipeline


def _category(name: str, pinned: set[str]) -> str:
    if name.startswith("component_"):
        return "component"
    if name.endswith("_worker"):
        return "internal_worker"
    if name in pinned or name.endswith("_replica"):
        return "replica"
    if name in {"evolution_cycle", "meta_evolution_cycle", "improver", "session_analyzer"}:
        return "evolution"
    return "template"


def audit(root: Path = ROOT) -> dict:
    harness_root = root / "harness"
    contract_path = root / "research_specs" / "harness_conformance.json"
    contract_data = json.loads(contract_path.read_text(encoding="utf-8"))
    contracts = {item["harness"]: item for item in contract_data.get("contracts", [])}
    names = {
        path.parent.name
        for path in harness_root.glob("*/config.json")
        if path.is_file()
    }
    records = []
    for name in sorted(names):
        path = harness_root / name / "config.json"
        errors = []
        dependencies = []
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            records.append({"name": name, "category": "invalid", "ok": False, "errors": [str(exc)]})
            continue
        pipeline = config.get("pipeline", {})
        errors.extend(validate_pipeline(pipeline))
        errors.extend(validate_component_manifest(config.get("component")))
        slots = set((config.get("slots") or {}).keys())
        nodes = pipeline.get("nodes") or {}
        for node_id, node in nodes.items():
            if not isinstance(node, dict):
                continue
            agent = node.get("agent")
            if agent and isinstance(agent, str) and not agent.startswith("$") and agent not in slots:
                errors.append(f"node {node_id!r} binds unknown local slot {agent!r}")
            if canonical_op(node.get("op", "")) != "子流程":
                continue
            dependency = node.get("harness")
            if isinstance(dependency, str) and dependency and not dependency.startswith("$"):
                dependencies.append(dependency)
                if dependency not in names:
                    errors.append(f"node {node_id!r} references missing subflow {dependency!r}")
                else:
                    child = json.loads((harness_root / dependency / "config.json").read_text(encoding="utf-8"))
                    child_slots = set((child.get("slots") or {}).keys())
                    mapped = set((node.get("agent_map") or {}).keys())
                    unknown = sorted(mapped - child_slots)
                    if unknown:
                        errors.append(f"node {node_id!r} maps unknown child slots {unknown!r}")
                    component = child.get("component") if isinstance(child.get("component"), dict) else None
                    if component:
                        declared_inputs = set((component.get("inputs") or {}).keys())
                        supplied_inputs = set((node.get("component_inputs") or {}).keys())
                        unknown_inputs = sorted(supplied_inputs - declared_inputs)
                        if unknown_inputs:
                            errors.append(f"node {node_id!r} supplies unknown component inputs {unknown_inputs!r}")
                        missing_inputs = sorted(
                            port for port, spec in (component.get("inputs") or {}).items()
                            if isinstance(spec, dict) and spec.get("required") and "default" not in spec
                            and port not in supplied_inputs
                        )
                        if missing_inputs:
                            errors.append(f"node {node_id!r} is missing required component inputs {missing_inputs!r}")
                        declared_outputs = set((component.get("outputs") or {}).keys())
                        supplied_outputs = set((node.get("component_outputs") or {}).keys())
                        unknown_outputs = sorted(supplied_outputs - declared_outputs)
                        if unknown_outputs:
                            errors.append(f"node {node_id!r} maps unknown component outputs {unknown_outputs!r}")
        contract = contracts.get(name)
        if contract:
            missing = sorted(set(contract.get("required_nodes", [])) - set(nodes))
            if missing:
                errors.append(f"pinned source contract is missing nodes {missing!r}")
        records.append({
            "name": name,
            "category": _category(name, set(contracts)),
            "description": str(config.get("description", "")),
            "nodes": len(nodes),
            "slots": sorted(slots),
            "dependencies": sorted(set(dependencies)),
            "pinned_contract": bool(contract),
            "behavioral_tests": list((contract or {}).get("behavioral_tests", [])),
            "ok": not errors,
            "errors": errors,
        })
    referenced = {dependency for item in records for dependency in item.get("dependencies", [])}
    for item in records:
        item["referenced_as_subflow"] = item["name"] in referenced
    failures = [item for item in records if not item["ok"]]
    categories = {}
    for item in records:
        categories[item["category"]] = categories.get(item["category"], 0) + 1
    return {
        "schema": "ego.harness-catalog-audit.v1",
        "root": str(root.resolve()),
        "total": len(records),
        "categories": categories,
        "pinned_contracts": len(contracts),
        "ok": not failures,
        "failures": len(failures),
        "harnesses": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print the complete machine-readable report")
    args = parser.parse_args()
    report = audit()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            f"Harnesses: {report['total']} | pinned: {report['pinned_contracts']} | "
            f"categories: {report['categories']} | failures: {report['failures']}"
        )
        for item in report["harnesses"]:
            marker = "PASS" if item["ok"] else "FAIL"
            deps = f" -> {','.join(item['dependencies'])}" if item["dependencies"] else ""
            print(f"{marker:4} {item['category']:15} {item['name']:38} nodes={item['nodes']:2}{deps}")
            for error in item["errors"]:
                print(f"     {error}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
