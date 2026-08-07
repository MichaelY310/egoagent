#!/usr/bin/env python3
"""
Structural Evolution Experiment
===============================
验证 EgoAgent evolver 能否**自主决定**修改 DAG 结构（而非仅改 prompt）。

核心设计：
- 题目要求答案严格符合 <final_answer>数字</final_answer> 格式
- 初始 prompt 故意不提格式要求
- Evolver（TextGrad LLM）在分析失败轨迹后，自己决定是改 prompt 还是加 DAG 节点
- Evolver 的输出空间被扩展为 JSON，包含 action_type: "modify_prompt" | "add_node"

关键：我们不硬编码任何"检测格式错误→自动加节点"的逻辑。
结构变更完全由 evolver LLM 的判断驱动。
"""

import json
import re
import copy
import time
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

# LLM config (same as engine.py)
LLM_BASE_URL = "http://[fdbd:dc05:10:10a::27]:9638/v1"
LLM_MODEL = "Qwen3-8B-yangyuan"

OUTPUT_DIR = Path(__file__).parent / "_structural_evolution_output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
# 题目集设计
# ============================================================
# 关键：答案必须包在 <final_answer></final_answer> 标签里
# 这种格式对 8B 模型来说，如果 prompt 没有强调，很容易遗忘或拼错

TASKS = [
    {"question": "What is 15 * 7 + 3?", "answer": "108"},
    {"question": "If a train travels 60km/h for 2.5 hours, how many km does it travel?", "answer": "150"},
    {"question": "What is the square root of 144?", "answer": "12"},
    {"question": "A store has a 20% off sale. What is the price of a $80 item?", "answer": "64"},
    {"question": "How many minutes are in 3.5 hours?", "answer": "210"},
    {"question": "What is 2^8?", "answer": "256"},
    {"question": "If you divide 450 by 9, what do you get?", "answer": "50"},
    {"question": "A rectangle has width 7 and length 13. What is its area?", "answer": "91"},
    {"question": "What is 17 + 28 + 45?", "answer": "90"},
    {"question": "If a car uses 8 liters per 100km, how many liters for 350km?", "answer": "28"},
    {"question": "What is 999 - 573?", "answer": "426"},
    {"question": "How many seconds are in 2 hours?", "answer": "7200"},
]

# ============================================================
# LLM 调用
# ============================================================

def llm_call(messages: List[Dict], max_tokens=2048, temperature=0.7) -> str:
    """调用 LLM API"""
    import requests
    url = f"{LLM_BASE_URL}/chat/completions"
    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    try:
        resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=120)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"].get("content", "")
        # Strip thinking tags
        if "</think>" in content:
            content = content.split("</think>")[-1].strip()
        elif "<think>" in content:
            content = ""
        return content
    except Exception as e:
        return f"[LLM_ERROR] {e}"


# ============================================================
# 评估逻辑（Ground Truth Exact Match）
# ============================================================

