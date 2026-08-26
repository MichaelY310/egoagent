from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[6]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from self_evolution.capability_evolution import PACKS, CapabilityEvolutionError, CapabilityEvolutionService, analyze_evolution_need  # noqa: E402


def evolve_capabilities(action: str, identity_name: str = None, observations=None,
                        pack: str = None, workspace: str = "", dry_run: bool = False,
                        reason: str = "", transaction_id: str = None):
    service = CapabilityEvolutionService(PROJECT_ROOT)
    try:
        if action == "list":
            result = {"ok": True, "packs": PACKS}
        elif action == "analyze":
            result = analyze_evolution_need(observations, workspace=workspace)
        elif action == "inspect":
            result = service.inspect(identity_name or "")
        elif action == "install":
            result = service.install(identity_name or "", pack or "", dry_run=bool(dry_run), reason=reason)
        elif action == "rollback":
            result = service.rollback(transaction_id or "")
        else:
            raise CapabilityEvolutionError(f"unknown action: {action}")
        return json.dumps(result, ensure_ascii=False, indent=2)
    except (CapabilityEvolutionError, OSError, ValueError) as error:
        return json.dumps({"ok": False, "action": action, "error": str(error)}, ensure_ascii=False)
