#!/usr/bin/env python3
"""
Data Adapters V2 — 整合所有已下载数据集（原始 + 扩充）到统一格式。
包含原始数据 + 新下载的 PersonaHub, SyntheticPersonaChat, MMLU-Pro, WildBench,
ARC-Pipeline, StreamBench, DebateGPT 等。
"""
import json, os, sys, random
from pathlib import Path
from typing import List, Dict

BASE_DIR = Path("/mnt/bn/yangyuan-search-agent-rl-hl/mlx/users/yangyuan.335/data/egoagent_datasets")

def load_jsonl(filepath: str) -> List[Dict]:
    data = []
    if not os.path.exists(filepath):
        return data
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    data.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return data

def save_jsonl(data: List[Dict], filepath: str):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"  Saved {len(data)} items to {os.path.basename(filepath)}")

def split_save(adapted, dir_path, train_ratio=0.8):
    """Shuffle, split, and save."""
    if not adapted:
        print("  [WARN] No data")
        return
    random.shuffle(adapted)
    idx = int(len(adapted) * train_ratio)
    save_jsonl(adapted[:idx], str(dir_path / "train_adapted.jsonl"))
    save_jsonl(adapted[idx:], str(dir_path / "test_adapted.jsonl"))
    print(f"  Total: {len(adapted)} (train={idx}, test={len(adapted)-idx})")

# =============================================================================
# Dir1: Meta-Evolution
# =============================================================================
def adapt_dir1():
    print("\n=== Dir1: Meta-Evolution ===")
    dp = BASE_DIR / "dir1_meta_evolution"
    adapted = []
    
    # GSM8K test
    for item in load_jsonl(str(dp / "gsm8k_test_300.jsonl")):
        q = item.get("question", "")
        a = item.get("answer", "")
        final = a.split("####")[-1].strip() if "####" in a else a
        adapted.append({"task": q, "reference_answer": final, "full_solution": a, "category": "reasoning", "difficulty": "medium", "source": "gsm8k"})
    
    # GSM8K train (new)
    for item in load_jsonl(str(dp / "gsm8k_train_300.jsonl")):
        if "task" in item:
            adapted.append(item)
        else:
            q = item.get("question", "")
            a = item.get("answer", "")
            final = a.split("####")[-1].strip() if "####" in a else a
            adapted.append({"task": q, "reference_answer": final, "full_solution": a, "category": "reasoning", "difficulty": "medium", "source": "gsm8k_train"})
    
    # BBH boolean + logical
    for item in load_jsonl(str(dp / "bbh_boolean_300.jsonl")):
        adapted.append({"task": item.get("input", ""), "reference_answer": item.get("target", ""), "category": "reasoning", "difficulty": "medium", "source": "bbh_boolean"})
    for item in load_jsonl(str(dp / "bbh_logical_300.jsonl")):
        adapted.append({"task": item.get("input", ""), "reference_answer": item.get("target", ""), "category": "reasoning", "difficulty": "hard", "source": "bbh_logical"})
    
    # IFEval
    for item in load_jsonl(str(dp / "ifeval_200.jsonl")):
        prompt = item.get("prompt", item.get("instruction", ""))
        if prompt:
            adapted.append({"task": prompt, "reference_answer": "", "category": "instruction_following", "difficulty": "medium", "source": "ifeval"})
    
    # MATH (if exists)
    for item in load_jsonl(str(dp / "math_300.jsonl")):
        if "task" in item:
            adapted.append(item)
    
    # Synthetic v1
    for item in load_jsonl(str(dp / "synthetic_prompt_tasks_100.jsonl")):
        if "task" in item:
            item.setdefault("source", "synthetic")
            adapted.append(item)
    
    # Synthetic v2
    for item in load_jsonl(str(dp / "synthetic_diverse_v2.jsonl")):
        if "task" in item:
            item.setdefault("source", "synthetic_v2")
            adapted.append(item)
    
    split_save(adapted, dp)

