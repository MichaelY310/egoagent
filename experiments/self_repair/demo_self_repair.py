"""
Self-Repair Demo: 端到端验证"自动检测格式错误 → 插入脚本补丁 → 监控效果 → 升级为 LLM 补丁"。

场景模拟:
  1. Agent 做数学题，被要求输出 <final_answer>42</final_answer> 格式
  2. 模拟 Agent 经常忘记加这个标签（或拼错）
  3. Self-Repair Engine 检测到这个 pattern
  4. 第一轮: 生成 regex 脚本补丁，插入 DAG
  5. 模拟 regex 补丁只修了 60% 的情况（有些 corner case 修不了）
  6. 第二轮: 引擎检测到效果不够，升级为 LLM 补丁

运行: python experiments/self_repair/demo_self_repair.py
"""

import sys
import json
import shutil
from pathlib import Path

# 添加项目根目录到 path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from self_evolution.self_repair import (
    SelfRepairEngine, FailureRecord, FailurePatternDetector,
    PatchGenerator, DAGPatcher, PatchMonitor
)


# ============================================================
# 模拟数据：Agent 做数学题的各种输出（有格式问题的）
# ============================================================

# 正确格式: 回答末尾应有 <final_answer>数字</final_answer>
EXPECTED_FORMAT = "<final_answer>ANSWER</final_answer>"

# 模拟 Agent 的各种错误输出
SIMULATED_RESPONSES_ROUND1 = [
    # --- 缺少标签 (最常见的问题) ---
    {
        "task": "What is 15 + 27?",
        "response": "Let me calculate: 15 + 27 = 42.\nThe answer is 42.",
        "error_type": "format_missing_tag",
        "details": "No <final_answer> tag found",
    },
    {
        "task": "What is 8 * 7?",
        "response": "8 times 7 equals 56.\nSo the result is 56.",
        "error_type": "format_missing_tag",
        "details": "No <final_answer> tag found",
    },
    {
        "task": "What is 100 - 37?",
        "response": "100 - 37 = 63",
        "error_type": "format_missing_tag",
        "details": "No <final_answer> tag found",
    },
    {
        "task": "What is 144 / 12?",
        "response": "To divide 144 by 12:\n144 ÷ 12 = 12\nThe answer is 12.",
        "error_type": "format_missing_tag",
        "details": "No <final_answer> tag found",
    },
    {
        "task": "What is 25 * 4?",
        "response": "25 * 4 = 100. Therefore, the answer is 100.",
        "error_type": "format_missing_tag",
        "details": "No <final_answer> tag found",
    },
    # --- 标签拼错 ---
    {
        "task": "What is 9 + 11?",
        "response": "9 + 11 = 20\n<final_anwser>20</final_anwser>",
        "error_type": "format_malformed",
        "details": "Misspelled tag: final_anwser instead of final_answer",
    },
    # --- 有一个是正确的（模拟不是100%错误）---
    {
        "task": "What is 3 + 4?",
        "response": "3 + 4 = 7\n<final_answer>7</final_answer>",
        "error_type": "none",  # 这个是正确的
        "details": "",
    },
]

# 第二轮：模拟 regex 补丁修不了的 corner cases
SIMULATED_RESPONSES_ROUND2_AFTER_REGEX_PATCH = [
    # --- regex 能修的（简单数字答案在最后一行）---
    {
        "task": "What is 5 + 3?",
        "response": "5 + 3 = 8\n<final_answer>8</final_answer>",  # regex 修好了
        "patched": True,
        "success": True,
    },
    {
        "task": "What is 10 * 2?",
        "response": "10 * 2 = 20\n<final_answer>20</final_answer>",  # regex 修好了
        "patched": True,
        "success": True,
    },
    # --- regex 修不了的（答案不是纯数字，或答案在中间）---
    {
        "task": "Is 7 a prime number?",
        "response": "Yes, 7 is a prime number because its only factors are 1 and 7.\nSo the answer is yes, it is prime.",
        "patched": True,
        "success": False,  # regex 找不到数字，补的标签内容不对
    },
    {
        "task": "What is the next number in the sequence 2, 4, 6, 8?",
        "response": "The sequence increases by 2 each time.\nThe next number is 10.\nBut we should also verify: 2+2=4, 4+2=6, 6+2=8, 8+2=10. Yes, 10 is correct.",
        "patched": True,
        "success": False,  # 答案在中间，regex 取了最后一个数字 10 但不确定
    },
    {
        "task": "What is 15% of 200?",
        "response": "15% of 200 = 0.15 × 200 = 30\nThe answer is thirty.",
        "patched": True,
        "success": False,  # 最后一行是 "thirty" 文字，regex 补了 "thirty" 而非 "30"
    },
]


def print_section(title: str):
    """打印分节标题"""
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}\n")


