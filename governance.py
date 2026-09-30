"""Inspectable composition of Identity, Superego, Flow and workspace policy.

The runtime remains fail-closed by intersection: no lower layer may widen a
higher-level restriction.  This module exposes that composition to the UI so a
user does not need to infer effective behavior from four separate editors.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from permissions import RuntimePolicy
from security_settings import load_security_settings


MUTATION_SWITCHES = {
    "allow_create_agent", "allow_create_identity", "allow_modify_agent", "allow_modify_identity",
    "allow_add_skill_to_self", "allow_add_knowledge_to_self", "allow_add_skill_to_other",
    "allow_add_knowledge_to_other", "allow_add_tool_to_environment",
    "allow_add_knowledge_to_environment",
}

PROBES = [
    ("read", "read_file", {"file_path": "README.md"}, None, "tool_access"),
    ("write", "patch_file", {"file_path": "README.md", "patch": "preview"}, None, "tool_access"),
    ("process", "run_command", {"command": "python -m unittest", "cwd": "."}, None, "tool_access"),
    ("network", "web_search", {"query": "EgoAgent"}, None, "tool_access"),
    ("create Flow", "create_harness", {"name": "preview"}, "allow_create_agent", "tool_access"),
    ("modify Flow", "modify_harness", {"action": "apply"}, "allow_modify_agent", "tool_access"),
    ("create Identity", "create_identity", {"name": "preview"}, "allow_create_identity", "tool_access"),
    ("modify Identity", "modify_identity", {"identity_name": "self"}, "allow_modify_identity", "tool_access"),
    ("add own Skill", "create_skill", {"identity_name": "self"}, "allow_add_skill_to_self", "tool_access"),
    ("add own Knowledge", "create_knowledge", {"identity_name": "self"}, "allow_add_knowledge_to_self", "tool_access"),
]


class GovernanceError(ValueError):
    pass


def _short_name(value: object) -> str:
    return str(value or "").rsplit(":", 1)[-1]


def _matches_access_list(tool: str, values: Any) -> bool:
    if not isinstance(values, list):
        return False
    short = _short_name(tool)
    return any(
        str(item) == tool or str(item) == short or _short_name(item) == short
        for item in values
    )


def _superego_access_decision(resource: str, access: dict[str, Any], access_name: str) -> tuple[str, str]:
    whitelist = access.get("whitelist", []) if isinstance(access, dict) else []
    blacklist = access.get("blacklist", []) if isinstance(access, dict) else []
    if _matches_access_list(resource, blacklist):
        return "deny", f"{resource} matches the Superego {access_name} blacklist"
    if whitelist and not _matches_access_list(resource, whitelist):
        return "deny", f"{resource} is absent from the non-empty Superego {access_name} whitelist"
    return "allow", f"allowed by Superego {access_name}"


def _safe_component(root: Path, group: str, name: str, required: str) -> Path:
    name = str(name or "").strip()
    if not name or Path(name).name != name or name in {".", ".."}:
        raise GovernanceError(f"Invalid {group} name")
    path = (root / group / name).resolve()
    expected_root = (root / group).resolve()
    if expected_root != path and expected_root not in path.parents:
        raise GovernanceError(f"{group} path escapes repository")
    if not (path / required).is_file():
        raise GovernanceError(f"{group.title()} not found: {name}")
    return path


def inspect_governance(project_root: Path, harness: str, identity: str, mode: str = "agent") -> dict[str, Any]:
    root = Path(project_root).resolve()
    harness_dir = _safe_component(root, "harness", harness, "config.json")
    identity_dir = _safe_component(root, "identity", identity, "id.json")
    harness_config = json.loads((harness_dir / "config.json").read_text(encoding="utf-8"))
    id_config = json.loads((identity_dir / "id.json").read_text(encoding="utf-8"))
    sego_path = identity_dir / "superego" / "config.json"
    sego = json.loads(sego_path.read_text(encoding="utf-8")) if sego_path.is_file() else {}
    pipeline = harness_config.get("pipeline", {}) if isinstance(harness_config, dict) else {}
    graph_permissions = pipeline.get("permissions") if isinstance(pipeline, dict) else None
    security = load_security_settings(root)
    policy = RuntimePolicy.for_interactive_run(
        root, mode, graph_config=graph_permissions, security_settings=security,
        allow_global_mutation=str(mode).lower() == "evolve",
        mutation_targets=("agent", "harness", "identity", "skill", "knowledge") if str(mode).lower() == "evolve" else (),
    )
    explicit_mutation_contract = any(key in sego for key in MUTATION_SWITCHES)
    hooks = [
        name for name in ("pre_llm_hook", "post_llm_hook", "pre_tool_hook", "post_tool_hook")
        if (identity_dir / "superego" / f"{name}.py").is_file()
    ]
    review_nodes = [
        node_id for node_id, node in (pipeline.get("nodes", {}) or {}).items()
        if isinstance(node, dict) and str(node.get("op", "")) in {"工具审查", "人工审批", "审批"}
    ]
    model_nodes_with_rules = []
    for node_id, node in (pipeline.get("nodes", {}) or {}).items():
        if not isinstance(node, dict) or str(node.get("op", "")) not in {"模型", "Model"}:
            continue
        if any(str(node.get(key, "")).strip() for key in ("system_prompt", "prompt", "instructions")):
            model_nodes_with_rules.append(node_id)

    tool_access = sego.get("tool_access", {}) if isinstance(sego.get("tool_access"), dict) else {}
    knowledge_access = sego.get("knowledge_access", {}) if isinstance(sego.get("knowledge_access"), dict) else {}
    probes = list(PROBES)
    knowledge_root = identity_dir / "ego" / "knowledge"
    knowledge_names = sorted(path.name for path in knowledge_root.iterdir() if path.is_dir()) if knowledge_root.is_dir() else []
    if knowledge_names:
        knowledge_name = knowledge_names[0]
        probes.append((
            "read Knowledge", f"knowledge:{knowledge_name}", {"knowledge": knowledge_name}, None,
            "knowledge_access",
        ))
    matrix = []
    rank = {"allow": 0, "ask": 1, "deny": 2}
    for label, tool, arguments, switch, access_name in probes:
        decision = policy.evaluate_tool(tool, arguments)
        runtime_decision = decision.decision.value
        access = knowledge_access if access_name == "knowledge_access" else tool_access
        superego_decision, superego_reason = _superego_access_decision(tool, access, access_name)
        if switch and explicit_mutation_contract:
            mutation_decision = "allow" if bool(sego.get(switch, False)) else "deny"
            if rank[mutation_decision] > rank[superego_decision]:
                superego_decision = mutation_decision
            superego_reason += f"; {switch}={bool(sego.get(switch, False))}"
        elif switch:
            if superego_decision == "allow":
                superego_decision = "legacy"
            superego_reason += "; no explicit mutation switch contract; RuntimePolicy only"
        effective_candidates = [runtime_decision]
        if superego_decision in rank:
            effective_candidates.append(superego_decision)
        effective = max(effective_candidates, key=lambda value: rank[value])
        matrix.append({
            "capability": label, "tool": tool, "superego": superego_decision,
            "runtime": runtime_decision, "effective": effective,
            "superego_reason": superego_reason, "runtime_reason": decision.reason,
            "risk": decision.risk.public(),
        })

    conflicts: list[dict[str, str]] = []
    if sego and not explicit_mutation_contract:
        conflicts.append({
            "severity": "high", "code": "superego.legacy_mutation_contract",
            "message": "This Superego has no explicit mutation switches; reusable-object mutation is governed only by the Flow/runtime policy.",
        })
    overlap = sorted(set(tool_access.get("whitelist", [])) & set(tool_access.get("blacklist", [])))
    if overlap:
        conflicts.append({
            "severity": "high", "code": "superego.tool_list_overlap",
            "message": "Tools occur in both whitelist and blacklist: " + ", ".join(overlap),
        })
    knowledge_overlap = sorted(set(knowledge_access.get("whitelist", [])) & set(knowledge_access.get("blacklist", [])))
    if knowledge_overlap:
        conflicts.append({
            "severity": "high", "code": "superego.knowledge_list_overlap",
            "message": "Knowledge packages occur in both whitelist and blacklist: " + ", ".join(knowledge_overlap),
        })
    if hooks:
        conflicts.append({
            "severity": "medium", "code": "superego.imperative_hooks",
            "message": "Python hooks can change behavior outside the visible Flow: " + ", ".join(hooks),
        })
    if sego.get("task_prompt") and model_nodes_with_rules:
        conflicts.append({
            "severity": "medium", "code": "instructions.multiple_authorities",
            "message": "Behavioral instructions exist in both Superego and Model nodes: " + ", ".join(model_nodes_with_rules),
        })
    if review_nodes and graph_permissions:
        conflicts.append({
            "severity": "info", "code": "approval.two_stage",
            "message": "A visible workflow approval checkpoint and backend RuntimePolicy are both active. Approval may resume the Flow, but it cannot grant a tool call that RuntimePolicy denies.",
        })

    return {
        "schema": "ego.governance-inspection.v1",
        "harness": harness,
        "identity": identity,
        "mode": str(mode).lower(),
        "effective_rule": "permission intersection: Superego ∩ workspace security/mode ∩ Flow RuntimePolicy; visible approval nodes are workflow checkpoints, not permission grants",
        "identity_layer": {
            "role": id_config.get("role", ""), "description": id_config.get("description", ""),
            "personality": id_config.get("personality", {}),
        },
        "superego_layer": {
            "task_prompt": sego.get("task_prompt", ""),
            "output_policy": copy.deepcopy(sego.get("output_policy") or {}),
            "tool_access": tool_access,
            "knowledge_access": knowledge_access,
            "mutation_contract": "explicit" if explicit_mutation_contract else "legacy",
            "mutation_switches": {key: bool(sego.get(key, False)) for key in sorted(MUTATION_SWITCHES)},
            "hooks": hooks,
        },
        "flow_layer": {
            "nodes": len(pipeline.get("nodes", {}) or {}),
            "permission_configured": isinstance(graph_permissions, dict),
            "permissions": graph_permissions or {},
            "approval_nodes": review_nodes,
            "instruction_nodes": model_nodes_with_rules,
        },
        "workspace_layer": {
            "profile": policy.profile, "workspace_only": policy.workspace_only,
            "sandbox": policy.sandbox, "allow_sensitive_files": policy.allow_sensitive_files,
        },
        "invariants": [
            "Identity describes persona and durable preferences; it does not grant tools.",
            "Superego is an Identity-level ceiling and reusable-object mutation contract.",
            "Flow defines orchestration and may narrow permissions, but cannot widen Superego/workspace policy.",
            "Mode and workspace security are runtime boundaries, not prompt instructions.",
            "Visible approval nodes explain and pause a workflow, but backend RuntimePolicy remains the non-bypassable enforcement boundary.",
            "The Agent runtime still injects a small provider/tool-protocol invariant prompt.",
        ],
        "matrix": matrix,
        "conflicts": conflicts,
    }


__all__ = ["GovernanceError", "inspect_governance"]
