#!/usr/bin/env python3
"""Download additional datasets to further expand weak directions (Dir4, Dir5, Dir6)."""
import json, os, sys, time
from pathlib import Path

DATA_BASE = Path("/mnt/bn/yangyuan-search-agent-rl-hl/mlx/users/yangyuan.335/data/egoagent_datasets")
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

def save_jsonl(data, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"  Saved {len(data)} items to {path.name}")

def download_dir4_humaneval():
    """Download HumanEval for pipeline search tasks (code generation pipelines)."""
    print("\n[Dir4] Downloading openai/humaneval...")
    try:
        from datasets import load_dataset
        ds = load_dataset("openai_humaneval", split="test[:200]", trust_remote_code=True)
        records = []
        for item in ds:
            records.append({
                "task": f"Write a Python function: {item['prompt'][:200]}",
                "answer": item.get("canonical_solution", "")[:500],
                "required_capabilities": ["code_generation", "algorithm_design"],
                "complexity": 3,
                "ideal_pipeline": "plan -> code_generate -> test -> refine"
            })
        save_jsonl(records, DATA_BASE / "dir4_pipeline_search" / "humaneval_200.jsonl")
        return len(records)
    except Exception as e:
        print(f"  Failed: {e}")
        return 0

def download_dir4_mbpp():
    """Download MBPP for pipeline tasks."""
    print("\n[Dir4] Downloading google-research-datasets/mbpp...")
    try:
        from datasets import load_dataset
        ds = load_dataset("google-research-datasets/mbpp", "sanitized", split="test[:200]", trust_remote_code=True)
        records = []
        for item in ds:
            records.append({
                "task": item.get("prompt", item.get("text", "")),
                "answer": item.get("code", ""),
                "required_capabilities": ["code_generation", "testing"],
                "complexity": 2,
                "ideal_pipeline": "understand -> code -> verify"
            })
        save_jsonl(records, DATA_BASE / "dir4_pipeline_search" / "mbpp_200.jsonl")
        return len(records)
    except Exception as e:
        print(f"  Failed: {e}")
        return 0

def download_dir5_ceval():
    """Download C-Eval for lifelong learning (Chinese domain shift)."""
    print("\n[Dir5] Downloading ceval/ceval-exam...")
    try:
        from datasets import load_dataset
        configs = ["computer_network", "operating_system", "discrete_mathematics", "probability_and_statistics"]
        records = []
        for cfg in configs:
            try:
                ds = load_dataset("ceval/ceval-exam", cfg, split="test[:50]", trust_remote_code=True)
                for i, item in enumerate(ds):
                    q = item.get("question", "")
                    choices = [item.get(f"A", ""), item.get(f"B", ""), item.get(f"C", ""), item.get(f"D", "")]
                    answer = item.get("answer", "A")
                    records.append({
                        "task": f"{q}\nA. {choices[0]}\nB. {choices[1]}\nC. {choices[2]}\nD. {choices[3]}",
                        "answer": answer,
                        "domain": cfg,
                        "stream_id": configs.index(cfg) + 100,
                        "position_in_stream": i
                    })
            except Exception as e:
                print(f"  {cfg} failed: {e}")
        if records:
            save_jsonl(records, DATA_BASE / "dir5_lifelong_learning" / "ceval_200.jsonl")
        return len(records)
    except Exception as e:
        print(f"  Failed: {e}")
        return 0

def download_dir5_winogrande():
    """Download WinoGrande for lifelong learning (commonsense reasoning domain)."""
    print("\n[Dir5] Downloading allenai/winogrande...")
    try:
        from datasets import load_dataset
        ds = load_dataset("allenai/winogrande", "winogrande_xl", split="validation[:200]", trust_remote_code=True)
        records = []
        for i, item in enumerate(ds):
            sentence = item.get("sentence", "")
            opt1, opt2 = item.get("option1", ""), item.get("option2", "")
            answer = opt1 if item.get("answer", "1") == "1" else opt2
            records.append({
                "task": f"Fill in the blank: {sentence}\nOption 1: {opt1}\nOption 2: {opt2}",
                "answer": answer,
                "domain": "commonsense",
                "stream_id": 200,
                "position_in_stream": i
            })
        save_jsonl(records, DATA_BASE / "dir5_lifelong_learning" / "winogrande_200.jsonl")
        return len(records)
    except Exception as e:
        print(f"  Failed: {e}")
        return 0

