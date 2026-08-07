#!/usr/bin/env python3
"""
大规模数据集扩充脚本 — 从 HuggingFace 下载更多数据集来扩充各方向。
重点扩充 Dir2 (400→1000+), Dir3 (300→800+), Dir6 (181→600+)

目标数据集：
- Dir2: google/Synthetic-Persona-Chat, proj-persona/PersonaHub
- Dir3: cais/mmlu (更多 subject), TIGER-Lab/MMLU-Pro
- Dir4: hotpotqa (更多split), musique
- Dir5: appier-ai-research/StreamBench (34.7k)
- Dir6: frasalvi/debategpt, lmsys/chatbot_arena_conversations
"""

import os
import sys
import json
import random
import time
from pathlib import Path

os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["HF_HOME"] = "/tmp/hf_cache"

BASE_DIR = Path("/mnt/bn/yangyuan-search-agent-rl-hl/mlx/users/yangyuan.335/data/egoagent_datasets")

def save_jsonl(data, filepath):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"  ✓ Saved {len(data)} items to {os.path.basename(filepath)}")

def download_with_timeout(func, timeout=120):
    """Run download function with timeout."""
    import signal
    def handler(signum, frame):
        raise TimeoutError("Download timed out")
    signal.signal(signal.SIGALRM, handler)
    signal.alarm(timeout)
    try:
        result = func()
        signal.alarm(0)
        return result
    except TimeoutError:
        print("  [TIMEOUT] Download timed out")
        return None
    except Exception as e:
        signal.alarm(0)
        print(f"  [ERROR] {e}")
        return None

# =============================================================================
# Direction 2: Identity/Persona — google/Synthetic-Persona-Chat
# =============================================================================
def download_dir2_synthetic_persona():
    """Download Synthetic-Persona-Chat for persona consistency evaluation."""
    print("\n--- Dir2: Downloading google/Synthetic-Persona-Chat ---")
    try:
        from datasets import load_dataset
        ds = load_dataset("google/Synthetic-Persona-Chat", split="train[:500]")
        data = []
        for item in ds:
            user_personas = item.get("user 1 personas", "") or item.get("User 1 personas", "")
            bot_personas = item.get("user 2 personas", "") or item.get("User 2 personas", "")
            conv = item.get("Best Generated Conversation", "") or item.get("conversation", "")
            
            # Parse personas
            if isinstance(user_personas, str):
                traits = [t.strip() for t in user_personas.split("\n") if t.strip()][:4]
            elif isinstance(user_personas, list):
                traits = user_personas[:4]
            else:
                traits = ["friendly"]
            
            if traits:
                data.append({
                    "persona": {
                        "traits": traits,
                        "tone": "conversational",
                        "role": "user_simulation",
                    },
                    "probe_question": "Tell me something about yourself that reflects your personality.",
                    "expected_behavior": f"Should demonstrate traits: {'; '.join(traits[:2])}",
                    "conversation_sample": str(conv)[:500] if conv else "",
                    "source": "synthetic_persona_chat",
                })
        
        if data:
            save_jsonl(data, str(BASE_DIR / "dir2_identity_persona" / "synthetic_persona_chat_500.jsonl"))
        return data
    except Exception as e:
        print(f"  [ERROR] {e}")
        return []

# =============================================================================
# Direction 2: PersonaHub — diverse persona descriptions
# =============================================================================
def download_dir2_personahub():
    """Download PersonaHub for diverse persona descriptions."""
    print("\n--- Dir2: Downloading proj-persona/PersonaHub ---")
    try:
        from datasets import load_dataset
        ds = load_dataset("proj-persona/PersonaHub", "instruction", split="train[:300]")
        data = []
        for item in ds:
            persona_desc = item.get("input persona", "") or item.get("persona", "")
            instruction = item.get("synthesized text", "") or item.get("instruction", "")
            
            if persona_desc:
                # Parse persona into traits
                traits = [s.strip() for s in str(persona_desc).split(".")[:3] if s.strip()]
                data.append({
                    "persona": {
                        "traits": traits if traits else [persona_desc[:100]],
                        "tone": "professional",
                        "role": "domain_expert",
                    },
                    "probe_question": str(instruction)[:200] if instruction else "Describe your expertise.",
                    "expected_behavior": f"Should respond as: {persona_desc[:100]}",
                    "source": "personahub",
                })
        
        if data:
            save_jsonl(data, str(BASE_DIR / "dir2_identity_persona" / "personahub_300.jsonl"))
        return data
    except Exception as e:
        print(f"  [ERROR] {e}")
        return []

