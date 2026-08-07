"""
Self-Evolution Engine — 核心实现。

融合多种自进化策略：
1. Principle Library (EvolveR) — 从轨迹中提炼策略原则
2. Evolution Archive (ADAS) — 记录所有修改尝试
3. Frontier Curriculum (Agent0) — 前沿难度任务选择
4. TextGrad Optimizer (EvoAgentX) — 文本梯度优化 prompt
5. Gated Evolution Controller — 快照/评估/门控/回滚
6. Main Evolution Loop — 完整进化循环
"""

import json
import os
import sys
import time
import uuid
import shutil
import requests
from pathlib import Path
from typing import List, Dict, Any, Optional

# 确保项目根目录在 path 中
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# ============================================================
# 配置
# ============================================================

DATA_DIR = Path(__file__).resolve().parent / "data"
PRINCIPLES_FILE = DATA_DIR / "principles.json"
ARCHIVE_FILE = DATA_DIR / "archive.json"
TASK_POOL_FILE = DATA_DIR / "task_pool.json"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"

LLM_BASE_URL = "http://[fdbd:dc05:10:10a::27]:9638/v1"
LLM_MODEL = "Qwen3-8B-yangyuan"


def _ensure_data_dirs():
    """确保所有数据目录存在"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    for f in [PRINCIPLES_FILE, ARCHIVE_FILE, TASK_POOL_FILE]:
        if not f.exists():
            f.write_text("[]", encoding="utf-8")


_ensure_data_dirs()


def _load_json(path: Path) -> Any:
    """安全加载 JSON 文件"""
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return []


def _save_json(path: Path, data: Any):
    """保存 JSON 文件"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _llm_call(messages: List[Dict], max_tokens: int = 2048, temperature: float = 0.7) -> str:
    """调用 LLM API（OpenAI 兼容格式）"""
    url = f"{LLM_BASE_URL}/chat/completions"
    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    headers = {"Content-Type": "application/json"}
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=120)
        resp.raise_for_status()
        result = resp.json()
        content = result["choices"][0]["message"].get("content", "")
        # 处理 thinking 标签（完整或被截断）
        if "</think>" in content:
            content = content.split("</think>")[-1].strip()
        elif "<think>" in content:
            # think 标签被截断 — 整个输出都是思考过程，无实际答案
            # 返回空字符串，调用方需处理
            content = ""
        return content
    except Exception as e:
        return f"[LLM_ERROR] {e}"


def _extract_json_from_response(text: str) -> Any:
    """从 LLM 响应中提取 JSON"""
    # 尝试找到 JSON 块
    if "```json" in text:
        start = text.index("```json") + 7
        end = text.index("```", start)
        text = text[start:end].strip()
    elif "```" in text:
        start = text.index("```") + 3
        end = text.index("```", start)
        text = text[start:end].strip()
    # 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 尝试找到第一个 [ 或 {
        for i, c in enumerate(text):
            if c in "[{":
                try:
                    return json.loads(text[i:])
                except json.JSONDecodeError:
                    continue
        return None


# ============================================================
# 1. Principle Library (EvolveR)
# ============================================================

def distill_principles(session_path: str) -> List[Dict]:
    """
    从 session 轨迹中提炼策略原则。
    
    Args:
        session_path: session 目录路径（含 messages.json）
    
    Returns:
        新提炼的原则列表
    """
    session_dir = Path(session_path)
    messages_file = session_dir / "messages.json"
    if not messages_file.exists():
        return []

    messages = _load_json(messages_file)
    if not messages:
        return []

    # 构建轨迹摘要
    trajectory_summary = []
    for msg in messages[-20:]:  # 取最后20条避免太长
        role = msg.get("role", "unknown")
        content = msg.get("content", "")[:500]
        trajectory_summary.append(f"[{role}] {content}")
    trajectory_text = "\n".join(trajectory_summary)

    prompt = f"""Analyze this agent session trajectory and distill strategic principles.
For each principle, determine:
- type: "guiding" (what to do) or "cautionary" (what to avoid)
- description: concise actionable principle

Return a JSON array of principles:
[{{"type": "guiding"|"cautionary", "description": "..."}}]

Trajectory:
{trajectory_text}

Output ONLY valid JSON array:"""

    response = _llm_call([
        {"role": "system", "content": "You are an expert at analyzing agent behaviors and extracting reusable strategic principles. Respond only with valid JSON."},
        {"role": "user", "content": prompt},
    ], max_tokens=1024, temperature=0.5)

    raw_principles = _extract_json_from_response(response)
    if not isinstance(raw_principles, list):
        return []

    # 加载现有原则库
    principles = _load_json(PRINCIPLES_FILE)
    new_principles = []

    for p in raw_principles:
        if not isinstance(p, dict) or "description" not in p:
            continue
        principle = {
            "id": str(uuid.uuid4())[:8],
            "type": p.get("type", "guiding"),
            "description": p["description"],
            "score": 0.5,  # 初始分 = (0+1)/(0+2) = 0.5
            "usage_count": 0,
            "success_count": 0,
        }
        new_principles.append(principle)
        principles.append(principle)

    _save_json(PRINCIPLES_FILE, principles)
    return new_principles


