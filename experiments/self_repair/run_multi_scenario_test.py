#!/usr/bin/env python3
"""
Structural Evolution V2 — Multi-scenario Test + GSM8K Batch
============================================================
1. 测试多种 failure scenario，确认 Evolver 能自主处理
2. 用 GSM8K 真实数据批量验证

Scenarios:
- A: 格式缺失（原始，已验证 work）
- B: 答案格式正确但提取最终数字错误（多步计算中间结果干扰）
- C: 需要不同格式（#### 而非 <final_answer>）
- D: GSM8K 批量（20题子集）
"""

import json
import re
import time
import sys
from pathlib import Path
from typing import List, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from llm.env_config import load_local_env

load_local_env(PROJECT_ROOT)

# LLM config
LLM_BASE_URL = os.environ.get("EGOAGENT_LLM_BASE_URL", "http://[fdbd:dc05:10:10a::27]:9638/v1").rstrip("/")
LLM_MODEL = os.environ.get("EGOAGENT_LLM_MODEL", "Qwen3-8B-yangyuan")
LLM_API_KEY = os.environ.get("EGOAGENT_LLM_API_KEY", "") or os.environ.get("DEEPSEEK_API_KEY", "") or os.environ.get("SILICONFLOW_API_KEY", "")

OUTPUT_DIR = Path(__file__).parent / "_v2_multi_test"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
SCRIPTS_DIR = OUTPUT_DIR / "scripts"
SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
# 多种 Scenario 的题目
# ============================================================

# Scenario A: 简单数学 + 格式缺失（baseline，已验证）
SCENARIO_A = {
    "name": "format_missing",
    "description": "Solver 不知道需要 <final_answer> 格式",
    "initial_prompt": "You are a math problem solver. Solve the given problem and provide the answer.",
    "tasks": [
        {"question": "What is 25 * 4?", "answer": "100"},
        {"question": "What is 99 + 1?", "answer": "100"},
        {"question": "What is 360 / 6?", "answer": "60"},
        {"question": "What is 7 * 8 - 6?", "answer": "50"},
    ],
}

# Scenario B: 多步计算——LLM 输出很多中间数字，简单 regex 可能提取错误数字
SCENARIO_B = {
    "name": "multi_step_extraction",
    "description": "多步计算题，response 中有很多中间数字，需要准确提取最终答案",
    "initial_prompt": (
        "You are a math problem solver. Show your work step by step. "
        "Put your final answer inside <final_answer></final_answer> tags."
    ),
    "tasks": [
        # 这些题的中间步骤会产生干扰数字
        {"question": "A farmer has 3 fields. The first has 12 cows, the second has 8 cows, the third has 15 cows. He sells 5 cows from each field. How many cows remain in total?", "answer": "20"},
        {"question": "A store sells 3 types of candy. Type A costs $2 and they sell 10. Type B costs $5 and they sell 4. Type C costs $1 and they sell 20. What is the total revenue?", "answer": "60"},
        {"question": "A train travels 100km in the first hour, 80km in the second hour, and 120km in the third hour. What is the average speed in km/h?", "answer": "100"},
        {"question": "There are 50 students. 30% study math, 40% study science, and the rest study art. How many study art?", "answer": "15"},
    ],
}

# Scenario C: 模型用 \boxed{} 而非 <final_answer> — 需要脚本提取
SCENARIO_C = {
    "name": "boxed_format_mismatch",
    "description": "LLM 倾向于输出 \\boxed{} 格式，但评估需要 <final_answer> 标签。需要后处理转换。",
    "initial_prompt": (
        "You are a math problem solver. Solve step by step. "
        "Present your final numerical answer clearly."
    ),
    "tasks": [
        {"question": "If 5 pencils cost $2.50, how much do 12 pencils cost in dollars?", "answer": "6"},
        {"question": "A rectangle has width 4cm and length 9cm. What is its area in cm²?", "answer": "36"},
        {"question": "John reads 30 pages per hour. How many pages in 2.5 hours?", "answer": "75"},
        {"question": "A pizza is cut into 8 slices. 3 people each eat 2 slices. How many remain?", "answer": "2"},
    ],
}

# Scenario D: GSM8K 真实数据（运行时从 parquet 加载）

# ============================================================
# LLM 调用（同 v2）
# ============================================================