# =============================================================================
# Direction 3: MMLU-Pro — harder benchmark evaluation tasks
# =============================================================================
def download_dir3_mmlu_pro():
    """Download MMLU-Pro for harder evaluation benchmarks."""
    print("\n--- Dir3: Downloading TIGER-Lab/MMLU-Pro ---")
    try:
        from datasets import load_dataset
        ds = load_dataset("TIGER-Lab/MMLU-Pro", split="test[:400]")
        data = []
        for item in ds:
            question = item.get("question", "")
            options = item.get("options", [])
            answer = item.get("answer", "")
            category = item.get("category", "general")
            
            if question and options:
                # Format as multi-choice
                choice_str = "\n".join([f"{chr(65+i)}. {c}" for i, c in enumerate(options[:6])])
                full_task = f"{question}\n\n{choice_str}"
                
                data.append({
                    "task": full_task,
                    "reference_answer": str(answer),
                    "suite": category,
                    "difficulty": 3,  # MMLU-Pro is harder
                    "evaluation_criteria": "Exact match of answer letter",
                    "source": "mmlu_pro",
                })
        
        if data:
            save_jsonl(data, str(BASE_DIR / "dir3_evo_benchmark" / "mmlu_pro_400.jsonl"))
        return data
    except Exception as e:
        print(f"  [ERROR] {e}")
        return []

# =============================================================================
# Direction 3: WildBench — real-world user tasks for agent benchmarking
# =============================================================================
def download_dir3_wildbench():
    """Download WildBench for real-world evaluation."""
    print("\n--- Dir3: Downloading allenai/WildBench ---")
    try:
        from datasets import load_dataset
        ds = load_dataset("allenai/WildBench", "v2", split="test[:300]")
        data = []
        for item in ds:
            conversation = item.get("conversation_input", [])
            category = item.get("primary_tag", "general")
            
            if conversation:
                # Extract user's task from conversation
                task = ""
                for msg in conversation:
                    if msg.get("role") == "user":
                        task = msg.get("content", "")
                        break
                
                if task:
                    data.append({
                        "task": task[:500],
                        "reference_answer": "",
                        "suite": category,
                        "difficulty": 2,
                        "evaluation_criteria": "Quality and helpfulness of response",
                        "source": "wildbench",
                    })
        
        if data:
            save_jsonl(data, str(BASE_DIR / "dir3_evo_benchmark" / "wildbench_300.jsonl"))
        return data
    except Exception as e:
        print(f"  [ERROR] {e}")
        return []

# =============================================================================
# Direction 4: Musique — multi-hop QA for pipeline architecture
# =============================================================================
def download_dir4_musique():
    """Download Musique for multi-hop QA pipeline evaluation."""
    print("\n--- Dir4: Downloading StonyBrookNLP/musique ---")
    try:
        from datasets import load_dataset
        # Try loading musique
        ds = load_dataset("drt/musique", split="train[:300]")
        data = []
        for item in ds:
            question = item.get("question", "")
            answer = item.get("answer", "")
            
            if question and answer:
                data.append({
                    "task": question,
                    "answer": answer,
                    "required_capabilities": ["multi_hop", "reasoning", "retrieval"],
                    "complexity": 4,
                    "ideal_pipeline": "decompose -> retrieve_per_hop -> synthesize -> answer",
                    "source": "musique",
                })
        
        if data:
            save_jsonl(data, str(BASE_DIR / "dir4_pipeline_search" / "musique_300.jsonl"))
        return data
    except Exception as e:
        print(f"  [ERROR] {e}")
        return []

