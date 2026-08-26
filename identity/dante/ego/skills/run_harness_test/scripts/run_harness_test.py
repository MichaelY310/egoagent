import json
import os
import sys
import re
from pathlib import Path


def run_harness_test(harness_name: str, agent_identity: str, task: str, max_steps: int = 10,
                     _context: dict = None):
    """Run a harness with a task and return structured evaluation."""
    project_root = Path(__file__).resolve().parents[6]
    
    harness_dir = project_root / "harness" / harness_name
    if not harness_dir.exists():
        return json.dumps({"error": f"Harness '{harness_name}' not found"})
    
    identity_dir = project_root / "identity" / agent_identity
    if not identity_dir.exists():
        return json.dumps({"error": f"Identity '{agent_identity}' not found"})
    
    # Import agent/harness modules
    sys.path.insert(0, str(project_root))
    try:
        from agent import Agent
        from harness import Harness, reset_current_harness, set_current_harness, get_current_harness
        
        # Determine which slot to fill
        config = json.loads((harness_dir / "config.json").read_text(encoding="utf-8"))
        slots = config.get("slots", {})
        
        # Find the first required slot (or first slot)
        slot_name = None
        for sn, sv in slots.items():
            if sv.get("required", False):
                slot_name = sn
                break
        if not slot_name and slots:
            slot_name = list(slots.keys())[0]
        
        if not slot_name:
            return json.dumps({"error": f"Harness '{harness_name}' has no slots defined"})
        
        # Create agent and harness
        workspace = Path(_context["workspace"]) if _context and _context.get("workspace") else None
        agent = Agent(str(identity_dir), name=slot_name, workspace=workspace)
        harness = Harness(str(harness_dir), agents={slot_name: agent}, workspace=workspace)
        harness._non_interactive = True
        
        # Override max_steps
        if hasattr(harness, 'config') and 'pipeline' in harness.config:
            harness.config['pipeline']['max_steps'] = max_steps
        
        # Save parent harness and set this as current
        parent = get_current_harness()
        harness_token = set_current_harness(harness)
        
        # Inject task
        msg = {"role": "user", "content": task}
        harness.session.record(msg)
        harness.session.record_full(msg)
        
        # Run
        try:
            harness.run_func(harness)
        except Exception as run_err:
            pass
        finally:
            reset_current_harness(harness_token)
        
        # Evaluate results
        messages = harness.session.messages
        total_msgs = len(messages)
        assistant_msgs = [m for m in messages if m.get("role") == "assistant"]
        
        # Count tool calls
        tool_call_count = 0
        tool_names_used = []
        for m in assistant_msgs:
            content = m.get("content", "")
            if isinstance(content, str) and "<tool_call>" in content:
                tc_matches = re.findall(r'"name":\s*"([^"]+)"', content)
                tool_call_count += len(tc_matches)
                tool_names_used.extend(tc_matches)
        
        # Check for errors
        errors = []
        for m in messages:
            content = m.get("content", "")
            if isinstance(content, str) and "<tool_response>" in content:
                if "error" in content.lower() or "Error" in content:
                    errors.append(content[:150])
        
        # Check task completion
        completed = False
        final_response = ""
        if messages and messages[-1].get("role") == "assistant":
            last_content = messages[-1].get("content", "")
            if isinstance(last_content, str) and "<tool_call>" not in last_content:
                completed = True
                final_response = last_content[:500]
        
        # Compute score
        score = 100
        if errors:
            score -= min(40, len(errors) * 15)
        if not completed:
            score -= 30
        if tool_call_count > 5:
            score -= min(20, (tool_call_count - 5) * 5)
        # Reward efficient completion
        if completed and tool_call_count <= 3:
            score = min(100, score + 10)
        score = max(0, score)
        
        # Save session
        harness.session.save()
        
        result = {
            "success": completed,
            "score": score,
            "total_messages": total_msgs,
            "assistant_steps": len(assistant_msgs),
            "tool_calls": tool_call_count,
            "tools_used": list(set(tool_names_used)),
            "errors": errors[:5],
            "final_response": final_response,
            "session_dir": str(harness.session.save_dir) if hasattr(harness.session, 'save_dir') else "",
        }
        return json.dumps(result, ensure_ascii=False)
    
    except Exception as e:
        import traceback
        return json.dumps({"error": f"{type(e).__name__}: {str(e)}", "traceback": traceback.format_exc()[:500]})
    finally:
        if str(project_root) in sys.path:
            sys.path.remove(str(project_root))
