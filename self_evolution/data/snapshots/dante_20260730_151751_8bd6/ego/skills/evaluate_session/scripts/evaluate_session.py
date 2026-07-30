import os
import re
import json


def evaluate_session(session_dir: str):
    """Analyze a completed session trajectory and return a structured report.
    
    Handles both formats:
    - Legacy XML format: <tool_call>{JSON}</tool_call> in assistant content,
      <tool_response>{JSON}</tool_response> in user content
    - Standard OpenAI format: tool_calls array in assistant msg, role=tool messages
    """
    from pathlib import Path
    project_root = Path(__file__).resolve().parents[6]
    
    if not session_dir:
        return json.dumps({"error": "session_dir is empty. Please provide a valid session directory path."})

    # Resolve relative paths against project root
    session_path = Path(session_dir)
    if not session_path.is_absolute():
        session_path = project_root / session_dir
    
    if not session_path.is_dir():
        return json.dumps({"error": f"Directory not found: '{session_dir}'. Resolved to: '{session_path}'. Check if the path is correct."})

    messages_path = session_path / "messages.json"
    if not messages_path.exists():
        return json.dumps({"error": f"messages.json not found in '{session_path}'."})

    try:
        with open(messages_path, "r", encoding="utf-8") as f:
            messages = json.load(f)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Failed to parse messages.json: {str(e)}"})
    except Exception as e:
        return json.dumps({"error": f"Failed to read messages.json: {str(e)}"})

    # Count messages by role
    total_messages = len(messages)
    assistant_messages = [m for m in messages if m.get("role") == "assistant"]
    user_messages = [m for m in messages if m.get("role") == "user"]
    steps = len(assistant_messages)

    # Extract tool calls from both formats
    tool_calls = []
    for m in assistant_messages:
        content = m.get("content", "")
        # Standard format: tool_calls array
        if "tool_calls" in m and m["tool_calls"]:
            for tc in m["tool_calls"]:
                func = tc.get("function", {})
                tool_calls.append({
                    "name": func.get("name", "unknown"),
                    "arguments": func.get("arguments", ""),
                })
        # Legacy XML format: <tool_call>{JSON}</tool_call>
        elif isinstance(content, str) and "<tool_call>" in content:
            tc_matches = re.findall(r'<tool_call>\s*(\{.*?\})\s*</tool_call>', content, re.DOTALL)
            for tc_json in tc_matches:
                try:
                    tc_data = json.loads(tc_json)
                    tool_calls.append({
                        "name": tc_data.get("name", "unknown"),
                        "arguments": json.dumps(tc_data.get("arguments", {}), ensure_ascii=False),
                    })
                except json.JSONDecodeError:
                    tool_calls.append({"name": "parse_error", "arguments": tc_json[:80]})

    total_tool_calls = len(tool_calls)

    # Detect repeated tool calls (same name + same arguments)
    seen = {}
    repeated_calls = []
    for tc in tool_calls:
        key = (tc["name"], tc["arguments"])
        if key in seen:
            seen[key] += 1
        else:
            seen[key] = 1

    for (name, args), count in seen.items():
        if count > 1:
            args_preview = args[:80] + "..." if len(args) > 80 else args
            repeated_calls.append({"name": name, "args_preview": args_preview, "count": count})

    # Check for tool errors in both formats
    tool_errors = []
    for m in messages:
        content = m.get("content", "")
        if not isinstance(content, str):
            continue
        # Standard format: role=tool
        if m.get("role") == "tool":
            if "error" in content.lower():
                tool_errors.append({
                    "tool_call_id": m.get("tool_call_id", "unknown"),
                    "error_preview": content[:120] + "..." if len(content) > 120 else content,
                })
        # Legacy format: <tool_response> in user messages
        elif m.get("role") == "user" and "<tool_response>" in content:
            tr_match = re.search(r'<tool_response>(.*?)</tool_response>', content, re.DOTALL)
            if tr_match:
                try:
                    tr_data = json.loads(tr_match.group(1))
                    tr_content = tr_data.get("content", "")
                    if isinstance(tr_content, str) and "error" in tr_content.lower():
                        tool_errors.append({
                            "tool_call_id": tr_data.get("tool", "unknown"),
                            "error_preview": tr_content[:120] + "..." if len(tr_content) > 120 else tr_content,
                        })
                except json.JSONDecodeError:
                    pass

    # Count tool response messages
    tool_response_count = sum(
        1 for m in messages
        if (m.get("role") == "tool") or
           (m.get("role") == "user" and "<tool_response>" in m.get("content", ""))
    )

    # Determine task completion
    task_completed = False
    if messages and messages[-1].get("role") == "assistant":
        last = messages[-1]
        has_content = bool(last.get("content"))
        # Check both formats for tool_calls
        has_tool_calls = bool(last.get("tool_calls"))
        if not has_tool_calls and isinstance(last.get("content", ""), str):
            has_tool_calls = "<tool_call>" in last.get("content", "")
        task_completed = has_content and not has_tool_calls

    # Build trajectory summary
    trajectory = []
    for m in messages:
        role = m.get("role", "unknown")
        content = m.get("content", "")
        if role == "assistant":
            # Standard format
            if m.get("tool_calls"):
                names = [tc.get("function", {}).get("name", "?") for tc in m["tool_calls"]]
                trajectory.append(f"assistant -> tool_call({', '.join(names)})")
            # Legacy format
            elif isinstance(content, str) and "<tool_call>" in content:
                tc_matches = re.findall(r'"name":\s*"([^"]+)"', content)
                trajectory.append(f"assistant -> tool_call({', '.join(tc_matches) if tc_matches else '?'})")
            elif content:
                content_preview = content[:60].replace("\n", " ")
                trajectory.append(f"assistant -> text: \"{content_preview}...\"")
        elif role == "user":
            if isinstance(content, str) and "<tool_response>" in content:
                tr_match = re.search(r'"tool":\s*"([^"]+)"', content)
                tool_name = tr_match.group(1) if tr_match else "?"
                trajectory.append(f"tool_result({tool_name})")
            else:
                preview = str(content)[:60].replace("\n", " ")
                trajectory.append(f"user: \"{preview}\"")
        elif role == "tool":
            trajectory.append(f"tool_result({m.get('tool_call_id', '?')[:12]})")

    # Limit trajectory summary length
    if len(trajectory) > 30:
        trajectory_summary = trajectory[:15] + [f"... ({len(trajectory) - 30} more steps) ..."] + trajectory[-15:]
    else:
        trajectory_summary = trajectory

    # Compute efficiency score (0-100)
    efficiency = 100
    if repeated_calls:
        efficiency -= min(30, len(repeated_calls) * 10)
    if tool_errors:
        efficiency -= min(30, len(tool_errors) * 10)
    if not task_completed:
        efficiency -= 20
    # Penalize excessive steps
    if total_tool_calls > 5:
        efficiency -= min(20, (total_tool_calls - 5) * 3)
    efficiency = max(0, efficiency)

    # Build report
    report_lines = [
        "=" * 60,
        "SESSION EVALUATION REPORT",
        "=" * 60,
        f"Directory: {session_dir}",
        "",
        "--- Statistics ---",
        f"Total messages: {total_messages}",
        f"  User messages: {len(user_messages)}",
        f"  Assistant steps: {steps}",
        f"  Tool calls: {total_tool_calls}",
        f"  Tool responses: {tool_response_count}",
        "",
        f"--- Task Completion ---",
        f"Completed: {'Yes' if task_completed else 'No'}",
        f"Efficiency score: {efficiency}/100",
        "",
    ]

    if repeated_calls:
        report_lines.append("--- Repeated Tool Calls (inefficiency) ---")
        for rc in repeated_calls:
            report_lines.append(f"  {rc['name']} x{rc['count']}: {rc['args_preview']}")
        report_lines.append("")
    else:
        report_lines.append("--- Repeated Tool Calls ---")
        report_lines.append("  None detected.")
        report_lines.append("")

    if tool_errors:
        report_lines.append(f"--- Tool Errors ({len(tool_errors)}) ---")
        for err in tool_errors[:10]:
            report_lines.append(f"  [{err['tool_call_id']}]: {err['error_preview']}")
        if len(tool_errors) > 10:
            report_lines.append(f"  ... and {len(tool_errors) - 10} more errors")
        report_lines.append("")
    else:
        report_lines.append("--- Tool Errors ---")
        report_lines.append("  None detected.")
        report_lines.append("")

    report_lines.append("--- Trajectory Summary ---")
    for step in trajectory_summary:
        report_lines.append(f"  {step}")
    report_lines.append("")
    report_lines.append("=" * 60)

    return "\n".join(report_lines)
