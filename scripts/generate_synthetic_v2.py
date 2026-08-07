#!/usr/bin/env python3
"""Synthetic Data Generator V2"""
import os, sys, json, time, random, re, requests
from pathlib import Path

BASE_DIR = Path("/mnt/bn/yangyuan-search-agent-rl-hl/mlx/users/yangyuan.335/data/egoagent_datasets")
LLM_URL = "http://[fdbd:dc05:10:10a::27]:9638/v1/chat/completions"

def call_llm(prompt, max_tokens=4096):
    try:
        resp = requests.post(LLM_URL, json={"model": "qwen3", "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens, "temperature": 0.8}, timeout=120)
        if resp.status_code == 200:
            c = resp.json()["choices"][0]["message"]["content"]
            c = re.sub(r'<think>.*?</think>', '', c, flags=re.DOTALL).strip()
            return c
    except Exception as e:
        print(f"  LLM err: {e}")
    return None

def parse_json_array(text):
    if not text: return []
    m = re.search(r'\[[\s\S]*\]', text)
    if m:
        try: return json.loads(m.group())
        except: pass
    results = []
    for line in text.split('\n'):
        line = line.strip()
        if line.startswith('{') and line.endswith('}'):
            try: results.append(json.loads(line))
            except: pass
    return results

def save_jsonl(data, filepath):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"  Saved {len(data)} to {os.path.basename(filepath)}")

def gen_dir4(n=15):
    print("\n=== Dir4: Pipeline Search ===")
    all_data = []
    for i in range(n):
        print(f"  Batch {i+1}/{n}...")
        r = call_llm(f'Generate 8 complex tasks requiring multi-step pipelines. JSON array, each item: {{"task":"the question", "answer":"expected answer", "required_capabilities":["reasoning","retrieval","math","coding","summarization"], "complexity":3, "ideal_pipeline":"step1 -> step2 -> step3"}}. Batch {i+1}, vary domains (science, business, engineering).')
        for item in parse_json_array(r):
            if "task" in item:
                item["source"] = "synthetic_v2"
                all_data.append(item)
        time.sleep(2)
    if all_data:
        save_jsonl(all_data, str(BASE_DIR / "dir4_pipeline_search" / "synthetic_complex_v2.jsonl"))
    return len(all_data)

def gen_dir6(n=15):
    print("\n=== Dir6: Self-Play ===")
    all_data = []
    for i in range(n):
        print(f"  Batch {i+1}/{n}...")
        r = call_llm(f'Generate 8 debate topics for multi-agent self-play. JSON array, each: {{"topic":"debate question", "turns":["pro argument","con argument","pro rebuttal","con rebuttal"], "category":"ethics/technology/education/science", "difficulty":"medium"}}. Batch {i+1}, nuanced topics with valid arguments on both sides.')
        for item in parse_json_array(r):
            if "topic" in item:
                item["source"] = "synthetic_v2"
                item.setdefault("turns", [item["topic"]])
                all_data.append(item)
        time.sleep(2)
    if all_data:
        save_jsonl(all_data, str(BASE_DIR / "dir6_self_play" / "synthetic_debates_v2.jsonl"))
    return len(all_data)

def gen_dir1(n=10):
    print("\n=== Dir1: Meta-Evolution ===")
    all_data = []
    for i in range(n):
        print(f"  Batch {i+1}/{n}...")
        r = call_llm(f'Generate 8 diverse cognitive tasks for prompt optimization evaluation. JSON array, each: {{"task":"the task", "reference_answer":"correct answer", "category":"reasoning/math/coding/analysis/logic", "difficulty":"easy/medium/hard"}}. Batch {i+1}, mix difficulty and domains.')
        for item in parse_json_array(r):
            if "task" in item:
                item["source"] = "synthetic_v2"
                all_data.append(item)
        time.sleep(2)
    if all_data:
        save_jsonl(all_data, str(BASE_DIR / "dir1_meta_evolution" / "synthetic_diverse_v2.jsonl"))
    return len(all_data)

def gen_dir2(n=8):
    print("\n=== Dir2: Persona ===")
    all_data = []
    for i in range(n):
        print(f"  Batch {i+1}/{n}...")
        r = call_llm(f'Generate 8 persona test cases. JSON array, each: {{"persona":{{"traits":["trait1","trait2","trait3"],"tone":"formal/casual/technical","role":"specific_role"}},"probe_question":"question testing persona","expected_behavior":"what correct response shows"}}. Batch {i+1}, diverse roles (scientist, artist, teacher, engineer, doctor).')
        for item in parse_json_array(r):
            if "persona" in item:
                item["source"] = "synthetic_v2"
                all_data.append(item)
        time.sleep(2)
    if all_data:
        save_jsonl(all_data, str(BASE_DIR / "dir2_identity_persona" / "synthetic_persona_v2.jsonl"))
    return len(all_data)

if __name__ == "__main__":
    print("=== Synthetic Data Generator V2 ===")
    r = {}
    r["dir4"] = gen_dir4(15)
    r["dir6"] = gen_dir6(15)
    r["dir1"] = gen_dir1(10)
    r["dir2"] = gen_dir2(8)
    print(f"\nDone: {r}, Total: {sum(r.values())}")
