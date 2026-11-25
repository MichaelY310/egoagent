"""Aggregate frozen scopes without changing them to fit test outcomes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def label(components):
    return "+".join(sorted(components)) or "parent"


def main():
    manifest = read(ROOT / "results/replay_manifest.json")
    probes = read(ROOT / "results/integration_probes_v3.json")["rows"]
    probe_map = {(r["case"], r["label"]): r for r in probes}
    rows = []
    for case in manifest["cases"]:
        batch = "runs_v3" if case["index"] == 10 else "runs_v2"
        cells = {}
        hashes = []
        for cell in case["cells"]:
            outcome = read(ROOT / "results" / batch / f'{case["id"]}__{cell["label"]}.json')
            # Verify that no test file changed between planning, execution, and audit.
            actual = {p: hashlib.sha256((ROOT / cell["tree"] / p).read_bytes()).hexdigest() for p in case["test_paths"]}
            assert actual == cell["test_hashes"] == outcome["test_hashes"]
            hashes.append(actual)
            cells[cell["label"]] = outcome
        assert all(h == hashes[0] for h in hashes), "Variants used different tests"
        whole = cells[label(case["components_all_production"]) ]
        assert whole["returncode"] == 0 and not whole["timeout"], "Full patch must pass to interpret this case"
        # Tests which fail every proper subset and pass the full patch.
        proper = [r for k, r in cells.items() if k != whole["label"]]
        joint_only = []
        if len(case["components_all_production"]) > 1:
            for test in whole["tests"]:
                if test["status"] != "passed":
                    continue
                states = [{t["id"]: t["status"] for t in r["tests"]}.get(test["id"]) for r in proper]
                # Missing/collection error is not treated as a behavioral failure.
                if all(s == "failure" for s in states):
                    joint_only.append(test["id"])
        arms = {}
        for arm, scope in case["scopes"].items():
            applied = set(scope) & set(case["components_all_production"])
            result = cells[label(applied)]
            probe = probe_map.get((case["id"], label(applied)))
            arms[arm] = {"scope": scope, "applied": sorted(applied), "upstream_pass": result["returncode"] == 0, "probe_pass": None if probe is None else probe["passed"], "combined_exploratory_pass": result["returncode"] == 0 and (probe is None or probe["passed"])}
        rows.append({"id": case["id"], "index": case["index"], "subject": case["subject"], "components": case["components_all_production"], "seed": case["seed"], "batch": batch, "cells": {k: {"counts": r["counts"], "returncode": r["returncode"], "seconds": r["seconds"], "timeout": r["timeout"]} for k, r in cells.items()}, "joint_only_individual_upstream_tests": joint_only, "arms": arms})
    totals = {}
    for arm in rows[0]["arms"]:
        totals[arm] = {"upstream_pass_cases": sum(r["arms"][arm]["upstream_pass"] for r in rows), "supplementary_pass_cases": sum(r["arms"][arm]["probe_pass"] is True for r in rows), "combined_exploratory_pass_cases": sum(r["arms"][arm]["combined_exploratory_pass"] for r in rows), "combined_non_ui_pass_cases": sum(r["arms"][arm]["combined_exploratory_pass"] for r in rows if r["index"] != 10), "average_nominal_scope_components": sum(len(r["arms"][arm]["scope"]) for r in rows) / len(rows), "average_applied_changed_components": sum(len(r["arms"][arm]["applied"]) for r in rows) / len(rows)}
    totals["denominators"] = {"upstream_cases": len(rows), "supplementary_cases": len({r["case"] for r in probes}), "non_ui_cases": len(rows) - 1, "canonical_variants": sum(len(r["cells"]) for r in rows), "canonical_test_outcomes": sum(sum(c["counts"].values()) for r in rows for c in r["cells"].values()), "canonical_seconds": sum(c["seconds"] for r in rows for c in r["cells"].values()), "multi_component_commits": sum(len(r["components"]) > 1 for r in rows)}
    value = {"warning": "Patch replay with oracle edit locations; not a live improver comparison. Supplemental integration outcomes are posthoc and not new independent cases.", "totals": totals, "cases": rows}
    (ROOT / "results/comparison.json").write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(totals, indent=2))
    for r in rows:
        print(r["id"], r["components"], {a: x["combined_exploratory_pass"] for a, x in r["arms"].items()})


if __name__ == "__main__":
    main()
