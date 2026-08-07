#!/usr/bin/env python3
"""
Download small subsets of public datasets for 6 research directions.
Uses HuggingFace mirror endpoint for China region access.
"""

import os
import json
import time
import traceback

# Set HF mirror endpoint before importing datasets
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

import requests
from datasets import load_dataset

BASE_DIR = "/mnt/bn/yangyuan-search-agent-rl-hl/mlx/users/yangyuan.335/data/egoagent_datasets"

SUBDIRS = {
    "dir1": "dir1_meta_evolution",
    "dir2": "dir2_identity_persona",
    "dir3": "dir3_evo_benchmark",
    "dir4": "dir4_pipeline_search",
    "dir5": "dir5_lifelong_learning",
    "dir6": "dir6_self_play",
}

results = {}  # track success/failure


def save_as_jsonl(dataset, filepath, max_examples=None):
    """Save a HuggingFace dataset as JSONL file."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    count = 0
    with open(filepath, "w", encoding="utf-8") as f:
        for i, example in enumerate(dataset):
            if max_examples and i >= max_examples:
                break
            f.write(json.dumps(example, ensure_ascii=False) + "\n")
            count += 1
    print(f"  ✓ Saved {count} examples to {filepath}")
    return count


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
# Direction 1: Meta-Evolution
# =============================================================================
def download_dir1():
    dir_path = os.path.join(BASE_DIR, SUBDIRS["dir1"])
    os.makedirs(dir_path, exist_ok=True)

    # GSM8K
    def dl_gsm8k():
        ds = load_dataset("openai/gsm8k", "main", split="test[:300]")
        save_as_jsonl(ds, os.path.join(dir_path, "gsm8k_test_300.jsonl"))

    download_with_retry("dir1/gsm8k", dl_gsm8k)

    # BBH boolean_expressions
    def dl_bbh_boolean():
        ds = load_dataset("maveriq/bigbenchhard", "boolean_expressions")
        # This dataset may have only one split
        split_name = list(ds.keys())[0]
        save_as_jsonl(ds[split_name], os.path.join(dir_path, "bbh_boolean_300.jsonl"), max_examples=300)

    download_with_retry("dir1/bbh_boolean", dl_bbh_boolean)

    # BBH logical_deduction
    def dl_bbh_logical():
        ds = load_dataset("maveriq/bigbenchhard", "logical_deduction_five_objects")
        split_name = list(ds.keys())[0]
        save_as_jsonl(ds[split_name], os.path.join(dir_path, "bbh_logical_300.jsonl"), max_examples=300)

    download_with_retry("dir1/bbh_logical", dl_bbh_logical)


# =============================================================================
# Direction 2: Identity/Persona Control
# =============================================================================
def download_dir2():
    dir_path = os.path.join(BASE_DIR, SUBDIRS["dir2"])
    os.makedirs(dir_path, exist_ok=True)

    def dl_personachat():
        try:
            print("  Trying bavard/personachat_truecased...")
            ds = load_dataset("bavard/personachat_truecased", split="train[:300]")
            save_as_jsonl(ds, os.path.join(dir_path, "personachat_300.jsonl"))
        except Exception as e1:
            print(f"  First attempt failed: {e1}")
            print("  Trying AlekseyKorshuk/persona-chat...")
            ds = load_dataset("AlekseyKorshuk/persona-chat", split="train[:300]")
            save_as_jsonl(ds, os.path.join(dir_path, "personachat_300.jsonl"))

    download_with_retry("dir2/personachat", dl_personachat)


# =============================================================================
# Direction 3: Evolution Benchmark (agent eval tasks)
# =============================================================================
def download_dir3():
    dir_path = os.path.join(BASE_DIR, SUBDIRS["dir3"])
    os.makedirs(dir_path, exist_ok=True)

    def dl_gaia():
        try:
            print("  Trying gaia-benchmark/GAIA 2023_all...")
            ds = load_dataset("gaia-benchmark/GAIA", "2023_all", split="validation[:200]")
            save_as_jsonl(ds, os.path.join(dir_path, "gaia_val_200.jsonl"))
        except Exception as e1:
            print(f"  First attempt failed: {e1}")
            try:
                print("  Trying gaia-benchmark/GAIA 2023_level1...")
                ds = load_dataset("gaia-benchmark/GAIA", "2023_level1", split="test[:200]")
                save_as_jsonl(ds, os.path.join(dir_path, "gaia_val_200.jsonl"))
            except Exception as e2:
                print(f"  Second attempt failed: {e2}")
                print("  Trying gaia-benchmark/GAIA default...")
                ds = load_dataset("gaia-benchmark/GAIA", split="validation[:200]")
                save_as_jsonl(ds, os.path.join(dir_path, "gaia_val_200.jsonl"))

    download_with_retry("dir3/gaia", dl_gaia)


# =============================================================================
# Direction 4: Pipeline Architecture Search (multi-step reasoning)
# =============================================================================
def download_dir4():
    dir_path = os.path.join(BASE_DIR, SUBDIRS["dir4"])
    os.makedirs(dir_path, exist_ok=True)

    def dl_hotpotqa():
        ds = load_dataset("hotpotqa/hotpot_qa", "distractor", split="validation[:300]")
        save_as_jsonl(ds, os.path.join(dir_path, "hotpotqa_val_300.jsonl"))

    download_with_retry("dir4/hotpotqa", dl_hotpotqa)


# =============================================================================
# Direction 5: Lifelong Learning (sequential tasks)
# =============================================================================
def download_dir5():
    dir_path = os.path.join(BASE_DIR, SUBDIRS["dir5"])
    os.makedirs(dir_path, exist_ok=True)

    # TriviaQA
    def dl_triviaqa():
        ds = load_dataset("trivia_qa", "rc.nocontext", split="validation[:300]")
        save_as_jsonl(ds, os.path.join(dir_path, "triviaqa_val_300.jsonl"))

    download_with_retry("dir5/triviaqa", dl_triviaqa)

    # MMLU
    def dl_mmlu():
        ds = load_dataset("cais/mmlu", "all", split="test[:300]")
        save_as_jsonl(ds, os.path.join(dir_path, "mmlu_test_300.jsonl"))

    download_with_retry("dir5/mmlu", dl_mmlu)


# =============================================================================
# Direction 6: Multi-Agent Self-Play (debate/evaluation tasks)
# =============================================================================
def download_dir6():
    dir_path = os.path.join(BASE_DIR, SUBDIRS["dir6"])
    os.makedirs(dir_path, exist_ok=True)

    # MT-Bench from raw GitHub URL
    def dl_mt_bench_raw():
        url = "https://raw.githubusercontent.com/lm-sys/FastChat/main/fastchat/llm_judge/data/mt_bench/question.jsonl"
        print(f"  Downloading from {url}")
        resp = requests.get(url, timeout=300)
        resp.raise_for_status()
        filepath = os.path.join(dir_path, "mt_bench_80.jsonl")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(resp.text)
        lines = resp.text.strip().split("\n")
        print(f"  ✓ Saved {len(lines)} examples to {filepath}")

    download_with_retry("dir6/mt_bench_raw", dl_mt_bench_raw)

    # MT-Bench from HuggingFace
    def dl_mt_bench_hf():
        ds = load_dataset("HuggingFaceH4/mt_bench_prompts", split="train")
        save_as_jsonl(ds, os.path.join(dir_path, "mt_bench_hf.jsonl"))

    download_with_retry("dir6/mt_bench_hf", dl_mt_bench_hf)


# =============================================================================
# Main
# =============================================================================
def main():
    print("=" * 70)
    print("EgoAgent Dataset Downloader")
    print(f"Base directory: {BASE_DIR}")
    print(f"HF_ENDPOINT: {os.environ.get('HF_ENDPOINT')}")
    print("=" * 70)

    start_time = time.time()

    # Create base directory
    os.makedirs(BASE_DIR, exist_ok=True)

    # Download all directions
    download_dir1()
    download_dir2()
    download_dir3()
    download_dir4()
    download_dir5()
    download_dir6()

    elapsed = time.time() - start_time

    # Print summary
    print("\n")
    print("=" * 70)
    print("DOWNLOAD SUMMARY")
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
        print("\nAll downloads completed successfully!")

    print("=" * 70)


if __name__ == "__main__":
    main()
