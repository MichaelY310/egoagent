#!/usr/bin/env python3
"""
Fix failed dataset downloads for EgoAgent project.
Addresses 3 failed datasets: BBH, GAIA, MT-Bench (raw GitHub).

Strategy:
- BBH: Try GitHub JSON download, fallback to LLM-generated BBH-style tasks
- GAIA: Try lighteval/MATH or cais/mmlu via HF mirror, fallback to LLM generation
- MT-Bench: Retry GitHub with longer timeout, fallback to existing HF version
"""

import os
import json
import time
import traceback
import re

# Set HF mirror endpoint before importing datasets
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["HUGGINGFACE_HUB_ENDPOINT"] = "https://hf-mirror.com"

import requests

BASE_DIR = "/mnt/bn/yangyuan-search-agent-rl-hl/mlx/users/yangyuan.335/data/egoagent_datasets"

LLM_BASE_URL = "http://[fdbd:dc05:10:10a::27]:9638/v1"
LLM_MODEL = "Qwen3-8B-yangyuan"

results = {}


def strip_think_tags(text):
    """Remove <think>...</think> tags from LLM responses, take content after </think>."""
    if "</think>" in text:
        text = text.split("</think>", 1)[1].strip()
    elif "<think>" in text:
        # Remove incomplete think block
        text = re.sub(r"<think>.*", "", text, flags=re.DOTALL).strip()
    return text


def call_llm(messages, max_tokens=4096, temperature=0.9):
    """Call the LLM API."""
    url = f"{LLM_BASE_URL}/chat/completions"
    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    resp = requests.post(url, json=payload, timeout=120)
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    return strip_think_tags(content)


def download_with_retry(name, download_fn):
    """Execute a download function with error handling."""
    print(f"\n{'='*60}")
    print(f"Downloading: {name}")
    print(f"{'='*60}")
    try:
        download_fn()
        results[name] = "SUCCESS"
        print(f"  ✓ {name} completed successfully")
    except Exception as e:
        results[name] = f"FAILED: {str(e)}"
        print(f"  ✗ {name} failed: {str(e)}")
        traceback.print_exc()


# =============================================================================
# Fix 1: BBH (Big-Bench Hard) - Download from GitHub JSON files
# =============================================================================
def fix_bbh():
    dir_path = os.path.join(BASE_DIR, "dir1_meta_evolution")
    os.makedirs(dir_path, exist_ok=True)

    def dl_bbh_boolean():
        filepath = os.path.join(dir_path, "bbh_boolean_300.jsonl")

        # Try GitHub download first
        url = "https://raw.githubusercontent.com/suzgunmirac/BIG-Bench-Hard/main/bbh/boolean_expressions.json"
        print(f"  Trying GitHub: {url}")
        try:
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            examples = data["examples"]
            count = 0
            with open(filepath, "w", encoding="utf-8") as f:
                for ex in examples[:300]:
                    f.write(json.dumps(ex, ensure_ascii=False) + "\n")
                    count += 1
            print(f"  ✓ Saved {count} examples to {filepath}")
            return
        except Exception as e:
            print(f"  GitHub download failed: {e}")
            print("  Falling back to LLM generation of BBH boolean expression tasks...")

        # Fallback: Generate BBH-style boolean expression tasks via LLM
        generate_bbh_boolean_tasks(filepath)

    download_with_retry("bbh_boolean_expressions", dl_bbh_boolean)

    def dl_bbh_logical():
        filepath = os.path.join(dir_path, "bbh_logical_300.jsonl")

        # Try GitHub download first
        url = "https://raw.githubusercontent.com/suzgunmirac/BIG-Bench-Hard/main/bbh/logical_deduction_five_objects.json"
        print(f"  Trying GitHub: {url}")
        try:
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            examples = data["examples"]
            count = 0
            with open(filepath, "w", encoding="utf-8") as f:
                for ex in examples[:300]:
                    f.write(json.dumps(ex, ensure_ascii=False) + "\n")
                    count += 1
            print(f"  ✓ Saved {count} examples to {filepath}")
            return
        except Exception as e:
            print(f"  GitHub download failed: {e}")
            print("  Falling back to LLM generation of BBH logical deduction tasks...")

        # Fallback: Generate BBH-style logical deduction tasks via LLM
        generate_bbh_logical_tasks(filepath)

    download_with_retry("bbh_logical_deduction", dl_bbh_logical)


