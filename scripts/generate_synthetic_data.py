#!/usr/bin/env python3
"""Generate synthetic datasets for all 6 research directions using LLM API calls."""

import json
import os
import sys
import time
import requests

# LLM API configuration
BASE_URL = "http://[fdbd:dc05:10:10a::27]:9638/v1"
MODEL = "Qwen3-8B-yangyuan"
API_KEY = ""

# Output base directory
OUTPUT_BASE = "/mnt/bn/yangyuan-search-agent-rl-hl/mlx/users/yangyuan.335/data/egoagent_datasets/"

MAX_RETRIES = 3
MAX_TOKENS = 4096
BATCH_SIZE = 10


def call_llm(prompt, max_tokens=MAX_TOKENS):
    """Call the LLM API and return the response text."""
    url = f"{BASE_URL}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"

    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.8,
    }

    resp = requests.post(url, json=payload, headers=headers, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    return content


def strip_think_tags(text):
    """Strip <think>...</think> tags from LLM response."""
    if "</think>" in text:
        text = text.split("</think>", 1)[1]
    return text.strip()


def parse_json_array(text):
    """Parse a JSON array from text, handling markdown code fences."""
    text = strip_think_tags(text)
    # Remove markdown code fences if present
    if "```json" in text:
        text = text.split("```json", 1)[1]
        text = text.split("```", 1)[0]
    elif "```" in text:
        text = text.split("```", 1)[1]
        text = text.split("```", 1)[0]
    text = text.strip()
    # Try to find the JSON array
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1:
        text = text[start:end + 1]
    return json.loads(text)


def generate_batch(prompt, batch_num, total_batches):
    """Generate a batch with retries."""
    for attempt in range(MAX_RETRIES):
        try:
            print(f"  Batch {batch_num}/{total_batches}, attempt {attempt + 1}...", flush=True)
            response = call_llm(prompt)
            items = parse_json_array(response)
            if isinstance(items, list) and len(items) > 0:
                print(f"  -> Got {len(items)} items", flush=True)
                return items
            else:
                print(f"  -> Empty or invalid result, retrying...", flush=True)
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            print(f"  -> Parse error: {e}, retrying...", flush=True)
        except requests.exceptions.RequestException as e:
            print(f"  -> Request error: {e}, retrying...", flush=True)
        time.sleep(2)
    print(f"  -> Failed after {MAX_RETRIES} attempts, skipping batch", flush=True)
    return []


def save_jsonl(items, filepath):
    """Save items as JSONL file."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"  Saved {len(items)} items to {filepath}", flush=True)


# ============================================================
# Direction 1: Meta-Evolution
# ============================================================
def generate_dir1():
    print("\n" + "=" * 60, flush=True)
    print("Direction 1: Meta-Evolution - Synthetic Prompt Tasks", flush=True)
    print("=" * 60, flush=True)

    all_items = []
    num_batches = 10  # 10 batches * 10 items = 100

    for i in range(num_batches):
        category_focus = ["coding", "reasoning", "writing", "general"][i % 4]
        prompt = f"""Generate exactly {BATCH_SIZE} diverse tasks that test an AI assistant's quality. Focus mostly on "{category_focus}" tasks for this batch but include some variety.

Return a JSON array of objects, each with these fields:
- "task": a question or instruction (be specific and detailed)
- "reference_answer": the ideal answer (2-3 sentences)
- "category": one of "coding", "reasoning", "writing", "general"
- "difficulty": one of "easy", "medium", "hard"

Return ONLY the JSON array, no extra text. Example format:
[{{"task": "Write a Python function...", "reference_answer": "...", "category": "coding", "difficulty": "medium"}}]

Make tasks diverse and realistic. Batch {i+1}/{num_batches}."""

        items = generate_batch(prompt, i + 1, num_batches)
        all_items.extend(items)

    filepath = os.path.join(OUTPUT_BASE, "dir1_meta_evolution/synthetic_prompt_tasks_100.jsonl")
    save_jsonl(all_items[:100], filepath)
    return len(all_items[:100])


# ============================================================
# Direction 2: Identity/Persona
# ============================================================
def generate_dir2():
    print("\n" + "=" * 60, flush=True)
    print("Direction 2: Identity/Persona - Synthetic Persona Probes", flush=True)
    print("=" * 60, flush=True)

    all_items = []
    num_batches = 10

    tone_styles = ["formal", "casual", "academic", "friendly", "authoritative",
                   "humorous", "empathetic", "direct", "poetic", "technical"]

    for i in range(num_batches):
        tone = tone_styles[i % len(tone_styles)]
        prompt = f"""Generate exactly {BATCH_SIZE} persona probe tasks for testing AI persona consistency. Focus on "{tone}" tone for this batch.

Return a JSON array of objects, each with these fields:
- "persona": an object with "tone" (string), "traits" (array of 2-3 strings like "analytical", "creative", "concise"), and "role" (string like "tech advisor", "life coach", "teacher")
- "probe_question": a question that tests whether the AI maintains this persona
- "expected_behavior": description of how this persona should respond (1-2 sentences)

Return ONLY the JSON array. Example:
[{{"persona": {{"tone": "formal", "traits": ["analytical", "precise"], "role": "data scientist"}}, "probe_question": "Explain machine learning to me", "expected_behavior": "Should use technical language..."}}]

Make personas diverse: formal/casual, analytical/creative, concise/verbose. Batch {i+1}/{num_batches}."""

        items = generate_batch(prompt, i + 1, num_batches)
        all_items.extend(items)

    filepath = os.path.join(OUTPUT_BASE, "dir2_identity_persona/synthetic_persona_probes_100.jsonl")
    save_jsonl(all_items[:100], filepath)
    return len(all_items[:100])


# ============================================================
# Direction 3: Evolution Benchmark
# ============================================================
def generate_dir3():
    print("\n" + "=" * 60, flush=True)
    print("Direction 3: Evolution Benchmark - Synthetic Eval Tasks", flush=True)
    print("=" * 60, flush=True)

    all_items = []
    num_batches = 10

    suites = ["coding", "reasoning", "writing", "mixed"]

    for i in range(num_batches):
        suite = suites[i % 4]
        prompt = f"""Generate exactly {BATCH_SIZE} agent evaluation tasks for the "{suite}" evaluation suite.

Return a JSON array of objects, each with these fields:
- "task": a detailed task description
- "suite": one of "coding", "reasoning", "writing", "mixed"
- "difficulty": an integer from 1 to 5
- "evaluation_criteria": what makes a good answer (1-2 sentences)

Return ONLY the JSON array. Example:
[{{"task": "Implement a binary search tree...", "suite": "coding", "difficulty": 3, "evaluation_criteria": "Correct implementation with O(log n) search"}}]

Make tasks progressively harder within the batch. Batch {i+1}/{num_batches}."""

        items = generate_batch(prompt, i + 1, num_batches)
        all_items.extend(items)

    filepath = os.path.join(OUTPUT_BASE, "dir3_evo_benchmark/synthetic_eval_tasks_100.jsonl")
    save_jsonl(all_items[:100], filepath)
    return len(all_items[:100])


# ============================================================
# Direction 4: Pipeline Architecture Search
# ============================================================
def generate_dir4():
    print("\n" + "=" * 60, flush=True)
    print("Direction 4: Pipeline Architecture Search - Workflow Tasks", flush=True)
    print("=" * 60, flush=True)

    all_items = []
    num_batches = 10

    pipeline_types = ["single-step reasoning", "multi-step planning", "tool-use heavy",
                      "retrieval-augmented", "mixed workflow"]

    for i in range(num_batches):
        ptype = pipeline_types[i % len(pipeline_types)]
        prompt = f"""Generate exactly {BATCH_SIZE} tasks that require different agent workflows. Focus on "{ptype}" tasks for this batch.

Return a JSON array of objects, each with these fields:
- "task": a detailed task description
- "required_capabilities": array from ["reasoning", "retrieval", "tool_use", "planning"] (include 1-4 capabilities)
- "complexity": integer from 1 to 5
- "ideal_pipeline": description of the best workflow to solve this task (1-2 sentences)

Return ONLY the JSON array. Example:
[{{"task": "Find the latest stock price of AAPL and calculate...", "required_capabilities": ["retrieval", "reasoning"], "complexity": 3, "ideal_pipeline": "First retrieve data via API, then compute..."}}]

Vary complexity levels. Batch {i+1}/{num_batches}."""

        items = generate_batch(prompt, i + 1, num_batches)
        all_items.extend(items)

    filepath = os.path.join(OUTPUT_BASE, "dir4_pipeline_search/synthetic_workflow_tasks_100.jsonl")
    save_jsonl(all_items[:100], filepath)
    return len(all_items[:100])


# ============================================================
# Direction 5: Lifelong Learning
# ============================================================
def generate_dir5():
    print("\n" + "=" * 60, flush=True)
    print("Direction 5: Lifelong Learning - Synthetic Task Stream", flush=True)
    print("=" * 60, flush=True)

    all_items = []
    num_batches = 10

    domains = ["math", "science", "coding", "history", "language"]

    for i in range(num_batches):
        domain = domains[i % len(domains)]
        stream_id = (i // 2) + 1  # streams 1-5, each domain gets ~2 batches
        prompt = f"""Generate exactly {BATCH_SIZE} tasks for a lifelong learning task stream in the "{domain}" domain. These tasks form stream #{stream_id} and should build on each other sequentially (positions 1-10 in the stream).

Return a JSON array of objects, each with these fields:
- "task": a detailed task description
- "domain": one of "math", "science", "coding", "history", "language"
- "stream_id": {stream_id}
- "position_in_stream": integer from 1 to 10 (assign sequentially)
- "depends_on_previous": true if understanding previous tasks helps, false otherwise
- "key_knowledge": what concept or skill this task teaches (1 sentence)

Return ONLY the JSON array. Example:
[{{"task": "Define what a variable is in programming", "domain": "coding", "stream_id": 1, "position_in_stream": 1, "depends_on_previous": false, "key_knowledge": "Understanding variables as named storage"}}]

Tasks should get progressively harder. Batch {i+1}/{num_batches}."""

        items = generate_batch(prompt, i + 1, num_batches)
        all_items.extend(items)

    filepath = os.path.join(OUTPUT_BASE, "dir5_lifelong_learning/synthetic_task_stream_100.jsonl")
    save_jsonl(all_items[:100], filepath)
    return len(all_items[:100])


# ============================================================
# Direction 6: Multi-Agent Self-Play
# ============================================================
def generate_dir6():
    print("\n" + "=" * 60, flush=True)
    print("Direction 6: Multi-Agent Self-Play - Debate Topics", flush=True)
    print("=" * 60, flush=True)

    all_items = []
    num_batches = 10

    debate_domains = ["ethics", "science", "policy", "technology", "philosophy"]

    for i in range(num_batches):
        domain = debate_domains[i % len(debate_domains)]
        prompt = f"""Generate exactly {BATCH_SIZE} debate/argumentation topics in the "{domain}" domain for a multi-agent debate system.

Return a JSON array of objects, each with these fields:
- "topic": a clear debate topic (a statement or question)
- "position_a": a pro/supporting argument (2-3 sentences)
- "position_b": a con/opposing argument (2-3 sentences)
- "difficulty": one of "easy", "medium", "hard"
- "domain": one of "ethics", "science", "policy", "technology", "philosophy"

Return ONLY the JSON array. Example:
[{{"topic": "AI should be regulated by governments", "position_a": "Regulation ensures safety...", "position_b": "Regulation stifles innovation...", "difficulty": "medium", "domain": "policy"}}]

Include a mix of difficulties. Make topics thought-provoking and balanced. Batch {i+1}/{num_batches}."""

        items = generate_batch(prompt, i + 1, num_batches)
        all_items.extend(items)

    filepath = os.path.join(OUTPUT_BASE, "dir6_self_play/synthetic_debate_topics_100.jsonl")
    save_jsonl(all_items[:100], filepath)
    return len(all_items[:100])


# ============================================================
# Main
# ============================================================
def main():
    print("=" * 60, flush=True)
    print("Synthetic Data Generation for EgoAgent Research Directions", flush=True)
    print("=" * 60, flush=True)
    print(f"LLM: {MODEL}", flush=True)
    print(f"API: {BASE_URL}", flush=True)
    print(f"Output: {OUTPUT_BASE}", flush=True)
    print(f"Batch size: {BATCH_SIZE}", flush=True)
    print("", flush=True)

    start_time = time.time()
    results = {}

    generators = [
        ("Direction 1: Meta-Evolution", generate_dir1),
        ("Direction 2: Identity/Persona", generate_dir2),
        ("Direction 3: Evolution Benchmark", generate_dir3),
        ("Direction 4: Pipeline Architecture Search", generate_dir4),
        ("Direction 5: Lifelong Learning", generate_dir5),
        ("Direction 6: Multi-Agent Self-Play", generate_dir6),
    ]

    for name, gen_func in generators:
        try:
            count = gen_func()
            results[name] = f"✓ {count} items"
        except Exception as e:
            results[name] = f"✗ Error: {e}"
            print(f"  ERROR: {e}", flush=True)

    elapsed = time.time() - start_time
    print("\n" + "=" * 60, flush=True)
    print("SUMMARY", flush=True)
    print("=" * 60, flush=True)
    for name, status in results.items():
        print(f"  {name}: {status}", flush=True)
    print(f"\nTotal time: {elapsed:.1f}s ({elapsed/60:.1f} min)", flush=True)
    print("Done!", flush=True)


if __name__ == "__main__":
    main()