# =============================================================================
# Direction 4: BambooET — complex multi-step tasks
# =============================================================================
def download_dir4_bamboo():
    """Download complex reasoning tasks for pipeline search."""
    print("\n--- Dir4: Downloading complex reasoning (GPQA) ---")
    try:
        from datasets import load_dataset
        ds = load_dataset("Idavidrein/gpqa", "gpqa_main", split="train[:200]")
        data = []
        for item in ds:
            question = item.get("Question", "")
            answer = item.get("Correct Answer", "")
            
            if question:
                data.append({
                    "task": question[:500],
                    "answer": str(answer) if answer else "",
                    "required_capabilities": ["expert_reasoning", "domain_knowledge", "analysis"],
                    "complexity": 5,
                    "ideal_pipeline": "analyze_domain -> retrieve_knowledge -> expert_reason -> verify -> answer",
                    "source": "gpqa",
                })
        
        if data:
            save_jsonl(data, str(BASE_DIR / "dir4_pipeline_search" / "gpqa_200.jsonl"))
        return data
    except Exception as e:
        print(f"  [ERROR] {e}")
        return []

# =============================================================================
# Direction 5: StreamBench — streaming task learning benchmark (PERFECT FIT!)
# =============================================================================
def download_dir5_streambench():
    """Download StreamBench — designed for continuous learning evaluation."""
    print("\n--- Dir5: Downloading appier-ai-research/StreamBench ---")
    try:
        from datasets import load_dataset
        # StreamBench has multiple configs
        ds = load_dataset("appier-ai-research/StreamBench", "overall", split="test[:500]")
        data = []
        stream_counter = 100  # Start from stream 100 to not overlap with existing
        position = 0
        prev_domain = ""
        
        for item in ds:
            question = item.get("input", item.get("question", ""))
            answer = item.get("output", item.get("answer", ""))
            domain = item.get("tag", item.get("domain", "general"))
            
            # New stream when domain changes
            if domain != prev_domain:
                stream_counter += 1
                position = 0
                prev_domain = domain
            position += 1
            
            if question:
                data.append({
                    "task": str(question)[:500],
                    "answer": str(answer)[:200] if answer else "",
                    "domain": str(domain),
                    "stream_id": stream_counter,
                    "position_in_stream": position,
                    "depends_on_previous": position > 1,
                    "key_knowledge": f"Domain: {domain}",
                    "source": "streambench",
                })
        
        if data:
            save_jsonl(data, str(BASE_DIR / "dir5_lifelong_learning" / "streambench_500.jsonl"))
        return data
    except Exception as e:
        print(f"  [ERROR] {e}")
        return []

# =============================================================================
# Direction 5: SuperGLUE tasks — diverse NLU for continual learning
# =============================================================================
def download_dir5_superglue():
    """Download SuperGLUE tasks for diverse NLU evaluation."""
    print("\n--- Dir5: Downloading super_glue (diverse NLU tasks) ---")
    try:
        from datasets import load_dataset
        all_data = []
        stream_base = 200
        
        # Download multiple SuperGLUE tasks
        tasks_configs = [
            ("super_glue", "boolq", "question", "label"),
            ("super_glue", "rte", "premise", "label"),
        ]
        
        for ds_name, config, q_field, a_field in tasks_configs:
            try:
                ds = load_dataset(ds_name, config, split="validation[:150]")
                stream_base += 1
                position = 0
                for item in ds:
                    position += 1
                    question = item.get(q_field, "")
                    answer = item.get(a_field, "")
                    
                    # Format based on task type
                    if config == "boolq":
                        passage = item.get("passage", "")
                        task_text = f"Passage: {passage[:300]}\nQuestion: {question}\nAnswer True or False."
                    elif config == "rte":
                        hypothesis = item.get("hypothesis", "")
                        task_text = f"Premise: {question[:300]}\nHypothesis: {hypothesis}\nDoes the premise entail the hypothesis? (0=yes, 1=no)"
                    else:
                        task_text = str(question)
                    
                    all_data.append({
                        "task": task_text,
                        "answer": str(answer),
                        "domain": f"nlu_{config}",
                        "stream_id": stream_base,
                        "position_in_stream": position,
                        "depends_on_previous": False,
                        "key_knowledge": f"Task: {config}, Answer: {answer}",
                        "source": f"superglue_{config}",
                    })
                print(f"  Loaded {config}: {min(150, len(ds))} items")
            except Exception as e:
                print(f"  [SKIP] {config}: {e}")
        
        if all_data:
            save_jsonl(all_data, str(BASE_DIR / "dir5_lifelong_learning" / "superglue_300.jsonl"))
        return all_data
    except Exception as e:
        print(f"  [ERROR] {e}")
        return []

