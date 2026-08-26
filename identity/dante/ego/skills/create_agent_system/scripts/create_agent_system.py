from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[6]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from harness_editor.agent_creator import create_agent_from_description, create_agent_from_spec  # noqa: E402


def create_agent_system(description: str = "", name: str = None, spec: dict = None):
    try:
        result = create_agent_from_spec(spec, name) if isinstance(spec, dict) else create_agent_from_description(description, name)
        return json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2)
    except (OSError, ValueError) as error:
        return json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False)
