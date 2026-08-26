from __future__ import annotations

import copy

from node_registry import get_node_definition
from self_evolution.search_control import (
    action_signature,
    recent_action_signatures,
    reconcile_search_state,
)


def _proposal():
    return {
        "update_reason": "one observation contradicted the first mapping",
        "hypotheses": [
            {
                "id": "h_map",
                "claim": "ACTION1 moves the controlled object left",
                "status": "falsified",
                "confidence": 0.1,
                "evidence": [{"kind": "counterexample", "ref": "step:2", "summary": "ACTION1 moved right"}],
            },
            {
                "id": "h_rotate",
                "claim": "ACTION2 rotates the scene",
                "status": "candidate",
                "confidence": 0.4,
                "evidence": [{"kind": "observation", "ref": "step:3", "summary": "not yet tested"}],
            },
        ],
        "experiments": [
            {
                "id": "repeat_left",
                "action": {"name": "ACTION1"},
                "discriminates": ["h_map"],
                "predicted_outcomes": ["move left", "not move left"],
                "information_gain": 0.7,
                "novelty": 0.1,
                "cost": 0.2,
                "repeat_risk": 0.8,
            },
            {
                "id": "test_rotate",
                "action": {"name": "ACTION2"},
                "discriminates": ["h_rotate"],
                "predicted_outcomes": ["scene rotates", "scene remains oriented"],
                "information_gain": 0.9,
                "novelty": 0.9,
                "cost": 0.2,
                "repeat_risk": 0.0,
            },
        ],
    }


def test_controller_selects_information_gain_over_repeated_action():
    result = reconcile_search_state(
        {},
        _proposal(),
        allowed_actions=["ACTION1", "ACTION2"],
        recent_actions=[action_signature({"name": "ACTION1"})] * 2,
    )
    assert result["ok"]
    assert result["selected"]["id"] == "test_rotate"
    assert result["ledger"]["revision"] == 1


def test_falsified_hypothesis_cannot_silently_reactivate_without_new_support():
    first = reconcile_search_state({}, _proposal(), allowed_actions=["ACTION1", "ACTION2"])
    second_proposal = copy.deepcopy(_proposal())
    second_proposal["hypotheses"][0]["status"] = "supported"
    second_proposal["hypotheses"][0]["confidence"] = 0.95
    second = reconcile_search_state(
        first["ledger"], second_proposal, allowed_actions=["ACTION1", "ACTION2"]
    )
    hypothesis = next(item for item in second["ledger"]["hypotheses"] if item["id"] == "h_map")
    assert hypothesis["status"] == "falsified"
    assert any(item["type"] == "blocked_reactivation" for item in second["audit"])


def test_new_support_can_reopen_falsified_hypothesis_but_confidence_is_bounded():
    first = reconcile_search_state({}, _proposal(), allowed_actions=["ACTION1", "ACTION2"])
    second_proposal = copy.deepcopy(_proposal())
    hypothesis = second_proposal["hypotheses"][0]
    hypothesis.update({
        "status": "supported",
        "confidence": 0.95,
        "evidence": hypothesis["evidence"] + [
            {"kind": "support", "ref": "step:9", "summary": "new state made ACTION1 move left"}
        ],
    })
    second = reconcile_search_state(
        first["ledger"], second_proposal, allowed_actions=["ACTION1", "ACTION2"]
    )
    reopened = next(item for item in second["ledger"]["hypotheses"] if item["id"] == "h_map")
    assert reopened["status"] == "supported"
    assert reopened["confidence"] <= 0.3


def test_invalid_coordinate_and_unavailable_action_are_rejected():
    proposal = _proposal()
    proposal["experiments"] = [
        {"id": "bad_coordinate", "action": {"name": "ACTION6", "x": 90, "y": 2}},
        {"id": "not_available", "action": {"name": "ACTION4"}},
    ]
    result = reconcile_search_state(
        {}, proposal, allowed_actions=["ACTION6"], coordinate_min=0, coordinate_max=63
    )
    assert not result["ok"]
    assert len(result["errors"]) >= 2


def test_recent_actions_extract_only_successful_canonical_calls():
    trajectory = [
        {"action": "arc_act", "ok": False, "arguments": {"action": "ACTION6"}},
        {"action": "arc_act", "ok": True, "arguments": {"action": "ACTION6", "x": 2, "y": 3, "reasoning": "x"}},
    ]
    assert recent_action_signatures(trajectory) == [
        action_signature({"name": "ACTION6", "x": 2, "y": 3})
    ]


def test_search_control_is_a_first_class_flow_node():
    definition = get_node_definition("search_control")
    assert definition is not None
    assert definition.op == "搜索控制"
    assert "controller_ready" in definition.events
