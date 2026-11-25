"""Descriptive audit of frozen DGM candidates; no causal claims from scores."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def group(path: str):
    if path.startswith("tools/"):
        return "tools"
    if path.startswith("prompts/"):
        return "prompts"
    if path.startswith("llm"):
        return "model_io"
    if path.startswith("coding_agent"):
        return "agent_loop"
    if path.startswith("utils/"):
        return "utils"
    return "other"


def tasks(performance: dict):
    return set().union(*(set(performance.get(k, [])) for k in ("total_resolved_ids", "total_unresolved_ids", "total_emptypatch_ids")))


def main():
    manifest = json.loads((ROOT / "results/dgm_sample_manifest.json").read_text())
    rows, by_id = [], {}
    for name in manifest["metadata"]:
        path = ROOT / "cache/dgm" / name
        m = json.loads(path.read_text())
        cid = path.parent.name
        perf = m.get("overall_performance") or {}
        patch = path.with_name("model_patch.diff")
        text = patch.read_text(encoding="utf-8") if patch.exists() else ""
        paths = sorted(set(re.findall(r"^diff --git a/(\S+) b/", text, re.M)))
        # Keep production files such as tools/test_log_analyzer.py; the name
        # describes a tool, not a unit test. Only the explicit tests/ tree is excluded.
        test_paths = [p for p in paths if p.startswith("tests/")]
        production = [p for p in paths if p not in test_paths]
        row = {"id": cid, "parent": m.get("parent_commit"), "entry": m.get("entry"), "patch_present": patch.exists(), "patch_nonempty": bool(text.strip()), "patch_sha256": hashlib.sha256(patch.read_bytes()).hexdigest() if patch.exists() else None, "paths": paths, "test_paths": test_paths, "production_paths": production, "raw_components_including_tests": sorted({group(p) for p in paths}), "components": sorted({group(p) for p in production}), "score": perf.get("accuracy_score"), "submitted": perf.get("total_submitted_instances"), "resolved": perf.get("total_resolved_instances"), "task_ids": sorted(tasks(perf)), "resolved_ids": perf.get("total_resolved_ids", [])}
        if perf:
            row["unique_reported_ids_match_submitted"] = len(row["task_ids"]) == row["submitted"]
            resolved = set(perf.get("total_resolved_ids", []))
            unresolved = set(perf.get("total_unresolved_ids", []))
            empty = set(perf.get("total_emptypatch_ids", []))
            row["overlapping_outcome_ids"] = sorted((resolved & unresolved) | (resolved & empty) | (unresolved & empty))
        rows.append(row)
        by_id[cid] = row
    for row in rows:
        if row["parent"] == "initial":
            initial_path = ROOT / "cache/dgm/swe_dgm/initial/metadata.json"
            if initial_path.exists():
                initial = json.loads(initial_path.read_text())["overall_performance"]
                by_id["initial"] = {"task_ids": sorted(tasks(initial)), "resolved_ids": initial["total_resolved_ids"], "score": initial["accuracy_score"]}
        p = by_id.get(row["parent"])
        if not p or p["score"] is None or row["score"] is None:
            row["parent_comparison"] = "unavailable"
            continue
        common = set(p["task_ids"]) & set(row["task_ids"])
        row["parent_comparison"] = "same_task_set" if p["task_ids"] == row["task_ids"] else "different_task_sets"
        row["shared_tasks"] = len(common)
        if common:
            row["shared_task_delta"] = (len(common & set(row["resolved_ids"])) - len(common & set(p["resolved_ids"]))) / len(common)
    summary = {"sample_size": len(rows), "patch_present": sum(r["patch_present"] for r in rows), "nonempty_patch": sum(r["patch_nonempty"] for r in rows), "scored": sum(r["score"] is not None for r in rows), "reported_id_count_mismatches": sum(r.get("unique_reported_ids_match_submitted") is False for r in rows), "component_count_distribution": dict(sorted(Counter(len(r["components"]) for r in rows).items())), "component_coediting": dict(Counter("+".join(r["components"]) for r in rows)), "parent_comparisons": dict(Counter(r["parent_comparison"] for r in rows)), "patch_basis": "Relative to parent: self_improve_step.py applies ancestry patches, commits parent, then requests patch vs that commit (lines 274-290, 332).", "warning": "Published outcomes are whole-candidate observations, not single-component counterfactuals. Shared-task differences are descriptive only: single samples, selection effects, changing budgets possible. Different task_sets means reported metadata ID sets, not necessarily true evaluated sets; incomplete/inconsistent metadata cannot establish matched evaluation."}
    (ROOT / "results/dgm_audit.json").write_text(json.dumps({"summary": summary, "candidates": rows}, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    print(json.dumps([{k: r[k] for k in ("id", "parent", "components", "score", "submitted", "parent_comparison")} for r in rows], indent=2))


if __name__ == "__main__":
    main()
