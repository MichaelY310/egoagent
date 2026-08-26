"""Dataset and scorer for translating source Harness contracts into EgoIR.

Targets are generated from the checked-in replicas, while scoring compiles a
candidate with the real EgoIR parser and applies the source conformance rules.
This makes syntax validity and semantic contract coverage separately visible.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from ego_ir import EgoIRError, config_to_text, revision, text_to_config
from harness_conformance import DEFAULT_MANIFEST, ROOT, inspect_config, load_manifest


def _split(contract_id: str) -> str:
    bucket = int(hashlib.sha256(contract_id.encode("utf-8")).hexdigest()[:8], 16) % 10
    return "train" if bucket < 6 else ("validation" if bucket < 8 else "heldout")


def build_dataset(
    *, manifest_path: str | Path = DEFAULT_MANIFEST, root: str | Path = ROOT
) -> list[dict[str, Any]]:
    root_path = Path(root).resolve()
    entries: list[dict[str, Any]] = []
    for contract in load_manifest(manifest_path)["contracts"]:
        config_path = root_path / "harness" / contract["harness"] / "config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        ir_text = config_to_text(config)
        entries.append(
            {
                "schema": "ego.harness-translation-example.v1",
                "id": contract["id"],
                "split": _split(contract["id"]),
                "source": {
                    "project": contract["project"],
                    "repository": contract["repository"],
                    "revision": contract["revision"],
                    "behavior": contract["source_contract"],
                    "required_nodes": contract["required_nodes"],
                    "required_ops": contract["required_ops"],
                    "external_boundaries": contract.get("external_blockers", []),
                },
                "target": {
                    "harness": contract["harness"],
                    "format": "EGOIR/1",
                    "text": ir_text,
                    "config_revision": revision(config),
                },
            }
        )
    return entries


def vocabulary_report(dataset: Iterable[dict[str, Any]]) -> dict[str, Any]:
    entries = list(dataset)
    op_projects: dict[str, set[str]] = {}
    node_counter: Counter[str] = Counter()
    for entry in entries:
        project_id = entry["id"]
        for operation in entry["source"]["required_ops"]:
            op_projects.setdefault(operation, set()).add(project_id)
        node_counter.update(entry["source"]["required_nodes"])
    # Greedy set cover exposes the smallest high-coverage *ordering*.  The full
    # union remains the only vocabulary that covers every declared contract.
    uncovered = {entry["id"] for entry in entries}
    greedy: list[dict[str, Any]] = []
    remaining = dict(op_projects)
    while uncovered and remaining:
        operation, projects = max(remaining.items(), key=lambda item: len(item[1] & uncovered))
        newly = sorted(projects & uncovered)
        if not newly:
            break
        uncovered -= projects
        greedy.append({"operation": operation, "new_projects": newly, "cumulative_coverage": len(entries) - len(uncovered)})
        remaining.pop(operation)
    return {
        "projects": len(entries),
        "minimum_complete_operation_vocabulary": sorted(op_projects),
        "operation_project_frequency": {key: len(value) for key, value in sorted(op_projects.items())},
        "greedy_coverage_order": greedy,
        "uncovered_projects": sorted(uncovered),
        "recurrent_named_nodes": dict(node_counter.most_common(30)),
    }


def score_translation(
    contract_id: str,
    candidate_text: str,
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST,
    root: str | Path = ROOT,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    try:
        contract = next(item for item in manifest["contracts"] if item["id"] == contract_id)
    except StopIteration as error:
        raise ValueError(f"unknown contract: {contract_id}") from error
    try:
        candidate = text_to_config(candidate_text)
    except (EgoIRError, ValueError, json.JSONDecodeError) as error:
        return {"contract_id": contract_id, "valid": False, "contract_passed": False, "exact": False, "error": str(error)}
    structural = inspect_config(candidate, contract)
    target_path = Path(root).resolve() / "harness" / contract["harness"] / "config.json"
    target = json.loads(target_path.read_text(encoding="utf-8"))
    return {
        "contract_id": contract_id,
        "valid": True,
        "contract_passed": structural["passed"],
        "exact": revision(candidate) == revision(target),
        "candidate_revision": revision(candidate),
        "target_revision": revision(target),
        "structural": structural,
    }


def write_dataset(destination: str | Path, *, jsonl: bool = True) -> Path:
    target = Path(destination).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    dataset = build_dataset()
    if jsonl:
        content = "".join(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n" for item in dataset)
    else:
        content = json.dumps({"schema": "ego.harness-translation-dataset.v1", "examples": dataset}, ensure_ascii=False, indent=2) + "\n"
    target.write_text(content, encoding="utf-8")
    return target


def main() -> int:
    import argparse

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    parser = argparse.ArgumentParser(description="Build and inspect the source-contract to EgoIR benchmark")
    parser.add_argument("--output")
    parser.add_argument("--json", action="store_true", help="write a JSON document instead of JSONL")
    args = parser.parse_args()
    dataset = build_dataset()
    report = {
        "schema": "ego.harness-translation-benchmark.v1",
        "examples": len(dataset),
        "splits": dict(Counter(item["split"] for item in dataset)),
        "vocabulary": vocabulary_report(dataset),
    }
    if args.output:
        report["path"] = str(write_dataset(args.output, jsonl=not args.json))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
