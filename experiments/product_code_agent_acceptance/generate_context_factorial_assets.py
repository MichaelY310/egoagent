"""Generate the frozen 2^4 context-mechanism factorial assets.

All generated Harnesses are internal experiment fixtures. They differ only in
memory, tool-result pruning, passive compaction, and repeat-tool guard.
"""

from __future__ import annotations

import copy
import itertools
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BASE_FLOW = ROOT / "harness" / "product_adaptive_code_agent" / "config.json"
SOURCE_TASK = ROOT / "task_bench" / "tasks" / "product_large_observation_repair.json"
OUTPUT_TASK = ROOT / "task_bench" / "tasks" / "product_context_four_factor.json"


def flow_name(memory: bool, pruning: bool, compaction: bool, repeat_guard: bool) -> str:
    return f"experiment_context_m{int(memory)}_p{int(pruning)}_c{int(compaction)}_r{int(repeat_guard)}"


def generate() -> dict:
    base = json.loads(BASE_FLOW.read_text(encoding="utf-8"))
    flow_names = []
    for memory, pruning, compaction, repeat_guard in itertools.product((False, True), repeat=4):
        config = copy.deepcopy(base)
        name = flow_name(memory, pruning, compaction, repeat_guard)
        flow_names.append(name)
        config["name"] = name
        config["description"] = (
            "Internal matched context factorial fixture: "
            f"memory={memory}, tool_pruning={pruning}, passive_compaction={compaction}, repeat_guard={repeat_guard}."
        )
        config["tags"] = ["experiment", "context-factorial", "do-not-recommend"]
        config["catalog"] = {
            "category": "experiment",
            "visibility": "internal",
            "display_name": f"Context M{int(memory)} P{int(pruning)} C{int(compaction)} R{int(repeat_guard)}",
        }
        context = config["pipeline"].setdefault("context", {})
        context.update(
            {
                "enable_memory": memory,
                "enable_tool_pruning": pruning,
                "enable_compaction": compaction,
                "enable_curation": False,
                "enable_evolution": False,
                "enable_delegation": False,
            }
        )
        if not repeat_guard:
            config["pipeline"]["nodes"]["count_turn"]["edges"] = [
                {"condition": "default", "to": "discover"}
            ]
            config["pipeline"]["nodes"]["tools"]["edges"] = [
                {"condition": "default", "to": "tool_pruning_policy"}
            ]
        destination = ROOT / "harness" / name / "config.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    source = json.loads(SOURCE_TASK.read_text(encoding="utf-8"))
    source.update(
        {
            "id": "product_context_four_factor",
            "title": "Four-factor context pressure and fresh-memory recall",
            "description": "A two-step real-code fixture combining a required 50KB observation with fresh-trajectory durable recall.",
            "tags": ["context", "memory", "tool-pruning", "compaction", "repeat-guard", "factorial"],
            "prompt": "Complete both pressure and fresh-trajectory recall steps without writing the durable fact to project files.",
            "selection": {
                "recommended_harness": flow_name(True, True, True, True),
                "recommended_identity": "adaptive_deepseek_coder",
                "compatible_harnesses": flow_names,
                "compatible_identities": ["adaptive_deepseek_coder"],
            },
            "steps": [
                {
                    "id": "pressure_and_teach",
                    "prompt": "DURABLE PROJECT_ORBIT fact: its recovery code is ORBIT-CEDAR-842. The Flow Runtime alone owns durable-memory persistence: do not search for, activate, or create a Skill, Knowledge item, capability, or project file to store this fact, and do not manually modify Identity data. Simply keep it in your answer evidence so the declared Memory node can persist it when that experimental arm enables Memory. Also repair generated_rules.py artifact_digest so it strictly follows the CONTRACT at the file head. Before editing, use read_file once to read the complete generated_rules.py, make the smallest change, and run `python -m unittest discover -v`. Finish with ACK-ORBIT.",
                    "resume_trajectory": False,
                    "evaluation": {
                        "pass_score": 1.0,
                        "checks": [
                            {"type": "command", "command": ["python", "-m", "unittest", "discover", "-v"], "weight": 4},
                            {"type": "file_regex", "path": "generated_rules.py", "pattern": "hashlib\\.sha256", "weight": 1},
                            {"type": "response_contains", "value": "ACK-ORBIT", "weight": 1}
                        ]
                    }
                },
                {
                    "id": "fresh_recall",
                    "prompt": "This is a fresh trajectory with no prior chat history. Use only memory already supplied by the Flow Runtime: do not inspect project files and do not search, activate, or create capabilities. What is the exact recovery code for PROJECT_ORBIT? Reply with the code only; if the Runtime supplied no such memory, reply exactly NO_MEMORY.",
                    "resume_trajectory": False,
                    "evaluation": {
                        "pass_score": 1.0,
                        "checks": [{"type": "response_contains", "value": "ORBIT-CEDAR-842", "weight": 1}]
                    }
                }
            ],
            "evaluation": {"pass_score": 1.0, "checks": []},
            "evolution": {"allowed": False, "targets": []},
        }
    )
    OUTPUT_TASK.write_text(json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"task": str(OUTPUT_TASK), "flows": flow_names}


if __name__ == "__main__":
    print(json.dumps(generate(), ensure_ascii=True, indent=2))