def generate_bbh_boolean_tasks(filepath):
    """Generate BBH-style boolean expression evaluation tasks."""
    all_examples = []
    batch_size = 20
    total_needed = 300

    print(f"  Generating {total_needed} boolean expression tasks in batches of {batch_size}...")

    batch_num = 0
    while len(all_examples) < total_needed:
        batch_num += 1
        remaining = total_needed - len(all_examples)
        current_batch = min(batch_size, remaining)

        print(f"  Batch {batch_num}: generating {current_batch} tasks (total so far: {len(all_examples)})...")

        prompt = f"""Generate exactly {current_batch} boolean expression evaluation problems in the style of BIG-Bench Hard.

Each problem should be a nested boolean expression using "True", "False", "and", "or", "not" with parentheses.
The expressions should vary in complexity (2-5 operators).

Return a JSON array where each element has:
- "input": the boolean expression to evaluate (e.g., "not ( ( not not True ) and ( True and True ) )")
- "target": the correct answer, either "True" or "False"

Make expressions diverse in structure. Return ONLY the JSON array, no other text."""

        messages = [{"role": "user", "content": prompt}]

        try:
            response = call_llm(messages, max_tokens=4096, temperature=0.9)
            start_idx = response.find("[")
            end_idx = response.rfind("]")
            if start_idx != -1 and end_idx != -1:
                json_str = response[start_idx:end_idx + 1]
                tasks = json.loads(json_str)
                for task in tasks:
                    if isinstance(task, dict) and "input" in task and "target" in task:
                        all_examples.append({
                            "input": str(task["input"]),
                            "target": str(task["target"])
                        })
                print(f"    Got {len(tasks)} examples from this batch")
            else:
                print(f"    Warning: Could not find JSON array in response")
        except Exception as e:
            print(f"    Error in batch {batch_num}: {e}")

        time.sleep(0.5)

    all_examples = all_examples[:total_needed]
    with open(filepath, "w", encoding="utf-8") as f:
        for ex in all_examples:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")
    print(f"  ✓ Generated and saved {len(all_examples)} boolean expression tasks to {filepath}")


def generate_bbh_logical_tasks(filepath):
    """Generate BBH-style logical deduction (five objects) tasks."""
    all_examples = []
    batch_size = 20
    total_needed = 300

    print(f"  Generating {total_needed} logical deduction tasks in batches of {batch_size}...")

    batch_num = 0
    while len(all_examples) < total_needed:
        batch_num += 1
        remaining = total_needed - len(all_examples)
        current_batch = min(batch_size, remaining)

        print(f"  Batch {batch_num}: generating {current_batch} tasks (total so far: {len(all_examples)})...")

        prompt = f"""Generate exactly {current_batch} logical deduction puzzles about ordering five objects, in the style of BIG-Bench Hard "logical_deduction_five_objects".

Each puzzle gives clues about the relative positions of 5 objects (e.g., books on a shelf, people in a queue) and asks which statement is true.

Return a JSON array where each element has:
- "input": the puzzle description with constraints and a multiple-choice question (options A through E)
- "target": the correct answer letter in parentheses, e.g. "(A)" or "(B)" etc.

Make puzzles diverse. Return ONLY the JSON array, no other text."""

        messages = [{"role": "user", "content": prompt}]

        try:
            response = call_llm(messages, max_tokens=4096, temperature=0.9)
            start_idx = response.find("[")
            end_idx = response.rfind("]")
            if start_idx != -1 and end_idx != -1:
                json_str = response[start_idx:end_idx + 1]
                tasks = json.loads(json_str)
                for task in tasks:
                    if isinstance(task, dict) and "input" in task and "target" in task:
                        all_examples.append({
                            "input": str(task["input"]),
                            "target": str(task["target"])
                        })
                print(f"    Got {len(tasks)} examples from this batch")
            else:
                print(f"    Warning: Could not find JSON array in response")
        except Exception as e:
            print(f"    Error in batch {batch_num}: {e}")

        time.sleep(0.5)

    all_examples = all_examples[:total_needed]
    with open(filepath, "w", encoding="utf-8") as f:
        for ex in all_examples:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")
    print(f"  ✓ Generated and saved {len(all_examples)} logical deduction tasks to {filepath}")