def retrieve_principles(query: str, top_k: int = 3) -> List[Dict]:
    """
    检索与 query 最相关的原则。
    使用 LLM 进行语义匹配排序。
    
    Args:
        query: 当前任务/场景描述
        top_k: 返回前 k 个
    
    Returns:
        最相关的原则列表
    """
    principles = _load_json(PRINCIPLES_FILE)
    if not principles:
        return []

    # 按 score 预排序，取候选集
    sorted_principles = sorted(principles, key=lambda x: x.get("score", 0), reverse=True)
    candidates = sorted_principles[:min(20, len(sorted_principles))]

    if len(candidates) <= top_k:
        return candidates

    # 用 LLM 做语义匹配
    candidates_text = "\n".join(
        f"{i}. [{p['type']}] {p['description']} (score: {p['score']:.2f})"
        for i, p in enumerate(candidates)
    )

    prompt = f"""Given the current task context, rank the most relevant principles.

Task context: {query}

Available principles:
{candidates_text}

Return the indices (0-based) of the top {top_k} most relevant principles as a JSON array of integers.
Output ONLY the JSON array:"""

    response = _llm_call([
        {"role": "user", "content": prompt},
    ], max_tokens=128, temperature=0.3)

    indices = _extract_json_from_response(response)
    if isinstance(indices, list):
        result = []
        for idx in indices[:top_k]:
            if isinstance(idx, int) and 0 <= idx < len(candidates):
                result.append(candidates[idx])
        if result:
            return result

    # 回退：直接返回 score 最高的
    return candidates[:top_k]


def update_scores(principle_ids: List[str], success: bool):
    """
    更新原则分数。
    score = (success_count + 1) / (usage_count + 2)
    
    Args:
        principle_ids: 要更新的原则 ID 列表
        success: 使用这些原则后是否成功
    """
    principles = _load_json(PRINCIPLES_FILE)
    id_set = set(principle_ids)

    for p in principles:
        if p["id"] in id_set:
            p["usage_count"] = p.get("usage_count", 0) + 1
            if success:
                p["success_count"] = p.get("success_count", 0) + 1
            p["score"] = (p["success_count"] + 1) / (p["usage_count"] + 2)

    _save_json(PRINCIPLES_FILE, principles)


# ============================================================
# 2. Evolution Archive (ADAS)
# ============================================================

def record_attempt(entry: Dict) -> str:
    """
    记录一次修改尝试到归档。
    
    Args:
        entry: 包含 target, action, diff, score_before, score_after, accepted
    
    Returns:
        生成的记录 ID
    """
    archive = _load_json(ARCHIVE_FILE)

    record = {
        "id": str(uuid.uuid4())[:8],
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "target": entry.get("target", "unknown"),
        "action": entry.get("action", ""),
        "diff": entry.get("diff", ""),
        "score_before": entry.get("score_before", 0.0),
        "score_after": entry.get("score_after", 0.0),
        "accepted": entry.get("accepted", False),
    }
    archive.append(record)
    _save_json(ARCHIVE_FILE, archive)
    return record["id"]


def get_history(target: str, limit: int = 10) -> List[Dict]:
    """
    获取某个目标的修改历史。
    
    Args:
        target: harness 或 identity 名称
        limit: 最多返回多少条
    
    Returns:
        按时间倒序的修改记录
    """
    archive = _load_json(ARCHIVE_FILE)
    filtered = [r for r in archive if r.get("target") == target]
    return sorted(filtered, key=lambda x: x.get("timestamp", ""), reverse=True)[:limit]


