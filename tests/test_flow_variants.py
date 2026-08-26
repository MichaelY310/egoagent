import copy
import json
from pathlib import Path

import pytest

from flow_variants import (
    FlowVariantError,
    apply_flow_variant,
    build_flow_variant_population,
    flow_digest,
    flow_promotion_decision,
    paired_flow_promotion_decision,
    validate_proposal_evidence,
)
from node_registry import get_node_definition


def _base():
    return {
        "name": "base",
        "pipeline": {
            "start": "input",
            "nodes": {
                "input": {"op": "输入", "edges": [{"condition": "input", "to": "act"}]},
                "act": {"op": "Agent", "agent": "worker", "max_tokens": 1000, "edges": [{"condition": "has_text", "to": "done"}]},
                "done": {"op": "结束", "value": "$last.text", "edges": []},
            },
        },
    }


def test_set_field_is_copy_on_write_and_audited():
    base = _base()
    before = copy.deepcopy(base)
    result = apply_flow_variant(
        base,
        {"operations": [{"op": "set_field", "path": "pipeline.nodes.act.max_tokens", "value": 2000}]},
        allowed_paths=["pipeline.nodes.act"],
    )
    assert base == before
    assert result["config"]["pipeline"]["nodes"]["act"]["max_tokens"] == 2000
    assert result["base_digest"] == flow_digest(base)
    assert result["candidate_digest"] != result["base_digest"]


def test_insert_node_on_edge_builds_valid_structure():
    result = apply_flow_variant(
        _base(),
        {"operations": [{
            "op": "insert_node_on_edge",
            "source": "input",
            "condition": "input",
            "node_id": "context",
            "node": {"op": "上下文", "action": "select", "last_n": 4},
        }]},
        allowed_paths=["pipeline.nodes"],
    )
    nodes = result["config"]["pipeline"]["nodes"]
    assert nodes["input"]["edges"][0]["to"] == "context"
    assert nodes["context"]["edges"][0]["to"] == "act"


def test_inserted_condition_must_declare_an_expression_and_real_events():
    with pytest.raises(FlowVariantError, match="cannot emit"):
        apply_flow_variant(
            _base(),
            {"operations": [{
                "op": "insert_node_on_edge",
                "source": "input",
                "condition": "input",
                "node_id": "imaginary_gate",
                "node": {
                    "op": "条件",
                    "edges": [
                        {"condition": "success", "to": "done"},
                        {"condition": "default", "to": "act"},
                    ],
                },
            }]},
            allowed_paths=["pipeline.nodes"],
        )

    with pytest.raises(FlowVariantError, match="requires condition"):
        apply_flow_variant(
            _base(),
            {"operations": [{
                "op": "insert_node_on_edge",
                "source": "input",
                "condition": "input",
                "node_id": "empty_gate",
                "node": {
                    "op": "条件",
                    "edges": [
                        {"condition": "true", "to": "done"},
                        {"condition": "false", "to": "act"},
                    ],
                },
            }]},
            allowed_paths=["pipeline.nodes"],
        )


def test_inserted_tool_requires_a_tool_call_source():
    with pytest.raises(FlowVariantError, match="no explicit tool_calls"):
        apply_flow_variant(
            _base(),
            {"operations": [{
                "op": "insert_node_on_edge",
                "source": "input",
                "condition": "input",
                "node_id": "detached_tools",
                "node": {"op": "工具"},
            }]},
            allowed_paths=["pipeline.nodes"],
        )


def test_invalid_or_out_of_surface_variant_is_rejected():
    with pytest.raises(FlowVariantError, match="outside"):
        apply_flow_variant(
            _base(),
            {"operations": [{"op": "set_field", "path": "pipeline.start", "value": "done"}]},
            allowed_paths=["pipeline.nodes.act"],
        )


def test_no_op_variant_is_rejected_instead_of_spending_evaluation_budget():
    with pytest.raises(FlowVariantError, match="no-op"):
        apply_flow_variant(
            _base(),
            {"operations": [{"op": "set_field", "path": "pipeline.nodes.act.max_tokens", "value": 1000}]},
            allowed_paths=["pipeline.nodes.act"],
        )


def test_population_deduplicates_and_preserves_diverse_valid_candidates():
    proposals = [
        {"operations": [{"op": "set_field", "path": "pipeline.nodes.act.max_tokens", "value": 1200}]},
        {"operations": [{"op": "set_field", "path": "pipeline.nodes.act.max_tokens", "value": 1200}]},
        {"operations": [{"op": "set_field", "path": "pipeline.nodes.act.max_tokens", "value": 1600}]},
    ]
    population = build_flow_variant_population(
        _base(), proposals, allowed_paths=["pipeline.nodes.act"], min_novelty=0.0
    )
    assert len(population["accepted"]) == 2
    assert population["rejected"][0]["reason"] == "duplicate proposal signature"
    assert len({item["candidate_digest"] for item in population["accepted"]}) == 2
    with pytest.raises(FlowVariantError, match="failed validation"):
        apply_flow_variant(
            _base(),
            {"operations": [{"op": "set_field", "path": "pipeline.nodes.input.edges", "value": [{"condition": "input", "to": "missing"}]}]},
            allowed_paths=["pipeline.nodes.input"],
        )


