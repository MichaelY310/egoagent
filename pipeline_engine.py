"""
声明式 Pipeline 引擎：基于有向条件图的通用数据流执行器。

核心理念：
  - 每个节点是一个操作（推理/处理工具/处理文字/执行工具/等待输入）
  - 每个节点有若干出边，标注条件
  - 引擎执行完一个节点后，根据当前数据状态匹配条件，沿着边走到下一个节点
  - 用户画什么图，引擎就跑什么图——没有预定义的"模式"

条件类型：
  - "input"           用户已输入
  - "has_tool_calls"  上一步产生了 tool_calls
  - "no_tool_calls"   上一步没有 tool_calls
  - "has_text"        上一步产生了文本
  - "default"         兜底（总是匹配）
  - "expr:..."        表达式条件，eval 上下文中有 ctx 变量
  - "loop_done"       循环结束
  - "loop_continue"   循环体继续

节点类型：
  - "等待输入"    等待用户输入
  - "推理"        agent.step(messages) → text + tool_calls
  - "处理工具"     agent.process_tool_calls(tool_calls, ...) → allowed + blocked
  - "处理文字"     agent.process_text(text, ...) → processed_text
  - "执行工具"     执行当前 tool_calls
  - "脚本"        执行 Python 脚本
  - "llm_call"    独立 LLM 调用
  - "循环"        遍历列表
  - "子流程"      运行子 harness
"""

import json as _json
from pathlib import Path


def _resolve_template(template: str, context: dict) -> str:
    """Resolve ${ctx.var_name} in template strings"""
    import re
    def replacer(m):
        var_path = m.group(1)
        if var_path.startswith("ctx."):
            key = var_path[4:]
            val = context.get(key, "")
            return str(val) if not isinstance(val, str) else val
        return m.group(0)
    return re.sub(r'\$\{([^}]+)\}', replacer, template)