def get_best_configs(target: str) -> List[Dict]:
    """
    获取某个目标的最佳配置（accepted=True 且 score_after 最高的）。
    
    Args:
        target: harness 或 identity 名称
    
    Returns:
        按 score_after 降序排列的已接受修改
    """
    archive = _load_json(ARCHIVE_FILE)
    accepted = [r for r in archive if r.get("target") == target and r.get("accepted")]
    return sorted(accepted, key=lambda x: x.get("score_after", 0), reverse=True)


# ============================================================
# 3. Frontier Curriculum (Agent0)
# ============================================================

def assess_difficulty(harness: str, identity: str, task: str, n_runs: int = 3) -> float:
    """
    通过一致性评分评估任务难度（相同任务运行N次，统计成功率）。
    
    Args:
        harness: harness 名称
        identity: identity 名称
        task: 任务描述
        n_runs: 运行次数
    
    Returns:
        成功率 [0, 1]，代表任务难度的反面
    """
    from config import CONFIG

    harness_dir = Path(CONFIG["harness_template_repository"]) / harness
    identity_dir = Path(CONFIG["identity_repository"]) / identity

    if not harness_dir.exists() or not identity_dir.exists():
        return 0.0

    successes = 0
    for _ in range(n_runs):
        try:
            score = _run_single_task(harness_dir, identity_dir, task)
            if score > 0.5:
                successes += 1
        except Exception:
            pass

    return successes / n_runs if n_runs > 0 else 0.0


def _run_single_task(harness_dir: Path, identity_dir: Path, task: str) -> float:
    """
    运行单个任务并返回分数。
    轻量级评估：直接读取 identity 配置，用 _llm_call 生成回答并评分。
    不创建完整 Agent/Harness 实例，避免环境初始化阻塞。
    """
    try:
        # 读取 identity 描述
        id_file = identity_dir / "id.json"
        description = "You are a helpful assistant."
        if id_file.exists():
            id_data = json.loads(id_file.read_text(encoding="utf-8"))
            desc = id_data.get("description", "")
            if not desc:
                # 从其他字段构建描述
                role = id_data.get("role", "assistant")
                personality = id_data.get("personality", {})
                tone = personality.get("tone", "helpful")
                traits = personality.get("traits", [])
                description = f"You are a {role}. Your style is {tone}. Traits: {', '.join(traits)}."
            else:
                description = desc

        # 用 LLM 生成回答
        messages = [
            {"role": "system", "content": description},
            {"role": "user", "content": task},
        ]
        response = _llm_call(messages, max_tokens=2048, temperature=0.3)
        if not response or response.startswith("[LLM_ERROR]"):
            return 0.0

        # 用 LLM 评估质量
        eval_prompt = f"""Rate the quality of this response to the task on a scale of 0.0 to 1.0.
Task: {task}
Response: {response[:1000]}

Output ONLY a single float number between 0.0 and 1.0. No explanation. No thinking. Just the number:"""

        score_text = _llm_call([
            {"role": "system", "content": "You are a strict evaluator. Output only a float between 0.0 and 1.0. No explanation."},
            {"role": "user", "content": eval_prompt},
        ], max_tokens=512, temperature=0.1)
        try:
            # 尝试从响应中提取浮点数
            if not score_text.strip():
                return 0.5
            import re
            numbers = re.findall(r"[01]?\.\d+|[01]\.0|1\.0|0\.0", score_text)
            if numbers:
                score = float(numbers[0])
            else:
                score = float(score_text.strip().split()[0])
            return max(0.0, min(1.0, score))
        except (ValueError, IndexError):
            return 0.5
    except Exception:
        return 0.0


def generate_frontier_tasks(harness: str, identity: str) -> List[Dict]:
    """
    生成处于"前沿区域"（成功率 0.3-0.8）的任务。
    
    Args:
        harness: harness 名称
        identity: identity 名称
    
    Returns:
        前沿任务列表
    """
    task_pool = _load_json(TASK_POOL_FILE)

    # 如果任务池为空，先生成一批候选任务
    if not task_pool:
        task_pool = _generate_candidate_tasks(harness, identity)
        _save_json(TASK_POOL_FILE, task_pool)

    # 筛选前沿区域的任务
    frontier_tasks = []
    for task in task_pool:
        difficulty = task.get("difficulty", -1)
        if difficulty < 0:
            # 未评估的任务，进行评估
            difficulty = assess_difficulty(harness, identity, task["description"], n_runs=3)
            task["difficulty"] = difficulty

        if 0.3 <= difficulty <= 0.8:
            frontier_tasks.append(task)

    _save_json(TASK_POOL_FILE, task_pool)
    return frontier_tasks


