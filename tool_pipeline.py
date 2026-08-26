"""Tool-execution adapter implementing the public runtime contract."""

from __future__ import annotations

import copy
import json
from typing import Any, Mapping

from runtime_contracts import ToolExecutionRequest, ToolExecutionResult


def _tool_status(value: Any) -> tuple[str, str | None]:
    if isinstance(value, Mapping) and (value.get("ok") is False or value.get("error")):
        return "error", str(value.get("error") or "tool reported failure")
    if isinstance(value, str):
        if value.startswith("Permission denied:"):
            return "denied", value
        if value.startswith("Tool not found:"):
            return "not_found", value
        if value.startswith("Tool ") and " error:" in value:
            return "error", value
    return "ok", None


class AgentToolExecutor:
    """Adapt one Agent's capability implementation to ``ToolExecutor``.

    Permission policy, hooks, trajectory recording and change tracking remain
    in the Agent implementation for now.  DAG/runtime callers depend only on
    this adapter, making that implementation independently replaceable later.
    """

    def __init__(self, agent: Any):
        self.agent = agent

    def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        if request.agent and request.agent != getattr(self.agent, "name", request.agent):
            raise ValueError(
                f"Tool request targets Agent {request.agent!r}, but this executor owns "
                f"{getattr(self.agent, 'name', '')!r}"
            )
        metadata = request.metadata if isinstance(request.metadata, Mapping) else {}
        raw_call = metadata.get("raw_tool_call")
        call = copy.deepcopy(raw_call) if isinstance(raw_call, Mapping) else {
            "id": request.call_id,
            "type": "function",
            "function": {
                "name": request.name,
                "arguments": json.dumps(dict(request.arguments), ensure_ascii=False),
            },
        }
        options = metadata.get("execution_options", {})
        if not isinstance(options, Mapping):
            options = {}
        try:
            observation = self.agent.execute_tool_call(call, **dict(options))
        except TypeError as error:
            # Third-party Agent implementations may expose the older one-arg
            # method. Only retry when an optional execution argument caused it.
            if not options or not any(str(name) in str(error) for name in options):
                raise
            observation = self.agent.execute_tool_call(call)
        status, error = _tool_status(observation)
        return ToolExecutionResult(
            status=status,
            raw_result=copy.deepcopy(observation),
            model_observation=observation,
            error=error,
        )


__all__ = ["AgentToolExecutor"]
