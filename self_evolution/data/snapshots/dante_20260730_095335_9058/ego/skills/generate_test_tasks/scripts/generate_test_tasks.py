import json
from pathlib import Path


def generate_test_tasks(harness_name: str, category: str, count: int = 3):
    """Generate test tasks based on harness capabilities."""
    project_root = Path(__file__).resolve().parents[6]
    harness_dir = project_root / "harness" / harness_name
    config_path = harness_dir / "config.json"

    if not config_path.exists():
        return json.dumps({"error": f"Harness '{harness_name}' not found"})

    config = json.loads(config_path.read_text(encoding="utf-8"))
    harness_desc = config.get("description", "")
    slots = config.get("slots", {})

    # Determine what agents/tools are typically available
    # by checking the first slot's typical identity
    slot_names = list(slots.keys())
    
    # Task templates by category
    task_templates = {
        "tool_usage": [
            "List all available identities and describe what each one does.",
            "Read the file at identity/dante/id.json and summarize the agent's configuration.",
            "Search for files containing 'pipeline' in the harness/ directory.",
            "Create a new knowledge file for dante identity about Python best practices.",
            "List all harness templates and describe their pipeline structures.",
        ],
        "reasoning": [
            "Explain the difference between the react_single and coder_react harness templates based on their configs.",
            "Analyze what would happen if a harness pipeline had a cycle with no exit condition.",
            "Given that dante has 18+ tools, suggest which tools are most important and which could be removed.",
            "Describe how you would design a harness for a code review workflow involving two agents.",
            "What are the pros and cons of high vs low temperature settings for a coding agent?",
        ],
        "multi_step": [
            "Create a new identity called 'analyst' with role 'data analyst', then verify it was created by listing identities.",
            "Read dante's superego config, identify its task_prompt, then modify it to add a rule about being concise.",
            "List all sessions, pick the one with the most messages, and evaluate it.",
            "Design a new harness called 'simple_qa' with a single agent slot and max 5 steps, then verify it exists.",
            "Copy the dante identity to 'dante_v2', then modify dante_v2's temperature to 0.3.",
        ],
        "error_recovery": [
            "Try to read a file that doesn't exist (nonexistent/path/file.txt) and gracefully handle the error.",
            "Attempt to modify an identity that doesn't exist called 'fake_agent' and explain what went wrong.",
            "Try to create a harness with an invalid pipeline (no start node) and explain the validation error.",
            "Search for the pattern 'xyzabc123' in the project - it won't be found. Report that clearly.",
            "Try to evaluate a session called 'nonexistent_session_12345' and handle the error appropriately.",
        ],
        "mixed": [
            "List identities, then pick one and read its configuration, then suggest improvements to its task_prompt.",
            "Evaluate the most recent session and write a brief report about agent performance.",
            "Design a simple 2-agent debate harness, then verify it was created correctly by reading its config.",
            "Read 3 different harness configs and create a comparison table of their features.",
            "Find all Python files in the skills directory that contain 'json.loads' and summarize what they do.",
        ],
    }

    tasks = task_templates.get(category, task_templates["mixed"])
    
    # Select tasks up to count
    selected = tasks[:min(count, len(tasks))]
    
    result = {
        "harness": harness_name,
        "harness_description": harness_desc,
        "category": category,
        "tasks": [
            {"id": i + 1, "task": t, "difficulty": "easy" if i < len(selected)//3 else "medium" if i < 2*len(selected)//3 else "hard"}
            for i, t in enumerate(selected)
        ],
    }
    return json.dumps(result, ensure_ascii=False, indent=2)
