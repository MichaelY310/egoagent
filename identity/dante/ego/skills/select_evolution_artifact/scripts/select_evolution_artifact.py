from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[6]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from self_evolution.proof_evolution import select_evolution_artifact as _select  # noqa: E402


def select_evolution_artifact(candidates, minimum_utility: float = 0.08):
    """Return an auditable economic ranking without performing a mutation."""
    try:
        result = _select(candidates or [], minimum_utility=float(minimum_utility))
        return json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2)
    except (TypeError, ValueError) as error:
        return json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False)
