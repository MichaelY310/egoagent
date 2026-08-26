from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[6]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from capability_authoring import CapabilityAuthoringError, create_executable_skill  # noqa: E402


def create_skill(identity_name: str, skill_name: str, description: str,
                 parameters_schema, function_code: str):
    try:
        return json.dumps(create_executable_skill(
            PROJECT_ROOT,
            identity_name=identity_name,
            skill_name=skill_name,
            description=description,
            parameters_schema=parameters_schema,
            function_code=function_code,
        ), ensure_ascii=False, indent=2)
    except (CapabilityAuthoringError, OSError) as error:
        return json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False)
