import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[6]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from capability_authoring import CapabilityAuthoringError, create_executable_skill  # noqa: E402


def create_tool(identity_name: str, tool_name: str, description: str,
                parameters_schema, function_code: str):
    """Compatibility alias: an executable Tool is persisted as a Skill package."""
    try:
        return json.dumps(create_executable_skill(
            PROJECT_ROOT,
            identity_name=identity_name,
            skill_name=tool_name,
            description=description,
            parameters_schema=parameters_schema,
            function_code=function_code,
        ), ensure_ascii=False, indent=2)
    except (CapabilityAuthoringError, OSError) as error:
        return json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False)
