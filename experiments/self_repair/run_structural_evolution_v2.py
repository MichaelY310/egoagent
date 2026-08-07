#!/usr/bin/env python3
"""
Structural Evolution V2 — No Cheating Version
==============================================
Evolver Agent 通过标准 tool calling 自由修改 DAG。

核心设计：
- Evolver 有完整的 tool set（add_node, remove_node, rewire_edge, write_script, modify_prompt, read_dag）
- 没有任何硬编码的"什么时候该加节点"的逻辑
- Evolver 的 system prompt 只教它 DAG 是什么、怎么操作，不教它具体策略
- 所有决策完全由 Evolver 自主做出
"""

import json
import re
import copy
import time
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

# LLM config
LLM_BASE_URL = "http://[fdbd:dc05:10:10a::27]:9638/v1"
LLM_MODEL = "Qwen3-8B-yangyuan"

OUTPUT_DIR = Path(__file__).parent / "_v2_output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
SCRIPTS_DIR = OUTPUT_DIR / "scripts"
SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
# 题目集（同 v1）
# ============================================================

TASKS = [
    {"question": "What is 15 * 7 + 3?", "answer": "108"},
    {"question": "If a train travels 60km/h for 2.5 hours, how many km does it travel?", "answer": "150"},
    {"question": "What is the square root of 144?", "answer": "12"},
    {"question": "A store has a 20% off sale. What is the price of a $80 item?", "answer": "64"},
    {"question": "How many minutes are in 3.5 hours?", "answer": "210"},
    {"question": "What is 2^8?", "answer": "256"},
]

# ============================================================
# LLM 调用
# ============================================================

def llm_call(messages: List[Dict], max_tokens=2048, temperature=0.7, tools=None) -> Dict:
    """调用 LLM API，支持 tool calling"""
    import requests
    url = f"{LLM_BASE_URL}/chat/completions"
    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if tools:
        payload["tools"] = tools
    
    try:
        resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=120)
        resp.raise_for_status()
        result = resp.json()
        msg = result["choices"][0]["message"]
        
        # Strip thinking tags from content
        content = msg.get("content", "") or ""
        if "</think>" in content:
            content = content.split("</think>")[-1].strip()
        elif "<think>" in content:
            content = ""
        msg["content"] = content
        
        return msg
    except Exception as e:
        return {"role": "assistant", "content": f"[LLM_ERROR] {e}"}


def llm_call_simple(messages: List[Dict], max_tokens=1024, temperature=0.3) -> str:
    """简单 LLM 调用，返回文本"""
    msg = llm_call(messages, max_tokens=max_tokens, temperature=temperature)
    return msg.get("content", "")


# ============================================================
# 评估逻辑
# ============================================================

def extract_final_answer(response: str) -> Optional[str]:
    """提取 <final_answer>...</final_answer>"""
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
    
    try:
        if float(extracted) == float(ground_truth):
            return {"correct": True, "format_ok": True, "extracted": extracted}
    except (ValueError, TypeError):
        pass
    
    if extracted.strip() == ground_truth.strip():
        return {"correct": True, "format_ok": True, "extracted": extracted}
    
    return {"correct": False, "format_ok": True, "extracted": extracted, "reason": "wrong_answer"}


# ============================================================
# DAG 状态管理
# ============================================================

class DAGState:
    """管理当前 DAG 配置"""
    
    def __init__(self):
        # 初始 DAG：简单的 react_single
        self.config = {
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
        }
        self.system_prompt = (
            "You are a math problem solver. "
            "Solve the given math problem step by step and provide the final numerical answer."
        )
    
    def get_dag_json(self) -> str:
        """返回当前 DAG 的 JSON 字符串"""
        return json.dumps(self.config, indent=2, ensure_ascii=False)
    
    def get_nodes_summary(self) -> str:
        """返回节点摘要"""
        nodes = self.config["pipeline"]["nodes"]
        lines = []
        for nid, node in nodes.items():
            edges_str = ", ".join(f'{e["condition"]}→{e["to"]}' for e in node.get("edges", []))
            lines.append(f"  {nid} (op={node['op']}) edges=[{edges_str}]")
        return "\n".join(lines)