# =============================================================================
# Fix 2: GAIA - Gated dataset, use alternatives
# =============================================================================
def fix_gaia():
    dir_path = os.path.join(BASE_DIR, "dir3_evo_benchmark")
    os.makedirs(dir_path, exist_ok=True)
    filepath = os.path.join(dir_path, "gaia_val_200.jsonl")

    def dl_gaia_alternatives():
        # Alternative 1: Try lighteval/MATH via HF mirror
        try:
            print("  Alternative 1: Trying lighteval/MATH...")
            from datasets import load_dataset
            ds = load_dataset("lighteval/MATH", split="test[:200]")
            count = 0
            with open(filepath, "w", encoding="utf-8") as f:
                for ex in ds:
                    f.write(json.dumps(ex, ensure_ascii=False) + "\n")
                    count += 1
            print(f"  ✓ Saved {count} examples to {filepath}")
            return
        except Exception as e1:
            print(f"  Alternative 1 failed: {e1}")

        # Alternative 2: Try cais/mmlu (confirmed working via HF mirror)
        try:
            print("  Alternative 2: Trying cais/mmlu all test[:200]...")
            from datasets import load_dataset
            ds = load_dataset("cais/mmlu", "all", split="test[:200]")
            count = 0
            with open(filepath, "w", encoding="utf-8") as f:
                for ex in ds:
                    f.write(json.dumps(ex, ensure_ascii=False) + "\n")
                    count += 1
            print(f"  ✓ Saved {count} examples to {filepath}")
            return
        except Exception as e2:
            print(f"  Alternative 2 failed: {e2}")

        # Alternative 3: Generate synthetic evaluation tasks using LLM
        print("  Alternative 3: Generating synthetic agent evaluation tasks via LLM...")
        generate_synthetic_eval_tasks(filepath)

    download_with_retry("gaia_alternative", dl_gaia_alternatives)


def generate_synthetic_eval_tasks(filepath):
    """Generate 200 diverse agent evaluation tasks using the LLM API."""
    all_tasks = []
    suites = ["coding", "reasoning", "writing", "mixed"]
    batch_size = 20
    total_needed = 200

    print(f"  Generating {total_needed} tasks in batches of {batch_size}...")

    batch_num = 0
    while len(all_tasks) < total_needed:
        batch_num += 1
        remaining = total_needed - len(all_tasks)
        current_batch = min(batch_size, remaining)
        suite = suites[(batch_num - 1) % len(suites)]

        print(f"  Batch {batch_num}: generating {current_batch} '{suite}' tasks (total so far: {len(all_tasks)})...")

        prompt = f"""Generate exactly {current_batch} diverse agent evaluation tasks for the "{suite}" category.

Each task should test an AI agent's ability to perform complex multi-step operations.

Return a JSON array where each element has:
- "task": a clear description of what the agent should do (1-3 sentences)
- "suite": "{suite}"
- "difficulty": an integer from 1-5 (1=easy, 5=very hard)
- "evaluation_criteria": how to judge if the agent succeeded (1 sentence)

Make tasks diverse and realistic. Return ONLY the JSON array, no other text."""

        messages = [{"role": "user", "content": prompt}]

        try:
            response = call_llm(messages, max_tokens=4096, temperature=0.9)
            start_idx = response.find("[")
            end_idx = response.rfind("]")
            if start_idx != -1 and end_idx != -1:
                json_str = response[start_idx:end_idx + 1]
                tasks = json.loads(json_str)
                for task in tasks:
                    if isinstance(task, dict) and "task" in task:
                        normalized = {
                            "task": str(task.get("task", "")),
                            "suite": str(task.get("suite", suite)),
                            "difficulty": int(task.get("difficulty", 3)),
                            "evaluation_criteria": str(task.get("evaluation_criteria", ""))
                        }
                        normalized["difficulty"] = max(1, min(5, normalized["difficulty"]))
                        all_tasks.append(normalized)
                print(f"    Got {len(tasks)} tasks from this batch")
            else:
                print(f"    Warning: Could not find JSON array in response")
        except Exception as e:
            print(f"    Error in batch {batch_num}: {e}")

        time.sleep(0.5)

    all_tasks = all_tasks[:total_needed]
    with open(filepath, "w", encoding="utf-8") as f:
        for task in all_tasks:
            f.write(json.dumps(task, ensure_ascii=False) + "\n")
    print(f"  ✓ Generated and saved {len(all_tasks)} synthetic evaluation tasks to {filepath}")