# =============================================================================
# Direction 6: DebateGPT — debate topics and conversations
# =============================================================================
def download_dir6_debategpt():
    """Download DebateGPT dataset for multi-agent debate."""
    print("\n--- Dir6: Downloading frasalvi/debategpt ---")
    try:
        from datasets import load_dataset
        ds = load_dataset("frasalvi/debategpt", split="train[:300]")
        data = []
        for item in ds:
            topic = item.get("topic", item.get("proposition", ""))
            conversation = item.get("conversation", item.get("messages", []))
            
            if topic:
                turns = []
                if isinstance(conversation, list):
                    for msg in conversation[:6]:
                        if isinstance(msg, dict):
                            turns.append(msg.get("content", str(msg)))
                        else:
                            turns.append(str(msg))
                elif isinstance(conversation, str):
                    turns = [conversation[:200]]
                
                data.append({
                    "topic": str(topic),
                    "turns": turns if turns else [str(topic)],
                    "category": "debate",
                    "difficulty": "medium",
                    "source": "debategpt",
                })
        
        if data:
            save_jsonl(data, str(BASE_DIR / "dir6_self_play" / "debategpt_300.jsonl"))
        return data
    except Exception as e:
        print(f"  [ERROR] {e}")
        return []

# =============================================================================
# Direction 6: UltraFeedback — comparative responses for Judge training
# =============================================================================
def download_dir6_ultrafeedback():
    """Download UltraFeedback for judge evaluation in self-play."""
    print("\n--- Dir6: Downloading openbmb/UltraFeedback ---")
    try:
        from datasets import load_dataset
        ds = load_dataset("openbmb/UltraFeedback", split="train[:400]")
        data = []
        for item in ds:
            instruction = item.get("instruction", "")
            completions = item.get("completions", [])
            
            if instruction and completions:
                # Extract responses as "debate turns" — model vs model
                turns = []
                for comp in completions[:3]:
                    if isinstance(comp, dict):
                        resp = comp.get("response", "")
                        if resp:
                            turns.append(str(resp)[:300])
                
                if turns:
                    data.append({
                        "topic": instruction[:300],
                        "turns": turns,
                        "category": "comparative_evaluation",
                        "difficulty": "medium",
                        "scores": [comp.get("overall_score", 3) for comp in completions[:3] if isinstance(comp, dict)],
                        "source": "ultrafeedback",
                    })
        
        if data:
            save_jsonl(data, str(BASE_DIR / "dir6_self_play" / "ultrafeedback_400.jsonl"))
        return data
    except Exception as e:
        print(f"  [ERROR] {e}")
        return []

# =============================================================================
# Direction 6: Chatbot Arena — pairwise battle data for Judge training
# =============================================================================
def download_dir6_arena():
    """Download Chatbot Arena conversations for judge evaluation."""
    print("\n--- Dir6: Downloading lmsys/chatbot_arena_conversations ---")
    try:
        from datasets import load_dataset
        ds = load_dataset("lmsys/chatbot_arena_conversations", split="train[:300]")
        data = []
        for item in ds:
            conversation_a = item.get("conversation_a", [])
            conversation_b = item.get("conversation_b", [])
            winner = item.get("winner", "")
            
            if conversation_a and conversation_b:
                # Extract the user prompt and both responses
                user_msg = ""
                resp_a = ""
                resp_b = ""
                for msg in conversation_a:
                    if msg.get("role") == "user" and not user_msg:
                        user_msg = msg.get("content", "")
                    elif msg.get("role") == "assistant" and not resp_a:
                        resp_a = msg.get("content", "")
                for msg in conversation_b:
                    if msg.get("role") == "assistant" and not resp_b:
                        resp_b = msg.get("content", "")
                
                if user_msg and (resp_a or resp_b):
                    data.append({
                        "topic": user_msg[:300],
                        "turns": [resp_a[:300], resp_b[:300]],
                        "category": "pairwise_battle",
                        "difficulty": "medium",
                        "winner": winner,
                        "source": "chatbot_arena",
                    })
        
        if data:
            save_jsonl(data, str(BASE_DIR / "dir6_self_play" / "chatbot_arena_300.jsonl"))
        return data
    except Exception as e:
        print(f"  [ERROR] {e}")
        return []

