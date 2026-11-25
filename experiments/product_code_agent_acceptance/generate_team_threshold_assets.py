"""Generate frozen P5 Team-threshold tasks without mutating source fixtures."""

from __future__ import annotations

import copy
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TASK_DIR = ROOT / "task_bench" / "tasks"

SOURCES = {
    "team_threshold_small": "product_parallel_diagnostics",
    "team_threshold_medium": "product_isolated_package_repairs",
    "team_threshold_large": "product_large_dual_subsystem_repair",
}
FLOWS = ["code_agent_long", "code_agent_team"]


def main() -> int:
    for target_id, source_id in SOURCES.items():
        source_path = TASK_DIR / f"{source_id}.json"
        task = json.loads(source_path.read_text(encoding="utf-8"))
        workspace_files = (task.get("workspace") or {}).get("files") or {}
        total_bytes = sum(len(str(content).encode("utf-8")) for content in workspace_files.values())
        generated = copy.deepcopy(task)
        generated["id"] = target_id
        generated["title"] = f"P5 threshold: {target_id.rsplit('_', 1)[-1]} — {task.get('title', source_id)}"
        generated["tags"] = list(dict.fromkeys([*(task.get("tags") or []), "team-threshold", "p5-parity"]))
        selection = generated.setdefault("selection", {})
        selection["recommended_harness"] = "code_agent_long"
        selection["compatible_harnesses"] = FLOWS
        generated["evolution"] = {"allowed": False, "targets": []}
        generated["experiment"] = {
            "campaign": "P5-team-threshold-20260908",
            "source_task": source_id,
            "team_threshold": {
                "workspace_files": len(workspace_files),
                "workspace_bytes": total_bytes,
                "deterministic_child_gate": "files >= 12 OR bytes >= 12000",
            },
        }
        destination = TASK_DIR / f"{target_id}.json"
        destination.write_text(json.dumps(generated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{destination.relative_to(ROOT)} files={len(workspace_files)} bytes={total_bytes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