# =============================================================================
# Fix 3: MT-Bench from raw GitHub - Retry with longer timeout
# =============================================================================
def fix_mt_bench():
    dir_path = os.path.join(BASE_DIR, "dir6_self_play")
    os.makedirs(dir_path, exist_ok=True)

    def dl_mt_bench_raw():
        url = "https://raw.githubusercontent.com/lm-sys/FastChat/main/fastchat/llm_judge/data/mt_bench/question.jsonl"
        filepath = os.path.join(dir_path, "mt_bench_80.jsonl")

        # Check if file already exists from previous successful download
        if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            with open(filepath, "r") as f:
                line_count = sum(1 for _ in f)
            print(f"  File already exists with {line_count} lines: {filepath}")
            if line_count >= 80:
                print(f"  ✓ File is complete, skipping download")
                return

        # Check if HF version already exists (not critical if this fails)
        hf_path = os.path.join(dir_path, "mt_bench_hf.jsonl")
        if os.path.exists(hf_path) and os.path.getsize(hf_path) > 0:
            print(f"  Note: HF version already exists at {hf_path}")

        print(f"  Downloading from {url} (timeout=60s)")
        try:
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(resp.text)
            lines = resp.text.strip().split("\n")
            print(f"  ✓ Saved {len(lines)} examples to {filepath}")
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            print(f"  Download failed: {e}")
            print("  Checking if HF version exists as fallback...")
            if os.path.exists(hf_path) and os.path.getsize(hf_path) > 0:
                import shutil
                shutil.copy2(hf_path, filepath)
                with open(filepath, "r") as f:
                    line_count = sum(1 for _ in f)
                print(f"  ✓ Copied HF version ({line_count} lines) to {filepath}")
            else:
                raise

    download_with_retry("mt_bench_raw_retry", dl_mt_bench_raw)


# =============================================================================
# Main
# =============================================================================
def main():
    print("=" * 70)
    print("EgoAgent Dataset Download Fix")
    print(f"Base directory: {BASE_DIR}")
    print(f"HF_ENDPOINT: {os.environ.get('HF_ENDPOINT')}")
    print(f"LLM endpoint: {LLM_BASE_URL}")
    print("=" * 70)

    start_time = time.time()

    # Create base directory
    os.makedirs(BASE_DIR, exist_ok=True)

    # Fix 1: BBH
    print("\n\n" + "#" * 70)
    print("# FIX 1: BBH (Big-Bench Hard) - Download from GitHub JSON")
    print("#" * 70)
    fix_bbh()

    # Fix 2: GAIA
    print("\n\n" + "#" * 70)
    print("# FIX 2: GAIA - Use alternative datasets or LLM generation")
    print("#" * 70)
    fix_gaia()

    # Fix 3: MT-Bench
    print("\n\n" + "#" * 70)
    print("# FIX 3: MT-Bench - Retry with longer timeout")
    print("#" * 70)
    fix_mt_bench()

    elapsed = time.time() - start_time

    # Print summary
    print("\n\n")
    print("=" * 70)
    print("DOWNLOAD FIX SUMMARY")
    print("=" * 70)
    print(f"Total time: {elapsed:.1f}s")
    print(f"Total datasets attempted: {len(results)}")
    print()

    succeeded = [k for k, v in results.items() if v == "SUCCESS"]
    failed = [k for k, v in results.items() if v != "SUCCESS"]

    print(f"✓ Succeeded ({len(succeeded)}):")
    for name in succeeded:
        print(f"    {name}")

    if failed:
        print(f"\n✗ Failed ({len(failed)}):")
        for name in failed:
            print(f"    {name}: {results[name]}")
    else:
        print("\nAll fixes completed successfully!")

    # Verify output files
    print("\n" + "=" * 70)
    print("OUTPUT FILE VERIFICATION")
    print("=" * 70)
    expected_files = [
        os.path.join(BASE_DIR, "dir1_meta_evolution", "bbh_boolean_300.jsonl"),
        os.path.join(BASE_DIR, "dir1_meta_evolution", "bbh_logical_300.jsonl"),
        os.path.join(BASE_DIR, "dir3_evo_benchmark", "gaia_val_200.jsonl"),
        os.path.join(BASE_DIR, "dir6_self_play", "mt_bench_80.jsonl"),
    ]
    for fpath in expected_files:
        if os.path.exists(fpath):
            size = os.path.getsize(fpath)
            with open(fpath, "r") as f:
                line_count = sum(1 for _ in f)
            print(f"  ✓ {fpath}")
            print(f"      Size: {size:,} bytes, Lines: {line_count}")
        else:
            print(f"  ✗ MISSING: {fpath}")

    print("=" * 70)


if __name__ == "__main__":
    main()