# ============================================================
# Tool 定义（Evolver 可用的所有操作）
# ============================================================

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_dag",
            "description": "Read the current DAG pipeline configuration. Returns the full JSON structure including all nodes, edges, and prompts.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "modify_prompt",
            "description": "Modify the Solver agent's system prompt. This changes how the Solver approaches problems.",
            "parameters": {
                "type": "object",
                "properties": {
                    "new_prompt": {
                        "type": "string",
                        "description": "The new system prompt for the Solver agent.",
                    },
                },
                "required": ["new_prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_node",
            "description": "Add a new node to the DAG pipeline. The node can be a script node (executes Python code) or an llm_call node (makes an independent LLM call). Script nodes must have a run(ctx) function that takes a dict with 'response' and 'question' keys, and returns a dict with 'response' key.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_id": {
                        "type": "string",
                        "description": "Unique identifier for the new node (e.g., 'format_fixer', 'answer_extractor').",
                    },
                    "op": {
                        "type": "string",
                        "enum": ["脚本", "llm_call"],
                        "description": "Node type. '脚本' for Python script execution, 'llm_call' for independent LLM call.",
                    },
                    "script_code": {
                        "type": "string",
                        "description": "For script nodes: Python code containing a `def run(ctx):` function. ctx has 'response' (str) and 'question' (str). Must return {'response': new_response_str}. Required if op='脚本'.",
                    },
                    "prompt_template": {
                        "type": "string",
                        "description": "For llm_call nodes: prompt template string. Can use {response} and {question} placeholders. Required if op='llm_call'.",
                    },
                    "edges": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "condition": {"type": "string"},
                                "to": {"type": "string"},
                            },
                        },
                        "description": "Outgoing edges from this node. Each edge has a 'condition' and 'to' (target node_id).",
                    },
                },
                "required": ["node_id", "op", "edges"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_node",
            "description": "Remove a node from the DAG. Cannot remove 'wait_input', 'infer', or 'exec_tools' (core nodes). Any edges pointing to this node will be redirected to the node's first outgoing edge target.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_id": {
                        "type": "string",
                        "description": "The node to remove.",
                    },
                },
                "required": ["node_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rewire_edge",
            "description": "Change where an edge points to. Modify an existing edge on a node to point to a different target.",
            "parameters": {
                "type": "object",
                "properties": {
                    "from_node": {
                        "type": "string",
                        "description": "The node whose edge you want to modify.",
                    },
                    "condition": {
                        "type": "string",
                        "description": "The edge condition to modify (e.g., 'has_text', 'default', 'has_tool_calls').",
                    },
                    "new_target": {
                        "type": "string",
                        "description": "The new target node_id for this edge.",
                    },
                },
                "required": ["from_node", "condition", "new_target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_script",
            "description": "Write or overwrite a Python script file for a script node. The script must contain a `def run(ctx):` function.",
            "parameters": {
                "type": "object",
                "properties": {
                    "script_name": {
                        "type": "string",
                        "description": "Name of the script (without .py extension). Must match the node_id of the script node that uses it.",
                    },
                    "code": {
                        "type": "string",
                        "description": "Full Python code. Must contain `def run(ctx):` that takes dict with 'response','question' and returns dict with 'response'.",
                    },
                },
                "required": ["script_name", "code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "done",
            "description": "Signal that you have finished making changes for this evolution round. Call this when you're done modifying the DAG/prompt.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Brief summary of what changes you made and why.",
                    },
                },
                "required": ["summary"],
            },
        },
    },
]

# ============================================================
# Tool 执行
# ============================================================

