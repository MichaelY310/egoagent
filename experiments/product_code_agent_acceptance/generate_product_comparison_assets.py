"""Generate immutable P6 task copies from already-audited redistributable fixtures."""

from __future__ import annotations

import copy
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TASKS = ROOT / "task_bench" / "tasks"
SOURCES = {
    "product_compare_small": "product_parallel_diagnostics",
    "product_compare_large": "product_large_dual_subsystem_repair",
}
EGO_FLOWS = [
    "code_agent_fast", "code_agent_auto", "code_agent_long", "code_agent_team",
    "product_core_code_agent",
]


def main() -> int:
    for target_id, source_id in SOURCES.items():
        source = json.loads((TASKS / f"{source_id}.json").read_text(encoding="utf-8"))
        task = copy.deepcopy(source)
        task["id"] = target_id
        task["title"] = f"P6 comparison — {source.get('title', source_id)}"
        task["tags"] = list(dict.fromkeys([*(source.get("tags") or []), "p6-product-comparison"]))
        task["evolution"] = {"allowed": False, "targets": []}
        selection = task.setdefault("selection", {})
        selection["recommended_harness"] = "code_agent_auto"
        selection["compatible_harnesses"] = EGO_FLOWS
        task["experiment"] = {
            "campaign": "P6-product-comparison-20260908",
            "source_task": source_id,
            "lanes": [*EGO_FLOWS, "codex_cli"],
        }
        destination = TASKS / f"{target_id}.json"
        destination.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(destination.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