# =============================================================================
# Dir2: Identity/Persona
# =============================================================================
def adapt_dir2():
    print("\n=== Dir2: Identity/Persona ===")
    dp = BASE_DIR / "dir2_identity_persona"
    adapted = []
    
    # PersonaChat original
    for item in load_jsonl(str(dp / "personachat_300.jsonl")):
        personality = item.get("personality", item.get("persona", []))
        history = item.get("history", item.get("utterances", []))
        if personality:
            traits = personality[:3] if len(personality) > 3 else personality
            probe = ""
            if isinstance(history, list) and history:
                if isinstance(history[-1], str):
                    probe = history[-1]
                elif isinstance(history[-1], list) and history[-1]:
                    probe = str(history[-1][-1])
            if not probe:
                probe = "Tell me about yourself."
            adapted.append({"persona": {"traits": traits, "tone": "conversational", "role": "assistant"}, "probe_question": probe, "expected_behavior": f"Respond consistently with: {'; '.join(traits[:2])}", "source": "personachat"})
    
    # Synthetic-Persona-Chat (new - 500)
    for item in load_jsonl(str(dp / "synthetic_persona_chat_500.jsonl")):
        if "persona" in item:
            item.setdefault("source", "synthetic_persona_chat")
            adapted.append(item)
    
    # PersonaHub (new - 300)
    for item in load_jsonl(str(dp / "personahub_300.jsonl")):
        if "persona" in item:
            item.setdefault("source", "personahub")
            adapted.append(item)
    
    # Synthetic v1
    for item in load_jsonl(str(dp / "synthetic_persona_probes_100.jsonl")):
        if "persona" in item:
            item.setdefault("source", "synthetic")
            adapted.append(item)
    
    # Synthetic v2
    for item in load_jsonl(str(dp / "synthetic_persona_v2.jsonl")):
        if "persona" in item:
            item.setdefault("source", "synthetic_v2")
            adapted.append(item)
    
    split_save(adapted, dp)

# =============================================================================
# Dir3: Evo Benchmark
# =============================================================================
def adapt_dir3():
    print("\n=== Dir3: Evo Benchmark ===")
    dp = BASE_DIR / "dir3_evo_benchmark"
    adapted = []
    
    # GAIA/MMLU substitute
    for item in load_jsonl(str(dp / "gaia_val_200.jsonl")):
        question = item.get("Question", item.get("question", ""))
        answer = item.get("Final answer", item.get("final_answer", item.get("answer", "")))
        level = item.get("Level", item.get("level", 1))
        if question:
            adapted.append({"task": question, "reference_answer": str(answer), "suite": "general", "difficulty": int(level) if level else 2, "evaluation_criteria": "Correctness", "source": "gaia_substitute"})
    
    # MMLU-Pro (new - 400)
    for item in load_jsonl(str(dp / "mmlu_pro_400.jsonl")):
        if "task" in item:
            item.setdefault("source", "mmlu_pro")
            adapted.append(item)
    
    # WildBench (new - 300)
    for item in load_jsonl(str(dp / "wildbench_300.jsonl")):
        if "task" in item:
            item.setdefault("source", "wildbench")
            adapted.append(item)
    
    # Synthetic
    for item in load_jsonl(str(dp / "synthetic_eval_tasks_100.jsonl")):
        if "task" in item:
            item.setdefault("source", "synthetic")
            adapted.append(item)
    
    split_save(adapted, dp)