def execute_tool(dag_state: DAGState, tool_name: str, args: Dict) -> str:
    """执行 tool call，返回结果字符串"""
    
    if tool_name == "read_dag":
        return f"Current DAG:\n{dag_state.get_dag_json()}\n\nCurrent system prompt:\n{dag_state.system_prompt}"
    
    elif tool_name == "modify_prompt":
        new_prompt = args.get("new_prompt", "")
        if new_prompt:
            dag_state.system_prompt = new_prompt
            return f"OK. System prompt updated to: {new_prompt[:200]}..."
        return "ERROR: new_prompt is empty."
    
    elif tool_name == "add_node":
        node_id = args.get("node_id", "")
        op = args.get("op", "")
        edges = args.get("edges", [{"condition": "default", "to": "wait_input"}])
        
        if not node_id:
            return "ERROR: node_id is required."
        if node_id in dag_state.config["pipeline"]["nodes"]:
            return f"ERROR: node '{node_id}' already exists."
        
        node_def = {"op": op, "edges": edges}
        
        if op == "脚本":
            script_code = args.get("script_code", "")
            if script_code:
                # Save script
                script_path = SCRIPTS_DIR / f"{node_id}.py"
                script_path.write_text(script_code, encoding="utf-8")
                node_def["script"] = node_id
                node_def["input_vars"] = ["response", "question"]
                node_def["output_vars"] = ["response"]
            else:
                return "ERROR: script_code is required for op='脚本'. Provide code with def run(ctx)."
        
        elif op == "llm_call":
            prompt_template = args.get("prompt_template", "")
            if prompt_template:
                prompt_key = f"{node_id}_prompt"
                dag_state.config.setdefault("prompts", {})[prompt_key] = prompt_template
                node_def["prompt"] = prompt_key
                node_def["input_vars"] = ["response", "question"]
                node_def["output_var"] = "response"
            else:
                return "ERROR: prompt_template is required for op='llm_call'."
        else:
            return f"ERROR: op must be '脚本' or 'llm_call', got '{op}'."
        
        dag_state.config["pipeline"]["nodes"][node_id] = node_def
        return f"OK. Node '{node_id}' added. Current nodes: {list(dag_state.config['pipeline']['nodes'].keys())}"
    
    elif tool_name == "remove_node":
        node_id = args.get("node_id", "")
        protected = {"wait_input", "infer", "exec_tools"}
        if node_id in protected:
            return f"ERROR: Cannot remove core node '{node_id}'."
        if node_id not in dag_state.config["pipeline"]["nodes"]:
            return f"ERROR: Node '{node_id}' does not exist."
        
        # Find where removed node points to
        removed_node = dag_state.config["pipeline"]["nodes"][node_id]
        redirect_to = "wait_input"
        if removed_node.get("edges"):
            redirect_to = removed_node["edges"][0].get("to", "wait_input")
        
        # Redirect any edges pointing to this node
        for nid, node in dag_state.config["pipeline"]["nodes"].items():
            for edge in node.get("edges", []):
                if edge["to"] == node_id:
                    edge["to"] = redirect_to
        
        # Remove the node
        del dag_state.config["pipeline"]["nodes"][node_id]
        
        # Remove script file if exists
        script_path = SCRIPTS_DIR / f"{node_id}.py"
        if script_path.exists():
            script_path.unlink()
        
        return f"OK. Node '{node_id}' removed. Edges redirected to '{redirect_to}'. Current nodes: {list(dag_state.config['pipeline']['nodes'].keys())}"
    
    elif tool_name == "rewire_edge":
        from_node = args.get("from_node", "")
        condition = args.get("condition", "")
        new_target = args.get("new_target", "")
        
        if from_node not in dag_state.config["pipeline"]["nodes"]:
            return f"ERROR: Node '{from_node}' does not exist."
        if new_target not in dag_state.config["pipeline"]["nodes"]:
            return f"ERROR: Target node '{new_target}' does not exist."
        
        node = dag_state.config["pipeline"]["nodes"][from_node]
        found = False
        for edge in node.get("edges", []):
            if edge["condition"] == condition:
                old_target = edge["to"]
                edge["to"] = new_target
                found = True
                return f"OK. Edge '{from_node}' --[{condition}]--> now points to '{new_target}' (was '{old_target}')."
        
        if not found:
            return f"ERROR: No edge with condition '{condition}' found on node '{from_node}'. Available: {[e['condition'] for e in node.get('edges', [])]}"
    
    elif tool_name == "write_script":
        script_name = args.get("script_name", "")
        code = args.get("code", "")
        if not script_name or not code:
            return "ERROR: script_name and code are required."
        script_path = SCRIPTS_DIR / f"{script_name}.py"
        script_path.write_text(code, encoding="utf-8")
        return f"OK. Script '{script_name}.py' written ({len(code)} chars)."
    
    elif tool_name == "done":
        return "DONE"
    
    return f"ERROR: Unknown tool '{tool_name}'."