def extract_final_answer(response: str) -> Optional[str]:
    """从回答中提取 <final_answer>...</final_answer> 中的内容"""
    pattern = r'<final_answer>\s*(.*?)\s*</final_answer>'
    match = re.search(pattern, response, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


def evaluate_response(response: str, ground_truth: str) -> Dict:
    """评估单个回答"""
    extracted = extract_final_answer(response)
    format_ok = extracted is not None
    
    if not format_ok:
        return {"correct": False, "format_ok": False, "extracted": None, "reason": "missing_format"}
    
    # Normalize numbers
    try:
        if float(extracted) == float(ground_truth):
            return {"correct": True, "format_ok": True, "extracted": extracted}
    except (ValueError, TypeError):
        pass
    
    if extracted.strip() == ground_truth.strip():
        return {"correct": True, "format_ok": True, "extracted": extracted}
    
    return {"correct": False, "format_ok": True, "extracted": extracted, "reason": "wrong_answer"}


# ============================================================
# DAG 执行（简化版，不走完整 pipeline_engine）
# ============================================================

def run_task_with_dag(dag_config: Dict, system_prompt: str, question: str) -> str:
    """
    按 DAG 执行任务。
    简化假设：
    - "推理" 节点 → LLM 调用
    - "脚本" 节点 → exec Python run(ctx) 
    - "llm_call" 节点 → 独立 LLM 调用（用节点的 prompt 模板）
    """
    nodes = dag_config["pipeline"]["nodes"]
    prompts = dag_config.get("prompts", {})
    scripts_dir = dag_config.get("_scripts_dir")  # 运行时注入的脚本目录
    
    # 执行推理
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question},
    ]
    response = llm_call(messages, max_tokens=1024, temperature=0.3)
    
    # 按 DAG 拓扑执行后续节点
    # 找 infer 节点的 has_text 出边指向的节点
    infer_node = nodes.get("infer", {})
    post_process_target = None
    for edge in infer_node.get("edges", []):
        if edge["condition"] == "has_text":
            target = edge["to"]
            # 如果指向的不是 wait_input，说明有后处理节点
            if target != "wait_input" and target in nodes:
                post_process_target = target
            break
    
    # 执行后处理节点链
    ctx = {"response": response, "question": question}
    current_node_id = post_process_target
    
    while current_node_id and current_node_id in nodes:
        node = nodes[current_node_id]
        op = node.get("op")
        
        if op == "脚本":
            script_name = node.get("script")
            if scripts_dir:
                script_path = Path(scripts_dir) / f"{script_name}.py"
                if script_path.exists():
                    script_code = script_path.read_text(encoding="utf-8")
                    script_ns = {"__file__": str(script_path)}
                    exec(script_code, script_ns)
                    result = script_ns["run"](ctx)
                    if isinstance(result, dict):
                        ctx.update(result)
                        if "response" in result:
                            response = result["response"]
            # Follow default edge
            current_node_id = _follow_default_edge(node)
        
        elif op == "llm_call":
            prompt_name = node.get("prompt", "")
            prompt_template = prompts.get(prompt_name, "")
            if prompt_template:
                formatted = prompt_template.format(**{k: ctx.get(k, "") for k in node.get("input_vars", [])})
                llm_result = llm_call([{"role": "user", "content": formatted}], max_tokens=512, temperature=0.3)
                output_var = node.get("output_var", "response")
                ctx[output_var] = llm_result
                if output_var == "response":
                    response = llm_result
            current_node_id = _follow_default_edge(node)
        
        else:
            # Unknown op or wait_input → stop
            break
    
    return response


def _follow_default_edge(node: Dict) -> Optional[str]:
    """Follow the default/first edge of a node"""
    for edge in node.get("edges", []):
        if edge.get("condition") in ("default", "has_text"):
            return edge["to"]
    # If only one edge, follow it
    edges = node.get("edges", [])
    if len(edges) == 1:
        return edges[0]["to"]
    return None


# ============================================================
# 核心：扩展版 TextGrad（evolver 可以建议结构变更）
# ============================================================

EVOLVER_SYSTEM_PROMPT = """You are an agent architecture optimizer. You analyze failed task trajectories and decide the BEST intervention to improve performance.

You have TWO types of actions available:

1. **modify_prompt**: Change the system prompt to give better instructions to the agent.
2. **add_node**: Insert a new processing node into the DAG pipeline (e.g., a post-processing script node that runs after the agent's response).

Guidelines for choosing:
- If the agent clearly understands what to do but fails on output FORMAT (e.g., missing tags, wrong structure), consider adding a post-processing node that programmatically fixes the format. This is MORE RELIABLE than asking an LLM to always remember format rules.
- If the agent fails on REASONING or KNOWLEDGE, modify the prompt.
- If you've already tried modifying the prompt for the same issue and it didn't help, escalate to structural changes.

Output your decision as JSON:
```json
{
  "analysis": "Brief analysis of failure pattern",
  "action_type": "modify_prompt" | "add_node",
  "details": { ... }
}
```

For modify_prompt:
```json
{
  "action_type": "modify_prompt",
  "analysis": "...",
  "details": {
    "instruction": "The specific change to make to the prompt"
  }
}
```

For add_node:
```json
{
  "action_type": "add_node",
  "analysis": "...",
  "details": {
    "node_type": "script" | "llm_call",
    "node_id": "unique_name_for_node",
    "insert_after": "infer",
    "description": "What this node does",
    "script_code": "python code with def run(ctx): ... return {'response': ...}" 
  }
}
```
(script_code is required for node_type=script; for llm_call provide "prompt_template" instead)
"""

