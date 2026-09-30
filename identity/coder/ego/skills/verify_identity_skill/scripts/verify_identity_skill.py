from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from capability_registry import CapabilityRegistry


_SAFE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,79}$")


def _deep_subset(expected, actual):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and _deep_subset(value, actual[key])
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and expected == actual
    return expected == actual


def _decode_result(value):
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if stripped.startswith(("{", "[")):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass
    return value


def verify_identity_skill(skill_name: str, cases: list, _context=None):
    """Verify one current-Identity Skill without widening the workspace guard."""

    context = _context or {}
    agent = context.get("agent")
    if agent is None or not hasattr(agent, "activate_capability"):
        return json.dumps({"ok": False, "error": "current Agent runtime is unavailable"})
    if not _SAFE_NAME.fullmatch(str(skill_name or "")) or skill_name == "verify_identity_skill":
        return json.dumps({"ok": False, "error": "invalid skill_name"})
    if not isinstance(cases, list) or not 1 <= len(cases) <= 4:
        return json.dumps({"ok": False, "error": "cases must contain 1 to 4 acceptance cases"})

    project_root = Path(str(context.get("project_root") or Path(__file__).resolve().parents[6])).resolve()
    workspace = Path(str(context.get("workspace") or project_root)).resolve()
    identity_path = Path(str(context.get("identity_path") or agent.identity.identity_path)).resolve()
    allowed_root = (identity_path / "ego" / "skills").resolve()

    registry = CapabilityRegistry(project_root, workspace=workspace)
    registry.reindex()
    result = registry.search(
        skill_name,
        kinds=["skill", "tool"],
        limit=20,
        record_impressions=False,
        mode="lexical",
    )
    match = next(
        (item for item in result.get("results", []) if str(item.get("name")) == skill_name),
        None,
    )
    candidate = registry.get(str(match.get("id"))) if match else None
    if candidate and Path(str(candidate.get("path"))).resolve().parent != allowed_root:
        candidate = None
    if candidate is None:
        return json.dumps({"ok": False, "error": "Skill is not persisted under the current Identity"})

    activation = agent.activate_capability(str(candidate["id"]), registry=registry)
    if not activation.get("ok") or activation.get("kind") not in {"skill", "tool"}:
        return json.dumps({"ok": False, "error": "Skill could not be activated", "activation": activation})

    reports = []
    for index, case in enumerate(cases, start=1):
        if not isinstance(case, dict) or not isinstance(case.get("arguments"), dict):
            reports.append({"case": index, "ok": False, "error": "arguments must be an object"})
            continue
        call = {
            "id": f"verify_{uuid.uuid4().hex}",
            "type": "function",
            "function": {
                "name": skill_name,
                "arguments": json.dumps(case["arguments"], ensure_ascii=False),
            },
        }
        try:
            raw = agent.execute_tool_call(call, max_result_chars=12_000)
            decoded = _decode_result(raw)
            expected_error = str(case.get("expect_error_contains") or "")
            if expected_error:
                passed = expected_error.casefold() in str(raw).casefold()
            elif "expected_subset" in case:
                passed = _deep_subset(case.get("expected_subset"), decoded)
            else:
                passed = not (isinstance(decoded, dict) and decoded.get("ok") is False)
            reports.append({"case": index, "ok": passed, "result": decoded})
        except Exception as error:
            expected_error = str(case.get("expect_error_contains") or "")
            reports.append({
                "case": index,
                "ok": bool(expected_error and expected_error.casefold() in str(error).casefold()),
                "error": str(error),
            })

    passed = bool(reports) and all(item.get("ok") for item in reports)
    return json.dumps({
        "ok": passed,
        "skill": skill_name,
        "capability_id": candidate["id"],
        "activation": activation,
        "cases": reports,
        "marker": "PASS" if passed else "FAIL",
    }, ensure_ascii=False)