# =============================================================================
# Dir4: Pipeline Architecture Search
# =============================================================================
def adapt_dir4():
    print("\n=== Dir4: Pipeline Architecture Search ===")
    dp = BASE_DIR / "dir4_pipeline_search"
    adapted = []
    
    # HotpotQA
    for item in load_jsonl(str(dp / "hotpotqa_val_300.jsonl")):
        q = item.get("question", "")
        a = item.get("answer", "")
        qt = item.get("type", "bridge")
        level = item.get("level", "medium")
        caps = ["reasoning"]
        if qt == "bridge": caps.append("multi_hop")
        if qt == "comparison": caps.append("comparison")
        caps.append("retrieval")
        complexity = {"easy": 2, "medium": 3, "hard": 4}.get(level, 3)
        if q and a:
            adapted.append({"task": q, "answer": a, "required_capabilities": caps, "complexity": complexity, "ideal_pipeline": f"retrieve -> reason_{qt} -> answer", "source": "hotpotqa"})
    
    # ARC-Pipeline (new - 300)
    for item in load_jsonl(str(dp / "arc_pipeline_300.jsonl")):
        if "task" in item:
            item.setdefault("source", "arc_pipeline")
            adapted.append(item)
    
    # StrategyQA (if exists)
    for item in load_jsonl(str(dp / "strategyqa_200.jsonl")):
        if "task" in item:
            item.setdefault("source", "strategyqa")
            adapted.append(item)
    
    # Synthetic v1
    for item in load_jsonl(str(dp / "synthetic_workflow_tasks_100.jsonl")):
        if "task" in item:
            item.setdefault("source", "synthetic")
            adapted.append(item)
    
    # Synthetic v2
    for item in load_jsonl(str(dp / "synthetic_complex_v2.jsonl")):
        if "task" in item:
            item.setdefault("source", "synthetic_v2")
            adapted.append(item)
    
    # HumanEval (new)
    for item in load_jsonl(str(dp / "humaneval_200.jsonl")):
        if "task" in item:
            item.setdefault("source", "humaneval")
            adapted.append(item)
    
    # MBPP (new)
    for item in load_jsonl(str(dp / "mbpp_200.jsonl")):
        if "task" in item:
            item.setdefault("source", "mbpp")
            adapted.append(item)
    
    split_save(adapted, dp)

# =============================================================================
# Dir5: Lifelong Learning
# =============================================================================
def adapt_dir5():
    print("\n=== Dir5: Lifelong Learning ===")
    dp = BASE_DIR / "dir5_lifelong_learning"
    adapted = []
    stream_id = 1
    position = 0
    
    # TriviaQA
    for item in load_jsonl(str(dp / "triviaqa_val_300.jsonl")):
        q = item.get("question", "")
        ad = item.get("answer", {})
        if isinstance(ad, dict):
            answer = ad.get("value", ad.get("normalized_value", ""))
            if not answer:
                aliases = ad.get("aliases", [])
                answer = aliases[0] if aliases else ""
        else:
            answer = str(ad)
        position += 1
        if position > 30:
            stream_id += 1
            position = 1
        if q and answer:
            adapted.append({"task": q, "answer": answer, "domain": "general_knowledge", "stream_id": stream_id, "position_in_stream": position, "source": "triviaqa"})
    
    # MMLU
    stream_id += 1
    position = 0
    for item in load_jsonl(str(dp / "mmlu_test_300.jsonl")):
        q = item.get("question", "")
        choices = item.get("choices", [])
        answer_idx = item.get("answer", 0)
        subject = item.get("subject", "general")
        if q and choices:
            cs = "\n".join([f"{chr(65+i)}. {c}" for i, c in enumerate(choices)])
            al = chr(65 + answer_idx) if isinstance(answer_idx, int) else str(answer_idx)
            position += 1
            if position > 30:
                stream_id += 1
                position = 1
            adapted.append({"task": f"{q}\n\n{cs}", "answer": al, "domain": subject, "stream_id": stream_id, "position_in_stream": position, "source": "mmlu"})
    
    # ARC Challenge
    stream_id += 1
    position = 0
    for item in load_jsonl(str(dp / "arc_challenge_200.jsonl")):
        q = item.get("question", "")
        if q:
            position += 1
            if position > 30:
                stream_id += 1
                position = 1
            adapted.append({"task": q, "answer": item.get("answerKey", item.get("answer", "")), "domain": "science", "stream_id": stream_id, "position_in_stream": position, "source": "arc_challenge"})
    
    # SuperGLUE (new - 300)
    stream_id += 1
    position = 0
    for item in load_jsonl(str(dp / "superglue_300.jsonl")):
        if "task" in item:
            position += 1
            if position > 30:
                stream_id += 1
                position = 1
            item["stream_id"] = stream_id
            item["position_in_stream"] = position
            item.setdefault("source", "superglue")
            adapted.append(item)
    
    # StreamBench (new)
    for item in load_jsonl(str(dp / "streambench_400.jsonl")):
        if "task" in item:
            item.setdefault("source", "streambench")
            adapted.append(item)
    
    # Synthetic
    for item in load_jsonl(str(dp / "synthetic_task_stream_100.jsonl")):
        if "task" in item:
            item.setdefault("source", "synthetic")
            adapted.append(item)
    
    # WinoGrande (new)
    for item in load_jsonl(str(dp / "winogrande_200.jsonl")):
        if "task" in item:
            item.setdefault("source", "winogrande")
            adapted.append(item)

    # HellaSwag (new)
    for item in load_jsonl(str(dp / "hellaswag_200.jsonl")):
        if "task" in item:
            item.setdefault("source", "hellaswag")
            adapted.append(item)

    # C-Eval (new)
    for item in load_jsonl(str(dp / "ceval_200.jsonl")):
        if "task" in item:
            item.setdefault("source", "ceval")
            adapted.append(item)

    split_save(adapted, dp)