def test_machine_verifiable_evidence_rejects_a_plausible_but_false_story():
    evidence = {"measured_failure": {"revisited_state_actions": 0, "action_budget_completed": True}}
    contradicted = {
        "evidence_refs": [{
            "path": "measured_failure.revisited_state_actions",
            "operator": "gt",
            "value": 0,
        }]
    }
    with pytest.raises(FlowVariantError, match="contradicted"):
        validate_proposal_evidence(contradicted, evidence)

    verified = validate_proposal_evidence({
        "evidence_refs": [
            {"path": "measured_failure.revisited_state_actions", "operator": "eq", "value": 0},
            {"path": "measured_failure.action_budget_completed", "operator": "eq", "value": True},
        ]
    }, evidence)
    assert [item["actual"] for item in verified] == [0, True]


def test_population_can_require_grounded_evidence_before_accepting_candidate():
    proposal = {
        "evidence_refs": [{"path": "runtime.model_calls", "operator": "gt", "value": 10}],
        "operations": [{"op": "set_field", "path": "pipeline.nodes.act.max_tokens", "value": 1200}],
    }
    accepted = build_flow_variant_population(
        _base(), [proposal], allowed_paths=["pipeline.nodes.act"],
        evaluation_evidence={"runtime": {"model_calls": 26}},
    )
    assert accepted["accepted"][0]["verified_evidence"][0]["actual"] == 26


def test_flow_variant_is_a_first_class_node():
    definition = get_node_definition("flow_variant")
    assert definition is not None
    assert definition.op == "流程变体"
    assert "variant_valid" in definition.events


def test_promotion_rejects_a_tied_but_more_expensive_candidate():
    decision = flow_promotion_decision(
        {"levels": 0, "score": 0, "tokens": 100},
        {"levels": 0, "score": 0, "tokens": 120},
        primary_metrics=["levels", "score"],
        cost_metrics=["tokens"],
        heldout_verified=False,
    )
    assert decision["status"] == "rejected"
    assert not decision["promoted"]


def test_promotion_still_requires_heldout_after_validation_gain():
    decision = flow_promotion_decision(
        {"levels": 0, "score": 0, "tokens": 100},
        {"levels": 1, "score": 1, "tokens": 130},
        primary_metrics=["levels", "score"],
        cost_metrics=["tokens"],
        heldout_verified=False,
    )
    assert decision["status"] == "needs_heldout"


def test_paired_promotion_requires_real_heldout_pairs_not_a_boolean():
    validation = [
        {"case_id": "v1", "baseline": {"levels": 0, "score": 0, "tokens": 100}, "candidate": {"levels": 1, "score": 1, "tokens": 120}},
        {"case_id": "v2", "baseline": {"levels": 0, "score": 0, "tokens": 100}, "candidate": {"levels": 0, "score": 0, "tokens": 90}},
    ]
    decision = paired_flow_promotion_decision(
        validation, [], primary_metrics=["levels", "score"], cost_metrics=["tokens"]
    )
    assert decision["status"] == "needs_more_evidence"
    assert not decision["promoted"]


def test_paired_promotion_rejects_one_heldout_primary_regression():
    validation = [
        {"case_id": "v1", "baseline": {"levels": 0, "score": 0, "tokens": 100}, "candidate": {"levels": 1, "score": 1, "tokens": 120}},
        {"case_id": "v2", "baseline": {"levels": 0, "score": 0, "tokens": 100}, "candidate": {"levels": 0, "score": 0, "tokens": 90}},
    ]
    heldout = [
        {"case_id": "h1", "baseline": {"levels": 1, "score": 1, "tokens": 100}, "candidate": {"levels": 0, "score": 0, "tokens": 90}},
        {"case_id": "h2", "baseline": {"levels": 0, "score": 0, "tokens": 100}, "candidate": {"levels": 0, "score": 0, "tokens": 90}},
    ]
    decision = paired_flow_promotion_decision(
        validation, heldout, primary_metrics=["levels", "score"], cost_metrics=["tokens"]
    )
    assert decision["status"] == "rejected"
    assert "heldout" in decision["reason"]


def test_paired_promotion_accepts_reproducible_primary_gain():
    def pair(case_id):
        return {"case_id": case_id, "baseline": {"levels": 0, "score": 0, "tokens": 100}, "candidate": {"levels": 1, "score": 1, "tokens": 110}}

    decision = paired_flow_promotion_decision(
        [pair("v1"), pair("v2")],
        [pair("h1"), pair("h2")],
        primary_metrics=["levels", "score"],
        cost_metrics=["tokens"],
    )
    assert decision["status"] == "promoted"
    assert decision["promoted"]


def test_paired_promotion_rejects_tiny_efficiency_noise_when_primary_ties():
    def pair(case_id):
        return {
            "case_id": case_id,
            "baseline": {"levels": 0, "score": 0, "tokens": 100000},
            "candidate": {"levels": 0, "score": 0, "tokens": 99999},
        }

    decision = paired_flow_promotion_decision(
        [pair("v1"), pair("v2")],
        [pair("h1"), pair("h2")],
        primary_metrics=["levels", "score"],
        cost_metrics=["tokens"],
        min_cost_improvement=0.05,
    )
    assert decision["status"] == "rejected"
    assert "material efficiency" in decision["reason"]


def test_paired_promotion_accepts_reproducible_material_efficiency_gain():
    def pair(case_id):
        return {
            "case_id": case_id,
            "baseline": {"levels": 0, "score": 0, "tokens": 100},
            "candidate": {"levels": 0, "score": 0, "tokens": 90},
        }

    decision = paired_flow_promotion_decision(
        [pair("v1"), pair("v2")],
        [pair("h1"), pair("h2")],
        primary_metrics=["levels", "score"],
        cost_metrics=["tokens"],
        min_cost_improvement=0.05,
    )
    assert decision["status"] == "promoted"
