"""Compatibility adapter for the pre-Blueprint Harness mutation tool."""

from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[6]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from harness_blueprint import BlueprintError, RevisionConflict, legacy_modify_harness  # noqa: E402


def modify_harness(harness_name: str, action: str, target: str, value: str):
    """Apply a legacy action through the validated, reversible Blueprint layer."""
    try:
        result = legacy_modify_harness(
            PROJECT_ROOT,
            harness_name,
            action,
            target,
            value,
            actor="identity:improver_agent:legacy_modify_harness",
        )
        return json.dumps(result, ensure_ascii=False, indent=2)
    except (BlueprintError, RevisionConflict, OSError, ValueError) as error:
        return json.dumps({"success": False, "error": str(error)}, ensure_ascii=False)