def llm_call(messages: List[Dict], max_tokens=2048, temperature=0.7, tools=None) -> Dict:
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
        headers = {"Content-Type": "application/json"}
        if LLM_API_KEY:
            headers["Authorization"] = f"Bearer {LLM_API_KEY}"
        resp = requests.post(url, json=payload, headers=headers, timeout=90)
        resp.raise_for_status()
        result = resp.json()
        msg = result["choices"][0]["message"]
        content = msg.get("content", "") or ""
        if "</think>" in content:
            content = content.split("</think>")[-1].strip()
        elif "<think>" in content and "</think>" not in content:
            content = ""
        msg["content"] = content
        return msg
    except Exception as e:
        return {"role": "assistant", "content": f"[LLM_ERROR] {e}"}


def llm_call_simple(messages: List[Dict], max_tokens=1024, temperature=0.3) -> str:
    """Solver 用的简单调用"""
    msg = llm_call(messages, max_tokens=max_tokens, temperature=temperature)
    return msg.get("content", "")


# ============================================================
# 评估逻辑（支持两种格式）
# ============================================================

def extract_final_answer(response: str, fmt: str = "<final_answer>") -> Optional[str]:
    """提取答案，支持 <final_answer> 和 #### 两种格式"""
    if fmt == "<final_answer>":
        pattern = r'<final_answer>\s*(.*?)\s*</final_answer>'
        match = re.search(pattern, response, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
    elif fmt == "####":
        pattern = r'####\s*(.*?)(?:\n|$)'
        match = re.search(pattern, response)
        if match:
            return match.group(1).strip()
    return None


def normalize_number(s: str) -> Optional[float]:
    """标准化数字（去掉逗号、$等）"""
    if not s:
        return None
    s = s.replace(",", "").replace("$", "").replace("%", "").strip()
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def evaluate_response(response: str, ground_truth: str, fmt: str = "<final_answer>") -> Dict:
    extracted = extract_final_answer(response, fmt)
    format_ok = extracted is not None
    
    if not format_ok:
        return {"correct": False, "format_ok": False, "extracted": None, "reason": "missing_format"}
    
    gt_num = normalize_number(ground_truth)
    ext_num = normalize_number(extracted)
    
    if gt_num is not None and ext_num is not None and gt_num == ext_num:
        return {"correct": True, "format_ok": True, "extracted": extracted}
    
    if extracted.strip() == ground_truth.strip():
        return {"correct": True, "format_ok": True, "extracted": extracted}
    
    return {"correct": False, "format_ok": True, "extracted": extracted, "reason": "wrong_answer"}


# ============================================================
# DAG State（同 v2，但支持 reset）
# ============================================================

class DAGState:
    def __init__(self, system_prompt: str = ""):
        self.config = {
            "pipeline": {
                "start": "wait_input",
                "nodes": {
                    "wait_input": {"op": "等待输入", "edges": [{"condition": "input", "to": "infer"}]},
                    "infer": {"op": "推理", "edges": [
                        {"condition": "has_tool_calls", "to": "exec_tools"},
                        {"condition": "has_text", "to": "wait_input"},
                    ]},
                    "exec_tools": {"op": "执行工具", "edges": [{"condition": "default", "to": "infer"}]},
                },
            },
            "prompts": {},
        }
        self.system_prompt = system_prompt or (
            "You are a math problem solver. Solve the given math problem step by step."
        )
    
    def get_dag_json(self) -> str:
        return json.dumps(self.config, indent=2, ensure_ascii=False)
    
    def get_nodes_summary(self) -> str:
        nodes = self.config["pipeline"]["nodes"]
        lines = []
        for nid, node in nodes.items():
            edges_str = ", ".join(f'{e["condition"]}→{e["to"]}' for e in node.get("edges", []))
            lines.append(f"  {nid} (op={node['op']}) edges=[{edges_str}]")
        return "\n".join(lines)


# ============================================================
# Tools（同 v2）
# ============================================================

TOOLS = [
    {"type": "function", "function": {"name": "read_dag", "description": "Read the current DAG pipeline configuration.", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "modify_prompt", "description": "Modify the Solver agent's system prompt.", "parameters": {"type": "object", "properties": {"new_prompt": {"type": "string", "description": "The new system prompt."}}, "required": ["new_prompt"]}}},
    {"type": "function", "function": {"name": "add_node", "description": "Add a new post-processing node to the DAG and automatically wire it in. The node is inserted after the 'infer' node on its 'has_text' edge. Script nodes need a `def run(ctx):` function taking {'response':str,'question':str} and returning {'response':str}.", "parameters": {"type": "object", "properties": {"node_id": {"type": "string", "description": "Unique name for the node"}, "op": {"type": "string", "enum": ["脚本", "llm_call"], "description": "'脚本' for Python script, 'llm_call' for LLM call"}, "script_code": {"type": "string", "description": "Python code with def run(ctx). Required for op='脚本'."}, "prompt_template": {"type": "string", "description": "Prompt template with {response},{question}. Required for op='llm_call'."}}, "required": ["node_id", "op"]}}},
    {"type": "function", "function": {"name": "remove_node", "description": "Remove a node (cannot remove wait_input/infer/exec_tools). Edges pointing to it redirect to its first outgoing target.", "parameters": {"type": "object", "properties": {"node_id": {"type": "string"}}, "required": ["node_id"]}}},
    {"type": "function", "function": {"name": "rewire_edge", "description": "Change where an edge points to.", "parameters": {"type": "object", "properties": {"from_node": {"type": "string"}, "condition": {"type": "string"}, "new_target": {"type": "string"}}, "required": ["from_node", "condition", "new_target"]}}},
    {"type": "function", "function": {"name": "write_script", "description": "Write/overwrite a script file for a script node.", "parameters": {"type": "object", "properties": {"script_name": {"type": "string"}, "code": {"type": "string"}}, "required": ["script_name", "code"]}}},
    {"type": "function", "function": {"name": "done", "description": "Signal completion of this evolution round.", "parameters": {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}}},
]


def execute_tool(dag_state: DAGState, tool_name: str, args: Dict) -> str:
    if tool_name == "read_dag":
        return f"DAG:\n{dag_state.get_dag_json()}\n\nPrompt:\n{dag_state.system_prompt}"
    elif tool_name == "modify_prompt":
        new_prompt = args.get("new_prompt", "")
        if new_prompt:
            dag_state.system_prompt = new_prompt
            return f"OK. Prompt updated."
        return "ERROR: empty prompt."
    elif tool_name == "add_node":
        node_id = args.get("node_id", "")
        # Strip accidental .py suffix from node_id
        if node_id.endswith(".py"):
            node_id = node_id[:-3]
        op = args.get("op", "")
        if not node_id:
            return "ERROR: node_id required."
        if node_id in dag_state.config["pipeline"]["nodes"]:
            return f"ERROR: '{node_id}' already exists."
        
        # Find current target of infer's has_text edge (for auto-rewire)
        infer_edges = dag_state.config["pipeline"]["nodes"].get("infer", {}).get("edges", [])
        old_target = "wait_input"
        for e in infer_edges:
            if e["condition"] == "has_text":
                old_target = e["to"]
                break
        
        # Create node with edge pointing to original target
        node_def = {"op": op, "edges": [{"condition": "default", "to": old_target}]}
        if op == "脚本":
            script_code = args.get("script_code", "")
            if not script_code:
                return "ERROR: script_code required for '脚本'."
            (SCRIPTS_DIR / f"{node_id}.py").write_text(script_code, encoding="utf-8")
            node_def["script"] = node_id
            node_def["input_vars"] = ["response", "question"]
            node_def["output_vars"] = ["response"]
        elif op == "llm_call":
            pt = args.get("prompt_template", "")
            if not pt:
                return "ERROR: prompt_template required for 'llm_call'."
            dag_state.config.setdefault("prompts", {})[f"{node_id}_prompt"] = pt
            node_def["prompt"] = f"{node_id}_prompt"
            node_def["input_vars"] = ["response", "question"]
            node_def["output_var"] = "response"
        else:
            return f"ERROR: op must be '脚本' or 'llm_call'."
        
        # Add node to DAG
        dag_state.config["pipeline"]["nodes"][node_id] = node_def
        
        # Auto-rewire: infer's has_text edge now points to new node
        for e in infer_edges:
            if e["condition"] == "has_text":
                e["to"] = node_id
                break
        
        return f"OK. Node '{node_id}' added and auto-wired: infer--[has_text]-->{node_id}--[default]-->{old_target}. Nodes: {list(dag_state.config['pipeline']['nodes'].keys())}"
    elif tool_name == "remove_node":
        node_id = args.get("node_id", "")
        if node_id in {"wait_input", "infer", "exec_tools"}:
            return f"ERROR: cannot remove core node."
        if node_id not in dag_state.config["pipeline"]["nodes"]:
            return f"ERROR: '{node_id}' not found."
        removed = dag_state.config["pipeline"]["nodes"][node_id]
        redirect = removed.get("edges", [{}])[0].get("to", "wait_input") if removed.get("edges") else "wait_input"
        for nid, nd in dag_state.config["pipeline"]["nodes"].items():
            for e in nd.get("edges", []):
                if e["to"] == node_id:
                    e["to"] = redirect
        del dag_state.config["pipeline"]["nodes"][node_id]
        sp = SCRIPTS_DIR / f"{node_id}.py"
        if sp.exists(): sp.unlink()
        return f"OK. '{node_id}' removed, edges redirected to '{redirect}'."
    elif tool_name == "rewire_edge":
        fn = args.get("from_node", "")
        cond = args.get("condition", "")
        nt = args.get("new_target", "")
        if fn not in dag_state.config["pipeline"]["nodes"]:
            return f"ERROR: '{fn}' not found."
        if nt not in dag_state.config["pipeline"]["nodes"]:
            return f"ERROR: target '{nt}' not found."
        for e in dag_state.config["pipeline"]["nodes"][fn].get("edges", []):
            if e["condition"] == cond:
                old = e["to"]
                e["to"] = nt
                return f"OK. {fn}--[{cond}]-->{nt} (was {old})."
        return f"ERROR: no edge '{cond}' on '{fn}'."
    elif tool_name == "write_script":
        sn = args.get("script_name", "")
        code = args.get("code", "")
        if not sn or not code:
            return "ERROR: script_name and code required."
        (SCRIPTS_DIR / f"{sn}.py").write_text(code, encoding="utf-8")
        return f"OK. Script '{sn}.py' written."
    elif tool_name == "done":
        return "DONE"
    return f"ERROR: unknown tool '{tool_name}'."


# ============================================================
# DAG 执行
# ============================================================

def run_task_with_dag(dag_state: DAGState, question: str) -> str:
    nodes = dag_state.config["pipeline"]["nodes"]
    messages = [
        {"role": "system", "content": dag_state.system_prompt},
        {"role": "user", "content": question},
    ]
    response = llm_call_simple(messages, max_tokens=1024, temperature=0.3)
    
    # Follow post-processing chain from infer's has_text edge
    infer_node = nodes.get("infer", {})
    next_node_id = None
    for edge in infer_node.get("edges", []):
        if edge["condition"] == "has_text":
            target = edge["to"]
            if target != "wait_input" and target in nodes:
                next_node_id = target
            break
    
    ctx = {"response": response, "question": question}
    visited = set()
    while next_node_id and next_node_id in nodes and next_node_id not in visited:
        visited.add(next_node_id)
        node = nodes[next_node_id]
        op = node.get("op")
        
        if op == "脚本":
            sp = SCRIPTS_DIR / f"{node.get('script', next_node_id)}.py"
            if sp.exists():
                try:
                    ns = {}
                    exec(sp.read_text(encoding="utf-8"), ns)
                    result = ns["run"](ctx)
                    if isinstance(result, dict) and "response" in result:
                        ctx["response"] = result["response"]
                        response = result["response"]
                except Exception as e:
                    pass  # Script error, skip
        elif op == "llm_call":
            pk = node.get("prompt", "")
            pt = dag_state.config.get("prompts", {}).get(pk, "")
            if pt:
                try:
                    formatted = pt.format(**ctx)
                    r = llm_call_simple([{"role": "user", "content": formatted}], max_tokens=512, temperature=0.3)
                    ctx["response"] = r
                    response = r
                except Exception:
                    pass
        
        # Follow first outgoing edge
        next_node_id = None
        for edge in node.get("edges", []):
            t = edge.get("to", "")
            if t and t != "wait_input" and t in nodes and t not in visited:
                next_node_id = t
                break
            elif t == "wait_input":
                break
    
    return response


# ============================================================
# Evolver
# ============================================================

EVOLVER_PROMPT = """You are an Agent Architecture Optimizer. Improve a Solver agent's performance by modifying its prompt and/or DAG pipeline structure.

## DAG basics:
- Nodes connected by conditional edges. Pipeline: wait_input → infer → (has_tool_calls→exec_tools | has_text→output)
- You can insert post-processing nodes between "infer" and the output to fix/transform the response
- Node types: "脚本" (Python with def run(ctx)) and "llm_call" (prompt template with {{response}},{{question}})

## Strategy:
- If failures are due to format issues that prompting cannot fix (e.g. model keeps using wrong format), ADD A SCRIPT NODE to post-process the output.
- add_node automatically wires itself after "infer" — just one call is needed, no need to call rewire_edge separately.
- Script nodes receive ctx={{'response':str,'question':str}} and must return {{'response':str}}.

## Evaluation:
{eval_criteria}

Analyze failures, decide strategy, use tools, call done when finished."""


def parse_text_tool_calls(content: str) -> List[Dict]:
    """Parse tool calls that appear in text format (model sometimes outputs them as text)."""
    calls = []
    # Match <tool_call>\n{"name": ..., "arguments": ...}\n</tool_call> pattern
    pattern = r'<tool_call>\s*(\{.*?\})\s*</tool_call>'
    matches = re.findall(pattern, content, re.DOTALL)
    if not matches:
        # Also try {"name": ..., "arguments": ...} without tags
        pattern2 = r'\{"name":\s*"(\w+)",\s*"arguments":\s*(\{.*?\})\}'
        matches2 = re.findall(pattern2, content, re.DOTALL)
        for name, args_str in matches2:
            try:
                args = json.loads(args_str)
                calls.append({"function": {"name": name, "arguments": json.dumps(args)}, "id": f"text_{name}"})
            except:
                pass
    else:
        for m in matches:
            try:
                obj = json.loads(m)
                name = obj.get("name", "")
                args = obj.get("arguments", {})
                if isinstance(args, str):
                    args = json.loads(args)
                calls.append({"function": {"name": name, "arguments": json.dumps(args)}, "id": f"text_{name}"})
            except:
                pass
    return calls


def run_evolver(dag_state: DAGState, failure_info: str, history_info: str, eval_criteria: str) -> Dict:
    sys_prompt = EVOLVER_PROMPT.format(eval_criteria=eval_criteria)
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": f"{failure_info}\n\n{history_info}\n\nMake improvements. Call done when finished."},
    ]
    actions = []
    start_time = time.time()
    max_time = 120  # 120 seconds max per evolver turn
    
    for turn in range(6):  # Max 6 LLM calls per turn
        if time.time() - start_time > max_time:
            actions.append({"action": "timeout", "content": "Evolver timed out"})
            break
        resp = llm_call(messages, max_tokens=1024, temperature=0.3, tools=TOOLS)
        tool_calls = resp.get("tool_calls", [])
        if not tool_calls:
            content = resp.get("content", "")
            # Fallback: parse tool calls from text content
            if content:
                text_calls = parse_text_tool_calls(content)
                if text_calls:
                    tool_calls = text_calls
                else:
                    actions.append({"action": "text", "content": content[:200]})
                    break
        if not tool_calls:
            break
        messages.append(resp)
        done_flag = False
        for tc in tool_calls:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments", "{}"))
            except:
                args = {}
            result = execute_tool(dag_state, name, args)
            actions.append({"action": name, "args": str(args)[:150], "result": result[:150]})
            messages.append({"role": "tool", "tool_call_id": tc.get("id", f"c{turn}"), "content": result})
            if name == "done" or result == "DONE":
                done_flag = True
        if done_flag:
            break
    return {"actions": actions}


