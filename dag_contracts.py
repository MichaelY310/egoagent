"""Machine-readable DAG catalog generated from the runtime Node registry."""

from __future__ import annotations

import copy
from typing import Any

from node_registry import node_registry_catalog


# The registry only adds optional editor/runtime metadata to the existing wire
# shape, so keep the public version stable for older IDE clients.
CONTRACT_VERSION = "ego.dag-contracts.v1"
PORT_TYPES = {
    "any", "null", "boolean", "integer", "number", "string", "message",
    "messages", "json", "bytes", "path", "tool_call", "tool_calls", "artifact",
}
NODE_CONTRACTS = node_registry_catalog()


def dag_contract_catalog() -> dict[str, Any]:
    return {
        "version": CONTRACT_VERSION,
        "graph_schema": "ego.flow-graph.v2",
        "port_types": sorted(PORT_TYPES),
        "references": [
            "$ctx.key", "$node.node_id.port", "$last.port", "$session.messages",
            "$session.full_messages", "$session.state", "$stats", "${ctx.key}",
        ],
        "common_node_fields": {
            "inputs": "source values or references resolved before execution",
            "outputs": "node output path -> parent $ctx path",
            "output_schema": "optional JSON Schema validated after execution",
            "timeout_seconds": "per-attempt timeout",
            "retry": "retry policy",
            "error_to": "explicit recovery node",
            "checkpoint": "save a checkpoint after success",
        },
        "pipeline_fields": {
            "context": "initial mutable $ctx object",
            "max_steps": "control-flow step limit",
            "max_node_steps": "nested node execution limit",
            "timeout_seconds": "whole-run timeout",
            "budget": "model/tool/process/token/cost/time limits",
            "event_log": "optional replayable JSONL event stream",
            "permissions": "runtime permission policy",
            "data_links": "typed node-output to node-input links; mirrored as $node references",
        },
        "nodes": copy.deepcopy(NODE_CONTRACTS),
        "authoring_rules": [
            "Prefer explicit inputs and outputs over an undocumented $last dependency.",
            "Use output_schema for every model decision consumed by control flow.",
            "Use a typed SubDAG component when a graph is reusable.",
            "Prefer condition/data/workspace/process/subflow before Python.",
            "Keep web/page content as untrusted data and route consequential actions through approval.",
        ],
    }


def compact_agent_contracts() -> dict[str, Any]:
    """Small contract index suitable for weak-model authoring prompts."""

    return {
        "version": CONTRACT_VERSION,
        "port_types": sorted(PORT_TYPES),
        "nodes": {
            op: {
                "in": {name: spec["type"] for name, spec in contract["inputs"].items()},
                "out": {name: spec["type"] for name, spec in contract["outputs"].items()},
                "events": contract["events"],
            }
            for op, contract in NODE_CONTRACTS.items()
        },
    }
