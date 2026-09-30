"""Single classification policy for user-facing Flow catalogs.

Runtime lookup remains directory based: a parent Flow can always invoke an
internal SubFlow by name.  This module only controls how authoring surfaces
group and expose those files, so helper workers no longer drown out useful
templates and user-created Flows naturally land in ``custom``.
"""

from __future__ import annotations

from typing import Any, Mapping


CATEGORY_LABELS = {
    "system": "系统内置",
    "example": "Examples",
    "experiment": "Experiments",
    "custom": "Custom",
}

SYSTEM_FLOWS = {
    "adaptive_code_agent",
    "adaptive_research_agent",
    "agent_factory",
    "code_agent_auto",
    "code_agent_fast",
    "code_agent_long",
    "code_agent_team",
    "codex_flow",
    "context_curator",
    "deepseek_harness_replica",
    "openhands_replica",
    "session_analyzer",
}

EXPERIMENT_FLOWS = {
    "ai_scientist_replica",
    "arc_direct_baseline",
    "arc_long_horizon",
    "arc_scientific_search",
    "demo_fragile_release_flow",
    "demo_noisy_research_flow",
    "evolution_cycle",
    "flow_evolution_showcase",
    "improver",
    "meta_evolution_cycle",
}

EXAMPLE_FLOWS = {
    "aider_replica",
    "autogpt_platform_replica",
    "browser_use_replica",
    "coc_lightless_beacon",
    "coc_the_haunting",
    "coder_react",
    "continue_agent_replica",
    "continue_plan_replica",
    "conversation_component_demo",
    "creative_roundtable",
    "debate_with_moderator",
    "devika_replica",
    "dual_guardian",
    "generative_agent_replica",
    "gpt_researcher_deep_replica",
    "gpt_researcher_replica",
    "guarded_react",
    "metagpt_mgx_replica",
    "metagpt_software_company_replica",
    "open_deep_research_replica",
    "openmanus_planning_replica",
    "openmanus_replica",
    "react_single",
    "stagehand_replica",
    "swe_agent_replica",
    "text_review_react",
    "tutorial_full_stack_code_agent",
    "voyager_replica",
}

INTERNAL_EXACT = {
    "aider_review_worker",
    "bounded_action_worker",
    "bounded_coder_worker",
}


def classify_harness(name: str, config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return stable catalog metadata without changing runtime availability."""

    config = config or {}
    override = config.get("catalog") if isinstance(config.get("catalog"), Mapping) else {}
    internal = (
        name.startswith("component_")
        or name.startswith("product_")
        or name.endswith("_worker")
        or name in INTERNAL_EXACT
    )

    if override.get("category") in CATEGORY_LABELS:
        category = str(override["category"])
    elif name in SYSTEM_FLOWS:
        category = "system"
    elif name in EXPERIMENT_FLOWS or name.startswith("ai_scientist_") or name.startswith("product_"):
        category = "experiment"
    elif name in EXAMPLE_FLOWS or name.endswith("_replica"):
        category = "example"
    elif internal:
        category = "system"
    else:
        category = "custom"

    pipeline = config.get("pipeline") if isinstance(config.get("pipeline"), Mapping) else {}
    nodes = pipeline.get("nodes") if isinstance(pipeline.get("nodes"), Mapping) else {}
    start = str(pipeline.get("start") or "")
    runnable = bool(nodes and start and start in nodes)
    visibility = str(override.get("visibility") or ("internal" if internal else "public"))

    return {
        "catalog_category": category,
        "catalog_label": CATEGORY_LABELS[category],
        "catalog_visibility": visibility,
        "display_name": str(override.get("display_name") or config.get("display_name") or name),
        "runnable": runnable,
    }


def is_public_runnable(name: str, config: Mapping[str, Any] | None = None) -> bool:
    metadata = classify_harness(name, config)
    return metadata["catalog_visibility"] == "public" and bool(metadata["runnable"])