# ============================================================
# 单个 Scenario 运行器
# ============================================================

def run_scenario(scenario: Dict, max_rounds: int = 5, eval_fmt: str = "<final_answer>") -> Dict:
    name = scenario["name"]
    print(f"\n{'='*60}")
    print(f"  Scenario: {name}")
    print(f"  {scenario['description']}")
    print(f"  Eval format: {eval_fmt}")
    print(f"{'='*60}")
    
    # Clean scripts dir for this scenario
    for f in SCRIPTS_DIR.glob("*.py"):
        f.unlink()
    
    dag_state = DAGState(scenario["initial_prompt"])
    tasks = scenario["tasks"]
    
    eval_criteria = f"Answer correct ONLY if response contains answer in `{eval_fmt}` format and number matches ground truth."
    if eval_fmt == "<final_answer>":
        eval_criteria = "Correct ONLY if response has `<final_answer>NUMBER</final_answer>` and NUMBER matches ground truth. 'format error'=tag missing. 'wrong answer'=tag present but number wrong."
    elif eval_fmt == "####":
        eval_criteria = "Correct ONLY if response has `#### NUMBER` (on its own line) and NUMBER matches ground truth. 'format error'=#### missing. 'wrong answer'=number wrong."
    
    all_rounds = []
    history = []
    
    for rd in range(max_rounds):
        print(f"\n  Round {rd+1}: nodes={list(dag_state.config['pipeline']['nodes'].keys())}")
        
        results = []
        failures = []
        for task in tasks:
            resp = run_task_with_dag(dag_state, task["question"])
            ev = evaluate_response(resp, task["answer"], eval_fmt)
            ev["question"] = task["question"]
            ev["response"] = resp[:400]
            ev["ground_truth"] = task["answer"]
            results.append(ev)
            if not ev["correct"]:
                failures.append(ev)
        
        acc = sum(1 for r in results if r["correct"]) / len(results)
        fmt_rate = sum(1 for r in results if r["format_ok"]) / len(results)
        print(f"    accuracy={acc:.0%}, format={fmt_rate:.0%}")
        
        all_rounds.append({"round": rd+1, "accuracy": acc, "format_rate": fmt_rate,
                          "nodes": list(dag_state.config["pipeline"]["nodes"].keys())})
        
        if acc >= 0.75:
            print(f"    ✓ Good enough. Stopping.")
            break
        if not failures:
            break
        
        # Build failure info
        fi = f"Prompt: {dag_state.system_prompt}\nDAG:\n{dag_state.get_nodes_summary()}\n\n"
        fi += f"Score: {sum(1 for r in results if r['correct'])}/{len(results)} correct, {sum(1 for r in results if r['format_ok'])}/{len(results)} format OK\n\nFailed:\n"
        for f in failures[:4]:
            fi += f"  Q: {f['question'][:100]}\n  Resp (last 200): ...{f['response'][-200:]}\n  Extracted: {f.get('extracted','NONE')}\n  Expected: {f['ground_truth']}\n  Reason: {f.get('reason','?')}\n\n"
        
        # If there's a script node but format is still failing, hint to improve script
        existing_scripts = [nid for nid in dag_state.config["pipeline"]["nodes"] 
                          if nid not in {"wait_input", "infer", "exec_tools"}]
        if existing_scripts and any(f.get("reason") == "missing_format" for f in failures):
            script_content = ""
            for sid in existing_scripts:
                sp = SCRIPTS_DIR / f"{sid}.py"
                if sp.exists():
                    script_content = sp.read_text(encoding="utf-8")
            if script_content:
                fi += f"\nCurrent script node '{existing_scripts[0]}':\n```\n{script_content}\n```\n"
                fi += "The script is not extracting answers correctly. The model often uses \\boxed{{}} or puts answer on last line. Consider using write_script to UPDATE the script with better extraction logic (e.g., check for \\boxed{{}}, ####, or last line number).\n"
        
        hi = ""
        if history:
            hi = "Previous attempts:\n"
            for h in history:
                hi += f"  Round {h['rd']}: accuracy={h['acc']:.0%}, actions_taken={h.get('actions', 'modify_prompt')}\n"
            if len(history) >= 1 and all(h['acc'] < 0.25 for h in history):
                hi += "\n  ⚠️ CRITICAL: Prompt changes have FAILED. You MUST use the add_node tool NOW to add a script node.\n"
                hi += "  Example: add_node(node_id='format_fixer', op='脚本', script_code='def run(ctx):\\n    response = ctx[\"response\"]\\n    import re\\n    # extract number and wrap in <final_answer>\\n    nums = re.findall(r\"\\\\d+\\\\.?\\\\d*\", response)\\n    if nums:\\n        return {\"response\": f\"<final_answer>{nums[-1]}</final_answer>\"}\\n    return {\"response\": response}\\n')\n"
            elif len(history) >= 2 and all(h['acc'] < 0.5 for h in history):
                hi += "\n  WARNING: Multiple rounds of prompt modification have NOT solved the problem. Consider structural changes (adding a script post-processing node) instead of modifying the prompt again.\n"
        
        print(f"    Calling Evolver...")
        ev_result = run_evolver(dag_state, fi, hi, eval_criteria)
        for a in ev_result["actions"]:
            if a["action"] == "text":
                print(f"      [text] {a['content'][:80]}")
            else:
                print(f"      [{a['action']}] {a['result'][:60]}")
        
        action_names = [a["action"] for a in ev_result["actions"] if a["action"] not in ("text", "timeout")]
        history.append({"rd": rd+1, "acc": acc, "actions": ", ".join(action_names[:3]) or "modify_prompt"})
    
    # Summary
    final_nodes = set(dag_state.config["pipeline"]["nodes"].keys())
    added = final_nodes - {"wait_input", "infer", "exec_tools"}
    
    result = {
        "scenario": name,
        "rounds": all_rounds,
        "final_accuracy": all_rounds[-1]["accuracy"],
        "structural_changes": list(added),
        "final_prompt": dag_state.system_prompt[:200],
    }
    
    if added:
        print(f"    ★ Added nodes: {added}")
        for nid in added:
            sp = SCRIPTS_DIR / f"{nid}.py"
            if sp.exists():
                print(f"      {nid}: {sp.read_text()[:150]}")
    
    return result


