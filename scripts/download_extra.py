import os
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

import json
from datasets import load_dataset

BASE_DIR = "/mnt/bn/yangyuan-search-agent-rl-hl/mlx/users/yangyuan.335/data/egoagent_datasets"

tasks = [
    {
        "name": "IFEval",
        "output": os.path.join(BASE_DIR, "dir1_meta_evolution/ifeval_200.jsonl"),
        "loaders": [
            lambda: load_dataset("google/IFEval", split="train[:200]"),
        ],
    },
    {
        "name": "AlpacaEval",
        "output": os.path.join(BASE_DIR, "dir1_meta_evolution/alpaca_eval_200.jsonl"),
        "loaders": [
            lambda: load_dataset("tatsu-lab/alpaca_eval", "alpaca_eval", split="eval[:200]"),
            lambda: load_dataset("tatsu-lab/alpaca_eval", split="eval[:200]"),
        ],
    },
    {
        "name": "SHP",
        "output": os.path.join(BASE_DIR, "dir6_self_play/shp_200.jsonl"),
        "loaders": [
            lambda: load_dataset("stanfordnlp/SHP", split="test[:200]"),
        ],
    },
    {
        "name": "MATH",
        "output": os.path.join(BASE_DIR, "dir3_evo_benchmark/math_200.jsonl"),
        "loaders": [
            lambda: load_dataset("hendrycks/competition_math", split="test[:200]"),
            lambda: load_dataset("lighteval/MATH", "all", split="test[:200]"),
        ],
    },
    {
        "name": "ARC Challenge",
        "output": os.path.join(BASE_DIR, "dir5_lifelong_learning/arc_challenge_200.jsonl"),
        "loaders": [
            lambda: load_dataset("allenai/ai2_arc", "ARC-Challenge", split="test[:200]"),
        ],
    },
    {
        "name": "Berkeley Function Calling",
        "output": os.path.join(BASE_DIR, "dir4_pipeline_search/bfcl_200.jsonl"),
        "loaders": [
            lambda: load_dataset("gorilla-llm/Berkeley-Function-Calling-Leaderboard", split="train[:200]"),
        ],
    },
]

succeeded = []
failed = []

for task in tasks:
    print(f"\n{'='*60}")
    print(f"Downloading: {task['name']}")
    print(f"Output: {task['output']}")
    print(f"{'='*60}")

    dataset = None
    for i, loader in enumerate(task["loaders"]):
        try:
            print(f"  Trying loader {i+1}...")
            dataset = loader()
            print(f"  Success! Got {len(dataset)} examples.")
            break
        except Exception as e:
            print(f"  Loader {i+1} failed: {e}")

    if dataset is None:
        print(f"  SKIPPED: All loaders failed for {task['name']}")
        failed.append(task["name"])
        continue

    # Ensure output directory exists
    os.makedirs(os.path.dirname(task["output"]), exist_ok=True)

    # Save as JSONL
    try:
        with open(task["output"], "w", encoding="utf-8") as f:
            for example in dataset:
                f.write(json.dumps(example, ensure_ascii=False) + "\n")
        print(f"  Saved to {task['output']}")
        succeeded.append(task["name"])
    except Exception as e:
        print(f"  Failed to save: {e}")
        failed.append(task["name"])

print(f"\n{'='*60}")
print("SUMMARY")
print(f"{'='*60}")
print(f"Succeeded ({len(succeeded)}): {', '.join(succeeded) if succeeded else 'None'}")
print(f"Failed ({len(failed)}): {', '.join(failed) if failed else 'None'}")
print(f"{'='*60}")