def _generate_candidate_tasks(harness: str, identity: str) -> List[Dict]:
    """使用 LLM 生成候选任务"""
    from config import CONFIG
    harness_dir = Path(CONFIG["harness_template_repository"]) / harness
    config_file = harness_dir / "config.json"

    harness_desc = ""
    if config_file.exists():
        config = json.loads(config_file.read_text(encoding="utf-8"))
        harness_desc = config.get("description", "")

    identity_dir = Path(CONFIG["identity_repository"]) / identity
    id_file = identity_dir / "id.json"
    identity_desc = ""
    if id_file.exists():
        id_data = json.loads(id_file.read_text(encoding="utf-8"))
        identity_desc = f"Role: {id_data.get('role', '')}, Description: {id_data.get('description', '')}"

    prompt = f"""Generate 10 test tasks of varying difficulty for this agent system.

Harness: {harness} — {harness_desc}
Agent: {identity} — {identity_desc}

Tasks should range from easy to hard, testing different capabilities.
Return a JSON array: [{{"description": "task text", "difficulty": -1}}]

Output ONLY valid JSON array:"""

    response = _llm_call([
        {"role": "system", "content": "Generate diverse test tasks as JSON. Respond only with valid JSON."},
        {"role": "user", "content": prompt},
    ], max_tokens=1536, temperature=0.8)

    tasks = _extract_json_from_response(response)
    if isinstance(tasks, list):
        # 确保格式正确
        valid_tasks = []
        for t in tasks:
            if isinstance(t, dict) and "description" in t:
                valid_tasks.append({
                    "id": str(uuid.uuid4())[:8],
                    "description": t["description"],
                    "difficulty": -1,  # 未评估
                })
        return valid_tasks

    # 回退：返回默认任务
    return [
        {"id": str(uuid.uuid4())[:8], "description": "Write a Python function to compute factorial.", "difficulty": -1},
        {"id": str(uuid.uuid4())[:8], "description": "Explain the concept of recursion with an example.", "difficulty": -1},
        {"id": str(uuid.uuid4())[:8], "description": "Debug a function with an off-by-one error.", "difficulty": -1},
    ]


def get_task_pool() -> List[Dict]:
    """获取当前任务池"""
    return _load_json(TASK_POOL_FILE)


# ============================================================
# 4. TextGrad Optimizer (EvoAgentX)
# ============================================================

def compute_text_gradient(session_path: str, current_prompt: str) -> str:
    """
    分析失败轨迹，生成针对性的 prompt 改进建议（文本梯度）。
    
    Args:
        session_path: 失败 session 的路径
        current_prompt: 当前使用的 prompt
    
    Returns:
        文本梯度 — 描述 prompt 应如何修改的指令
    """
    session_dir = Path(session_path)
    messages_file = session_dir / "messages.json"

    trajectory = ""
    if messages_file.exists():
        messages = _load_json(messages_file)
        # 提取关键失败信息
        for msg in messages[-15:]:
            role = msg.get("role", "")
            content = msg.get("content", "")[:300]
            trajectory += f"[{role}] {content}\n"

    prompt = f"""You are a prompt optimization expert. Analyze this failed agent trajectory and the current prompt,
then produce a "text gradient" — specific instructions for how to modify the prompt to fix the failure.

Current Prompt:
{current_prompt[:2000]}

Failed Trajectory:
{trajectory[:3000]}

Analyze:
1. What went wrong in this trajectory?
2. What aspects of the current prompt led to this failure?
3. What specific changes should be made to the prompt?

Output a concise "text gradient" — ONE specific, small modification (not a rewrite):"""

    gradient = _llm_call([
        {"role": "system", "content": "You are a prompt optimization expert. Suggest ONE small, targeted change. Be specific and concise (under 100 words)."},
        {"role": "user", "content": prompt},
    ], max_tokens=2048, temperature=0.5)

    return gradient