# ============================================================
# GSM8K 加载
# ============================================================

def load_gsm8k(n: int = 20) -> List[Dict]:
    """从 parquet 加载 GSM8K 子集"""
    import pandas as pd
    df = pd.read_parquet("/mnt/hdfs/data/gsm8k/test.parquet")
    tasks = []
    for _, row in df.head(n).iterrows():
        gt = row["reward_model"]
        if isinstance(gt, str):
            gt = json.loads(gt)
        answer = gt.get("ground_truth", "")
        
        extra = row.get("extra_info", {})
        if isinstance(extra, str):
            extra = json.loads(extra)
        question = extra.get("question", "")
        if not question:
            # fallback: extract from prompt
            prompts = row.get("prompt", [])
            if isinstance(prompts, str):
                prompts = json.loads(prompts)
            if prompts:
                question = prompts[0].get("content", "")
        
        if question and answer:
            tasks.append({"question": question, "answer": str(answer)})
    
    return tasks


# ============================================================
# 主函数
# ============================================================

def main():
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  EgoAgent Structural Evolution — Multi-Scenario Test        ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    
    all_results = []
    
    # Scenario A: 格式缺失
    r = run_scenario(SCENARIO_A, max_rounds=5, eval_fmt="<final_answer>")
    all_results.append(r)
    
    # Scenario B: 多步计算 + 格式
    r = run_scenario(SCENARIO_B, max_rounds=5, eval_fmt="<final_answer>")
    all_results.append(r)
    
    # Scenario C: \boxed{} 格式冲突
    r = run_scenario(SCENARIO_C, max_rounds=5, eval_fmt="<final_answer>")
    all_results.append(r)
    
    # Scenario D: GSM8K 真实数据（前 12 题）— 只在 A/B/C 都通过后运行
    all_passed = all(r["final_accuracy"] >= 0.75 for r in all_results)
    if all_passed:
        print("\n  All synthetic scenarios passed! Loading GSM8K...")
        gsm8k_tasks = load_gsm8k(20)
        print(f"  Loaded {len(gsm8k_tasks)} tasks")
        gsm8k_scenario = {
            "name": "gsm8k_real",
            "description": "GSM8K real test set (20 questions), ground truth exact match",
            "initial_prompt": "You are a math problem solver. Think step by step and solve the problem. Put your final numerical answer inside <final_answer></final_answer> tags.",
            "tasks": gsm8k_tasks[:20],
        }
        r = run_scenario(gsm8k_scenario, max_rounds=8, eval_fmt="<final_answer>")
        all_results.append(r)
    else:
        print("\n  Skipping GSM8K (some scenarios failed).")
    
    # Final report
    print(f"\n{'═'*60}")
    print("  FINAL SUMMARY")
    print(f"{'═'*60}")
    for r in all_results:
        status = "✓" if r["final_accuracy"] >= 0.75 else "✗"
        struct = f" +{r['structural_changes']}" if r["structural_changes"] else ""
        print(f"  {status} {r['scenario']}: accuracy={r['final_accuracy']:.0%}{struct}")
    
    # Save
    report_path = OUTPUT_DIR / f"multi_test_{time.strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(json.dumps(all_results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  Report: {report_path}")


if __name__ == "__main__":
    main()
