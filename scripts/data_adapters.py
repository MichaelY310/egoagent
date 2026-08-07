#!/usr/bin/env python3
"""
Data Adapters — 将下载的公开数据集转换为 EgoAgent 各方向实验所需的统一格式。

每个方向的数据格式：
- Dir1 (Meta-Evolution): {"task": str, "reference_answer": str, "category": str}
- Dir2 (Identity/Persona): {"persona": dict, "probe_question": str, "expected_behavior": str}
- Dir3 (Evo Benchmark): {"task": str, "suite": str, "difficulty": int, "evaluation_criteria": str}
- Dir4 (Pipeline Search): {"task": str, "answer": str, "required_capabilities": list, "complexity": int}
- Dir5 (Lifelong Learning): {"task": str, "answer": str, "domain": str, "stream_id": int}
- Dir6 (Self-Play): {"topic": str, "turns": list, "category": str}
"""

import json
import os
import sys
import random
from pathlib import Path
from typing import List, Dict, Any, Optional

BASE_DIR = Path("/mnt/bn/yangyuan-search-agent-rl-hl/mlx/users/yangyuan.335/data/egoagent_datasets")

ADAPTED_SUFFIX = "_adapted.jsonl"


def load_jsonl(filepath: str) -> List[Dict]:
    """Load a JSONL file."""
    data = []
    if not os.path.exists(filepath):
        print(f"  [SKIP] File not found: {filepath}")
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
    """Save data as JSONL file."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"  ✓ Saved {len(data)} items to {filepath}")


# =============================================================================
# Direction 1: Meta-Evolution (Prompt Optimization Tasks)
# =============================================================================
def adapt_dir1():
    """Convert GSM8K + BBH to prompt optimization evaluation format."""
    print("\n" + "=" * 60)
    print("Adapting Direction 1: Meta-Evolution")
    print("=" * 60)
    
    dir_path = BASE_DIR / "dir1_meta_evolution"
    adapted = []
    
    # Adapt GSM8K
    gsm8k = load_jsonl(str(dir_path / "gsm8k_test_300.jsonl"))
    for item in gsm8k:
        question = item.get("question", "")
        answer = item.get("answer", "")
        # Extract the final numeric answer from GSM8K format (after ####)
        final_answer = answer.split("####")[-1].strip() if "####" in answer else answer
        adapted.append({
            "task": question,
            "reference_answer": final_answer,
            "full_solution": answer,
            "category": "reasoning",
            "difficulty": "medium",
            "source": "gsm8k",
        })
    
    # Adapt BBH boolean
    bbh_bool = load_jsonl(str(dir_path / "bbh_boolean_300.jsonl"))
    for item in bbh_bool:
        inp = item.get("input", "")
        target = item.get("target", "")
        adapted.append({
            "task": inp,
            "reference_answer": target,
            "full_solution": target,
            "category": "reasoning",
            "difficulty": "medium",
            "source": "bbh_boolean",
        })
    
    # Adapt BBH logical
    bbh_logic = load_jsonl(str(dir_path / "bbh_logical_300.jsonl"))
    for item in bbh_logic:
        inp = item.get("input", "")
        target = item.get("target", "")
        adapted.append({
            "task": inp,
            "reference_answer": target,
            "full_solution": target,
            "category": "reasoning",
            "difficulty": "hard",
            "source": "bbh_logical",
        })
    
    # Also include synthetic data if available
    synthetic = load_jsonl(str(dir_path / "synthetic_prompt_tasks_100.jsonl"))
    for item in synthetic:
        if "task" in item and "reference_answer" in item:
            item["source"] = "synthetic"
            adapted.append(item)
    
    if adapted:
        # Shuffle and split into train/test
        random.shuffle(adapted)
        split_idx = int(len(adapted) * 0.8)
        train_data = adapted[:split_idx]
        test_data = adapted[split_idx:]
        
        save_jsonl(train_data, str(dir_path / "train_adapted.jsonl"))
        save_jsonl(test_data, str(dir_path / "test_adapted.jsonl"))
        print(f"  Total: {len(adapted)} (train: {len(train_data)}, test: {len(test_data)})")
    else:
        print("  [WARN] No data available for Direction 1")


# =============================================================================
# Direction 2: Identity/Persona Control
# =============================================================================
def adapt_dir2():
    """Convert PersonaChat to persona evaluation format."""
    print("\n" + "=" * 60)
    print("Adapting Direction 2: Identity/Persona Control")
    print("=" * 60)
    
    dir_path = BASE_DIR / "dir2_identity_persona"
    adapted = []
    
    # Adapt PersonaChat
    personachat = load_jsonl(str(dir_path / "personachat_300.jsonl"))
    for item in personachat:
        # PersonaChat format: personality (list of strings), utterances (list)
        personality = item.get("personality", [])
        if not personality:
            personality = item.get("persona", [])
        
        # Extract conversation
        candidates = item.get("candidates", [])
        history = item.get("history", item.get("utterances", []))
        
        if personality:
            # Create persona probe from the conversation
            traits = personality[:3] if len(personality) > 3 else personality
            
            # Use last history item as probe question
            probe = ""
            if isinstance(history, list) and history:
                if isinstance(history[-1], str):
                    probe = history[-1]
                elif isinstance(history[-1], list) and history[-1]:
                    probe = history[-1][-1] if isinstance(history[-1][-1], str) else str(history[-1][-1])
            
            if not probe:
                probe = "Tell me about yourself."
            
            adapted.append({
                "persona": {
                    "traits": traits,
                    "tone": "conversational",
                    "role": "assistant",
                },
                "probe_question": probe,
                "expected_behavior": f"Should respond consistently with persona: {'; '.join(traits[:2])}",
                "source": "personachat",
            })
    
    # Include synthetic data
    synthetic = load_jsonl(str(dir_path / "synthetic_persona_probes_100.jsonl"))
    for item in synthetic:
        if "persona" in item and "probe_question" in item:
            item["source"] = "synthetic"
            adapted.append(item)
    
    if adapted:
        random.shuffle(adapted)
        split_idx = int(len(adapted) * 0.8)
        save_jsonl(adapted[:split_idx], str(dir_path / "train_adapted.jsonl"))
        save_jsonl(adapted[split_idx:], str(dir_path / "test_adapted.jsonl"))
        print(f"  Total: {len(adapted)} (train: {split_idx}, test: {len(adapted) - split_idx})")
    else:
        print("  [WARN] No data available for Direction 2")


# =============================================================================
# Direction 3: Evolution Benchmark
# =============================================================================
def adapt_dir3():
    """Convert GAIA to agent evaluation benchmark format."""
    print("\n" + "=" * 60)
    print("Adapting Direction 3: Evolution Benchmark")
    print("=" * 60)
    
    dir_path = BASE_DIR / "dir3_evo_benchmark"
    adapted = []
    
    # Adapt GAIA
    gaia = load_jsonl(str(dir_path / "gaia_val_200.jsonl"))
    for item in gaia:
        question = item.get("Question", item.get("question", ""))
        answer = item.get("Final answer", item.get("final_answer", ""))
        level = item.get("Level", item.get("level", 1))
        
        # Map GAIA levels to our suites
        suite_map = {1: "general", 2: "reasoning", 3: "mixed"}
        suite = suite_map.get(level, "mixed")
        
        if question:
            adapted.append({
                "task": question,
                "reference_answer": str(answer),
                "suite": suite,
                "difficulty": int(level) if level else 2,
                "evaluation_criteria": "Correctness of final answer",
                "source": "gaia",
            })
    
    # Include synthetic data
    synthetic = load_jsonl(str(dir_path / "synthetic_eval_tasks_100.jsonl"))
    for item in synthetic:
        if "task" in item:
            item["source"] = "synthetic"
            adapted.append(item)
    
    if adapted:
        random.shuffle(adapted)
        split_idx = int(len(adapted) * 0.8)
        save_jsonl(adapted[:split_idx], str(dir_path / "train_adapted.jsonl"))
        save_jsonl(adapted[split_idx:], str(dir_path / "test_adapted.jsonl"))
        print(f"  Total: {len(adapted)} (train: {split_idx}, test: {len(adapted) - split_idx})")
    else:
        print("  [WARN] No data available for Direction 3")


# =============================================================================
# Direction 4: Pipeline Architecture Search
# =============================================================================
def adapt_dir4():
    """Convert HotpotQA to pipeline search evaluation format."""
    print("\n" + "=" * 60)
    print("Adapting Direction 4: Pipeline Architecture Search")
    print("=" * 60)
    
    dir_path = BASE_DIR / "dir4_pipeline_search"
    adapted = []
    
    # Adapt HotpotQA
    hotpotqa = load_jsonl(str(dir_path / "hotpotqa_val_300.jsonl"))
    for item in hotpotqa:
        question = item.get("question", "")
        answer = item.get("answer", "")
        q_type = item.get("type", "bridge")
        level = item.get("level", "medium")
        supporting = item.get("supporting_facts", {})
        
        # Determine required capabilities based on question type
        capabilities = ["reasoning"]
        if q_type == "bridge":
            capabilities.append("multi_hop")
        if q_type == "comparison":
            capabilities.append("comparison")
        capabilities.append("retrieval")  # HotpotQA always needs retrieval
        
        complexity = {"easy": 2, "medium": 3, "hard": 4}.get(level, 3)
        
        if question and answer:
            adapted.append({
                "task": question,
                "answer": answer,
                "required_capabilities": capabilities,
                "complexity": complexity,
                "ideal_pipeline": f"retrieve_context -> reason_{q_type} -> answer",
                "source": "hotpotqa",
            })
    
    # Include synthetic data
    synthetic = load_jsonl(str(dir_path / "synthetic_workflow_tasks_100.jsonl"))
    for item in synthetic:
        if "task" in item:
            item["source"] = "synthetic"
            adapted.append(item)
    
    if adapted:
        random.shuffle(adapted)
        split_idx = int(len(adapted) * 0.8)
        save_jsonl(adapted[:split_idx], str(dir_path / "train_adapted.jsonl"))
        save_jsonl(adapted[split_idx:], str(dir_path / "test_adapted.jsonl"))
        print(f"  Total: {len(adapted)} (train: {split_idx}, test: {len(adapted) - split_idx})")
    else:
        print("  [WARN] No data available for Direction 4")


# =============================================================================
# Direction 5: Lifelong Learning
# =============================================================================
def adapt_dir5():
    """Convert TriviaQA + MMLU to streaming task format."""
    print("\n" + "=" * 60)
    print("Adapting Direction 5: Lifelong Learning")
    print("=" * 60)
    
    dir_path = BASE_DIR / "dir5_lifelong_learning"
    adapted = []
    
    # Adapt TriviaQA
    triviaqa = load_jsonl(str(dir_path / "triviaqa_val_300.jsonl"))
    stream_id = 1
    position = 0
    for item in triviaqa:
        question = item.get("question", "")
        answer_data = item.get("answer", {})
        if isinstance(answer_data, dict):
            answer = answer_data.get("value", answer_data.get("normalized_value", ""))
            if not answer:
                aliases = answer_data.get("aliases", [])
                answer = aliases[0] if aliases else ""
        else:
            answer = str(answer_data)
        
        position += 1
        if position > 30:  # New stream every 30 tasks
            stream_id += 1
            position = 1
        
        if question and answer:
            adapted.append({
                "task": question,
                "answer": answer,
                "domain": "general_knowledge",
                "stream_id": stream_id,
                "position_in_stream": position,
                "depends_on_previous": False,
                "key_knowledge": f"Factual: {answer}",
                "source": "triviaqa",
            })
    
    # Adapt MMLU
    mmlu = load_jsonl(str(dir_path / "mmlu_test_300.jsonl"))
    stream_id += 1
    position = 0
    for item in mmlu:
        question = item.get("question", "")
        choices = item.get("choices", [])
        answer_idx = item.get("answer", 0)
        subject = item.get("subject", "general")
        
        if question and choices:
            # Format as multiple choice
            choice_str = "\n".join([f"{chr(65+i)}. {c}" for i, c in enumerate(choices)])
            full_task = f"{question}\n\n{choice_str}"
            answer_letter = chr(65 + answer_idx) if isinstance(answer_idx, int) else str(answer_idx)
            
            position += 1
            if position > 30:
                stream_id += 1
                position = 1
            
            # Map subjects to domains
            domain_map = {
                "abstract_algebra": "math", "anatomy": "science",
                "astronomy": "science", "business_ethics": "humanities",
                "clinical_knowledge": "science", "college_biology": "science",
                "college_chemistry": "science", "college_computer_science": "coding",
                "college_mathematics": "math", "college_medicine": "science",
                "college_physics": "science", "computer_security": "coding",
                "conceptual_physics": "science", "econometrics": "math",
                "electrical_engineering": "coding", "formal_logic": "math",
            }
            domain = domain_map.get(subject, "general_knowledge")
            
            adapted.append({
                "task": full_task,
                "answer": answer_letter,
                "domain": domain,
                "stream_id": stream_id,
                "position_in_stream": position,
                "depends_on_previous": False,
                "key_knowledge": f"Subject: {subject}, Answer: {answer_letter}",
                "source": "mmlu",
            })
    
    # Include synthetic data
    synthetic = load_jsonl(str(dir_path / "synthetic_task_stream_100.jsonl"))
    for item in synthetic:
        if "task" in item:
            item["source"] = "synthetic"
            adapted.append(item)
    
    if adapted:
        random.shuffle(adapted)
        split_idx = int(len(adapted) * 0.8)
        save_jsonl(adapted[:split_idx], str(dir_path / "train_adapted.jsonl"))
        save_jsonl(adapted[split_idx:], str(dir_path / "test_adapted.jsonl"))
        print(f"  Total: {len(adapted)} (train: {split_idx}, test: {len(adapted) - split_idx})")
    else:
        print("  [WARN] No data available for Direction 5")


# =============================================================================
# Direction 6: Multi-Agent Self-Play
# =============================================================================
def adapt_dir6():
    """Convert MT-Bench to self-play debate format."""
    print("\n" + "=" * 60)
    print("Adapting Direction 6: Multi-Agent Self-Play")
    print("=" * 60)
    
    dir_path = BASE_DIR / "dir6_self_play"
    adapted = []
    
    # Adapt MT-Bench (raw from GitHub)
    mt_bench = load_jsonl(str(dir_path / "mt_bench_80.jsonl"))
    for item in mt_bench:
        turns = item.get("turns", [])
        category = item.get("category", "general")
        qid = item.get("question_id", "")
        
        if turns:
            # First turn as debate topic
            topic = turns[0] if isinstance(turns[0], str) else str(turns[0])
            adapted.append({
                "topic": topic,
                "turns": turns,
                "category": category,
                "question_id": qid,
                "difficulty": "medium",
                "source": "mt_bench",
            })
    
    # Adapt MT-Bench HF version
    mt_bench_hf = load_jsonl(str(dir_path / "mt_bench_hf.jsonl"))
    for item in mt_bench_hf:
        prompt = item.get("prompt", [])
        category = item.get("category", "general")
        
        if prompt:
            topic = prompt[0] if isinstance(prompt[0], str) else str(prompt[0])
            if not any(a["topic"] == topic for a in adapted):  # Avoid duplicates
                adapted.append({
                    "topic": topic,
                    "turns": prompt,
                    "category": category,
                    "difficulty": "medium",
                    "source": "mt_bench_hf",
                })
    
    # Include synthetic data
    synthetic = load_jsonl(str(dir_path / "synthetic_debate_topics_100.jsonl"))
    for item in synthetic:
        if "topic" in item:
            item["source"] = "synthetic"
            adapted.append(item)
    
    if adapted:
        random.shuffle(adapted)
        split_idx = int(len(adapted) * 0.8)
        save_jsonl(adapted[:split_idx], str(dir_path / "train_adapted.jsonl"))
        save_jsonl(adapted[split_idx:], str(dir_path / "test_adapted.jsonl"))
        print(f"  Total: {len(adapted)} (train: {split_idx}, test: {len(adapted) - split_idx})")
    else:
        print("  [WARN] No data available for Direction 6")


# =============================================================================
# Main
# =============================================================================
def main():
    print("=" * 70)
    print("EgoAgent Data Adapter — Converting datasets to experiment format")
    print(f"Base directory: {BASE_DIR}")
    print("=" * 70)
    
    random.seed(42)
    
    adapt_dir1()
    adapt_dir2()
    adapt_dir3()
    adapt_dir4()
    adapt_dir5()
    adapt_dir6()
    
    print("\n" + "=" * 70)
    print("Adaptation complete!")
    print("=" * 70)
    
    # Print summary
    for d in sorted(BASE_DIR.iterdir()):
        if d.is_dir():
            files = list(d.glob("*_adapted.jsonl"))
            total = 0
            for f in files:
                with open(f) as fh:
                    total += sum(1 for _ in fh)
            print(f"  {d.name}: {len(files)} adapted files, {total} total examples")


if __name__ == "__main__":
    main()
