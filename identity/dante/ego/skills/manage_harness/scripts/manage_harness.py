"""Model-facing adapter for the constrained Harness Blueprint service."""

from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[6]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from harness_blueprint import (  # noqa: E402
    BlueprintError,
    HarnessBlueprintService,
    RevisionConflict,
    blueprint_guide,
)
from dag_contracts import dag_contract_catalog  # noqa: E402


def _compact(result):
    """Keep tool observations useful without duplicating the full config."""
    value = dict(result)
    value.pop("config", None)
    diff = value.get("diff")
    if isinstance(diff, str) and len(diff) > 12000:
        value["diff"] = diff[:12000] + "\n... diff truncated; inspect the Harness for the full result"
    return value


def manage_harness(
    action: str,
    harness_name: str = None,
    blueprint: dict = None,
    operations: list = None,
    expected_revision: str = None,
    transaction_id: str = None,
    reason: str = "",
    dry_run: bool = False,
    node_type: str = None,
):
    service = HarnessBlueprintService(PROJECT_ROOT)
    try:
        if action == "guide":
            result = {"ok": True, "guide": blueprint_guide()}
        elif action == "contract":
            catalog = dag_contract_catalog()
            if node_type:
                contract = catalog["nodes"].get(node_type)
                if contract is None:
                    raise BlueprintError(f"unknown node type: {node_type}")
                result = {"ok": True, "version": catalog["version"], "node_type": node_type, "contract": contract, "references": catalog["references"]}
            else:
                result = {"ok": True, "version": catalog["version"], "node_types": sorted(catalog["nodes"]), "references": catalog["references"]}
        elif action == "inspect":
            result = service.load(harness_name or "")
            result.pop("config", None)
            result["ok"] = True
        elif action == "validate":
            result = service.validate(blueprint or {}, name=harness_name)
        elif action == "create":
            result = service.create(blueprint or {}, dry_run=bool(dry_run))
        elif action == "patch":
            if not expected_revision:
                raise BlueprintError("patch requires expected_revision from a fresh inspect")
            result = service.patch(
                harness_name or "",
                operations or [],
                expected_revision=expected_revision,
                dry_run=bool(dry_run),
                reason=reason,
                actor="identity:dante",
            )
        elif action == "rollback":
            result = service.rollback(transaction_id or "", expected_revision=expected_revision)
        else:
            raise BlueprintError(f"unknown action: {action}")
        return json.dumps(_compact(result), ensure_ascii=False, indent=2)
    except (BlueprintError, RevisionConflict, OSError, ValueError) as error:
        return json.dumps({"ok": False, "error": str(error), "action": action}, ensure_ascii=False)