def _standalone_llm_call(prompt, harness, max_tokens=2048, temperature=0.7):
    """Make a standalone LLM call using the harness's agent or fallback to HTTP."""
    agent = _get_main_agent(harness)
    if agent and hasattr(agent, 'llm'):
        result = agent.llm.chat([{"role": "user", "content": prompt}], max_tokens=max_tokens, temperature=temperature)
        content = result["choices"][0]["message"].get("content", "")
        if "</think>" in content:
            content = content.split("</think>")[-1].strip()
        elif "<think>" in content:
            content = ""
        return content
    # Fallback: direct HTTP
    import requests
    try:
        resp = requests.post(
            "http://[fdbd:dc05:10:10a::27]:9638/v1/chat/completions",
            json={"model": "Qwen3-8B-yangyuan", "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens, "temperature": temperature},
            timeout=120
        )
        content = resp.json()["choices"][0]["message"].get("content", "")
        if "</think>" in content:
            content = content.split("</think>")[-1].strip()
        elif "<think>" in content:
            content = ""
        return content
    except Exception:
        return ""


def run_pipeline(harness):
    """终端交互版本：使用 print/input"""
    graph = harness.config["pipeline"]
    nodes = graph["nodes"]
    current = graph["start"]
    max_steps = graph.get("max_steps", 100)
    context = graph.get("context", {}).copy()
    workspace_preview = graph.get("workspace_preview", False)

    from harness import parse_user_tool_call, execute_user_tool_call

    tool_calls = None
    text = None
    step_count = 0
    _last_tool_signature = None  # For loop detection

    if workspace_preview and harness.workspace:
        _inject_workspace_preview(harness)

    while current is not None:
        if current not in nodes:
            raise ValueError(f"节点 '{current}' 未在 pipeline.nodes 中定义")

        node = nodes[current]
        op = node["op"]

        if op == "等待输入":
            # If session already has messages (e.g. initial_message injected), skip input
            if harness.session.messages and harness.session.messages[-1].get("role") == "user":
                current = _follow_edge(node, "input", context=context)
                continue
            # If this is a sub-harness (has parent) or non-interactive mode, don't block on input
            if harness.parent or getattr(harness, '_non_interactive', False):
                return
            while True:
                try:
                    user_input = input(">>> ")
                except EOFError:
                    print()
                    return
                if user_input.strip().lower() in ("exit", "quit", "q"):
                    return
                if not user_input.strip():
                    continue

                main_agent = _get_main_agent(harness)
                parsed = parse_user_tool_call(user_input)
                if parsed:
                    tool_name, arguments = parsed
                    print(f"[user-tool] 调用 {tool_name}({arguments})")
                    result = execute_user_tool_call(harness, main_agent, tool_name, arguments)
                    print(f"[user-tool] 结果:\n{result if result else '(empty)'}")
                    continue

                harness.session.record({"role": "user", "content": user_input})
                harness.session.record_full({"role": "user", "content": user_input})
                break

            current = _follow_edge(node, "input", context=context)

        elif op == "推理":
            if step_count >= max_steps:
                print(f"[Warning] Reached max steps ({max_steps}), stopping.")
                return

            agent = harness.agents[node["agent"]]
            agent_label = _agent_label(agent)
            print(f"\n{agent_label} ", end="", flush=True)
            # Check if this node has a has_tool_calls edge
            has_tc_edge = any(e.get("condition") == "has_tool_calls" for e in node.get("edges", []))
            # If no tool_calls edge, don't pass tools to prevent model from calling tools
            if has_tc_edge:
                text, tool_calls = agent.step(harness.session.messages)
            else:
                text, tool_calls = agent.step(harness.session.messages, tools_desc="")
            step_count += 1

            # Loop detection: if same tool_calls as last time, inject error
            if tool_calls and has_tc_edge:
                sig = _json.dumps([(tc["function"]["name"], tc["function"]["arguments"]) for tc in tool_calls], sort_keys=True)
                if sig == _last_tool_signature:
                    print(f"  [loop-detect] Repeated tool call, injecting error.")
                    for tc in tool_calls:
                        err_msg = {
                            "role": "user",
                            "content": f'<tool_response>{{"tool": "{tc["function"]["name"]}", "content": "Error: You already called this with identical arguments. You MUST now summarize your findings and respond to the user directly."}}</tool_response>'
                        }
                        harness.session.record(err_msg)
                        harness.session.record_full(err_msg)
                    tool_calls = None
                    _last_tool_signature = None  # Reset so next iteration can detect new loops
                    # Force re-infer: don't reassign `current` — stays on infer node for retry
                else:
                    _last_tool_signature = sig
                    current = _follow_edge(node, "has_tool_calls", "default", context=context)
            elif text or (tool_calls and not has_tc_edge):
                # If node has no tool_calls edge, treat any output (even tool_calls) as text
                _last_tool_signature = None
                current = _follow_edge(node, "has_text", "default", context=context)
            else:
                _last_tool_signature = None
                current = _follow_edge(node, "default", context=context)

        elif op == "处理工具":
            if not tool_calls:
                current = _follow_edge(node, "default", context=context)
                continue

            agent = harness.agents[node["agent"]]
            agent_label = _agent_label(agent)
            prompt_name = node.get("prompt")
            prompt_template = harness.prompts.get(prompt_name) if prompt_name else None
            allowed, blocked = agent.process_tool_calls(
                tool_calls, harness.session.messages, prompt_template
            )

            for tc, reason in blocked:
                blocked_msg = f"[BLOCKED by {agent.name}] {reason}"
                tool_name_b = tc["function"]["name"]
                tool_msg = {
                    "role": "user",
                    "content": (
                        f'<tool_response>'
                        f'{{"tool": "{tool_name_b}", "status": "blocked", '
                        f'"content": {_json.dumps(blocked_msg, ensure_ascii=False)}}}'
                        f'</tool_response>'
                    ),
                }
                harness.session.record(tool_msg)
                harness.session.record_full(tool_msg)
                print(f"  {agent_label} [blocked] {tool_name_b} -> {blocked_msg}")

            tool_calls = allowed
            current = _follow_edge(node, "default", context=context)

        elif op == "处理文字":
            if not text:
                current = _follow_edge(node, "default", context=context)
                continue

            agent = harness.agents[node["agent"]]
            prompt_name = node.get("prompt")
            prompt_template = harness.prompts.get(prompt_name) if prompt_name else None
            text = agent.process_text(text, harness.session.messages, prompt_template)

            harness.session.record({
                "role": "assistant", "name": agent.name,
                "content": text, "_op": "process_text",
            })
            harness.session.record_full({
                "role": "assistant", "name": agent.name,
                "content": text, "_op": "process_text",
            })

            if tool_calls:
                current = _follow_edge(node, "has_tool_calls", "default", context=context)
            else:
                current = _follow_edge(node, "default", context=context)

        elif op == "执行工具":
            exec_agent_name = node.get("agent")
            exec_agent = harness.agents.get(exec_agent_name) if exec_agent_name else _get_main_agent(harness)

            if tool_calls:
                from harness import EndSession
                for tc in tool_calls:
                    try:
                        result = exec_agent.execute_tool_call(tc)
                    except EndSession as e:
                        print(f"  [end_session] {str(e)[:100]}")
                        harness.session.record({"role": "assistant", "content": str(e)})
                        harness.session.record_full({"role": "assistant", "content": str(e)})
                        return
                    preview = result[:100] if result else "(empty)"
                    print(f"  [tool] {tc['function']['name']} -> {preview}")
                tool_calls = None

            current = _follow_edge(node, "default", context=context)

        elif op == "脚本":
            script_name = node.get("script")
            input_vars = node.get("input_vars", [])
            output_vars = node.get("output_vars", [])

            # Build local context from input_vars
            local_ctx = {k: context.get(k) for k in input_vars}

            # Load and exec script
            script_path = Path(harness.dir) / "scripts" / f"{script_name}.py"
            script_code = script_path.read_text(encoding="utf-8")
            script_ns = {"__file__": str(script_path)}
            exec(script_code, script_ns)
            result = script_ns["run"](local_ctx)

            # Write output_vars back to context
            if isinstance(result, dict):
                for k in output_vars:
                    if k in result:
                        context[k] = result[k]

            current = _follow_edge(node, "default", context=context)

        elif op == "llm_call":
            prompt_name = node.get("prompt")
            input_vars = node.get("input_vars", [])
            output_var = node.get("output_var", "_llm_result")
            parse_as = node.get("parse_as", "text")

            # Get prompt template and format it
            prompt_template = harness.prompts.get(prompt_name, "")
            format_vars = {k: context.get(k, "") for k in input_vars}
            formatted_prompt = prompt_template.format(**format_vars)

            # Call LLM
            response = _standalone_llm_call(formatted_prompt, harness)

            # Parse response
            if parse_as == "json":
                try:
                    response = _json.loads(response)
                except (ValueError, TypeError):
                    pass

            context[output_var] = response
            current = _follow_edge(node, "default", context=context)

        elif op == "循环":
            list_var = node.get("list_var", "")
            item_var = node.get("item_var", "_item")
            counter_var = node.get("counter_var", "_i")
            body_start = node.get("body_start")
            max_count = node.get("max_count", 100)

            items = context.get(list_var, [])
            if not isinstance(items, list):
                items = []

            # Check if we're returning from a loop body (loop state exists for this node)
            loop_stack = context.setdefault("_loop_stack", [])
            loop_state = None
            if loop_stack and loop_stack[-1].get("loop_node") == current:
                loop_state = loop_stack[-1]

            if loop_state is None:
                # First entry: initialize
                loop_state = {"loop_node": current, "index": 0, "list_var": list_var, "item_var": item_var, "counter_var": counter_var, "max_count": max_count, "results": []}
                loop_stack.append(loop_state)
            else:
                # Returning from body: collect result if any, increment
                if context.get("_loop_result") is not None:
                    loop_state["results"].append(context.pop("_loop_result"))
                loop_state["index"] += 1

            idx = loop_state["index"]
            if idx < len(items) and idx < max_count:
                context[item_var] = items[idx]
                context[counter_var] = idx
                current = body_start
            else:
                # Loop done
                context[f"{list_var}_results"] = loop_state["results"]
                loop_stack.pop()
                current = _follow_edge(node, "loop_done", "default", context=context)

        elif op == "子流程":
            from harness import Harness, set_current_harness, get_current_harness
            from agent import Agent
            from config import CONFIG

            sub_harness_name = _resolve_template(node.get("harness", ""), context)
            identity_map = node.get("identity_map", {})
            initial_msg_template = node.get("initial_message", "")
            output_var = node.get("output_var", "_sub_result")

            # Resolve template variables like ${ctx.current_task}
            initial_msg = _resolve_template(initial_msg_template, context)

            # Load sub-harness
            harness_dir = Path(CONFIG["harness_template_repository"]) / sub_harness_name
            sub_harness = Harness(harness_dir)

            # Assign agents
            for slot_name, identity_name in identity_map.items():
                id_name = _resolve_template(identity_name, context) if "${" in identity_name else identity_name
                identity_dir = Path(CONFIG["identity_repository"]) / id_name
                sub_agent = Agent(identity_dir)
                sub_harness.agents[slot_name] = sub_agent

            # Inject initial message
            if initial_msg:
                sub_harness.session.record({"role": "user", "content": initial_msg})
                sub_harness.session.record_full({"role": "user", "content": initial_msg})

            # Run non-interactively with proper harness context switching
            sub_harness._non_interactive = True
            parent_harness = get_current_harness()
            set_current_harness(sub_harness)
            try:
                run_pipeline(sub_harness)
            finally:
                set_current_harness(parent_harness)

            # Extract result (last assistant message)
            result = ""
            for msg in reversed(sub_harness.session.messages):
                if msg.get("role") == "assistant":
                    result = msg.get("content", "")
                    break

            context[output_var] = result
            current = _follow_edge(node, "default", context=context)

        else:
            raise ValueError(f"未知操作: {op} (节点 '{current}')")


def run_pipeline_stream(harness, on_output, get_input, is_running):
    """WebSocket 流式版本：通过回调与前端通信

    on_output(type, data): 输出回调
      type: "token"   — LLM 流式 token，data={"agent": "创意家", "text": "..."}
      type: "label"   — Agent 标签，data={"agent": "创意家"}
      type: "tool"    — 工具执行结果，data={"name": "ls", "result": "..."}
      type: "blocked" — 工具被拦截，data={"agent": "...", "tool": "...", "reason": "..."}
      type: "done"    — 执行完成
      type: "error"   — 错误，data={"message": "..."}

    get_input(): 阻塞等待用户输入，返回字符串或 None（停止）

    is_running(): 返回是否应该继续执行
    """
    graph = harness.config["pipeline"]
    nodes = graph["nodes"]
    current = graph["start"]
    max_steps = graph.get("max_steps", 100)
    context = graph.get("context", {}).copy()
    workspace_preview = graph.get("workspace_preview", False)

    from harness import parse_user_tool_call, execute_user_tool_call

    tool_calls = None
    text = None
    step_count = 0
    _last_tool_signature = None  # For loop detection

    if workspace_preview and harness.workspace:
        _inject_workspace_preview(harness)

    while current is not None and is_running():
        if current not in nodes:
            on_output("error", {"message": f"节点 '{current}' 未在 pipeline.nodes 中定义"})
            return

        node = nodes[current]
        op = node["op"]

        on_output("node_enter", {"node_id": current, "agent": node.get("agent", "")})

        if op == "等待输入":
            # If session already has messages (e.g. initial_message injected), skip input
            if harness.session.messages and harness.session.messages[-1].get("role") == "user":
                current = _follow_edge(node, "input", context=context)
                continue
            on_output("label", {"agent": "system", "text": f"⏳ 等待输入 (节点: {current})"})
            while is_running():
                user_input = get_input()
                print(f"[pipeline] 等待输入 get_input() returned: {repr(user_input)}")
                if user_input is None:
                    print("[pipeline] 等待输入 got None, returning")
                    return
                if user_input.strip().lower() in ("exit", "quit", "q"):
                    on_output("done", {})
                    return
                if not user_input.strip():
                    continue

                main_agent = _get_main_agent(harness)
                parsed = parse_user_tool_call(user_input)
                if parsed:
                    tool_name, arguments = parsed
                    on_output("tool", {"name": f"[user] {tool_name}", "result": f"调用 {tool_name}({arguments})"})
                    result = execute_user_tool_call(harness, main_agent, tool_name, arguments)
                    on_output("tool", {"name": f"[user] {tool_name}", "result": result if result else "(empty)"})
                    continue

                harness.session.record({"role": "user", "content": user_input})
                harness.session.record_full({"role": "user", "content": user_input})
                print(f"[pipeline] 等待输入 recorded user input, breaking to follow edge")
                break

            current = _follow_edge(node, "input", context=context)

        elif op == "推理":
            if step_count >= max_steps:
                on_output("error", {"message": f"达到最大步数 ({max_steps})"})
                return

            agent = harness.agents[node["agent"]]
            slot_name = node["agent"]
            on_output("label", {"agent": slot_name})

            def on_token(token_text):
                if not is_running():
                    raise InterruptedError("执行已停止")
                on_output("token", {"agent": slot_name, "text": token_text})

            text, tool_calls = agent.step(harness.session.messages, on_token=on_token)
            if not is_running():
                return  # 被停止，直接退出
            step_count += 1

            # Loop detection
            # Check if this node has a has_tool_calls edge; if not, ignore tool_calls
            has_tc_edge = any(e.get("condition") == "has_tool_calls" for e in node.get("edges", []))
            if tool_calls and has_tc_edge:
                sig = _json.dumps([(tc["function"]["name"], tc["function"]["arguments"]) for tc in tool_calls], sort_keys=True)
                if sig == _last_tool_signature:
                    for tc in tool_calls:
                        err_msg = {
                            "role": "user",
                            "content": f'<tool_response>{{"tool": "{tc["function"]["name"]}", "content": "Error: You already called this with identical arguments. You MUST now summarize your findings and respond to the user directly."}}</tool_response>'
                        }
                        harness.session.record(err_msg)
                        harness.session.record_full(err_msg)
                    tool_calls = None
                    _last_tool_signature = None  # Reset so next iteration can detect new loops
                    # Force re-infer: don't reassign `current` — stays on infer node for retry
                else:
                    _last_tool_signature = sig
                    current = _follow_edge(node, "has_tool_calls", "default", context=context)
            elif text or (tool_calls and not has_tc_edge):
                # If node has no tool_calls edge, treat any output (even tool_calls) as text
                _last_tool_signature = None
                current = _follow_edge(node, "has_text", "default", context=context)
            else:
                _last_tool_signature = None
                current = _follow_edge(node, "default", context=context)

        elif op == "处理工具":
            if not tool_calls:
                current = _follow_edge(node, "default", context=context)
                continue

            agent = harness.agents[node["agent"]]
            slot_name = node["agent"]
            prompt_name = node.get("prompt")
            prompt_template = harness.prompts.get(prompt_name) if prompt_name else None
            allowed, blocked = agent.process_tool_calls(
                tool_calls, harness.session.messages, prompt_template
            )

            for tc, reason in blocked:
                tool_name_b = tc["function"]["name"]
                blocked_msg = f"[BLOCKED by {slot_name}] {reason}"
                tool_msg = {
                    "role": "user",
                    "content": (
                        f'<tool_response>'
                        f'{{"tool": "{tool_name_b}", "status": "blocked", '
                        f'"content": {_json.dumps(blocked_msg, ensure_ascii=False)}}}'
                        f'</tool_response>'
                    ),
                }
                harness.session.record(tool_msg)
                harness.session.record_full(tool_msg)
                on_output("blocked", {"agent": slot_name, "tool": tool_name_b, "reason": reason})

            tool_calls = allowed
            current = _follow_edge(node, "default", context=context)

        elif op == "处理文字":
            if not text:
                current = _follow_edge(node, "default", context=context)
                continue

            agent = harness.agents[node["agent"]]
            prompt_name = node.get("prompt")
            prompt_template = harness.prompts.get(prompt_name) if prompt_name else None
            text = agent.process_text(text, harness.session.messages, prompt_template)

            harness.session.record({
                "role": "assistant", "name": agent.name,
                "content": text, "_op": "process_text",
            })
            harness.session.record_full({
                "role": "assistant", "name": agent.name,
                "content": text, "_op": "process_text",
            })

            current = _follow_edge(node, "default", context=context)

        elif op == "执行工具":
            exec_agent_name = node.get("agent")
            exec_agent = harness.agents.get(exec_agent_name) if exec_agent_name else _get_main_agent(harness)

            if tool_calls:
                from harness import EndSession
                for tc in tool_calls:
                    try:
                        result = exec_agent.execute_tool_call(tc)
                    except EndSession as e:
                        on_output("token", {"agent": exec_agent_name or "", "text": str(e)})
                        harness.session.record({"role": "assistant", "content": str(e)})
                        harness.session.record_full({"role": "assistant", "content": str(e)})
                        on_output("done", {})
                        return
                    preview = result[:200] if result else "(empty)"
                    on_output("tool", {"name": tc["function"]["name"], "result": preview, "agent": exec_agent_name})
                tool_calls = None

            current = _follow_edge(node, "default", context=context)

        elif op == "脚本":
            script_name = node.get("script")
            input_vars = node.get("input_vars", [])
            output_vars = node.get("output_vars", [])

            # Build local context from input_vars
            local_ctx = {k: context.get(k) for k in input_vars}

            # Load and exec script
            script_path = Path(harness.dir) / "scripts" / f"{script_name}.py"
            script_code = script_path.read_text(encoding="utf-8")
            script_ns = {"__file__": str(script_path)}
            exec(script_code, script_ns)
            result = script_ns["run"](local_ctx)

            # Write output_vars back to context
            if isinstance(result, dict):
                for k in output_vars:
                    if k in result:
                        context[k] = result[k]

            preview = str(result)[:200]
            on_output("script", {"name": script_name, "result": preview})
            current = _follow_edge(node, "default", context=context)

        elif op == "llm_call":
            prompt_name = node.get("prompt")
            input_vars = node.get("input_vars", [])
            output_var = node.get("output_var", "_llm_result")
            parse_as = node.get("parse_as", "text")

            # Get prompt template and format it
            prompt_template = harness.prompts.get(prompt_name, "")
            format_vars = {k: context.get(k, "") for k in input_vars}
            formatted_prompt = prompt_template.format(**format_vars)

            # Call LLM
            response = _standalone_llm_call(formatted_prompt, harness)

            # Parse response
            if parse_as == "json":
                try:
                    response = _json.loads(response)
                except (ValueError, TypeError):
                    pass

            context[output_var] = response
            preview = str(response)[:200]
            on_output("llm_call", {"prompt": prompt_name, "result": preview})
            current = _follow_edge(node, "default", context=context)

        elif op == "循环":
            list_var = node.get("list_var", "")
            item_var = node.get("item_var", "_item")
            counter_var = node.get("counter_var", "_i")
            body_start = node.get("body_start")
            max_count = node.get("max_count", 100)

            items = context.get(list_var, [])
            if not isinstance(items, list):
                items = []

            # Check if we're returning from a loop body (loop state exists for this node)
            loop_stack = context.setdefault("_loop_stack", [])
            loop_state = None
            if loop_stack and loop_stack[-1].get("loop_node") == current:
                loop_state = loop_stack[-1]

            if loop_state is None:
                # First entry: initialize
                loop_state = {"loop_node": current, "index": 0, "list_var": list_var, "item_var": item_var, "counter_var": counter_var, "max_count": max_count, "results": []}
                loop_stack.append(loop_state)
            else:
                # Returning from body: collect result if any, increment
                if context.get("_loop_result") is not None:
                    loop_state["results"].append(context.pop("_loop_result"))
                loop_state["index"] += 1

            idx = loop_state["index"]
            if idx < len(items) and idx < max_count:
                context[item_var] = items[idx]
                context[counter_var] = idx
                on_output("loop", {"var": list_var, "index": idx, "total": len(items)})
                current = body_start
            else:
                # Loop done
                context[f"{list_var}_results"] = loop_state["results"]
                loop_stack.pop()
                current = _follow_edge(node, "loop_done", "default", context=context)

        elif op == "子流程":
            from harness import Harness, set_current_harness, get_current_harness
            from agent import Agent
            from config import CONFIG

            sub_harness_name = _resolve_template(node.get("harness", ""), context)
            identity_map = node.get("identity_map", {})
            initial_msg_template = node.get("initial_message", "")
            output_var = node.get("output_var", "_sub_result")

            # Resolve template variables like ${ctx.current_task}
            initial_msg = _resolve_template(initial_msg_template, context)

            # Load sub-harness
            harness_dir = Path(CONFIG["harness_template_repository"]) / sub_harness_name
            sub_harness = Harness(harness_dir)

            # Assign agents
            for slot_name, identity_name in identity_map.items():
                id_name = _resolve_template(identity_name, context) if "${" in identity_name else identity_name
                identity_dir = Path(CONFIG["identity_repository"]) / id_name
                sub_agent = Agent(identity_dir)
                sub_harness.agents[slot_name] = sub_agent

            # Inject initial message
            if initial_msg:
                sub_harness.session.record({"role": "user", "content": initial_msg})
                sub_harness.session.record_full({"role": "user", "content": initial_msg})

            # Run non-interactively with proper harness context switching
            sub_harness._non_interactive = True
            parent_harness = get_current_harness()
            set_current_harness(sub_harness)
            try:
                run_pipeline(sub_harness)
            finally:
                set_current_harness(parent_harness)

            # Extract result (last assistant message)
            result = ""
            for msg in reversed(sub_harness.session.messages):
                if msg.get("role") == "assistant":
                    result = msg.get("content", "")
                    break

            context[output_var] = result
            preview = str(result)[:200]
            on_output("sub_pipeline", {"harness": sub_harness_name, "result": preview})
            current = _follow_edge(node, "default", context=context)

        else:
            on_output("error", {"message": f"未知操作: {op} (节点 '{current}')"})
            return

    on_output("done", {})


def _follow_edge(node, *conditions, context=None):
    for edge in node.get("edges", []):
        cond = edge["condition"]
        if cond in conditions:
            return edge["to"]
        # Expression condition
        if cond.startswith("expr:") and context is not None:
            expr_str = cond[5:]
            try:
                if eval(expr_str, {"__builtins__": {}}, {"ctx": context}):
                    return edge["to"]
            except Exception:
                pass
    return None


def _get_main_agent(harness):
    if harness.agents:
        return list(harness.agents.values())[0]
    return None


def _inject_workspace_preview(harness):
    import os

    workspace_path = str(harness.workspace)
    try:
        top_items = sorted(os.listdir(workspace_path))[:30]
        dir_preview = "\n".join(
            f"  {'[dir] ' if os.path.isdir(os.path.join(workspace_path, x)) else '      '}{x}"
            for x in top_items
            if not x.startswith(".")
        )
    except Exception:
        dir_preview = "(unable to list)"
    workspace_msg = (
        f"[System] Working directory: {workspace_path}\n"
        f"Top-level contents:\n{dir_preview}"
    )
    harness.session.record({"role": "user", "content": workspace_msg})
    harness.session.record_full({"role": "user", "content": workspace_msg})


_AGENT_COLORS = {
    "创意家": "\033[95m",
    "批评家": "\033[91m",
    "裁判": "\033[93m",
    "正方": "\033[92m",
    "反方": "\033[91m",
    "guardian": "\033[94m",
    "worker": "\033[96m",
    "agent": "\033[96m",
    "coder": "\033[96m",
}
_RESET = "\033[0m"


def _agent_label(agent):
    name = agent.name
    color = _AGENT_COLORS.get(name, "\033[96m")
    return f"{color}[{name}]{_RESET}"