def print_dag(config: dict):
    """打印 DAG 结构（简化视图）"""
    nodes = config["pipeline"]["nodes"]
    start = config["pipeline"]["start"]
    print(f"  DAG Structure (start={start}, {len(nodes)} nodes):")
    for nid, node in nodes.items():
        op = node["op"]
        edges = node.get("edges", [])
        edge_str = " → ".join(f"[{e['condition']}]{e['to']}" for e in edges)
        meta = node.get("_patch_meta", {})
        patch_mark = " 🔧 PATCH" if meta else ""
        level_mark = f" (L{meta.get('level', '')})" if meta else ""
        print(f"    {nid}: [{op}]{patch_mark}{level_mark}  → {edge_str}")
    print()


def run_demo():
    """运行完整的 self-repair demo。"""

    print_section("Self-Repair Demo: 自动检测格式错误 → 补丁 → 监控 → 升级")
    print("场景: Agent 做数学题，需要输出 <final_answer>X</final_answer> 格式")
    print("问题: Agent 经常忘记加标签或拼错标签\n")

    # ============================================================
    # 准备工作：创建临时 harness
    # ============================================================
    demo_dir = PROJECT_ROOT / "experiments" / "self_repair" / "_demo_harness"
    if demo_dir.exists():
        shutil.rmtree(demo_dir)
    demo_dir.mkdir(parents=True)
    (demo_dir / "scripts").mkdir()

    # 初始 DAG：标准 react_single
    initial_config = {
        "name": "math_react",
        "description": "数学问答 Agent，ReAct 循环",
        "slots": {"agent": {"description": "Math solver agent", "required": True}},
        "return_mode": "all",
        "pipeline": {
            "start": "wait_input",
            "max_steps": 50,
            "nodes": {
                "wait_input": {
                    "op": "等待输入",
                    "edges": [{"condition": "input", "to": "infer"}]
                },
                "infer": {
                    "op": "推理",
                    "agent": "agent",
                    "edges": [
                        {"condition": "has_tool_calls", "to": "exec_tools"},
                        {"condition": "has_text", "to": "wait_input"}
                    ]
                },
                "exec_tools": {
                    "op": "执行工具",
                    "agent": "agent",
                    "edges": [{"condition": "default", "to": "infer"}]
                }
            }
        }
    }

    (demo_dir / "config.json").write_text(
        json.dumps(initial_config, indent=4, ensure_ascii=False), encoding="utf-8"
    )

    print("初始 DAG (标准 ReAct 循环):")
    print_dag(initial_config)

    # ============================================================
    # Phase 1: 运行 Agent，收集失败记录
    # ============================================================
    print_section("Phase 1: 运行 Agent，收集失败记录")
    print(f"模拟跑 {len(SIMULATED_RESPONSES_ROUND1)} 道数学题...\n")

    failure_records = []
    total_tasks = 0
    failures = 0

    for sim in SIMULATED_RESPONSES_ROUND1:
        total_tasks += 1
        has_tag = "<final_answer>" in sim["response"] and "</final_answer>" in sim["response"]

        if sim["error_type"] != "none":
            failures += 1
            failure_records.append(FailureRecord(
                task=sim["task"],
                response=sim["response"],
                expected_format=EXPECTED_FORMAT,
                error_type=sim["error_type"],
                details=sim["details"],
            ))
            print(f"  ✗ Task: {sim['task']}")
            print(f"    Response: {sim['response'][:80]}...")
            print(f"    Error: {sim['details']}")
            print()
        else:
            print(f"  ✓ Task: {sim['task']} (格式正确)")
            print()

    print(f"\n结果: {total_tasks} 题中 {failures} 题格式错误 ({failures/total_tasks*100:.0f}%)")

    # ============================================================
    # Phase 2: Self-Repair Engine 检测 pattern 并生成 L1 patch
    # ============================================================
    print_section("Phase 2: Self-Repair Engine 检测 pattern → 生成 L1 脚本补丁")

    engine = SelfRepairEngine(harness_dir=str(demo_dir))
    report = engine.run_repair_cycle(failure_records)

    print("检测到的 patterns:")
    for p in report["patterns_detected"]:
        print(f"  - [{p['type']}] {p['description']} (频率: {p['frequency']:.0%})")
    print()

    print("生成的 patches:")
    for p in report["patches_generated"]:
        print(f"  - {p['node_id']} (类型: {p['type']}, 级别: L{p['level']})")
    print()

    print("应用到 DAG 的 patches:")
    for p in report["patches_applied"]:
        print(f"  - {p}")
    print()

    # 展示修改后的 DAG
    patched_config = engine.load_config()
    print("修改后的 DAG:")
    print_dag(patched_config)

    # 展示生成的脚本
    scripts_dir = demo_dir / "scripts"
    for script_file in scripts_dir.iterdir():
        if script_file.suffix == ".py":
            print(f"生成的修复脚本 ({script_file.name}):")
            content = script_file.read_text(encoding="utf-8")
            # 只显示前 30 行
            lines = content.split("\n")[:30]
            for line in lines:
                print(f"    {line}")
            if len(content.split("\n")) > 30:
                print(f"    ... (共 {len(content.split(chr(10)))} 行)")
            print()

    # ============================================================
    # Phase 3: 模拟 L1 patch 的效果（部分成功部分失败）
    # ============================================================
    print_section("Phase 3: 模拟 L1 (regex) 补丁的效果")
    print("模拟跑第二轮任务，测试 regex 补丁的修复率...\n")

    # 找到我们应用的 patch ID
    patch_ids = list(engine.applied_patches.keys())
    main_patch_id = patch_ids[0] if patch_ids else "unknown"

    successes = 0
    total_r2 = len(SIMULATED_RESPONSES_ROUND2_AFTER_REGEX_PATCH)

    for sim in SIMULATED_RESPONSES_ROUND2_AFTER_REGEX_PATCH:
        is_success = sim["success"]
        # 记录到 monitor
        engine.monitor.record_result(main_patch_id, "pat_format_missing_tag", 1, is_success)
        if is_success:
            successes += 1
            print(f"  ✓ {sim['task']} → regex 补丁修复成功")
        else:
            print(f"  ✗ {sim['task']} → regex 补丁修复失败 (corner case)")

    success_rate = successes / total_r2
    print(f"\nL1 (regex) 补丁效果: {successes}/{total_r2} = {success_rate:.0%}")
    print(f"  escalation 阈值: {engine.monitor.escalation_threshold:.0%}")
    print(f"  需要升级: {'是' if success_rate < engine.monitor.escalation_threshold else '否'}")

    # ============================================================
    # Phase 4: 检测到效果不够 → 升级为 L2 (LLM) 补丁
    # ============================================================
    print_section("Phase 4: 效果不够 → 自动升级为 L2 (LLM) 补丁")

    # 检查是否需要升级
    should_escalate = engine.monitor.should_escalate(main_patch_id)
    print(f"Patch '{main_patch_id}' should escalate: {should_escalate}")

    if should_escalate:
        # 构造新一轮失败记录（来自 regex 修不了的 case）
        new_failures = [
            FailureRecord(
                task=sim["task"],
                response=sim["response"],
                expected_format=EXPECTED_FORMAT,
                error_type="format_missing_tag",
                details="Regex patch insufficient for this case",
            )
            for sim in SIMULATED_RESPONSES_ROUND2_AFTER_REGEX_PATCH
            if not sim["success"]
        ]

        # 运行第二轮修复循环（会触发升级）
        report2 = engine.run_repair_cycle(new_failures)

        print("\n升级报告:")
        for esc in report2.get("escalations", []):
            print(f"  {esc['old_patch']} (L{esc['old_level']}) → {esc['new_patch']} (L{esc['new_level']})")
            print(f"  原因: {esc['reason']}")
        print()

        # 展示升级后的 DAG
        final_config = engine.load_config()
        print("升级后的 DAG:")
        print_dag(final_config)

        # 展示 LLM prompt
        if "prompts" in final_config:
            print("LLM 补丁的 prompt 模板:")
            for name, prompt in final_config["prompts"].items():
                print(f"  [{name}]:")
                for line in prompt.split("\n")[:10]:
                    print(f"    {line}")
                print(f"    ...")
            print()

    # ============================================================
    # 总结
    # ============================================================
    print_section("总结: 自修复进化轨迹")
    print("""
    ┌─────────────────────────────────────────────────────────────┐
    │  Evolution Timeline                                         │
    ├─────────────────────────────────────────────────────────────┤
    │                                                             │
    │  Round 0: 原始 ReAct DAG                                    │
    │    wait_input → infer → wait_input                          │
    │    格式正确率: ~14% (1/7)                                    │
    │                                                             │
    │  Round 1: 检测到 format_missing_tag (频率 71%)              │
    │    → 自动生成 regex 脚本补丁                                 │
    │    → 插入 DAG: infer → [脚本patch] → wait_input             │
    │    格式正确率: ~40% (2/5)                                    │
    │                                                             │
    │  Round 2: regex 补丁效果不足 (< 80% 阈值)                   │
    │    → 自动升级为 LLM 补丁                                    │
    │    → 替换 DAG: infer → [llm_call patch] → wait_input        │
    │    预期格式正确率: ~95%+                                     │
    │                                                             │
    └─────────────────────────────────────────────────────────────┘

    关键创新点:
    1. 失败模式自动检测 (从散落的错误中识别出系统性问题)
    2. 渐进式修复 (先试成本低的 regex，不够再升级为 LLM)
    3. DAG 结构自动修改 (不只是改 prompt，而是插入新节点)
    4. Patch 节点带 mandatory 标记 (不会被后续进化删除)
    5. 效果闭环监控 (持续追踪，效果不够自动升级)
    """)

    # 清理
    print(f"\nDemo 文件保留在: {demo_dir}")
    print("可以查看 config.json 和 scripts/ 目录看到实际生成的 DAG 和脚本。")


if __name__ == "__main__":
    run_demo()