# =============================================================================
# Direction 1: MATH dataset — harder reasoning for meta-evolution
# =============================================================================
def download_dir1_math():
    """Download MATH dataset for harder prompt optimization tasks."""
    print("\n--- Dir1: Downloading hendrycks/competition_math ---")
    try:
        from datasets import load_dataset
        ds = load_dataset("hendrycks/competition_math", split="test[:300]")
        data = []
        for item in ds:
            problem = item.get("problem", "")
            solution = item.get("solution", "")
            level = item.get("level", "Level 3")
            subject = item.get("type", "math")
            
            if problem:
                # Extract difficulty level number
                diff = "hard"
                if "1" in str(level) or "2" in str(level):
                    diff = "easy"
                elif "3" in str(level):
                    diff = "medium"
                
                data.append({
                    "task": problem,
                    "reference_answer": solution[:200] if solution else "",
                    "full_solution": solution,
                    "category": subject,
                    "difficulty": diff,
                    "source": "competition_math",
                })
        
        if data:
            save_jsonl(data, str(BASE_DIR / "dir1_meta_evolution" / "math_competition_300.jsonl"))
        return data
    except Exception as e:
        print(f"  [ERROR] {e}")
        return []

# =============================================================================
# Main execution
# =============================================================================
def main():
    print("=" * 70)
    print("EgoAgent Dataset Expansion — Downloading additional datasets")
    print(f"Target: {BASE_DIR}")
    print("=" * 70)
    
    results = {}
    
    # Direction 1
    r = download_with_timeout(download_dir1_math, 180)
    results["dir1_math"] = len(r) if r else 0
    
    # Direction 2
    r = download_with_timeout(download_dir2_synthetic_persona, 180)
    results["dir2_synthetic_persona"] = len(r) if r else 0
    
    r = download_with_timeout(download_dir2_personahub, 180)
    results["dir2_personahub"] = len(r) if r else 0
    
    # Direction 3
    r = download_with_timeout(download_dir3_mmlu_pro, 180)
    results["dir3_mmlu_pro"] = len(r) if r else 0
    
    r = download_with_timeout(download_dir3_wildbench, 180)
    results["dir3_wildbench"] = len(r) if r else 0
    
    # Direction 4
    r = download_with_timeout(download_dir4_musique, 180)
    results["dir4_musique"] = len(r) if r else 0
    
    r = download_with_timeout(download_dir4_bamboo, 180)
    results["dir4_gpqa"] = len(r) if r else 0
    
    # Direction 5
    r = download_with_timeout(download_dir5_streambench, 180)
    results["dir5_streambench"] = len(r) if r else 0
    
    r = download_with_timeout(download_dir5_superglue, 180)
    results["dir5_superglue"] = len(r) if r else 0
    
    # Direction 6 (most in need of expansion)
    r = download_with_timeout(download_dir6_debategpt, 180)
    results["dir6_debategpt"] = len(r) if r else 0
    
    r = download_with_timeout(download_dir6_ultrafeedback, 180)
    results["dir6_ultrafeedback"] = len(r) if r else 0
    
    r = download_with_timeout(download_dir6_arena, 180)
    results["dir6_arena"] = len(r) if r else 0
    
    # Summary
    print("\n" + "=" * 70)
    print("Download Summary:")
    print("=" * 70)
    total = 0
    for name, count in results.items():
        status = "✓" if count > 0 else "✗"
        print(f"  {status} {name}: {count} items")
        total += count
    print(f"\n  Total new items: {total}")
    print("=" * 70)


if __name__ == "__main__":
    main()