def download_dir5_hellaswag():
    """Download HellaSwag for lifelong learning (sentence completion domain)."""
    print("\n[Dir5] Downloading Rowan/hellaswag...")
    try:
        from datasets import load_dataset
        ds = load_dataset("Rowan/hellaswag", split="validation[:200]", trust_remote_code=True)
        records = []
        for i, item in enumerate(ds):
            ctx = item.get("ctx", "")
            endings = item.get("endings", [])
            label = int(item.get("label", 0))
            answer = endings[label] if label < len(endings) else endings[0]
            choices_text = "\n".join([f"{chr(65+j)}. {e}" for j, e in enumerate(endings)])
            records.append({
                "task": f"Complete the sentence: {ctx}\n{choices_text}",
                "answer": answer,
                "domain": "sentence_completion",
                "stream_id": 201,
                "position_in_stream": i
            })
        save_jsonl(records, DATA_BASE / "dir5_lifelong_learning" / "hellaswag_200.jsonl")
        return len(records)
    except Exception as e:
        print(f"  Failed: {e}")
        return 0

def download_dir6_anthropic_hh():
    """Download Anthropic HH-RLHF for self-play (preference learning)."""
    print("\n[Dir6] Downloading Anthropic/hh-rlhf...")
    try:
        from datasets import load_dataset
        ds = load_dataset("Anthropic/hh-rlhf", split="test[:300]", trust_remote_code=True)
        records = []
        for item in ds:
            chosen = item.get("chosen", "")
            rejected = item.get("rejected", "")
            # Extract topic from first human turn
            lines = chosen.split("\n\nHuman: ")
            topic = lines[1].split("\n")[0] if len(lines) > 1 else chosen[:100]
            # Build turns from chosen
            turns = []
            parts = chosen.split("\n\n")
            for p in parts[:6]:
                if p.startswith("Human:"):
                    turns.append({"role": "human", "content": p[7:].strip()[:200]})
                elif p.startswith("Assistant:"):
                    turns.append({"role": "assistant", "content": p[11:].strip()[:200]})
            records.append({
                "topic": topic[:200],
                "turns": turns[:6],
                "category": "preference_learning",
                "difficulty": "medium"
            })
        save_jsonl(records, DATA_BASE / "dir6_self_play" / "anthropic_hh_300.jsonl")
        return len(records)
    except Exception as e:
        print(f"  Failed: {e}")
        return 0

def download_dir6_chatbot_arena():
    """Download lmsys chatbot arena conversations for debate/self-play."""
    print("\n[Dir6] Downloading lmsys/chatbot_arena_conversations...")
    try:
        from datasets import load_dataset
        ds = load_dataset("lmsys/chatbot_arena_conversations", split="train[:200]", trust_remote_code=True)
        records = []
        for item in ds:
            conv_a = item.get("conversation_a", [])
            conv_b = item.get("conversation_b", [])
            if not conv_a: continue
            topic = conv_a[0].get("content", "")[:200] if conv_a else ""
            turns = []
            for msg in conv_a[:4]:
                turns.append({"role": msg.get("role", "user"), "content": msg.get("content", "")[:200]})
            records.append({
                "topic": topic,
                "turns": turns,
                "category": "model_comparison",
                "difficulty": "medium"
            })
        save_jsonl(records, DATA_BASE / "dir6_self_play" / "arena_conv_200.jsonl")
        return len(records)
    except Exception as e:
        print(f"  Failed: {e}")
        return 0

def download_dir1_math():
    """Download MATH dataset subset for meta-evolution (harder tasks)."""
    print("\n[Dir1] Downloading lighteval/MATH...")
    try:
        from datasets import load_dataset
        ds = load_dataset("lighteval/MATH", "all", split="test[:300]", trust_remote_code=True)
        records = []
        for item in ds:
            records.append({
                "task": item.get("problem", ""),
                "reference_answer": item.get("solution", ""),
                "category": item.get("type", "math"),
                "difficulty": item.get("level", "medium"),
                "source": "MATH"
            })
        save_jsonl(records, DATA_BASE / "dir1_meta_evolution" / "math_300.jsonl")
        return len(records)
    except Exception as e:
        print(f"  Failed: {e}")
        return 0

def main():
    print("="*60 + "\nExpanded Dataset Download V2\n" + "="*60)
    start = time.time()
    total = 0
    
    # Dir1: More challenging tasks
    total += download_dir1_math()
    
    # Dir4: Pipeline-oriented tasks
    total += download_dir4_humaneval()
    total += download_dir4_mbpp()
    
    # Dir5: More domains for lifelong learning
    total += download_dir5_winogrande()
    total += download_dir5_hellaswag()
    total += download_dir5_ceval()
    
    # Dir6: More debate/preference data
    total += download_dir6_anthropic_hh()
    total += download_dir6_chatbot_arena()
    
    elapsed = time.time() - start
    print(f"\n{'='*60}\nDone! Total new records: {total} | Time: {elapsed:.0f}s\n{'='*60}")

if __name__ == "__main__":
    main()
