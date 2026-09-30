"""One canonical registry for DAG execution, validation and authoring UI."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class NodeDefinition:
    op: str
    handler: str
    description: str
    inputs: Mapping[str, str]
    outputs: Mapping[str, str]
    events: tuple[str, ...]
    aliases: tuple[str, ...] = ()
    call_style: str = "node_inputs"
    side_effecting: bool = False
    category: str = "高级"
    icon: str = "◇"
    css_class: str = "dnd-tool"
    color: str = "#64748b"
    editor_defaults: Mapping[str, Any] = field(default_factory=dict)
    palette: bool = True

    def contract(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "inputs": {name: {"type": kind} for name, kind in self.inputs.items()},
            "outputs": {name: {"type": kind} for name, kind in self.outputs.items()},
            "events": list(self.events),
            "handler": self.handler,
            "side_effecting": self.side_effecting,
            "aliases": list(self.aliases),
            "editor": {
                "category": self.category,
                "icon": self.icon,
                "css_class": self.css_class,
                "color": self.color,
                "defaults": copy.deepcopy(dict(self.editor_defaults)),
                "palette": self.palette,
            },
        }


def _node(
    op: str,
    handler: str,
    description: str,
    inputs: Mapping[str, str],
    outputs: Mapping[str, str],
    events: tuple[str, ...],
    *,
    aliases: tuple[str, ...] = (),
    call_style: str = "node_inputs",
    side_effecting: bool = False,
    category: str = "高级",
    icon: str = "◇",
    css_class: str = "dnd-tool",
    color: str = "#64748b",
    defaults: Mapping[str, Any] = (),
    palette: bool = True,
) -> NodeDefinition:
    return NodeDefinition(
        op, handler, description, dict(inputs), dict(outputs), events, aliases,
        call_style, side_effecting, category, icon, css_class, color,
        dict(defaults), palette,
    )


NODE_DEFINITIONS = (
    _node("输入", "_input_node", "Read or reuse one user message.", {}, {"text": "string", "value": "string"}, ("input", "no_input"), aliases=("等待输入", "input"), category="核心", icon="⌨", css_class="dnd-wait", color="#3b82f6"),
    _node("Agent", "_agent_node", "Run a model/tool loop bound to one Identity slot.", {"messages": "messages"}, {"text": "string", "tool_calls": "tool_calls", "structured": "json"}, ("has_text", "has_tool_calls", "no_tool_calls", "output_truncated", "stuck", "end_session"), aliases=("推理", "agent"), call_style="node_id", side_effecting=True, category="核心", icon="🧠", css_class="dnd-infer", color="#22c55e", defaults={"tools": "auto"}),
    _node("工具审查", "_tool_review_node", "Review proposed model tool calls before execution.", {"tool_calls": "tool_calls"}, {"tool_calls": "tool_calls"}, ("approved", "rejected", "has_tool_calls", "no_tool_calls"), aliases=("处理工具", "tool_review", "toolreview"), side_effecting=True, category="核心", icon="⚖", css_class="dnd-tool", color="#f59e0b"),
    _node("文本处理", "_text_process_node", "Transform text with an Identity or deterministic protocol.", {"text": "string"}, {"text": "string", "structured": "json"}, ("has_text", "empty"), aliases=("处理文字", "text_process", "textprocess"), side_effecting=True, category="核心", icon="✎", css_class="dnd-text", color="#06b6d4", defaults={"mode": "agent"}),
    _node("工具", "_tool_node", "Execute the current model tool calls.", {"tool_calls": "tool_calls"}, {"results": "json", "human_required": "json"}, ("tools_executed", "no_tool_calls", "stuck", "human_required", "end_session"), aliases=("执行工具", "tool"), side_effecting=True, category="核心", icon="⚡", css_class="dnd-exec", color="#ec4899"),
    _node("进程", "_process_node", "Run a bounded process without invoking a shell implicitly.", {"command": "string", "args": "json", "cwd": "path"}, {"value": "json", "stdout": "string", "stderr": "string", "exit_code": "integer", "artifacts": "json"}, ("success", "error", "timeout"), aliases=("process", "command", "命令"), side_effecting=True, category="核心", icon="▸", css_class="dnd-exec", color="#f97316", defaults={"command": "python", "args": [], "cwd": ".", "success_codes": [0], "fail_on_error": True, "artifacts": [], "output_var": "process_result"}),
    _node("工作区", "_workspace_node", "Perform a validated workspace file or transaction operation.", {"source": "path", "target": "path", "value": "any"}, {"value": "any", "artifacts": "json"}, ("default", "success", "error"), aliases=("workspace",), side_effecting=True, category="数据", icon="▧", css_class="dnd-text", color="#14b8a6", defaults={"action": "mkdir", "target": ".egoagent/work", "output_var": "workspace_result"}),
    _node("Python", "_python_node", "Advanced in-process custom node; prefer declarative nodes.", {"data": "json"}, {"value": "any"}, ("default", "error"), aliases=("脚本", "python"), side_effecting=True, category="高级", icon="⌘", css_class="dnd-script", color="#84cc16", defaults={"script": "custom_node", "input_vars": [], "output_vars": []}),
    _node("模型", "_model_node", "Make one ordinary model call, optionally parsed and schema checked.", {"messages": "messages", "text": "string"}, {"text": "string", "structured": "json"}, ("has_text", "empty"), aliases=("llm_call", "model"), side_effecting=True, category="核心", icon="◉", css_class="dnd-llm", color="#0ea5e9"),
    _node("上下文", "_context_node", "Snapshot, select, compact or apply conversation state.", {"source": "messages", "plan": "json"}, {"value": "json", "messages": "messages", "stats": "json", "model_payload": "string"}, ("context_ready", "conversation_ready", "review_due", "review_not_due", "pressure_due", "pressure_ok", "applied"), aliases=("context", "history", "context_window", "contextwindow"), side_effecting=True, category="数据", icon="☰", css_class="dnd-llm", color="#8b5cf6", defaults={"action": "select", "source": "$session.messages", "last_n": 20, "output_var": "context_messages"}),
    _node("记忆", "_memory_node", "Read or mutate scoped long-term memory.", {"query": "string", "value": "json"}, {"value": "json", "memories": "json"}, ("default", "found", "not_found"), aliases=("memory",), side_effecting=True, category="数据", icon="◈", css_class="dnd-llm", color="#a855f7", defaults={"action": "search", "namespace": "default", "query": "$ctx.request", "top_k": 8, "output_var": "memories"}),
    _node("能力", "_capability_node", "Search the capability catalog or activate one result on a selected Agent slot.", {"query": "string", "capability_id": "string", "source": "json"}, {"value": "json", "results": "json", "activation": "json"}, ("found", "not_found", "activated", "error"), aliases=("capability", "capability_registry"), side_effecting=True, category="进化", icon="⌕", css_class="dnd-llm", color="#7c3aed", defaults={"action": "search", "agent": "agent", "query": "$ctx.request", "top_k": 8, "output_var": "capability_result", "min_score": 2.5, "min_margin": 0.7, "min_query_coverage": 0.6, "strong_semantic_score": 0.68}),
    _node("条件", "_condition_node", "Route with a safe expression.", {"value": "any"}, {"value": "boolean"}, ("true", "false"), aliases=("if", "if_else"), category="流程", icon="⑂", css_class="dnd-tool", color="#f59e0b", defaults={"condition": "true"}),
    _node("数据", "_data_node", "Perform deterministic state transformations.", {"value": "any", "source": "any", "schema": "json"}, {"value": "any", "errors": "json"}, ("default", "schema_valid", "schema_invalid"), aliases=("data",), call_style="data_op", category="数据", icon="▣", css_class="dnd-text", color="#14b8a6", defaults={"action": "set", "scope": "run", "key": "value", "value": ""}),
    _node("保存数据", "_data_node", "Save a value to run/session/file state.", {"value": "any"}, {"value": "any"}, ("default",), aliases=("set_data", "data_store", "datastore"), call_style="data_op", side_effecting=True, category="数据", icon="↓", css_class="dnd-text", color="#14b8a6"),
    _node("读取数据", "_data_node", "Read a value from run/session/file state.", {}, {"value": "any"}, ("default", "found", "not_found"), aliases=("get_data", "data_load", "dataload"), call_style="data_op", category="数据", icon="↑", css_class="dnd-text", color="#06b6d4"),
    _node("循环", "_loop_node", "Iterate over a bounded list.", {"items": "json"}, {"item": "any", "index": "integer"}, ("loop_continue", "loop_done", "loop_break"), aliases=("loop",), call_style="node_id", side_effecting=True, category="流程", icon="↻", css_class="dnd-text", color="#8b5cf6", defaults={"list_var": "items", "item_var": "_item", "counter_var": "_i", "max_count": 100}),
    _node("并行", "_parallel_node", "Execute declared branches concurrently.", {"data": "json"}, {"branches": "json"}, ("parallel_done", "error"), aliases=("parallel",), side_effecting=True, category="流程", icon="⑂", css_class="dnd-exec", color="#f97316", defaults={"branches": [], "max_workers": 4, "fail_fast": True}),
    _node("映射", "_map_node", "Run one bounded branch for each list item.", {"items": "json"}, {"results": "json"}, ("map_done", "joined", "error"), aliases=("map", "parallel_map", "parallelmap"), side_effecting=True, category="流程", icon="⫴", css_class="dnd-exec", color="#fb7185", defaults={"list_var": "items", "item_var": "_item", "counter_var": "_i", "max_workers": 4, "fail_fast": True}),
    _node("合并", "_join_node", "Join branch outputs deterministically.", {"source": "json"}, {"value": "any"}, ("joined",), aliases=("join",), category="流程", icon="⑃", css_class="dnd-llm", color="#eab308", defaults={"source": "$last.branches", "strategy": "list", "output_var": "joined"}),
    _node("人工审批", "_approval_node", "Pause for an auditable human decision.", {"data": "json"}, {"decision": "string", "value": "any"}, ("approved", "rejected"), aliases=("approval", "human", "human_approval", "humanapproval", "审批"), side_effecting=True, category="流程", icon="✋", css_class="dnd-tool", color="#ef4444", defaults={"prompt_text": "是否允许继续执行？", "default": "rejected", "output_var": "approval"}),
    _node("子流程", "_subflow_node", "Run an isolated or shared-session Harness/SubDAG.", {"message": "string", "data": "json"}, {"value": "any", "text": "string", "data": "json", "component_outputs": "json"}, ("subflow_done", "component_done"), aliases=("subflow",), side_effecting=True, category="流程", icon="◫", css_class="dnd-llm", color="#6366f1", defaults={"identity_map": {}, "agent_map": {}, "output_var": "_sub_result"}),
    _node("检查点", "_checkpoint_node", "Save, list, inspect, restore or delete a run checkpoint.", {"checkpoint": "string"}, {"value": "json"}, ("checkpoint_saved", "checkpoint_loaded", "checkpoint_restored", "default"), aliases=("checkpoint",), category="数据", icon="◉", css_class="dnd-wait", color="#64748b", defaults={"action": "save", "label": "checkpoint"}),
    _node("流程变体", "_flow_variant_node", "Apply a typed, allowlisted Flow mutation to a copy and validate it atomically.", {"base_config": "json", "proposal": "json"}, {"value": "json", "config": "json", "errors": "json"}, ("variant_valid", "variant_invalid", "variant_written"), aliases=("flow_variant", "flow_mutation"), side_effecting=True, category="进化", icon="↗", css_class="dnd-tool", color="#a855f7", defaults={"persist": False, "max_operations": 12, "output_var": "flow_variant"}),
    _node("搜索控制", "_search_control_node", "Reconcile a typed belief ledger and rank falsifiable experiments without task-specific rules.", {"ledger": "json", "proposal": "json", "trajectory": "json", "allowed_actions": "json"}, {"value": "json", "ledger": "json", "selected": "json", "errors": "json"}, ("controller_ready", "controller_invalid", "no_experiment"), aliases=("search_control", "belief_controller", "experiment_selector"), side_effecting=True, category="进化", icon="⌁", css_class="dnd-llm", color="#7c3aed", defaults={"max_hypotheses": 8, "max_experiments": 12, "output_var": "search_control"}),
    _node("循环守卫", "_loop_guard_node", "Track exact repeated tool calls and inject advisory reminders at declared thresholds without blocking execution.", {"trajectory": "json", "action": "string"}, {"value": "json", "state": "json", "reminders": "json"}, ("guard_reset", "guard_clear", "guard_reminder"), aliases=("loop_guard", "repeat_tool_guard"), side_effecting=True, category="流程", icon="↯", css_class="dnd-tool", color="#f59e0b", defaults={"action": "observe", "thresholds": [3, 5, 8], "arguments_preview_chars": 500, "inject_message": True, "output_var": "loop_guard"}),
    _node("输出", "_output_node", "Publish a result and usually stop this path.", {"value": "any"}, {"value": "any", "text": "string"}, ("output",), aliases=("output",), call_style="output", category="核心", icon="✅", css_class="dnd-tool", color="#10b981", defaults={"value": "$last.text"}),
    _node("结束", "_output_node", "Publish a terminal result.", {"value": "any"}, {"value": "any", "text": "string"}, ("output", "done"), aliases=("end",), call_style="output", category="核心", icon="■", css_class="dnd-tool", color="#059669", palette=False),
)


NODE_REGISTRY = {definition.op: definition for definition in NODE_DEFINITIONS}
if len(NODE_REGISTRY) != len(NODE_DEFINITIONS):
    raise RuntimeError("Duplicate canonical DAG operation in NodeDefinition registry")


def _normalized_alias(value: str) -> tuple[str, str]:
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", value).replace("-", "_").replace(" ", "_").lower()
    return snake, snake.replace("_", "")


_ALIASES: dict[str, str] = {}
for definition in NODE_DEFINITIONS:
    for alias in (definition.op, *definition.aliases):
        raw = str(alias).strip()
        snake, compact = _normalized_alias(raw)
        for key in {raw, raw.lower(), snake, compact}:
            existing = _ALIASES.get(key)
            if existing is not None and existing != definition.op:
                raise RuntimeError(f"DAG operation alias {key!r} maps to both {existing!r} and {definition.op!r}")
            _ALIASES[key] = definition.op
NODE_ALIASES = dict(_ALIASES)


def canonical_node_op(op: str) -> str:
    value = str(op or "").strip()
    snake, compact = _normalized_alias(value)
    return _ALIASES.get(value, _ALIASES.get(value.lower(), _ALIASES.get(snake, _ALIASES.get(compact, value))))


def get_node_definition(op: str) -> NodeDefinition | None:
    return NODE_REGISTRY.get(canonical_node_op(op))


def execute_registered_node(runner: Any, node_id: str, node: dict[str, Any], inputs: dict[str, Any]) -> Any:
    definition = get_node_definition(node.get("op", ""))
    if definition is None:
        raise KeyError(f"unknown operation: {node.get('op')!r}")
    handler = getattr(runner, definition.handler)
    if definition.call_style == "node_id":
        return handler(node_id, node, inputs)
    if definition.call_style == "data_op":
        return handler(node, inputs, definition.op)
    if definition.call_style == "output":
        stop = definition.op == "结束" or not node.get("continue", False)
        return handler(node, inputs, stop=stop)
    return handler(node, inputs)


def node_registry_catalog() -> dict[str, Any]:
    return {definition.op: definition.contract() for definition in NODE_DEFINITIONS}


SUPPORTED_NODE_OPS = frozenset(NODE_REGISTRY)
SIDE_EFFECTING_NODE_OPS = frozenset(
    definition.op for definition in NODE_DEFINITIONS if definition.side_effecting
)


__all__ = [
    "NODE_ALIASES", "NODE_DEFINITIONS", "NODE_REGISTRY", "NodeDefinition", "SIDE_EFFECTING_NODE_OPS",
    "SUPPORTED_NODE_OPS", "canonical_node_op", "execute_registered_node",
    "get_node_definition", "node_registry_catalog",
]
