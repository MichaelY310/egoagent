#!/usr/bin/env python3
"""
GSM8K-only evolution test — focuses on real data with structural evolution.
"""
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))

from run_multi_scenario_test import (
    run_scenario, load_gsm8k, OUTPUT_DIR, run_task_with_dag, evaluate_response, DAGState
)
import time
import json
from pathlib import Path

def main():
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  EgoAgent — GSM8K Batch Validation (50 questions)           ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    
    gsm8k_tasks = load_gsm8k(50)
    print(f"  Loaded {len(gsm8k_tasks)} GSM8K tasks")
    
    # Phase 1: Evolution on first 20 tasks
    print(f"\n  Phase 1: Evolve on first 20 tasks")
    evolve_scenario = {
        "name": "gsm8k_evolve",
        "description": "GSM8K evolution phase (20 questions)",
        "initial_prompt": "You are a math problem solver. Think step by step and solve the problem. Put your final numerical answer inside <final_answer></final_answer> tags.",
        "tasks": gsm8k_tasks[:20],
    }
    r = run_scenario(evolve_scenario, max_rounds=6, eval_fmt="<final_answer>")
    
    evolve_acc = r["final_accuracy"]
    print(f"\n  Evolution result: {evolve_acc:.0%}")
    
    # Phase 2: Test evolved system on remaining 30 tasks (no further evolution)
    print(f"\n  Phase 2: Testing evolved system on tasks 21-50 (no evolution, just eval)")
    
    # Reconstruct the evolved DAG state
    dag_state = DAGState(r["final_prompt"])
    
    test_tasks = gsm8k_tasks[20:50]
    correct = 0
    total = 0
    failures = []
    for task in test_tasks:
        resp = run_task_with_dag(dag_state, task["question"])
        ev = evaluate_response(resp, task["answer"], "<final_answer>")
        total += 1
        if ev["correct"]:
            correct += 1
        else:
            failures.append({
                "question": task["question"][:100],
                "expected": task["answer"],
                "extracted": ev.get("extracted"),
                "reason": ev.get("reason"),
            })
    
    test_acc = correct / total if total > 0 else 0
    print(f"  Test accuracy (30 unseen tasks): {correct}/{total} = {test_acc:.0%}")
    
    # Phase 3: Report
    print(f"\n{'═'*60}")
    print("  FINAL REPORT")
    print(f"{'═'*60}")
    print(f"  Evolution (20 tasks): {evolve_acc:.0%}")
    print(f"  Generalization (30 unseen): {test_acc:.0%}")
    print(f"  Structural changes: {r['structural_changes']}")
    print(f"  Evolution rounds: {len(r['rounds'])}")
    rounds_info = [f"{rd['round']}: {rd['accuracy']:.0%}" for rd in r['rounds']]
    print(f"  Round-by-round: {rounds_info}")
    
    if failures[:5]:
        print(f"\n  Sample failures (5/{len(failures)}):")
        for f in failures[:5]:
            print(f"    Q: {f['question'][:80]}...")
            print(f"    Expected: {f['expected']}, Got: {f['extracted']}, Reason: {f['reason']}")
    
    report = {
        "evolution_accuracy": evolve_acc,
        "test_accuracy": test_acc,
        "evolution_rounds": r["rounds"],
        "structural_changes": r["structural_changes"],
        "final_prompt": r["final_prompt"],
        "test_failures": failures[:10],
    }
    report_path = OUTPUT_DIR / f"gsm8k_batch_{time.strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  Report: {report_path}")


if __name__ == "__main__":
    main()