def compute_structural_gradient(
    failed_trajectories: List[Dict],
    current_prompt: str,
    current_dag: Dict,
    evolution_history: List[Dict],
) -> Dict:
    """
    扩展版 TextGrad：evolver 分析失败后自主决定改 prompt 还是改结构。
    
    返回 evolver 的 JSON 决策。
    """
    # Build trajectory summary
    traj_summary = ""
    format_fails = 0
    reasoning_fails = 0
    total_fails = len(failed_trajectories)
    
    for t in failed_trajectories[:8]:  # 最多展示8条
        traj_summary += f"\nQuestion: {t['question']}\n"
        traj_summary += f"Response (first 300 chars): {t['response'][:300]}\n"
        traj_summary += f"Expected answer: {t['ground_truth']}\n"
        traj_summary += f"Failure reason: {t['reason']}\n"
        traj_summary += "---\n"
        if t["reason"] == "missing_format":
            format_fails += 1
        else:
            reasoning_fails += 1
    
    # Show evolution history so evolver knows what's been tried
    history_summary = ""
    if evolution_history:
        history_summary = "\n\nPrevious evolution attempts:\n"
        for h in evolution_history[-5:]:
            score_str = f"{h['score_after']:.0%}" if h['score_after'] is not None else "pending"
            history_summary += f"- Round {h['round']}: {h['action_type']} → accuracy {score_str}\n"
            if h.get("details_summary"):
                history_summary += f"  Details: {h['details_summary']}\n"
    
    user_msg = f"""Current system prompt:
{current_prompt}

Current DAG structure:
{json.dumps({k: v.get("op") for k, v in current_dag["pipeline"]["nodes"].items()}, indent=2)}

Evaluation criteria: The answer is scored as correct ONLY if the response contains <final_answer>NUMBER</final_answer> (exact XML tags) AND the number matches the ground truth. "format error" means this tag is missing or malformed.

Failed trajectories ({total_fails} failures, {format_fails} format errors, {reasoning_fails} reasoning errors):
{traj_summary}
{history_summary}

Based on this analysis, what is the best action to improve performance? Output JSON."""

    response = llm_call(
        [
            {"role": "system", "content": EVOLVER_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=2048,
        temperature=0.5,
    )
    
    # Parse JSON from response
    try:
        # Try to extract JSON block
        if "```json" in response:
            json_str = response.split("```json")[1].split("```")[0]
        elif "```" in response:
            json_str = response.split("```")[1].split("```")[0]
        else:
            # Try to find JSON directly
            start = response.find("{")
            end = response.rfind("}") + 1
            json_str = response[start:end]
        
        decision = json.loads(json_str)
        decision["_raw_response"] = response
        return decision
    except (json.JSONDecodeError, IndexError, ValueError):
        # Fallback: treat as prompt modification
        return {
            "action_type": "modify_prompt",
            "analysis": "Failed to parse evolver output",
            "details": {"instruction": response[:500]},
            "_raw_response": response,
            "_parse_error": True,
        }


# ============================================================
# 应用 evolver 决策
# ============================================================

def apply_decision(decision: Dict, current_prompt: str, dag_config: Dict) -> Tuple[str, Dict]:
    """
    根据 evolver 的决策，修改 prompt 或 DAG。
    返回 (new_prompt, new_dag_config)
    """
    action_type = decision.get("action_type", "modify_prompt")
    details = decision.get("details", {})
    
    new_prompt = current_prompt
    new_dag = copy.deepcopy(dag_config)
    
    if action_type == "modify_prompt":
        instruction = details.get("instruction", "")
        if instruction:
            # 让 LLM 根据 instruction 修改 prompt
            modify_response = llm_call([
                {"role": "system", "content": "You are a prompt rewriter. Given the current prompt and a modification instruction, output ONLY the new prompt. No explanation."},
                {"role": "user", "content": f"Current prompt:\n{current_prompt}\n\nModification instruction:\n{instruction}\n\nNew prompt:"},
            ], max_tokens=1024, temperature=0.3)
            if modify_response and "[LLM_ERROR]" not in modify_response:
                new_prompt = modify_response
    
    elif action_type == "add_node":
        node_type = details.get("node_type", "script")
        node_id = details.get("node_id", f"patch_{int(time.time())}")
        insert_after = details.get("insert_after", "infer")
        
        if node_type == "script":
            script_code = details.get("script_code", "")
            if script_code:
                # Save script to file
                scripts_dir = Path(dag_config.get("_scripts_dir", OUTPUT_DIR / "scripts"))
                scripts_dir.mkdir(parents=True, exist_ok=True)
                script_path = scripts_dir / f"{node_id}.py"
                script_path.write_text(script_code, encoding="utf-8")
                
                # Add node to DAG
                new_dag["pipeline"]["nodes"][node_id] = {
                    "op": "脚本",
                    "script": node_id,
                    "input_vars": ["response"],
                    "output_vars": ["response"],
                    "edges": [{"condition": "default", "to": "wait_input"}],
                    "_added_by_evolver": True,
                }
                
                # Rewire: infer's has_text edge → new node (instead of wait_input)
                infer_node = new_dag["pipeline"]["nodes"].get(insert_after, {})
                for edge in infer_node.get("edges", []):
                    if edge["condition"] == "has_text":
                        edge["to"] = node_id
                        break
        
        elif node_type == "llm_call":
            prompt_template = details.get("prompt_template", "")
            if prompt_template:
                # Add prompt to prompts dict
                prompt_key = f"{node_id}_prompt"
                new_dag.setdefault("prompts", {})[prompt_key] = prompt_template
                
                # Add node to DAG
                new_dag["pipeline"]["nodes"][node_id] = {
                    "op": "llm_call",
                    "prompt": prompt_key,
                    "input_vars": ["response", "question"],
                    "output_var": "response",
                    "edges": [{"condition": "default", "to": "wait_input"}],
                    "_added_by_evolver": True,
                }
                
                # Rewire
                infer_node = new_dag["pipeline"]["nodes"].get(insert_after, {})
                for edge in infer_node.get("edges", []):
                    if edge["condition"] == "has_text":
                        edge["to"] = node_id
                        break
    
    return new_prompt, new_dag


# ============================================================
# 主实验循环
# ============================================================

def run_experiment(max_rounds: int = 6, tasks_per_round: int = 8):
    """
    运行完整的结构进化实验。
    
    每轮：
    1. 用当前 prompt + DAG 跑所有题目
    2. 收集失败的题目和轨迹
    3. 调用扩展 TextGrad（evolver 自主决定改什么）
    4. 应用决策
    5. 门控：验证改动是否有效
    """
    print("=" * 70)
    print("  Structural Evolution Experiment")
    print("  Evolver decides: modify prompt OR modify DAG structure")
    print("=" * 70)
    
    # Initial setup: intentionally vague prompt (no format instructions!)
    current_prompt = (
        "You are a math problem solver. "
        "Solve the given math problem step by step and provide the final numerical answer."
    )
    
    # Initial DAG: simple react_single
    dag_config = {
        "pipeline": {
            "start": "wait_input",
            "nodes": {
                "wait_input": {
                    "op": "等待输入",
                    "edges": [{"condition": "input", "to": "infer"}],
                },
                "infer": {
                    "op": "推理",
                    "edges": [
                        {"condition": "has_tool_calls", "to": "exec_tools"},
                        {"condition": "has_text", "to": "wait_input"},
                    ],
                },
                "exec_tools": {
                    "op": "执行工具",
                    "edges": [{"condition": "default", "to": "infer"}],
                },
            },
        },
        "prompts": {},
        "_scripts_dir": str(OUTPUT_DIR / "scripts"),
    }
    
    evolution_history = []
    all_round_results = []
    
    for round_idx in range(max_rounds):
        print(f"\n{'─'*60}")
        print(f"  Round {round_idx + 1}/{max_rounds}")
        print(f"{'─'*60}")
        print(f"  System prompt: {current_prompt[:80]}...")
        print(f"  DAG nodes: {list(dag_config['pipeline']['nodes'].keys())}")
        
        # Select tasks for this round
        round_tasks = TASKS[:tasks_per_round]
        
        # Run all tasks
        results = []
        failed_trajectories = []
        
        for task in round_tasks:
            response = run_task_with_dag(dag_config, current_prompt, task["question"])
            eval_result = evaluate_response(response, task["answer"])
            eval_result["question"] = task["question"]
            eval_result["response"] = response
            eval_result["ground_truth"] = task["answer"]
            results.append(eval_result)
            
            if not eval_result["correct"]:
                failed_trajectories.append({
                    "question": task["question"],
                    "response": response,
                    "ground_truth": task["answer"],
                    "reason": eval_result.get("reason", "unknown"),
                })
        
        # Calculate metrics
        n_correct = sum(1 for r in results if r["correct"])
        n_format_ok = sum(1 for r in results if r["format_ok"])
        accuracy = n_correct / len(results)
        format_rate = n_format_ok / len(results)
        
        print(f"\n  Results: accuracy={accuracy:.0%} ({n_correct}/{len(results)}), "
              f"format_rate={format_rate:.0%} ({n_format_ok}/{len(results)})")
        
        round_report = {
            "round": round_idx + 1,
            "prompt": current_prompt,
            "dag_nodes": list(dag_config["pipeline"]["nodes"].keys()),
            "accuracy": accuracy,
            "format_rate": format_rate,
            "n_correct": n_correct,
            "n_total": len(results),
            "results": results,
        }
        all_round_results.append(round_report)
        
        # If accuracy is good enough, stop
        if accuracy >= 0.9:
            print(f"\n  ✓ Target accuracy reached ({accuracy:.0%} >= 90%). Stopping.")
            break
        
        # No failures? (shouldn't happen at < 90% but just in case)
        if not failed_trajectories:
            print("  No failures to analyze. Stopping.")
            break
        
        # === CORE: Let evolver decide ===
        print(f"\n  Calling evolver ({len(failed_trajectories)} failures to analyze)...")
        
        decision = compute_structural_gradient(
            failed_trajectories=failed_trajectories,
            current_prompt=current_prompt,
            current_dag=dag_config,
            evolution_history=evolution_history,
        )
        
        action_type = decision.get("action_type", "unknown")
        analysis = decision.get("analysis", "")
        
        print(f"  Evolver decision: {action_type}")
        print(f"  Analysis: {analysis[:120]}")
        
        if action_type == "add_node":
            details = decision.get("details", {})
            print(f"  → Adding {details.get('node_type')} node: {details.get('node_id')}")
            if details.get("script_code"):
                print(f"  → Script preview: {details['script_code'][:100]}...")
        
        # Apply decision
        old_prompt = current_prompt
        old_dag = copy.deepcopy(dag_config)
        
        current_prompt, dag_config = apply_decision(decision, current_prompt, dag_config)
        
        # Record
        history_entry = {
            "round": round_idx + 1,
            "action_type": action_type,
            "analysis": analysis,
            "score_before": accuracy,
            "score_after": None,  # Will be filled next round
            "details_summary": str(decision.get("details", {}))[:200],
            "decision_raw": decision,
        }
        
        if evolution_history:
            evolution_history[-1]["score_after"] = accuracy
        evolution_history.append(history_entry)
        
        # Log what changed
        if action_type == "modify_prompt":
            if current_prompt != old_prompt:
                print(f"  → Prompt changed: {current_prompt[:100]}...")
            else:
                print(f"  → Prompt unchanged (application failed)")
        elif action_type == "add_node":
            new_nodes = set(dag_config["pipeline"]["nodes"].keys()) - set(old_dag["pipeline"]["nodes"].keys())
            if new_nodes:
                print(f"  → New DAG nodes added: {new_nodes}")
            else:
                print(f"  → DAG unchanged (application failed)")
    
    # Final summary
    if evolution_history:
        evolution_history[-1]["score_after"] = all_round_results[-1]["accuracy"]
    
    print(f"\n{'='*70}")
    print("  EXPERIMENT COMPLETE")
    print(f"{'='*70}")
    print(f"\n  Evolution trajectory:")
    for r in all_round_results:
        nodes_str = ", ".join(r["dag_nodes"])
        print(f"    Round {r['round']}: accuracy={r['accuracy']:.0%}, format={r['format_rate']:.0%}, nodes=[{nodes_str}]")
    
    print(f"\n  Evolver decisions:")
    for h in evolution_history:
        print(f"    Round {h['round']}: {h['action_type']} — {h['analysis'][:80]}")
    
    # DAG structure changes
    initial_nodes = {"wait_input", "infer", "exec_tools"}
    final_nodes = set(dag_config["pipeline"]["nodes"].keys())
    added_nodes = final_nodes - initial_nodes
    if added_nodes:
        print(f"\n  ★ DAG structural changes (evolver-driven):")
        for node_id in added_nodes:
            node = dag_config["pipeline"]["nodes"][node_id]
            print(f"    + {node_id}: op={node.get('op')}, added_by_evolver={node.get('_added_by_evolver', False)}")
    else:
        print(f"\n  (No structural changes — evolver chose prompt modifications only)")
    
    # Save full report
    report = {
        "timestamp": time.strftime("%Y%m%d_%H%M%S"),
        "config": {
            "max_rounds": max_rounds,
            "tasks_per_round": tasks_per_round,
            "initial_prompt": "You are a math problem solver. Solve the given math problem step by step and provide the final numerical answer.",
            "model": LLM_MODEL,
        },
        "rounds": all_round_results,
        "evolution_history": evolution_history,
        "final_prompt": current_prompt,
        "final_dag": dag_config,
        "structural_changes": list(added_nodes) if added_nodes else [],
    }
    
    report_path = OUTPUT_DIR / f"experiment_{time.strftime('%Y%m%d_%H%M%S')}.json"
    
    # Clean non-serializable items from results
    def _clean_for_json(obj):
        if isinstance(obj, dict):
            return {k: _clean_for_json(v) for k, v in obj.items() if not k.startswith("_raw")}
        elif isinstance(obj, list):
            return [_clean_for_json(i) for i in obj]
        return obj
    
    report_path.write_text(
        json.dumps(_clean_for_json(report), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\n  Report saved to: {report_path}")
    
    return report


if __name__ == "__main__":
    run_experiment(max_rounds=5, tasks_per_round=4)