def apply_gradient(identity_name: str, field: str, gradient: str) -> Dict:
    """
    将文本梯度应用到 identity 的指定字段。
    
    Args:
        identity_name: identity 名称
        field: 要修改的字段（如 "description", "personality.tone" 等）
        gradient: 文本梯度（修改指令）
    
    Returns:
        {"old_value": ..., "new_value": ..., "success": bool}
    """
    from config import CONFIG
    identity_dir = Path(CONFIG["identity_repository"]) / identity_name
    id_file = identity_dir / "id.json"

    if not id_file.exists():
        return {"old_value": None, "new_value": None, "success": False}

    id_data = json.loads(id_file.read_text(encoding="utf-8"))

    # 获取当前值（支持嵌套字段如 "personality.tone"）
    keys = field.split(".")
    current = id_data
    for k in keys[:-1]:
        current = current.get(k, {})
    old_value = current.get(keys[-1], "")

    # 使用 LLM 应用梯度（保守修改）
    prompt = f"""Apply this modification instruction to the given text value.
IMPORTANT CONSTRAINTS:
- Make MINIMAL changes. Only modify what the instruction explicitly asks for.
- Keep the result SHORT (under 200 characters for tone/style fields, under 500 for description).
- Preserve the existing style and structure as much as possible.
- If the current value is short, keep the result short too.

Current value of field "{field}":
{old_value if old_value else "(empty)"}

Modification instruction (gradient):
{gradient[:500]}

Output ONLY the new value for this field (no explanation, no quotes unless part of the value):"""

    new_value = _llm_call([
        {"role": "system", "content": "You make minimal, conservative edits. Keep output concise."},
        {"role": "user", "content": prompt},
    ], max_tokens=512, temperature=0.2)

    # 写回
    current[keys[-1]] = new_value.strip()
    id_file.write_text(json.dumps(id_data, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"old_value": old_value, "new_value": new_value.strip(), "success": True}


# ============================================================
# 5. Gated Evolution Controller
# ============================================================

def snapshot(target: str) -> str:
    """
    在修改前创建快照。
    
    Args:
        target: 目标名称（harness/identity 路径标识）
    
    Returns:
        snapshot_id
    """
    from config import CONFIG

    snapshot_id = f"{target}_{time.strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:4]}"
    snapshot_dir = SNAPSHOTS_DIR / snapshot_id

    # 判断 target 类型
    harness_dir = Path(CONFIG["harness_template_repository"]) / target
    identity_dir = Path(CONFIG["identity_repository"]) / target

    source = None
    if harness_dir.exists():
        source = harness_dir
    elif identity_dir.exists():
        source = identity_dir

    if source:
        shutil.copytree(source, snapshot_dir)
    else:
        # 尝试直接作为路径
        source = Path(target)
        if source.exists():
            shutil.copytree(source, snapshot_dir)
        else:
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            (snapshot_dir / "_meta.json").write_text(
                json.dumps({"target": target, "error": "source not found"}, ensure_ascii=False),
                encoding="utf-8"
            )

    # 保存元信息
    meta = {
        "snapshot_id": snapshot_id,
        "target": target,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source_path": str(source) if source else None,
    }
    (snapshot_dir / "_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return snapshot_id


def evaluate(harness: str, identity: str, tasks: List[str], n_repeats: int = 3) -> float:
    """在一组任务上评估当前 harness+identity 的表现。多次评估取中位数以提高稳定性。"""
    if not tasks:
        return 0.0

    from config import CONFIG
    harness_dir = Path(CONFIG["harness_template_repository"]) / harness
    identity_dir = Path(CONFIG["identity_repository"]) / identity

    all_scores = []
    for _ in range(n_repeats):
        round_scores = []
        for task in tasks:
            try:
                score = _run_single_task(harness_dir, identity_dir, task)
                round_scores.append(score)
            except Exception:
                round_scores.append(0.0)
        all_scores.append(sum(round_scores) / len(round_scores) if round_scores else 0.0)

    # 取中位数
    all_scores.sort()
    mid = len(all_scores) // 2
    return all_scores[mid] if len(all_scores) % 2 == 1 else (all_scores[mid-1] + all_scores[mid]) / 2


def gate_decision(score_before: float, score_after: float, threshold: float = 5.0) -> str:
    """
    门控决策：决定是否接受修改。
    
    Args:
        score_before: 修改前分数（百分制，即 0-100 scale）
        score_after: 修改后分数
        threshold: 改进阈值（百分比点数）
    
    Returns:
        "accept" / "reject" / "rollback"
    """
    improvement = score_after - score_before

    if improvement >= threshold:
        return "accept"
    elif improvement >= 0:
        # 有微小改进但不够显著 — 仍接受但标记
        return "accept"
    elif improvement > -threshold:
        # 略有退步但在容忍范围内
        return "reject"
    else:
        # 显著退步，需要回滚
        return "rollback"


def rollback(target: str, snapshot_id: str) -> bool:
    """
    回滚到之前的快照。
    
    Args:
        target: 目标名称
        snapshot_id: 快照 ID
    
    Returns:
        是否回滚成功
    """
    from config import CONFIG

    snapshot_dir = SNAPSHOTS_DIR / snapshot_id
    if not snapshot_dir.exists():
        return False

    meta_file = snapshot_dir / "_meta.json"
    if meta_file.exists():
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        source_path = meta.get("source_path")
    else:
        source_path = None

    # 确定恢复目标路径
    harness_dir = Path(CONFIG["harness_template_repository"]) / target
    identity_dir = Path(CONFIG["identity_repository"]) / target

    restore_to = None
    if harness_dir.exists():
        restore_to = harness_dir
    elif identity_dir.exists():
        restore_to = identity_dir
    elif source_path:
        restore_to = Path(source_path)

    if restore_to is None:
        return False

    # 执行回滚：删除当前，复制快照（排除 _meta.json）
    try:
        if restore_to.exists():
            shutil.rmtree(restore_to)
        shutil.copytree(snapshot_dir, restore_to)
        # 删除 _meta.json（不属于原始文件）
        meta_in_restored = restore_to / "_meta.json"
        if meta_in_restored.exists():
            meta_in_restored.unlink()
        return True
    except Exception:
        return False


# ============================================================
# 6. Main Evolution Loop
# ============================================================

def run_evolution_cycle(
    target_harness: str,
    target_identity: str,
    max_iterations: int = 5,
    verbose: bool = True,
    progress_callback=None,
) -> Dict:
    """
    主进化循环，编排完整的自进化流程。
    
    流程：
    1. 评估当前表现（在任务池上）
    2. 选择前沿任务
    3. 运行测试、收集轨迹
    4. 从轨迹提炼原则
    5. 从失败计算文本梯度
    6. 应用修改（prompt 或 pipeline）
    7. 门控决策（接受或回滚）
    8. 记录到归档
    9. 重复
    
    Args:
        target_harness: 目标 harness 名称
        target_identity: 目标 identity 名称
        max_iterations: 最大迭代次数
        verbose: 是否打印详细信息
    
    Returns:
        进化总结报告
    """
    # Auto-snapshot before evolution
    try:
        from self_evolution.snapshot_manager import SnapshotManager
        sm = SnapshotManager()
        sm.create_snapshot(target_identity, reason="pre_evolution")
    except Exception:
        pass  # snapshot failure should not block evolution

    from config import CONFIG

    def _emit(step: str, detail: str = ""):
        if progress_callback:
            progress_callback(step, detail)
        if verbose:
            print(f"  {step}" + (f" — {detail}" if detail else ""))

    report = {
        "target_harness": target_harness,
        "target_identity": target_identity,
        "iterations": [],
        "initial_score": 0.0,
        "final_score": 0.0,
        "total_accepted": 0,
        "total_rejected": 0,
        "total_rollbacks": 0,
    }

    if verbose:
        print(f"\n{'='*60}")
        print(f"  Self-Evolution Engine — Starting Cycle")
        print(f"  Target: {target_harness} / {target_identity}")
        print(f"  Max Iterations: {max_iterations}")
        print(f"{'='*60}\n")

    # Step 1: 生成或加载任务池
    _emit("[1/9] Generating task pool...")
    task_pool = get_task_pool()
    if not task_pool:
        task_pool = _generate_candidate_tasks(target_harness, target_identity)
        _save_json(TASK_POOL_FILE, task_pool)

    eval_tasks = [t["description"] for t in task_pool[:5]]

    # Step 2: 评估当前基线
    _emit("[2/9] Evaluating baseline performance...")
    baseline_score = evaluate(target_harness, target_identity, eval_tasks)
    report["initial_score"] = baseline_score
    current_score = baseline_score

    _emit(f"[2/9] Baseline score: {baseline_score:.2f}")

    # 迭代进化
    for iteration in range(max_iterations):
        _emit(f"[Iter {iteration+1}/{max_iterations}] Starting iteration...")

        iter_report = {
            "iteration": iteration + 1,
            "score_before": current_score,
            "score_after": current_score,
            "action": "",
            "decision": "",
        }

        # Step 3: 选择前沿任务
        _emit(f"[Iter {iteration+1}] [3/9] Selecting frontier tasks...")
        frontier = []
        for t in task_pool:
            d = t.get("difficulty", -1)
            if 0.3 <= d <= 0.8:
                frontier.append(t)
        if not frontier:
            frontier = task_pool[:3]

        test_tasks = [t["description"] for t in frontier[:3]]

        # Step 4: 运行测试收集轨迹
        _emit(f"[Iter {iteration+1}] [4/9] Running tests...")

        session_paths = []
        failed_tasks = []
        for task in test_tasks:
            from config import CONFIG as _cfg
            harness_dir = Path(_cfg["harness_template_repository"]) / target_harness
            identity_dir = Path(_cfg["identity_repository"]) / target_identity
            score = _run_single_task(harness_dir, identity_dir, task)
            if score < 0.8:  # 提高阈值：0.8以下都认为有改进空间
                failed_tasks.append(task)

        # Step 5: 提炼原则（如果有session路径）
        _emit(f"[Iter {iteration+1}] [5/9] Distilling principles...")
        # 使用最近的 session 目录（如果存在）
        sessions_dir = PROJECT_ROOT / "sessions"
        if sessions_dir.exists():
            session_dirs = sorted(sessions_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)
            for sd in session_dirs[:2]:
                if (sd / "messages.json").exists():
                    new_principles = distill_principles(str(sd))
                    session_paths.append(str(sd))
                    if new_principles:
                        _emit(f"[Iter {iteration+1}] Distilled {len(new_principles)} principles")
                    break

        # Step 6: 计算文本梯度
        _emit(f"[Iter {iteration+1}] [6/9] Computing text gradients...")

        gradient = ""
        if failed_tasks:
            identity_dir = Path(CONFIG["identity_repository"]) / target_identity
            id_file = identity_dir / "id.json"
            current_prompt = ""
            if id_file.exists():
                id_data = json.loads(id_file.read_text(encoding="utf-8"))
                current_prompt = id_data.get("description", "")
                if not current_prompt:
                    # 用 fallback 构建的 prompt 作为 current_prompt
                    role = id_data.get("role", "assistant")
                    personality = id_data.get("personality", {})
                    tone = personality.get("tone", "helpful")
                    traits = personality.get("traits", [])
                    current_prompt = f"You are a {role}. Your style is {tone}. Traits: {', '.join(traits)}."

            # 生成真实失败响应用于梯度计算（而非伪造轨迹）
            pseudo_session = DATA_DIR / "_temp_session"
            pseudo_session.mkdir(parents=True, exist_ok=True)

            real_response = _llm_call([
                {"role": "system", "content": current_prompt},
                {"role": "user", "content": failed_tasks[0]},
            ], max_tokens=1024, temperature=0.3)

            pseudo_messages = [
                {"role": "user", "content": failed_tasks[0]},
                {"role": "assistant", "content": real_response[:1500] if real_response else "[Empty response]"},
            ]
            (pseudo_session / "messages.json").write_text(
                json.dumps(pseudo_messages, ensure_ascii=False), encoding="utf-8"
            )
            gradient = compute_text_gradient(str(pseudo_session), current_prompt)
            if verbose:
                print(f"       Gradient: {gradient[:100]}...")

        # Step 7: 创建快照并应用修改
        if verbose:
            print("[7/9] Applying modifications...")

        snap_id = snapshot(target_identity)
        action_desc = ""

        if gradient and "[LLM_ERROR]" not in gradient:
            # 优先修改 personality.tone（有实际内容），避免修改空的 description
            identity_dir_tmp = Path(CONFIG["identity_repository"]) / target_identity
            id_tmp = json.loads((identity_dir_tmp / "id.json").read_text(encoding="utf-8"))
            target_field = "description" if id_tmp.get("description", "") else "personality.tone"
            result = apply_gradient(target_identity, target_field, gradient)
            if result["success"]:
                action_desc = f"Updated description via text gradient"
                if verbose:
                    print(f"       Applied gradient to description")
            else:
                action_desc = "Gradient application failed"
        else:
            # 如果没有梯度，跳过本轮修改（不用低质量原则做盲目增强）
            action_desc = "No modifications applied (no gradient available)"

        iter_report["action"] = action_desc

        # Step 8: 门控决策
        if verbose:
            print("[8/9] Evaluating and gating...")

        new_score = evaluate(target_harness, target_identity, eval_tasks)
        iter_report["score_after"] = new_score

        # 门控（使用百分制）
        decision = gate_decision(current_score * 100, new_score * 100, threshold=5.0)
        iter_report["decision"] = decision

        if verbose:
            print(f"       Score: {current_score:.2f} → {new_score:.2f} | Decision: {decision}")

        if decision == "rollback":
            rollback(target_identity, snap_id)
            report["total_rollbacks"] += 1
            if verbose:
                print("       ⟲ Rolled back")
        elif decision == "reject":
            rollback(target_identity, snap_id)
            report["total_rejected"] += 1
            if verbose:
                print("       ✗ Rejected (rolled back)")
        else:
            current_score = new_score
            report["total_accepted"] += 1
            # 更新使用到的原则分数
            if 'principles' in dir() and principles:
                update_scores([p["id"] for p in principles], success=(new_score > current_score))
            if verbose:
                print("       ✓ Accepted")

        # Step 9: 记录到归档
        record_attempt({
            "target": f"{target_harness}/{target_identity}",
            "action": action_desc,
            "diff": gradient[:500] if gradient else "",
            "score_before": current_score,
            "score_after": new_score,
            "accepted": decision == "accept",
        })

        report["iterations"].append(iter_report)

    report["final_score"] = current_score

    if verbose:
        print(f"\n{'='*60}")
        print(f"  Evolution Cycle Complete")
        print(f"  Score: {report['initial_score']:.2f} → {report['final_score']:.2f}")
        print(f"  Accepted: {report['total_accepted']} | Rejected: {report['total_rejected']} | Rollbacks: {report['total_rollbacks']}")
        print(f"{'='*60}\n")

    # 保存报告
    report_file = DATA_DIR / f"report_{time.strftime('%Y%m%d_%H%M%S')}.json"
    _save_json(report_file, report)

    return report


# ============================================================
# 类接口包装（供技能调用）
# ============================================================

class PrincipleLibrary:
    """原则库的类接口包装。"""

    def retrieve(self, query: str, top_k: int = 3) -> List[Dict]:
        return retrieve_principles(query, top_k)

    def distill(self, session_path: str) -> List[Dict]:
        return distill_principles(session_path)

    def update(self, principle_ids: List[str], success: bool):
        update_scores(principle_ids, success)


class EvolutionArchive:
    """进化归档的类接口包装。"""

    def get_history(self, target: str, limit: int = 10) -> List[Dict]:
        return get_history(target, limit)

    def record(self, entry: Dict) -> str:
        return record_attempt(entry)

    def get_best(self, target: str) -> List[Dict]:
        return get_best_configs(target)


class SelfEvolutionEngine:
    """自进化引擎的类接口包装。"""

    def run_evolution_cycle(self, target_harness: str, target_identity: str,
                           max_tasks: int = 3, max_iterations: int = 3) -> Dict:
        return run_evolution_cycle(
            target_harness=target_harness,
            target_identity=target_identity,
            max_iterations=max_iterations,
            verbose=False,
        )


# ============================================================
# CLI 入口
# ============================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Self-Evolution Engine for EgoAgent")
    parser.add_argument("--harness", default="react_single", help="Target harness name")
    parser.add_argument("--identity", default="dante", help="Target identity name")
    parser.add_argument("--iterations", type=int, default=5, help="Max evolution iterations")
    parser.add_argument("--quiet", action="store_true", help="Suppress verbose output")

    args = parser.parse_args()

    run_evolution_cycle(
        target_harness=args.harness,
        target_identity=args.identity,
        max_iterations=args.iterations,
        verbose=not args.quiet,
    )