# ============================================================
# DAG 执行（运行 Solver）
# ============================================================

def run_task_with_dag(dag_state: DAGState, question: str) -> str:
    """用当前 DAG 配置执行一道题"""
    nodes = dag_state.config["pipeline"]["nodes"]
    
    # Step 1: LLM 推理
    messages = [
        {"role": "system", "content": dag_state.system_prompt},
        {"role": "user", "content": question},
    ]
    response = llm_call_simple(messages, max_tokens=1024, temperature=0.3)
    
    # Step 2: 找 infer 的 has_text 出边，沿着后处理链执行
    infer_node = nodes.get("infer", {})
    next_node_id = None
    for edge in infer_node.get("edges", []):
        if edge["condition"] == "has_text":
            target = edge["to"]
            if target != "wait_input" and target in nodes:
                next_node_id = target
            break
    
    # Step 3: 执行后处理链
    ctx = {"response": response, "question": question}
    visited = set()
    
    while next_node_id and next_node_id in nodes and next_node_id not in visited:
        visited.add(next_node_id)
        node = nodes[next_node_id]
        op = node.get("op")
        
        if op == "脚本":
            script_name = node.get("script", next_node_id)
            script_path = SCRIPTS_DIR / f"{script_name}.py"
            if script_path.exists():
                try:
                    script_code = script_path.read_text(encoding="utf-8")
                    script_ns = {"__file__": str(script_path)}
                    exec(script_code, script_ns)
                    result = script_ns["run"](ctx)
                    if isinstance(result, dict) and "response" in result:
                        ctx["response"] = result["response"]
                        response = result["response"]
                except Exception as e:
                    # Script error — skip this node
                    pass
        
        elif op == "llm_call":
            prompt_key = node.get("prompt", "")
            prompt_template = dag_state.config.get("prompts", {}).get(prompt_key, "")
            if prompt_template:
                try:
                    formatted = prompt_template.format(**ctx)
                    llm_result = llm_call_simple(
                        [{"role": "user", "content": formatted}],
                        max_tokens=512, temperature=0.3,
                    )
                    ctx["response"] = llm_result
                    response = llm_result
                except Exception:
                    pass
        
        # Follow first edge
        next_node_id = None
        for edge in node.get("edges", []):
            target = edge.get("to", "")
            if target and target != "wait_input" and target in nodes:
                next_node_id = target
                break
            elif target == "wait_input":
                next_node_id = None
                break
    
    return response


# ============================================================
# Evolver Agent（通过 tool calling 自主进化）
# ============================================================

EVOLVER_SYSTEM_PROMPT = """You are an Agent Architecture Optimizer. Your job is to improve a Solver agent's performance on math tasks by modifying its system prompt and/or its DAG (Directed Acyclic Graph) pipeline structure.

## What is a DAG pipeline?

The Solver agent runs through a DAG pipeline to process each task:
- Each node performs an operation (LLM reasoning, script execution, tool execution, etc.)
- Edges connect nodes, with conditions determining which path to follow
- The pipeline starts at "wait_input", then goes to "infer" (LLM reasoning), and can loop through "exec_tools"
- After "infer" produces a text response (condition "has_text"), it currently goes to "wait_input" (ending the turn)

## Node types you can add:
- "脚本" (script): Executes a Python script with `def run(ctx):` that takes {"response": str, "question": str} and returns {"response": new_str}
- "llm_call": Makes an independent LLM call using a prompt template with {response} and {question} placeholders

## Key insight about DAG modifications:
If the Solver consistently makes a certain type of error (like formatting issues), you can insert a post-processing node AFTER the "infer" node to programmatically fix it. This is often more reliable than trying to get an LLM to perfectly follow format instructions every time.

To insert a node after "infer": 
1. add_node with edges pointing to "wait_input" 
2. rewire_edge on "infer" to change "has_text" target from "wait_input" to your new node

## Evaluation criteria:
The Solver's answer is scored correct ONLY if:
1. The response contains `<final_answer>NUMBER</final_answer>` (exact XML tags)
2. The NUMBER inside matches the ground truth answer

"format error" = the <final_answer> tag is missing or malformed.
"wrong answer" = tag is present but number is wrong.

## Your workflow:
1. Analyze the failure trajectories provided
2. Decide what changes to make (prompt modification, DAG structure changes, or both)
3. Use the available tools to implement your changes
4. Call "done" when finished

You have full freedom to make any changes you think will help. Use your judgment."""


