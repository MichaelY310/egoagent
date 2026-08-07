#!/usr/bin/env python3
"""Download Fix Round 2"""
import os, sys, json, random
from pathlib import Path

os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["HF_HOME"] = "/tmp/hf_cache"

BASE_DIR = Path("/mnt/bn/yangyuan-search-agent-rl-hl/mlx/users/yangyuan.335/data/egoagent_datasets")

def save_jsonl(data, filepath):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"  Saved {len(data)} to {os.path.basename(filepath)}")

def download_dir1():
    print("\n--- Dir1: GSM8K train ---")
    from datasets import load_dataset
    ds = load_dataset("openai/gsm8k", "main", split="train[:300]")
    data = []
    for item in ds:
        q = item.get("question", "")
        a = item.get("answer", "")
        final = a.split("####")[-1].strip() if "####" in a else a
        data.append({"task": q, "reference_answer": final, "full_solution": a, "category": "reasoning", "difficulty": "medium", "source": "gsm8k_train"})
    save_jsonl(data, str(BASE_DIR / "dir1_meta_evolution" / "gsm8k_train_300.jsonl"))
    return len(data)

def download_dir4():
    print("\n--- Dir4: ARC-Challenge ---")
    from datasets import load_dataset
    ds = load_dataset("allenai/ai2_arc", "ARC-Challenge", split="test[:300]")
    data = []
    for item in ds:
        q = item.get("question", "")
        choices = item.get("choices", {})
        ak = item.get("answerKey", "")
        if q and choices:
            labels = choices.get("label", [])
            texts = choices.get("text", [])
            cs = "\n".join([f"{l}. {t}" for l, t in zip(labels, texts)])
            data.append({"task": f"{q}\n\n{cs}", "answer": ak, "required_capabilities": ["reasoning", "science"], "complexity": 3, "ideal_pipeline": "understand -> retrieve -> reason -> answer", "source": "arc_pipeline"})
    save_jsonl(data, str(BASE_DIR / "dir4_pipeline_search" / "arc_pipeline_300.jsonl"))
    return len(data)

def download_dir5():
    print("\n--- Dir5: StreamBench ---")
    from datasets import load_dataset
    all_data = []
    sb = 300
    for cfg in ["hotpotqa_distract", "ddxplus"]:
        try:
            ds = load_dataset("appier-ai-research/StreamBench", cfg, split="test[:200]")
            sb += 1
            for i, item in enumerate(ds):
                t = item.get("input", item.get("question", ""))
                a = item.get("output", item.get("answer", ""))
                if t:
                    all_data.append({"task": str(t)[:500], "answer": str(a)[:200] if a else "", "domain": cfg, "stream_id": sb, "position_in_stream": i+1, "depends_on_previous": i > 0, "source": f"streambench_{cfg}"})
            print(f"  {cfg}: OK")
        except Exception as e:
            print(f"  {cfg}: {e}")
    if all_data:
        save_jsonl(all_data, str(BASE_DIR / "dir5_lifelong_learning" / "streambench_400.jsonl"))
    return len(all_data)

def download_dir6():
    print("\n--- Dir6: UltraFeedback ---")
    from datasets import load_dataset
    ds = load_dataset("openbmb/UltraFeedback", split="train[:400]")
    data = []
    for item in ds:
        instr = item.get("instruction", "")
        comps = item.get("completions", [])
        if instr and comps:
            turns = []
            for c in comps[:3]:
                if isinstance(c, dict) and c.get("response"):
                    turns.append(str(c["response"])[:300])
            if turns:
                data.append({"topic": instr[:300], "turns": turns, "category": "comparative", "difficulty": "medium", "source": "ultrafeedback"})
    save_jsonl(data, str(BASE_DIR / "dir6_self_play" / "ultrafeedback_400.jsonl"))
    return len(data)

if __name__ == "__main__":
    print("=== Download Fix Round 2 ===")
    r = {}
    for name, fn in [("dir1", download_dir1), ("dir4", download_dir4), ("dir5", download_dir5), ("dir6", download_dir6)]:
        try:
            r[name] = fn()
        except Exception as e:
            print(f"  FAILED {name}: {e}")
            r[name] = 0
    print(f"\nDone: {r}")