# =============================================================================
# Dir6: Multi-Agent Self-Play
# =============================================================================
def adapt_dir6():
    print("\n=== Dir6: Multi-Agent Self-Play ===")
    dp = BASE_DIR / "dir6_self_play"
    adapted = []
    
    # MT-Bench raw
    for item in load_jsonl(str(dp / "mt_bench_80.jsonl")):
        turns = item.get("turns", [])
        category = item.get("category", "general")
        if turns:
            topic = turns[0] if isinstance(turns[0], str) else str(turns[0])
            adapted.append({"topic": topic, "turns": turns, "category": category, "difficulty": "medium", "source": "mt_bench"})
    
    # MT-Bench HF (deduplicate)
    existing_topics = {a["topic"][:50] for a in adapted}
    for item in load_jsonl(str(dp / "mt_bench_hf.jsonl")):
        prompt = item.get("prompt", [])
        if prompt:
            topic = prompt[0] if isinstance(prompt[0], str) else str(prompt[0])
            if topic[:50] not in existing_topics:
                adapted.append({"topic": topic, "turns": prompt, "category": item.get("category", "general"), "difficulty": "medium", "source": "mt_bench_hf"})
                existing_topics.add(topic[:50])
    
    # DebateGPT (new - 300)
    for item in load_jsonl(str(dp / "debategpt_300.jsonl")):
        if "topic" in item:
            item.setdefault("source", "debategpt")
            adapted.append(item)
    
    # UltraFeedback (new - 400)
    for item in load_jsonl(str(dp / "ultrafeedback_400.jsonl")):
        if "topic" in item:
            item.setdefault("source", "ultrafeedback")
            adapted.append(item)
    
    # SHP (preference data)
    for item in load_jsonl(str(dp / "shp_200.jsonl")):
        title = item.get("history", item.get("title", ""))
        if title:
            adapted.append({"topic": str(title)[:300], "turns": [item.get("human_ref_A", "")[:200], item.get("human_ref_B", "")[:200]], "category": "preference", "difficulty": "medium", "source": "shp"})
    
    # Synthetic v1
    for item in load_jsonl(str(dp / "synthetic_debate_topics_100.jsonl")):
        if "topic" in item:
            item.setdefault("source", "synthetic")
            adapted.append(item)
    
    # Synthetic v2
    for item in load_jsonl(str(dp / "synthetic_debates_v2.jsonl")):
        if "topic" in item:
            item.setdefault("source", "synthetic_v2")
            adapted.append(item)
    
    # Anthropic HH-RLHF (new)
    for item in load_jsonl(str(dp / "anthropic_hh_300.jsonl")):
        if "topic" in item:
            item.setdefault("source", "anthropic_hh")
            adapted.append(item)
    
    split_save(adapted, dp)

# =============================================================================
def main():
    print("=" * 70)
    print("EgoAgent Data Adapter V2 — Full Integration")
    print(f"Base: {BASE_DIR}")
    print("=" * 70)
    random.seed(42)
    
    adapt_dir1()
    adapt_dir2()
    adapt_dir3()
    adapt_dir4()
    adapt_dir5()
    adapt_dir6()
    
    print("\n" + "=" * 70)
    print("Summary:")
    for d in sorted(BASE_DIR.iterdir()):
        if d.is_dir():
            train_f = d / "train_adapted.jsonl"
            test_f = d / "test_adapted.jsonl"
            train_n = sum(1 for _ in open(train_f)) if train_f.exists() else 0
            test_n = sum(1 for _ in open(test_f)) if test_f.exists() else 0
            print(f"  {d.name}: train={train_n}, test={test_n}, total={train_n+test_n}")
    print("=" * 70)

if __name__ == "__main__":
    main()