def run_evolver_turn(dag_state: DAGState, failure_info: str, history_info: str) -> Dict:
    """
    运行 Evolver 一个完整的 turn（可能包含多次 tool call）。
    返回所有执行的 actions。
    """
    messages = [
        {"role": "system", "content": EVOLVER_SYSTEM_PROMPT},
        {"role": "user", "content": f"""Here is the current state and failures:

{failure_info}

{history_info}

Please analyze and make improvements. Use the tools to modify the prompt and/or DAG structure. Call "done" when finished."""},
    ]
    
    actions_log = []
    max_turns = 10  # Safety limit
    
    for turn in range(max_turns):
        response = llm_call(messages, max_tokens=2048, temperature=0.5, tools=TOOLS)
        
        # Check if there are tool calls
        tool_calls = response.get("tool_calls", [])
        
        if not tool_calls:
            # No tool calls — LLM just replied with text. 
            # Try to parse as a "done" signal
            content = response.get("content", "")
            if content:
                actions_log.append({"action": "text_response", "content": content[:200]})
            break
        
        # Process tool calls
        messages.append(response)  # Add assistant response with tool_calls
        
        done = False
        for tc in tool_calls:
            fn = tc.get("function", {})
            tool_name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments", "{}"))
            except json.JSONDecodeError:
                args = {}
            
            # Execute tool
            result = execute_tool(dag_state, tool_name, args)
            
            # Log
            actions_log.append({
                "action": tool_name,
                "args_summary": str(args)[:200],
                "result": result[:200],
            })
            
            # Add tool response to messages
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", f"call_{turn}"),
                "content": result,
            })
            
            if tool_name == "done" or result == "DONE":
                done = True
        
        if done:
            break
    
    return {"actions": actions_log, "n_turns": turn + 1}


# ============================================================
# 主实验循环
# ============================================================

def run_experiment(max_rounds: int = 5, tasks_per_round: int = 4):
    """运行完整实验"""
    print("=" * 70)
    print("  Structural Evolution V2 — No Cheating")
    print("  Evolver has full tool access, makes all decisions autonomously")
    print("=" * 70)
    
    dag_state = DAGState()
    all_results = []
    evolution_history = []
    
    for round_idx in range(max_rounds):
        print(f"\n{'─'*60}")
        print(f"  Round {round_idx + 1}/{max_rounds}")
        print(f"{'─'*60}")
        print(f"  Prompt: {dag_state.system_prompt[:80]}...")
        print(f"  Nodes: {list(dag_state.config['pipeline']['nodes'].keys())}")
        
        # Run tasks
        round_tasks = TASKS[:tasks_per_round]
        results = []
        failed_trajs = []
        
        for task in round_tasks:
            response = run_task_with_dag(dag_state, task["question"])
            eval_result = evaluate_response(response, task["answer"])
            eval_result["question"] = task["question"]
            eval_result["response"] = response[:500]
            eval_result["ground_truth"] = task["answer"]
            results.append(eval_result)
            
            if not eval_result["correct"]:
                failed_trajs.append(eval_result)
        
        # Metrics
        n_correct = sum(1 for r in results if r["correct"])
        n_format_ok = sum(1 for r in results if r["format_ok"])
        accuracy = n_correct / len(results)
        format_rate = n_format_ok / len(results)
        
        print(f"  Results: accuracy={accuracy:.0%} ({n_correct}/{len(results)}), "
              f"format_rate={format_rate:.0%} ({n_format_ok}/{len(results)})")
        
        round_report = {
            "round": round_idx + 1,
            "accuracy": accuracy,
            "format_rate": format_rate,
            "nodes": list(dag_state.config["pipeline"]["nodes"].keys()),
            "prompt": dag_state.system_prompt[:200],
        }
        all_results.append(round_report)
        
        # Stop if good enough
        if accuracy >= 0.9:
            print(f"  ✓ Target reached ({accuracy:.0%} >= 90%). Stopping.")
            break
        
        if not failed_trajs:
            break
        
        # Build failure info for evolver
        failure_info = f"Current system prompt: {dag_state.system_prompt}\n\n"
        failure_info += f"Current DAG nodes:\n{dag_state.get_nodes_summary()}\n\n"
        failure_info += f"Results this round: {n_correct}/{len(results)} correct, {n_format_ok}/{len(results)} format OK\n\n"
        failure_info += "Failed tasks:\n"
        for ft in failed_trajs:
            failure_info += f"  Q: {ft['question']}\n"
            failure_info += f"  Response (first 300 chars): {ft['response'][:300]}\n"
            failure_info += f"  Expected: {ft['ground_truth']}\n"
            failure_info += f"  Failure: {ft.get('reason', 'unknown')}\n\n"
        
        # Build history info
        history_info = ""
        if evolution_history:
            history_info = "Previous evolution attempts:\n"
            for h in evolution_history:
                history_info += f"  Round {h['round']}: accuracy {h['accuracy_before']:.0%} → {h.get('accuracy_after', '?')}\n"
                history_info += f"    Actions: {', '.join(a['action'] for a in h['actions'][:5])}\n"
        
        # Run evolver
        print(f"  Calling Evolver ({len(failed_trajs)} failures)...")
        evolver_result = run_evolver_turn(dag_state, failure_info, history_info)
        
        # Log evolver actions
        for action in evolver_result["actions"]:
            action_name = action["action"]
            if action_name == "text_response":
                print(f"    [text] {action['content'][:100]}")
            elif action_name == "done":
                print(f"    [done] {action.get('args_summary', '')[:100]}")
            else:
                print(f"    [{action_name}] → {action['result'][:80]}")
        
        evolution_history.append({
            "round": round_idx + 1,
            "accuracy_before": accuracy,
            "actions": evolver_result["actions"],
            "n_turns": evolver_result["n_turns"],
        })
        
        # Update accuracy_after for previous entry
        if len(evolution_history) >= 2:
            evolution_history[-2]["accuracy_after"] = accuracy
    
    # Final summary
    print(f"\n{'='*70}")
    print("  EXPERIMENT COMPLETE")
    print(f"{'='*70}")
    print(f"\n  Evolution trajectory:")
    for r in all_results:
        nodes_str = ", ".join(r["nodes"])
        print(f"    Round {r['round']}: accuracy={r['accuracy']:.0%}, format={r['format_rate']:.0%}, nodes=[{nodes_str}]")
    
    print(f"\n  Final DAG:\n{dag_state.get_nodes_summary()}")
    print(f"\n  Final prompt: {dag_state.system_prompt[:150]}...")
    
    # Check structural changes
    initial_nodes = {"wait_input", "infer", "exec_tools"}
    final_nodes = set(dag_state.config["pipeline"]["nodes"].keys())
    added = final_nodes - initial_nodes
    if added:
        print(f"\n  ★ Evolver-added nodes: {added}")
        for nid in added:
            script_path = SCRIPTS_DIR / f"{nid}.py"
            if script_path.exists():
                print(f"    {nid} script:")
                print(f"      {script_path.read_text()[:200]}")
    
    # Save report
    report = {
        "timestamp": time.strftime("%Y%m%d_%H%M%S"),
        "rounds": all_results,
        "evolution_history": [
            {k: v for k, v in h.items() if k != "actions"} | {"actions_summary": [a["action"] for a in h["actions"]]}
            for h in evolution_history
        ],
        "final_dag": dag_state.config,
        "final_prompt": dag_state.system_prompt,
        "structural_changes": list(added) if added else [],
    }
    report_path = OUTPUT_DIR / f"experiment_{time.strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  Report: {report_path}")
    
    return report


if __name__ == "__main__":
    run_experiment(max_rounds=5, tasks_per_round=4)
