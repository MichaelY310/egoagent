"""
EgoAgent Harness Editor 后端 API 服务器

提供：
  Harness:
    GET  /api/harnesses           列出所有 harness
    GET  /api/harness/<name>      加载 harness config
    PUT  /api/harness/<name>      保存 harness config
    GET  /api/harness/<name>/blueprint 读取弱模型友好 Blueprint
    POST /api/harness/blueprint/* 校验、创建、事务补丁与回滚

  Identity:
    GET  /api/identities                    列出所有 identity
    GET  /api/identity/<name>               获取完整 identity
    PUT  /api/identity/<name>               保存 id.json
    PUT  /api/identity/<name>/superego      保存 superego/config.json
    GET  /api/identity/<name>/skill/<sname> 获取 skill 详情
    PUT  /api/identity/<name>/skill/<sname> 保存 skill
    DELETE /api/identity/<name>/skill/<sname> 删除 skill
    GET  /api/identity/<name>/knowledge/<kname> 获取 knowledge 详情
    PUT  /api/identity/<name>/knowledge/<kname> 保存 knowledge
    DELETE /api/identity/<name>/knowledge/<kname> 删除 knowledge
    POST /api/identity/<name>/clone         克隆 identity
    DELETE /api/identity/<name>             删除 identity

  Environment:
    GET  /api/environments                   列出所有 environment
    GET  /api/environment/<path_base64>      获取 environment 详情
    PUT  /api/environment/<path_base64>/tool/<tname>     保存 tool
    DELETE /api/environment/<path_base64>/tool/<tname>   删除 tool
    PUT  /api/environment/<path_base64>/knowledge/<kname> 保存 knowledge
    DELETE /api/environment/<path_base64>/knowledge/<kname> 删除 knowledge

  Execution:
    GET  /api/execution/state     获取执行状态
    POST /api/execution/start     启动执行
    POST /api/execution/stop      停止执行
    POST /api/execution/input     发送用户输入
    POST /api/execution/control   暂停、单步或恢复
    WS   ws://localhost:8766      实时执行状态推送 + 输出流
"""

import json
import os
import sys
import shutil
import copy
import threading
import base64
import queue as queue_module
import time
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

_PROJECT_ROOT_FOR_IMPORTS = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT_FOR_IMPORTS) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT_FOR_IMPORTS))

from llm.env_config import load_local_env
from product_runtime import apply_product_environment
from local_api_security import (
    UnsafeResourcePath,
    is_trusted_local_origin,
    resolve_registered_root,
    resolve_resource_path,
    validate_resource_segment,
)
from trajectory import (
    TrajectoryReader,
    export_training_data,
    load_collection_settings,
    save_collection_settings,
)
from training_data import (
    TrainingAnnotationStore,
    annotated_session_messages,
    export_annotated_training_data,
    resolve_target_source,
)
from session_branching import SessionBranchError, SessionBranchService, read_session_lineage
from project_portfolio import (
    ProjectPortfolio,
    infer_session_workspace,
    project_id_for_workspace,
    workspace_key,
)
from interactive_runs import InteractiveRun, InteractiveRunManager
from interactive_execution_service import InteractiveExecutionError, InteractiveExecutionService
from agent_factory import AgentFactory

# HEART_FLOW_DEMO_HOOK: optional experiment; core Project/Session management
# does not import it.  Deleting ``heart_flow/`` therefore keeps the server
# operational and simply removes the optional routes.
try:
    from heart_flow import api as heart_flow_api
except ImportError:
    heart_flow_api = None

load_local_env(_PROJECT_ROOT_FOR_IMPORTS)
apply_product_environment(_PROJECT_ROOT_FOR_IMPORTS)

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True
from urllib.parse import urlparse, unquote, parse_qs

_MAX_JSON_BODY_BYTES = 16 * 1024 * 1024

# Windows redirects a hidden server's stdout to the active ANSI code page.
# Agent token mirroring may contain Chinese (or any other Unicode), so make the
# diagnostic streams loss-tolerant UTF-8 instead of letting printing abort a
# perfectly valid model call.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

from harness_blueprint import (
    BlueprintError,
    HarnessBlueprintService,
    RevisionConflict,
    blueprint_guide,
)
from dag_contracts import dag_contract_catalog

HARNESS_DIR = Path(__file__).resolve().parent.parent / "harness"
IDENTITY_DIR = Path(__file__).resolve().parent.parent / "identity"
SESSIONS_DIR = Path(__file__).resolve().parent.parent / "sessions"
ENVIRONMENT_DIR = Path(__file__).resolve().parent.parent / "environment"
TRAINING_ANNOTATIONS_PATH = Path(__file__).resolve().parent.parent / ".egoagent" / "training" / "annotations.json"
PROJECT_PORTFOLIO_PATH = Path(__file__).resolve().parent.parent / ".egoagent" / "project_portfolio.json"
HEART_FLOW_STATE_PATH = Path(__file__).resolve().parent.parent / ".egoagent" / "heart_flow.json"
_identity_agent_factory = AgentFactory(identity_roots=(IDENTITY_DIR,))


_project_portfolio_services = {}


def _project_portfolio():
    # SESSIONS_DIR is patched by focused HTTP tests, so construct the cheap
    # service lazily instead of capturing the production directory at import.
    key = (str(PROJECT_PORTFOLIO_PATH.resolve()), str(SESSIONS_DIR.resolve()))
    service = _project_portfolio_services.get(key)
    if service is None:
        service = ProjectPortfolio(PROJECT_PORTFOLIO_PATH, SESSIONS_DIR)
        _project_portfolio_services[key] = service
    return service

# 确保 environment 根目录存在
ENVIRONMENT_DIR.mkdir(parents=True, exist_ok=True)

# 额外兼容的旧 environment 路径（会被扫描但新建不走这里）
_LEGACY_ENV_DIRS = [
    # This is the product's active built-in Environment.  It used to be absent
    # from the manager even though every Agent loaded it, which made the UI and
    # runtime disagree during demos and debugging.
    Path(__file__).resolve().parent.parent / ".environment",
    Path("/home/tiger/.environment"),
    Path(__file__).resolve().parent.parent / "playground_malkuth" / ".environment",
    Path(__file__).resolve().parent.parent / "playground" / ".environment",
]

interactive_runs = InteractiveRunManager()
interactive_execution = InteractiveExecutionService(
    interactive_runs,
    notify=lambda state: notify_clients(state),
)
_legacy_interactive_run = interactive_runs.create(
    Path(__file__).resolve().parent.parent,
    run_id="legacy-interactive",
)
# Compatibility aliases for older embedding code and focused tests. Product
# requests resolve a concrete InteractiveRun and do not use these aliases as a
# process-global control plane.
execution_state = _legacy_interactive_run.state
accumulated_outputs: list = _legacy_interactive_run.outputs

ws_clients = set()


def _current_interactive_run() -> InteractiveRun:
    return interactive_runs.current() or interactive_runs.latest() or _legacy_interactive_run


def _trace_for_node(node_id):
    """Return the latest invocation of a node (loops create several)."""
    if not node_id:
        return None
    for trace in reversed(_current_interactive_run().state.get("node_traces", [])):
        if trace.get("node_id") == node_id:
            return trace
    return None


def _debug_before_node(ctx, node_id, _node):
    """Block immediately before side effects without counting a retry."""
    handle = _current_interactive_run()
    state = handle.state
    with handle.debug_condition:
        state["pending_node"] = node_id
        state["pause_reason"] = "before"
        while state.get("running"):
            mode = state.get("debug_mode", "auto")
            if mode == "auto":
                state["paused"] = False
                state["pause_requested"] = False
                state["pending_node"] = None
                state["pause_reason"] = None
                notify_clients(state)
                return None
            directive = handle.node_directive
            if isinstance(directive, dict) and directive.get("node_id") in {None, "", node_id}:
                handle.node_directive = None
                state["paused"] = False
                state["pause_requested"] = True
                state["pending_node"] = None
                state["pause_reason"] = None
                notify_clients(state)
                return {key: value for key, value in directive.items() if key != "node_id"}
            if handle.step_budget > 0:
                handle.step_budget -= 1
                state["paused"] = False
                state["pause_requested"] = True
                state["pending_node"] = None
                state["pause_reason"] = None
                notify_clients(state)
                return None
            if not state.get("paused"):
                state["paused"] = True
                state["pause_requested"] = False
                notify_clients(state)
            handle.debug_condition.wait(timeout=0.25)
        state["paused"] = False
        state["pending_node"] = None
        state["pause_reason"] = None
        return None


def _debug_on_node_error(ctx, node_id, _node, error):
    """Offer an explicit retry gate after the runtime has exhausted node retries."""
    handle = _current_interactive_run()
    state = handle.state
    with handle.debug_condition:
        if state.get("debug_mode") == "auto" or not state.get("running"):
            return None
        state["pending_node"] = node_id
        state["pause_reason"] = "error"
        state["paused"] = True
        state["pause_requested"] = False
        state["last_node_error"] = {"type": type(error).__name__, "message": str(error)}
        notify_clients(state)
        while state.get("running"):
            if state.get("debug_mode") == "auto":
                state["paused"] = False
                state["pending_node"] = None
                state["pause_reason"] = None
                notify_clients(state)
                return None
            directive = handle.node_directive
            if isinstance(directive, dict) and directive.get("action") == "retry" and directive.get("node_id") in {None, "", node_id}:
                handle.node_directive = None
                state["paused"] = False
                state["pending_node"] = None
                state["pause_reason"] = None
                state["pause_requested"] = True
                notify_clients(state)
                return {key: value for key, value in directive.items() if key != "node_id"}
            handle.debug_condition.wait(timeout=0.25)
        state["paused"] = False
        state["pending_node"] = None
        state["pause_reason"] = None
        return None


import uuid as _uuid
_async_tasks = {}  # task_id -> {"status": "running"|"completed"|"error", "result": {}, "error": ""}
_durable_run_queue = None
_durable_run_worker = None
_durable_run_lock = threading.RLock()
_package_registry = None


def _get_package_registry():
    global _package_registry
    if _package_registry is None:
        from package_registry import LocalPackageRegistry
        _package_registry = LocalPackageRegistry(_PROJECT_ROOT_FOR_IMPORTS / ".egoagent" / "registry")
    return _package_registry


def _confined_repository_path(value, *allowed_roots):
    from agent_package import PackageError
    candidate = Path(str(value)).expanduser()
    candidate = candidate.resolve() if candidate.is_absolute() else (_PROJECT_ROOT_FOR_IMPORTS / candidate).resolve()
    roots = [Path(root).resolve() for root in allowed_roots]
    if not any(candidate == root or root in candidate.parents for root in roots):
        raise PackageError("path is outside the allowed package directories")
    return candidate


def _handle_package_post(handler, path):
    """Handle package mutations before the main API routing chain."""
    if not path.startswith("/api/packages/"):
        return False
    body = handler._read_body()
    try:
        if path == "/api/packages/pack":
            raw_components = body.get("components", [])
            if not isinstance(raw_components, list):
                raise PackageError("components must be an array")
            components = []
            for value in raw_components:
                kind, name = str(value.get("kind", "")), str(value.get("name", ""))
                if kind not in PACKAGE_COMPONENT_ROOTS:
                    raise PackageError(f"unsupported component kind: {kind}")
                component_root = (_PROJECT_ROOT_FOR_IMPORTS / PACKAGE_COMPONENT_ROOTS[kind]).resolve()
                source = (component_root / name).resolve()
                source.relative_to(component_root)
                if not source.exists():
                    raise PackageError(f"component not found: {kind}/{name}")
                components.append({"kind": kind, "name": name, "source": str(source.relative_to(_PROJECT_ROOT_FOR_IMPORTS))})
            manifest = build_agent_package_manifest(
                str(body.get("name", "")), str(body.get("version", "")), components,
                description=str(body.get("description", "")), permissions=body.get("permissions", []),
                compatibility=body.get("compatibility"), provenance=body.get("provenance"),
                dependencies=body.get("dependencies"), examples=body.get("examples"),
            )
            registry = _get_package_registry()
            output = _PROJECT_ROOT_FOR_IMPORTS / ".egoagent" / "exports" / f"{manifest['package']['name']}-{manifest['package']['version']}.egoagentpkg"
            result = pack_agent_package(manifest, _PROJECT_ROOT_FOR_IMPORTS, output, signing_key=registry.signing_key(create=body.get("sign", True) is True))
            if body.get("add_to_registry", True) is True:
                result["registry"] = registry.add(output, trust=str(body.get("trust", "local")))
            handler._send_json(result, 201)
        elif path == "/api/packages/add":
            archive = _confined_repository_path(body.get("archive", ""), _PROJECT_ROOT_FOR_IMPORTS)
            handler._send_json(_get_package_registry().add(archive, trust=str(body.get("trust", "untrusted"))), 201)
        elif path == "/api/packages/install":
            handler._send_json(_get_package_registry().install(
                str(body.get("name", "")), _PROJECT_ROOT_FOR_IMPORTS,
                version=str(body["version"]) if body.get("version") else None,
                allow_update=body.get("allow_update") is True,
                allow_untrusted=body.get("allow_untrusted") is True,
            ))
        elif path == "/api/packages/uninstall":
            handler._send_json(uninstall_agent_package(str(body.get("name", "")), _PROJECT_ROOT_FOR_IMPORTS, force=body.get("force") is True))
        elif path == "/api/packages/trust":
            handler._send_json(_get_package_registry().set_trust(str(body.get("name", "")), str(body.get("version", "")), str(body.get("trust", "untrusted"))))
        elif path == "/api/packages/rate":
            handler._send_json(_get_package_registry().rate(str(body.get("name", "")), str(body.get("version", "")), str(body.get("reviewer", "local")), int(body.get("score", 0)), str(body.get("note", ""))))
        elif path == "/api/packages/fork":
            package = _get_package_registry().get(str(body.get("name", "")), str(body["version"]) if body.get("version") else None)
            if package is None:
                raise PackageError("package not found")
            new_name, new_version = str(body.get("new_name", "")), str(body.get("new_version", "0.1.0"))
            output = _PROJECT_ROOT_FOR_IMPORTS / ".egoagent" / "exports" / f"{new_name}-{new_version}.egoagentpkg"
            result = fork_agent_package(package["archive"], output, new_name, new_version, signing_key=_get_package_registry().signing_key(create=True))
            result["registry"] = _get_package_registry().add(output, trust="local")
            handler._send_json(result, 201)
        else:
            handler._send_error("Unknown package action", 404)
        return True
    except (OSError, PackageError, ValueError, json.JSONDecodeError) as error:
        handler._send_error(str(error), 409 if path in {"/api/packages/install", "/api/packages/uninstall"} else 400)
        return True

# Change tracking module. Use the package-qualified name so Agent tool writes
# and HTTP review actions share the same in-memory change list.
from harness_editor.change_tracker import (
    record_change, apply_text_change, get_changes, get_change_content, accept_change, reject_change, undo_change,
    revert_all, clear_changes, clear_workspace_changes, compute_diff, get_last_operation_error,
)
import fnmatch as _fnmatch
import glob as _glob_module

# Checkpoint & Agent Creator modules
try:
    from harness_editor.checkpoint_manager import (
        create_checkpoint, list_checkpoints, get_checkpoint, preview_restore, rollback, auto_checkpoint,
        clear_all as clear_checkpoints
    )
    from harness_editor.agent_creator import create_agent_from_description, create_agent_from_spec, list_templates as list_agent_templates
except ImportError:
    try:
        from checkpoint_manager import (
            create_checkpoint, list_checkpoints, get_checkpoint, preview_restore, rollback, auto_checkpoint,
            clear_all as clear_checkpoints
        )
        from agent_creator import create_agent_from_description, create_agent_from_spec, list_templates as list_agent_templates
    except ImportError:
        create_checkpoint = list_checkpoints = get_checkpoint = preview_restore = rollback = auto_checkpoint = clear_checkpoints = None
        create_agent_from_description = create_agent_from_spec = list_agent_templates = None

# Extended API module (experiments, environments, identities, pipeline status)
try:
    from api_extensions import handle_api_request as _handle_ext_api
except ImportError:
    import sys as _sys2
    _sys2.path.insert(0, str(Path(__file__).parent))
    from api_extensions import handle_api_request as _handle_ext_api

# Project Rules & Memory module
try:
    from harness_editor.project_rules import (
        get_rules, create_rule, delete_rule, get_effective_rules_prompt,
        save_memory, get_memories, search_memories, get_memory_prompt
    )
except ImportError:
    try:
        from project_rules import (
            get_rules, create_rule, delete_rule, get_effective_rules_prompt,
            save_memory, get_memories, search_memories, get_memory_prompt
        )
    except ImportError:
        get_rules = create_rule = delete_rule = get_effective_rules_prompt = None
        save_memory = get_memories = search_memories = get_memory_prompt = None

# Model Router & Experiment module
try:
    from harness_editor.model_router import (
        list_models as list_model_endpoints, add_model, remove_model, route_request,
        list_model_profiles, get_role_assignments, upsert_model_profile,
        assign_model_role, route_model, set_run_budget, get_run_budget,
        create_experiment, list_experiments, get_experiment, record_result, get_experiment_stats
    )
except ImportError:
    try:
        from model_router import (
            list_models as list_model_endpoints, add_model, remove_model, route_request,
            list_model_profiles, get_role_assignments, upsert_model_profile,
            assign_model_role, route_model, set_run_budget, get_run_budget,
            create_experiment, list_experiments, get_experiment, record_result, get_experiment_stats
        )
    except ImportError:
        list_model_endpoints = add_model = remove_model = route_request = None
        list_model_profiles = get_role_assignments = upsert_model_profile = None
        assign_model_role = route_model = set_run_budget = get_run_budget = None
        create_experiment = list_experiments = get_experiment = record_result = get_experiment_stats = None

# ==================== OpenAI-Compatible API for Void/IDE Integration ====================
import time as _time

try:
    from harness_editor.ai_service import AIServiceError, get_ai_status, run_ai_operation
except ImportError:
    from ai_service import AIServiceError, get_ai_status, run_ai_operation

try:
    from harness_editor.context_engine import (
        build_catalog, build_index, index_status, plan_context, record_context_feedback, retrieve,
    )
except ImportError:
    from context_engine import (
        build_catalog, build_index, index_status, plan_context, record_context_feedback, retrieve,
    )

from harness_editor.background_workspace import apply_handoff, create_isolated_workspace, fork_isolated_workspace, preview_handoff
from agent_package import (
    COMPONENT_ROOTS as PACKAGE_COMPONENT_ROOTS,
    PackageError,
    build_manifest as build_agent_package_manifest,
    fork_package as fork_agent_package,
    list_installed as list_installed_packages,
    pack_package as pack_agent_package,
    uninstall_package as uninstall_agent_package,
)

EGOAGENT_MODELS = [
    {"id": "egoagent-dag", "object": "model", "created": 1700000000, "owned_by": "egoagent"},
    {"id": "egoagent-evolve", "object": "model", "created": 1700000000, "owned_by": "egoagent"},
]


def _workspace_security(workspace):
    from security_settings import load_security_settings, sandbox_capability

    settings = load_security_settings(Path(workspace).resolve())
    return settings, sandbox_capability(settings)


def _interactive_permission_policy(workspace, mode, harness_config, mutation_targets=()):
    from permissions import RuntimePolicy

    settings, _capability = _workspace_security(workspace)
    pipeline = harness_config.get("pipeline", {}) if isinstance(harness_config, dict) else {}
    return RuntimePolicy.for_interactive_run(
        Path(workspace).resolve(),
        mode,
        graph_config=pipeline.get("permissions"),
        security_settings=settings,
        allow_global_mutation=str(mode).lower() == "evolve" and bool(mutation_targets),
        mutation_targets=mutation_targets,
    )


_DEFAULT_CHAT_TOKEN_LIMIT = object()


def _configured_chat_token_limit(harness_config):
    pipeline = harness_config.get("pipeline", {}) if isinstance(harness_config, dict) else {}
    if "interactive_max_tokens" in pipeline:
        return pipeline.get("interactive_max_tokens")
    return _DEFAULT_CHAT_TOKEN_LIMIT


def _cap_chat_agent_tokens(agent, multi_agent=False, configured_limit=_DEFAULT_CHAT_TOKEN_LIMIT):
    """Keep interactive DAG turns responsive on small hosted models.

    Dedicated IDE operations have their own token budgets in ai_service.py;
    this cap only applies to chat/DAG turns exposed through the local API.
    """
    if configured_limit is not _DEFAULT_CHAT_TOKEN_LIMIT:
        normalized = str(configured_limit).strip().lower() if configured_limit is not None else "unlimited"
        if configured_limit is None or normalized in {"", "0", "none", "null", "off", "unlimited"}:
            agent.llm.max_tokens = None
            return agent
        try:
            cap = max(128, int(configured_limit))
        except (TypeError, ValueError) as error:
            raise ValueError(f"interactive_max_tokens must be a positive integer or null, got {configured_limit!r}") from error
    else:
        env_name = "EGOAGENT_MULTI_AGENT_MAX_TOKENS" if multi_agent else "EGOAGENT_DAG_MAX_TOKENS"
        default_cap = 768 if multi_agent else 2048
        try:
            cap = max(128, int(os.environ.get(env_name, default_cap)))
        except (TypeError, ValueError):
            cap = default_cap
    current = getattr(agent.llm, "max_tokens", None)
    try:
        agent.llm.max_tokens = min(int(current), cap) if current else cap
    except (TypeError, ValueError):
        agent.llm.max_tokens = cap
    return agent

def _build_chat_harness(messages, harness_name="react_single", identity_name="dante", workspace=None):
    """Build one chat Harness identically for sync and streaming adapters."""
    from harness import Harness

    try:
        harness_name = validate_resource_segment(harness_name or "react_single", label="harness name")
    except UnsafeResourcePath:
        harness_name = "react_single"
    try:
        identity_name = validate_resource_segment(identity_name or "dante", label="identity name")
    except UnsafeResourcePath:
        identity_name = "dante"
    harness_path = resolve_resource_path(HARNESS_DIR, harness_name, label="harness path")
    identity_path = resolve_resource_path(IDENTITY_DIR, identity_name, label="identity path")
    if not harness_path.exists():
        harness_path = HARNESS_DIR / "react_single"
    if not identity_path.exists():
        identity_path = IDENTITY_DIR / "dante"

    hconfig = json.loads((harness_path / "config.json").read_text(encoding="utf-8"))
    configured_limit = _configured_chat_token_limit(hconfig)
    workspace_path = Path(workspace).resolve() if workspace else None
    slots = hconfig.get("slots", {})
    agents = {}
    if slots:
        for slot_name, slot_def in slots.items():
            try:
                slot_identity = validate_resource_segment(
                    slot_def.get("identity", identity_name), label="identity name"
                )
            except UnsafeResourcePath:
                slot_identity = identity_name
            slot_identity_path = resolve_resource_path(
                IDENTITY_DIR, slot_identity, label="identity path"
            )
            if not slot_identity_path.exists():
                slot_identity_path = identity_path
            agents[slot_name] = _cap_chat_agent_tokens(
                _identity_agent_factory.create(slot_identity_path, name=slot_name, workspace=workspace_path),
                multi_agent=len(slots) > 1,
                configured_limit=configured_limit,
            )
    else:
        agents["agent"] = _cap_chat_agent_tokens(
            _identity_agent_factory.create(identity_path, name="agent", workspace=workspace_path),
            configured_limit=configured_limit,
        )

    harness = Harness(str(harness_path), agents=agents, workspace=workspace_path)
    harness._non_interactive = True
    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        if role in {"user", "assistant"} and content:
            normalized = {"role": role, "content": content}
            harness.session.record(normalized)
            harness.session.record_full(normalized.copy())
    return harness, slots


def _run_dag_completion(
    messages,
    harness_name="react_single",
    identity_name="dante",
    stream=False,
    workspace=None,
):
    """Run user message through DAG pipeline and return assistant response.
    
    Returns structured multi-agent trace when harness has multiple slots.
    Format: [MULTI_AGENT_TRACE]\n<json array of {agent, content}>
    """
    try:
        from harness import runtime_scope
        from pipeline_engine import PipelineRunner

        harness, slots = _build_chat_harness(messages, harness_name, identity_name, workspace=workspace)
        workspace_root = Path(workspace).resolve() if workspace else _PROJECT_ROOT_FOR_IMPORTS
        permission_policy = _interactive_permission_policy(workspace_root, "agent", harness.config, ())
        with runtime_scope(harness=harness):
            PipelineRunner(
                harness,
                on_output=lambda _event, _payload: None,
                get_input=lambda: None,
                is_running=lambda: True,
                permission_policy=permission_policy,
            ).run()
        # The compatible chat endpoint creates a normal Session, so persist
        # the same audit/working/state triplet as terminal and Workbench runs.
        # Without this call context-curation decisions existed only in memory
        # and Session Explorer could not explain or restore them afterwards.
        harness.session.save()
        
        # Multi-agent: return structured trace with agent names
        is_multi = len(slots) > 1
        if is_multi:
            # Collect all assistant messages generated during this run (after user msgs)
            trace = []
            # Find messages that were generated (not from input history)
            input_count = sum(1 for m in messages if m.get("role") in ("user", "assistant") and m.get("content"))
            all_session_msgs = harness.session.messages
            # Skip the input history messages we fed in
            new_msgs = all_session_msgs[input_count:] if len(all_session_msgs) > input_count else all_session_msgs
            for msg in new_msgs:
                if msg.get("role") == "assistant" and msg.get("content"):
                    content = msg.get("content", "")
                    # Filter out think tags (Qwen3 reasoning blocks)
                    if "<think>" in content or "</think>" in content:
                        import re
                        content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
                        content = content.replace('</think>', '').replace('<think>', '').strip()
                    # Skip raw tool_call messages - not useful to show to user
                    if "<tool_call>" in content and "</tool_call>" in content:
                        import re
                        # Remove tool_call blocks, keep any surrounding text
                        cleaned = re.sub(r'<tool_call>.*?</tool_call>', '', content, flags=re.DOTALL).strip()
                        if not cleaned:
                            continue
                        content = cleaned
                    # Also filter out <tool_response> blocks
                    if "<tool_response>" in content:
                        import re
                        content = re.sub(r'<tool_response>.*?</tool_response>', '', content, flags=re.DOTALL).strip()
                        if not content:
                            continue
                    trace.append({
                        "agent": msg.get("name", "Agent"),
                        "content": content
                    })
            if trace:
                return "[MULTI_AGENT_TRACE]\n" + json.dumps(trace, ensure_ascii=False)
            # Fallback: get last assistant message
            for msg in reversed(all_session_msgs):
                if msg.get("role") == "assistant":
                    return msg.get("content", "(No response)")
            return "(No response from DAG pipeline)"
        else:
            # Single agent: return last assistant response as before
            response_text = ""
            for msg in reversed(harness.session.messages):
                if msg.get("role") == "assistant":
                    response_text = msg.get("content", "")
                    break
            return response_text or "(No response from DAG pipeline)"
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"[EgoAgent Error] {str(e)}"


def _stream_single_agent(messages, harness_name, identity_name, send_chunk_fn, workspace=None):
    """Compatibility entry point; every stream now uses PipelineRunner."""
    return _run_dag_streaming(messages, harness_name, identity_name, send_chunk_fn, workspace=workspace)


def _run_dag_streaming(messages, harness_name, identity_name, send_chunk_fn, workspace=None):
    """Adapt PipelineRunner events to the OpenAI-compatible SSE protocol."""
    harness, _slots = _build_chat_harness(messages, harness_name, identity_name, workspace=workspace)
    workspace_root = Path(workspace).resolve() if workspace else _PROJECT_ROOT_FOR_IMPORTS
    permission_policy = _interactive_permission_policy(workspace_root, "agent", harness.config, ())

    # Execute through pipeline_engine.PipelineRunner. This is the same engine
    # used by terminal runs and the native WebSocket DAG editor.
    from pipeline_engine import run_pipeline_stream

    active_agent = [None]
    sent_content = [False]

    def _close_agent():
        if active_agent[0] is None:
            return
        send_chunk_fn("\n[AGENT_END]\n" if sent_content[0] else "[AGENT_CANCEL]\n")
        active_agent[0] = None
        sent_content[0] = False

    def _on_pipeline_event(event, payload):
        if event == "label":
            _close_agent()
            active_agent[0] = payload.get("agent") or "Agent"
            send_chunk_fn(f"[AGENT_START:{active_agent[0]}]\n")
        elif event == "token":
            text = payload.get("text", "")
            if text:
                if active_agent[0] is None:
                    active_agent[0] = payload.get("agent") or "Agent"
                    send_chunk_fn(f"[AGENT_START:{active_agent[0]}]\n")
                sent_content[0] = True
                send_chunk_fn(text)
        elif event == "node_exit" and payload.get("op") in {"Agent", "文本处理", "模型"}:
            _close_agent()
        elif event == "tool":
            name = payload.get("name", "tool")
            result = payload.get("result", "")
            if active_agent[0] is None:
                active_agent[0] = payload.get("agent") or "Tool"
                send_chunk_fn(f"[AGENT_START:{active_agent[0]}]\n")
            sent_content[0] = True
            send_chunk_fn(f"\n[tool:{name}] {result}\n")
        elif event == "output" and not sent_content[0]:
            value = payload.get("value")
            if value not in (None, ""):
                active_agent[0] = active_agent[0] or "Output"
                send_chunk_fn(f"[AGENT_START:{active_agent[0]}]\n")
                sent_content[0] = True
                send_chunk_fn(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
        elif event == "error":
            _close_agent()
            send_chunk_fn(f"\n[Error: {payload.get('message', 'DAG execution failed')}]")

    try:
        run_pipeline_stream(
            harness,
            on_output=_on_pipeline_event,
            get_input=lambda: None,
            is_running=lambda: True,
            permission_policy=permission_policy,
        )
    finally:
        _close_agent()
        harness.session.save()


def _get_durable_run_queue():
    global _durable_run_queue
    with _durable_run_lock:
        if _durable_run_queue is None:
            from run_coordinator import DurableRunQueue

            default_path = Path(__file__).resolve().parent.parent / ".egoagent" / "runs.sqlite3"
            database_path = Path(os.environ.get("EGOAGENT_RUN_DB", str(default_path))).resolve()
            _durable_run_queue = DurableRunQueue(database_path)
            _durable_run_queue.recover_startup()
        return _durable_run_queue


def _execute_durable_run(record, emit, is_cancelled):
    """Execute one leased run through the same PipelineRunner as every UI/API."""
    from pipeline_engine import PipelineRunner
    payload = record.payload
    harness_name = str(payload.get("harness", "react_single"))
    identity_name = str(payload.get("identity", "dante"))
    messages = payload.get("messages", [])
    if not isinstance(messages, list):
        raise ValueError("messages must be an array")
    initial_data = payload.get("initial_data", {})
    if not isinstance(initial_data, dict):
        raise ValueError("initial_data must be an object")
    workspace = Path(payload.get("workspace") or (HARNESS_DIR / harness_name)).resolve()
    if not workspace.is_dir():
        raise ValueError(f"workspace does not exist: {workspace}")
    mode = str(payload.get("mode") or "agent").lower()
    if mode not in {"chat", "plan", "agent", "debug", "evolve", "evaluate"}:
        raise ValueError(f"unsupported run mode: {mode}")
    mutation_targets = payload.get("mutation_targets", [])
    if isinstance(mutation_targets, str):
        mutation_targets = [mutation_targets]
    if mode == "evolve" and not mutation_targets:
        raise ValueError("Evolve mode requires explicit mutation_targets")

    harness, _slots = _build_chat_harness(messages, harness_name, identity_name, workspace=workspace)
    permission_policy = _interactive_permission_policy(
        workspace, mode, harness.config, mutation_targets,
    )
    initial_data = {**initial_data, "run_mode": mode, "mutation_targets": list(mutation_targets)}
    runner = PipelineRunner(
        harness,
        on_output=emit,
        get_input=lambda: None,
        is_running=lambda: not is_cancelled(),
        initial_data=initial_data,
        permission_policy=permission_policy,
        resume_from=record.checkpoint_path or payload.get("resume_from"),
        auto_checkpoint=True,
        allow_inflight_resume=bool(payload.get("allow_inflight_resume", False)),
        allow_revision_conflicts=bool(payload.get("allow_revision_conflicts", False)),
    )
    context = runner.run()
    try:
        harness.session.save()
    except Exception:
        pass
    latest_record = _get_durable_run_queue().get(record.id)
    return {
        "run_id": context.run_id,
        "result": context.result,
        "stats": context.stats.as_dict(),
        "messages": harness.session.messages,
        "checkpoint_path": latest_record.checkpoint_path if latest_record else record.checkpoint_path,
    }


def _start_durable_run_worker():
    global _durable_run_worker
    with _durable_run_lock:
        if _durable_run_worker is None:
            from run_coordinator import DurableRunWorker

            lease_seconds = max(3.0, float(os.environ.get("EGOAGENT_RUN_LEASE_SECONDS", "30")))
            _durable_run_worker = DurableRunWorker(
                _get_durable_run_queue(),
                _execute_durable_run,
                lease_seconds=lease_seconds,
            ).start()
        return _durable_run_worker


def _fork_durable_run(record, *, from_checkpoint=True, replay=False, payload_overrides=None):
    """Create an independent durable run from a run snapshot or original input."""
    if record.status in {"queued", "running"}:
        raise ValueError("pause or finish the source run before forking it")
    payload = copy.deepcopy(record.payload)
    overrides = payload_overrides or {}
    if not isinstance(overrides, dict):
        raise ValueError("payload_overrides must be an object")
    allowed_overrides = {"messages", "initial_data", "mode", "mutation_targets", "harness", "identity"}
    unknown = sorted(set(overrides) - allowed_overrides)
    if unknown:
        raise ValueError(f"unsupported fork overrides: {', '.join(unknown)}")
    payload.update(copy.deepcopy(overrides))
    new_run_id = _uuid.uuid4().hex
    source_workspace = Path(payload.get("source_workspace") or payload.get("workspace") or _PROJECT_ROOT_FOR_IMPORTS).resolve()
    previous_workspace = Path(record.payload.get("workspace") or source_workspace).resolve()
    if replay:
        isolation = create_isolated_workspace(source_workspace, new_run_id)
    else:
        isolation = fork_isolated_workspace(source_workspace, previous_workspace, new_run_id)
    payload["workspace"] = isolation["workspace"]
    payload["source_workspace"] = str(source_workspace)
    payload["isolation"] = isolation
    payload["parent_run_id"] = record.id
    payload["fork_kind"] = "replay" if replay else "checkpoint" if from_checkpoint else "snapshot"
    payload.pop("allow_inflight_resume", None)
    payload.pop("allow_revision_conflicts", None)
    payload.pop("resume_from", None)

    if from_checkpoint and not replay:
        if not record.checkpoint_path:
            raise ValueError("source run has no checkpoint")
        source_checkpoint = Path(record.checkpoint_path).resolve()
        checkpoint_payload = json.loads(source_checkpoint.read_text(encoding="utf-8"))
        if checkpoint_payload.get("phase") == "in_flight":
            raise ValueError("cannot fork an in-flight checkpoint without first resolving its side effect")
        checkpoint_payload["run_id"] = new_run_id
        checkpoint_payload["change_transaction_id"] = f"run-{new_run_id}"
        checkpoint_payload.setdefault("data", {})["_run_id"] = new_run_id
        checkpoint_root = Path(isolation["workspace"]) / ".egoagent" / "checkpoints"
        checkpoint_root.mkdir(parents=True, exist_ok=True)
        fork_checkpoint = checkpoint_root / f"{new_run_id}-fork.json"
        temporary = fork_checkpoint.with_suffix(".tmp")
        temporary.write_text(json.dumps(checkpoint_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, fork_checkpoint)
        payload["resume_from"] = str(fork_checkpoint)

    created = _get_durable_run_queue().enqueue(
        payload,
        run_id=new_run_id,
        priority=record.priority,
        max_attempts=record.max_attempts,
    )
    _get_durable_run_queue().append_event(new_run_id, "run_forked", {
        "parent_run_id": record.id,
        "kind": payload["fork_kind"],
        "checkpoint": payload.get("resume_from"),
    })
    return created


def _compare_durable_runs(left, right, queue):
    def details(record):
        events = queue.events(record.id, 0, 10000)
        path = [
            {
                "node_id": event["payload"].get("node_id"),
                "op": event["payload"].get("op"),
                "agent": event["payload"].get("agent"),
            }
            for event in events if event["event"] == "node_enter"
        ]
        mutations = [
            {
                "sequence": event["sequence"],
                "tool": event["payload"].get("name"),
                "node_id": event["payload"].get("node_id"),
                "result": event["payload"].get("result"),
            }
            for event in events
            if event["event"] == "tool" and event["payload"].get("name") in {"modify_harness", "manage_harness", "modify_identity"}
        ]
        result = record.result if isinstance(record.result, dict) else {"result": record.result}
        stats = result.get("stats", {}) if isinstance(result, dict) else {}
        return {"record": record.as_dict(include_payload=False), "output": result.get("result"), "stats": stats, "path": path, "mutations": mutations}

    left_details, right_details = details(left), details(right)
    common = 0
    for left_step, right_step in zip(left_details["path"], right_details["path"]):
        if left_step != right_step:
            break
        common += 1
    numeric = ("cost_actual", "cost_estimated", "input_tokens_actual", "output_tokens_actual", "node_steps", "model_calls", "tool_calls")
    delta = {
        field: float(right_details["stats"].get(field, 0) or 0) - float(left_details["stats"].get(field, 0) or 0)
        for field in numeric
    }
    return {
        "left": left_details,
        "right": right_details,
        "same_output": left_details["output"] == right_details["output"],
        "path": {
            "common_prefix": common,
            "left_only": left_details["path"][common:],
            "right_only": right_details["path"][common:],
        },
        "delta": delta,
    }


def notify_clients(state):
    # Incremental events carry node traces and streamed text. Re-broadcasting
    # the entire (up to 500-entry) trace history for every state transition
    # made both Studio and Void repeatedly parse large JSON payloads. New
    # WebSocket clients and the HTTP recovery endpoint still receive the full
    # snapshot, while routine state notifications stay compact.
    payload = dict(state)
    payload.pop("node_traces", None)
    message = json.dumps(payload, separators=(",", ":"))
    for client in list(ws_clients):
        try:
            client.send(message)
        except Exception:
            ws_clients.discard(client)


def notify_output(msg_type, data):
    """向所有 WebSocket 客户端推送输出，并递增 _tick 强制重渲染"""
    handle = _current_interactive_run()
    execution_state = handle.state
    accumulated_outputs = handle.outputs
    handle.touch()
    execution_state["_tick"] = (execution_state.get("_tick", 0) + 1) % 1000000
    if msg_type == "run_started":
        pipeline_run_id = str((data or {}).get("run_id") or "")
        change_transaction_id = str(
            (data or {}).get("change_transaction_id")
            or (f"run-{pipeline_run_id}" if pipeline_run_id else "")
        )
        execution_state["pipeline_run_id"] = pipeline_run_id
        execution_state["change_transaction_id"] = change_transaction_id
        notify_clients(execution_state)
    elif msg_type == "input_required":
        # An interactive run can visit the same model node many times.  Seal
        # every completed projection before accepting another user turn so a
        # later response from the same Agent cannot be concatenated onto the
        # previous chat bubble.
        for output in accumulated_outputs:
            output["sealed"] = True
        execution_state["waiting_for_input"] = True
        notify_clients(execution_state)
    elif msg_type == "approval_required":
        with handle.approval_lock:
            execution_state["waiting_for_input"] = True
            execution_state["pending_approval"] = copy.deepcopy(data)
            execution_state["status"] = "waiting_approval"
        notify_clients(execution_state)
    elif msg_type == "approval":
        with handle.approval_lock:
            execution_state["waiting_for_input"] = False
            execution_state["pending_approval"] = None
            execution_state["status"] = "running"
        notify_clients(execution_state)
    elif msg_type == "model_output_truncated":
        warning = {"type": msg_type, **(copy.deepcopy(data) if isinstance(data, dict) else {})}
        warnings = execution_state.setdefault("warnings", [])
        warnings.append(warning)
        del warnings[:-20]
        notify_clients(execution_state)
    elif msg_type in {"run_limit_exceeded", "cancelled", "error"}:
        status = "limit_exceeded" if msg_type == "run_limit_exceeded" else msg_type
        execution_state["status"] = status
        detail = copy.deepcopy(data) if isinstance(data, dict) else {}
        execution_state["termination"] = {
            **detail,
            "kind": status,
            "message": str(detail.get("message", "")),
            "at": time.time(),
        }
        notify_clients(execution_state)
    elif msg_type == "done":
        done_status = str((data or {}).get("status") or "completed")
        if execution_state.get("termination") is None and done_status != "completed":
            execution_state["termination"] = {
                "kind": done_status,
                "message": str((data or {}).get("message", "")),
                "at": time.time(),
            }
        execution_state["status"] = done_status
        notify_clients(execution_state)

    # Keep a bounded, loop-aware execution timeline for the Studio inspector.
    # WebSocket clients receive every event immediately; this copy is the HTTP
    # fallback and lets a user click any previous node invocation.
    node_id = data.get("node_id") if isinstance(data, dict) else None
    traces = execution_state.setdefault("node_traces", [])
    if msg_type == "node_input" and node_id:
        traces.append({
            "sequence": len(traces) + 1,
            "node_id": node_id,
            "op": data.get("op", ""),
            "agent": data.get("agent", ""),
            "status": "entered",
            "input": data.get("input"),
            "last_output": data.get("last_output"),
            "output": None,
            "model": {"request": None, "response": "", "tool_calls": []},
            "tools": [],
            "usage": {},
            "retries": [],
            "artifacts": [],
            "error": None,
            "stats": {},
            "started_at": time.time(),
        })
        if len(traces) > 500:
            del traces[:-500]
    elif node_id:
        trace = _trace_for_node(node_id)
        if trace is not None:
            if msg_type == "node_enter":
                trace["status"] = "running"
            elif msg_type == "model_request":
                trace["model"]["request"] = {
                    key: value for key, value in data.items()
                    if key not in {"run_id", "node_id"}
                }
            elif msg_type == "token":
                trace["model"]["response"] = str(trace["model"].get("response", "")) + str(data.get("text", ""))
            elif msg_type == "model_response":
                trace["model"]["response"] = data.get("text", trace["model"].get("response", ""))
                trace["model"]["tool_calls"] = data.get("tool_calls", [])
            elif msg_type == "provider_usage":
                trace["usage"] = {
                    key: data.get(key) for key in (
                        "model", "request_ids", "attempts", "reconnects", "input_tokens",
                        "cached_input_tokens", "output_tokens",
                    )
                }
            elif msg_type == "node_retry":
                trace["retries"].append({
                    "attempt": data.get("attempt"), "max_attempts": data.get("max_attempts"),
                    "message": data.get("message", ""),
                })
            elif msg_type == "node_error":
                trace["error"] = {
                    "type": data.get("type", "Error"), "message": data.get("message", ""),
                    "attempt": data.get("attempt"), "max_attempts": data.get("max_attempts"),
                }
            elif msg_type == "node_input_override":
                trace["input"] = data.get("input")
                trace["stats"]["debug_input_override"] = True
            elif msg_type == "node_skipped":
                trace["output"] = data.get("output")
                trace["stats"]["debug_skipped"] = True
            elif msg_type == "debug_retry":
                trace["input"] = data.get("input")
                trace["error"] = None
                trace["status"] = "running"
                trace["retries"].append({
                    "attempt": data.get("attempt"), "max_attempts": 10,
                    "message": f"Debugger retry after: {data.get('previous_error', '')}",
                })
            elif msg_type == "tool":
                trace["tools"].append({
                    "name": data.get("name", ""),
                    "arguments": data.get("arguments"),
                    "result": data.get("result"),
                })
            elif msg_type == "blocked":
                trace["tools"].append({
                    "name": data.get("tool", ""),
                    "blocked": True,
                    "reason": data.get("reason", ""),
                })
            elif msg_type == "node_output":
                trace["output"] = data.get("output")
                trace["status"] = data.get("status", "ok")
                output = data.get("output")
                if isinstance(output, dict) and isinstance(output.get("artifacts"), list):
                    trace["artifacts"] = output.get("artifacts", [])
            elif msg_type == "node_exit":
                trace["status"] = "error" if data.get("status") == "error" else "completed"
                trace["completed_at"] = time.time()
                trace["duration_ms"] = round((trace["completed_at"] - trace.get("started_at", trace["completed_at"])) * 1000, 2)
                trace["stats"] = {**trace.get("stats", {}), **(data.get("stats", {}) or {})}

    if msg_type == "token":
        agent = data.get("agent", "unknown")
        text = data.get("text", "")
        if accumulated_outputs and accumulated_outputs[-1]["agent"] == agent and not accumulated_outputs[-1].get("sealed") and not accumulated_outputs[-1].get("tools") and not accumulated_outputs[-1].get("blocked") and not accumulated_outputs[-1].get("sub_harness"):
            accumulated_outputs[-1]["text"] += text
        else:
            accumulated_outputs.append({"id": len(accumulated_outputs), "agent": agent, "text": text, "tools": [], "blocked": [], "sealed": False})
    elif msg_type == "model_response":
        agent = data.get("agent", "unknown")
        response_text = str(data.get("text", "") or "")
        if accumulated_outputs and accumulated_outputs[-1].get("agent") == agent and not accumulated_outputs[-1].get("sealed"):
            # The streamed tokens are the display source.  model_response is
            # also a reliable fallback for providers that do not stream.
            if not accumulated_outputs[-1].get("text") and response_text:
                accumulated_outputs[-1]["text"] = response_text
            accumulated_outputs[-1]["sealed"] = True
        elif response_text:
            accumulated_outputs.append({
                "id": len(accumulated_outputs), "agent": agent,
                "text": response_text, "tools": [], "blocked": [], "sealed": True,
            })
    elif msg_type == "tool":
        agent = data.get("agent", "system")
        tool_entry = {"name": data.get("name", ""), "result": data.get("result", "")}
        if accumulated_outputs and accumulated_outputs[-1]["agent"] == agent:
            accumulated_outputs[-1].setdefault("tools", []).append(tool_entry)
        else:
            accumulated_outputs.append({"id": len(accumulated_outputs), "agent": agent, "text": "", "tools": [tool_entry], "blocked": [], "sealed": True})
    elif msg_type == "blocked":
        agent = data.get("agent", "system")
        blocked_entry = {"name": data.get("tool", ""), "reason": data.get("reason", "")}
        if accumulated_outputs and accumulated_outputs[-1]["agent"] == agent:
            accumulated_outputs[-1].setdefault("blocked", []).append(blocked_entry)
        else:
            accumulated_outputs.append({"id": len(accumulated_outputs), "agent": agent, "text": "", "tools": [], "blocked": [blocked_entry], "sealed": True})
    elif msg_type == "error":
        error_text = f"\u274c {data.get('message', '')}"
        if (
            accumulated_outputs
            and accumulated_outputs[-1].get("agent") == "system"
            and accumulated_outputs[-1].get("text") == error_text
        ):
            return
        accumulated_outputs.append({"id": len(accumulated_outputs), "agent": "system", "text": error_text, "tools": [], "blocked": [], "sealed": True})
    elif msg_type == "sub_harness_start":
        # 子 Harness 开始：创建一个新气泡，包含嵌套子 session
        accumulated_outputs.append({
            "id": len(accumulated_outputs),
            "agent": data.get("parent_agent", "system"),
            "text": "",
            "tools": [],
            "blocked": [],
            "sub_harness": {
                "harness_id": data.get("harness_id", ""),
                "harness_name": data.get("harness_name", ""),
                "slots": data.get("slots", {}),
                "messages": [],
                "status": "running",
            }
        })
    elif msg_type == "sub_token":
        # 子 Harness token：追加到最近的 sub_harness 气泡中
        harness_id = data.get("harness_id", "")
        agent = data.get("agent", "unknown")
        text = data.get("text", "")
        # 找到对应的 sub_harness 气泡
        for output in reversed(accumulated_outputs):
            sh = output.get("sub_harness")
            if sh and sh["harness_id"] == harness_id:
                msgs = sh["messages"]
                if msgs and msgs[-1]["agent"] == agent and not msgs[-1].get("tools"):
                    msgs[-1]["text"] += text
                else:
                    msgs.append({"agent": agent, "text": text, "tools": []})
                break
    elif msg_type == "sub_tool":
        # 子 Harness 工具调用
        harness_id = data.get("harness_id", "")
        agent = data.get("agent", "system")
        tool_entry = {"name": data.get("name", ""), "result": data.get("result", "")}
        for output in reversed(accumulated_outputs):
            sh = output.get("sub_harness")
            if sh and sh["harness_id"] == harness_id:
                msgs = sh["messages"]
                if msgs and msgs[-1]["agent"] == agent:
                    msgs[-1].setdefault("tools", []).append(tool_entry)
                else:
                    msgs.append({"agent": agent, "text": "", "tools": [tool_entry]})
                break
    elif msg_type == "sub_harness_end":
        # 子 Harness 结束
        harness_id = data.get("harness_id", "")
        for output in reversed(accumulated_outputs):
            sh = output.get("sub_harness")
            if sh and sh["harness_id"] == harness_id:
                sh["status"] = "completed"
                output["sealed"] = True
                break

    msg = json.dumps({
        "type": msg_type,
        "scope": {
            "workspace": execution_state.get("workspace", ""),
            "harness": execution_state.get("harness", ""),
            "agents": execution_state.get("agents", {}),
            "mode": execution_state.get("mode", "agent"),
            "run_id": execution_state.get("run_id", 0),
        },
        "data": data,
    })
    for client in list(ws_clients):
        try:
            client.send(msg)
        except Exception:
            ws_clients.discard(client)


def _find_env_dirs():
    """扫描所有 environment 目录：统一目录 + 兼容旧路径"""
    result = []
    # 统一目录：environment/<name>/ 每个子目录就是一个 environment
    if ENVIRONMENT_DIR.exists():
        for d in sorted(ENVIRONMENT_DIR.iterdir()):
            if d.is_dir() and (d / "tools").exists():
                result.append(str(d))
    # 兼容旧的 .environment 路径
    for d in _LEGACY_ENV_DIRS:
        if d.exists() and str(d) not in result:
            result.append(str(d))
    return result


def _get_identity_skills(identity_name):
    skills_dir = resolve_resource_path(
        IDENTITY_DIR,
        identity_name,
        "ego",
        "skills",
        label="identity skills path",
    )
    if not skills_dir.exists():
        return []
    result = []
    for sd in sorted(skills_dir.iterdir()):
        if sd.is_dir() and (sd / "meta.json").exists():
            result.append(sd.name)
    return result


def _get_identity_knowledge(identity_name):
    knowledge_dir = resolve_resource_path(
        IDENTITY_DIR,
        identity_name,
        "ego",
        "knowledge",
        label="identity knowledge path",
    )
    if not knowledge_dir.exists():
        return []
    result = []
    for kd in sorted(knowledge_dir.iterdir()):
        if kd.is_dir() and (kd / "meta.json").exists():
            result.append(kd.name)
    return result


def _get_env_tools(env_path_str):
    tools_dir = Path(env_path_str) / "tools"
    if not tools_dir.exists():
        return []
    result = []
    for td in sorted(tools_dir.iterdir()):
        if td.is_dir() and (td / "meta.json").exists():
            result.append(td.name)
    return result


def _get_env_knowledge(env_path_str):
    knowledge_dir = Path(env_path_str) / "knowledge"
    if not knowledge_dir.exists():
        return []
    result = []
    for kd in sorted(knowledge_dir.iterdir()):
        if kd.is_dir() and (kd / "meta.json").exists():
            result.append(kd.name)
    return result


class InvalidJSONBody(ValueError):
    pass


class APIHandler(BaseHTTPRequestHandler):
    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (InvalidJSONBody, UnsafeResourcePath) as error:
            try:
                self._send_error(str(error), 400)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

    def log_message(self, format, *args):
        pass

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._send_security_headers(cors=True)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, msg, status=400):
        self._send_json({"error": msg}, status)

    def _send_security_headers(self, *, cors=False):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if self.path.startswith("/api/") or self.path.startswith("/v1/"):
            self.send_header("Cache-Control", "no-store")
        origin = self.headers.get("Origin", "")
        if cors and origin and is_trusted_local_origin(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def _guard_browser_request(self, *, require_json=False):
        origin = self.headers.get("Origin", "")
        if origin and not is_trusted_local_origin(origin):
            self._send_error("This local EgoAgent API rejects requests from untrusted browser origins", 403)
            return False
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            self._send_error("Invalid Content-Length", 400)
            return False
        if length < 0 or length > _MAX_JSON_BODY_BYTES:
            self._send_error(f"Request body exceeds {_MAX_JSON_BODY_BYTES} bytes", 413)
            return False
        # Keep origin-less local CLI/SDK clients backwards compatible (some
        # stdlib clients send JSON bytes as application/x-www-form-urlencoded).
        # Browser mutation requests are the CSRF boundary and must be explicit.
        if require_json and length > 0 and origin:
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                self._send_error("Content-Type must be application/json", 415)
                return False
        return True

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        try:
            data = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise InvalidJSONBody("Malformed JSON request body") from error
        if not isinstance(data, dict):
            raise InvalidJSONBody("JSON request body must be an object")
        return data

    @staticmethod
    def _resource_path(root, *segments, label="resource"):
        """Resolve public resource ids through the shared confinement rule."""

        return resolve_resource_path(
            root,
            *(unquote(str(segment)) for segment in segments),
            label=label,
        )

    @staticmethod
    def _resource_name(value, label="resource"):
        return validate_resource_segment(unquote(str(value)), label=label)

    @staticmethod
    def _identity_reference(value):
        """Normalize the UI's legacy ``identity/<name>`` reference safely."""

        raw = unquote(str(value or "")).replace("\\", "/").strip("/")
        parts = raw.split("/")
        if len(parts) == 1:
            name = validate_resource_segment(parts[0], label="identity name")
        elif len(parts) == 2 and parts[0] == "identity":
            name = validate_resource_segment(parts[1], label="identity name")
        else:
            raise UnsafeResourcePath("Invalid identity reference")
        return f"identity/{name}"

    @staticmethod
    def _environment_dir(path_b64):
        """Resolve the legacy opaque Environment handle against live roots."""

        encoded = unquote(str(path_b64 or ""))
        try:
            decoded = base64.b64decode(
                encoded.encode("ascii"), altchars=b"-_", validate=True
            ).decode("utf-8")
        except (ValueError, UnicodeError) as error:
            raise UnsafeResourcePath("Invalid environment path encoding") from error
        return resolve_registered_root(decoded, _find_env_dirs(), label="environment")

    @staticmethod
    def _interactive_run(data=None, *, required=False):
        """Resolve the live execution explicitly addressed by an API request."""
        try:
            return interactive_execution.resolve(data if isinstance(data, dict) else {}, required=required)
        except InteractiveExecutionError:
            return None

    def _send_execution_operation(self, operation, data):
        try:
            self._send_json(operation(data))
        except InteractiveExecutionError as error:
            self._send_error(str(error), error.status)

    @staticmethod
    def _resolve_session_dir(name):
        """Resolve a public session id without allowing path traversal.

        Current sessions live directly below ``sessions/``.  A small number of
        legacy builds nested them one directory deeper, so those are supported
        by leaf-name lookup while every returned path is still confined to the
        sessions root.
        """
        raw_name = unquote(str(name or "")).strip().strip("/")
        if raw_name.startswith("taskbench/"):
            parts = raw_name.split("/")
            if len(parts) != 3 or any(not part or Path(part).name != part or part in {".", ".."} for part in parts[1:]):
                raise ValueError("Invalid Task Bench session id")
            task_root = (_PROJECT_ROOT_FOR_IMPORTS / ".egoagent" / "task_runs").resolve()
            resolved = (task_root / parts[1] / "session" / parts[2]).resolve()
            try:
                resolved.relative_to(task_root)
            except ValueError as error:
                raise ValueError("Task Bench session escapes its storage root") from error
            if resolved.is_dir():
                return resolved
            raise FileNotFoundError(raw_name)
        if not raw_name or Path(raw_name).name != raw_name or raw_name in {".", ".."}:
            raise ValueError("Invalid session id")
        root = SESSIONS_DIR.resolve()
        candidates = [SESSIONS_DIR / raw_name]
        if SESSIONS_DIR.is_dir():
            candidates.extend(parent / raw_name for parent in SESSIONS_DIR.iterdir() if parent.is_dir())
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
                resolved.relative_to(root)
            except (OSError, ValueError):
                continue
            if resolved.is_dir():
                return resolved
        raise FileNotFoundError(raw_name)

    @classmethod
    def _trajectory_reader(cls, name):
        session_dir = cls._resolve_session_dir(name)
        trajectory_path = session_dir / "trajectory.jsonl"
        if not trajectory_path.is_file():
            raise FileNotFoundError(f"Session '{name}' has no native trajectory (it may predate trajectory recording)")
        return session_dir, TrajectoryReader(trajectory_path)

    def _get_sessions_history(self, *, workspace=None, project_id="", include_archived=False):
        """Get session history from saved session directories."""
        history = []
        if not SESSIONS_DIR.is_dir():
            return history
        portfolio_sessions = {
            item["name"]: item
            for item in _project_portfolio().list_sessions(
                workspace=workspace,
                project_id=str(project_id or ""),
                include_archived=bool(include_archived),
                limit=5000,
            )
        }
        for d in sorted(SESSIONS_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if not d.is_dir():
                continue
            portfolio_info = portfolio_sessions.get(d.name)
            if portfolio_info is None:
                continue
            parts = d.name.split("_")
            # Extract harness name and timestamp from directory name like "coder_react_20260628_113151"
            harness = "_".join(parts[:-2]) if len(parts) >= 3 else d.name
            info = {
                "id": d.name,
                "name": d.name,
                "path": str(d),
                "timestamp": d.stat().st_mtime,
                "harness": harness,
                "identity": "",
                "message_count": 0,
                "working_message_count": 0,
                "summary": "",
                "has_trajectory": (d / "trajectory.jsonl").is_file(),
                "trajectory_events": 0,
                "trajectory_agents": [],
                "health": None,
                "lineage": None,
            }
            info.update(portfolio_info)
            working_file = d / "messages.json"
            if working_file.exists():
                try:
                    working = json.loads(working_file.read_text(encoding="utf-8"))
                    info["working_message_count"] = len(working)
                except (json.JSONDecodeError, OSError):
                    pass
            msgs_file = d / "full_messages.json"
            if not msgs_file.exists():
                msgs_file = working_file
            if msgs_file.exists():
                try:
                    msgs = json.loads(msgs_file.read_text(encoding="utf-8"))
                    info["message_count"] = len(msgs)
                    # Extract first user message as summary
                    for m in msgs:
                        if m.get("role") == "user":
                            info["summary"] = str(m.get("content", ""))[:80]
                            break
                except (json.JSONDecodeError, OSError):
                    pass
            trajectory_file = d / "trajectory.jsonl"
            if trajectory_file.is_file():
                try:
                    session_meta_file = d / "session.json"
                    session_meta = json.loads(session_meta_file.read_text(encoding="utf-8")) if session_meta_file.is_file() else {}
                    info["trajectory_events"] = int(session_meta.get("trajectory_events", 0) or 0)
                    info["trajectory_agents"] = list(session_meta.get("trajectory_agents", []))
                    info["health"] = session_meta.get("health") if isinstance(session_meta.get("health"), dict) else None
                    # Full hash/pair validation is intentionally deferred until
                    # selection; scanning every large trace made Session list
                    # rendering scale with all historical tokens.
                    info["trajectory_valid"] = None
                except (OSError, ValueError, TypeError):
                    info["trajectory_valid"] = False
            lineage = read_session_lineage(d)
            if lineage:
                info["lineage"] = {
                    "operation": lineage.get("operation"),
                    "merge_mode": lineage.get("merge_mode"),
                    "parents": [
                        str(parent.get("name") or "")
                        for parent in lineage.get("parents", [])
                        if isinstance(parent, dict) and parent.get("name")
                    ],
                    "created_at": lineage.get("created_at"),
                }
            history.append(info)
            if len(history) >= 50:
                break
        task_runs_root = _PROJECT_ROOT_FOR_IMPORTS / ".egoagent" / "task_runs"
        if not workspace and not project_id and task_runs_root.is_dir():
            for trajectory_file in task_runs_root.glob("*/session/*/trajectory.jsonl"):
                d = trajectory_file.parent
                run_id = trajectory_file.parents[2].name
                step_id = d.name
                info = {
                    "id": f"taskbench/{run_id}/{step_id}",
                    "name": f"taskbench/{run_id}/{step_id}",
                    "path": str(d),
                    "timestamp": trajectory_file.stat().st_mtime,
                    "harness": "task_bench",
                    "identity": "",
                    "message_count": 0,
                    "working_message_count": 0,
                    "summary": f"Task Bench run {run_id}, step {step_id}",
                    "has_trajectory": True,
                    "trajectory_events": 0,
                    "trajectory_agents": [],
                    "trajectory_valid": None,
                    "health": None,
                }
                try:
                    session_meta_file = d / "session.json"
                    session_meta = json.loads(session_meta_file.read_text(encoding="utf-8")) if session_meta_file.is_file() else {}
                    info["trajectory_events"] = int(session_meta.get("trajectory_events", 0) or 0)
                    info["trajectory_agents"] = list(session_meta.get("trajectory_agents", []))
                    info["health"] = session_meta.get("health") if isinstance(session_meta.get("health"), dict) else None
                    working_file = d / "messages.json"
                    if working_file.is_file():
                        messages = json.loads(working_file.read_text(encoding="utf-8"))
                        info["working_message_count"] = len(messages)
                        info["message_count"] = len(messages)
                except (OSError, ValueError, TypeError):
                    pass
                history.append(info)
        history.sort(key=lambda item: float(item.get("timestamp", 0)), reverse=True)
        return history[:100]

    def do_OPTIONS(self):
        origin = self.headers.get("Origin", "")
        if not origin or not is_trusted_local_origin(origin):
            self._send_error("Untrusted browser origin", 403)
            return
        self.send_response(204)
        self._send_security_headers(cors=True)
        self.send_header("Access-Control-Allow-Methods", "GET,PUT,POST,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # ==================== GET ====================

    def do_GET(self):
        if not self._guard_browser_request():
            return
        parsed_url = urlparse(self.path)
        path = parsed_url.path

        if heart_flow_api and heart_flow_api.handle_get(
            self,
            path,
            parsed_url,
            service=heart_flow_api.FlowRelayService(HEART_FLOW_STATE_PATH),
            portfolio=_project_portfolio(),
            runs=interactive_runs,
        ):
            return

        if path == "/api/security/settings":
            query = parse_qs(parsed_url.query)
            workspace_raw = str((query.get("workspace") or [str(_PROJECT_ROOT_FOR_IMPORTS)])[0])
            try:
                workspace = Path(workspace_raw).expanduser().resolve()
                settings, capability = _workspace_security(workspace)
                policy = _interactive_permission_policy(workspace, "agent", {"pipeline": {}}, ())
            except (OSError, ValueError) as error:
                self._send_error(f"Invalid workspace: {error}", 400)
                return
            self._send_json({
                "workspace": str(workspace),
                "settings": settings,
                "sandbox": capability,
                "effective_policy": policy.public(),
            })

        elif path == "/api/coc/characters":
            from tabletop.coc_identity import public_character

            characters = []
            for identity_dir in sorted(IDENTITY_DIR.iterdir(), key=lambda item: item.name):
                if not (identity_dir / "id.json").is_file():
                    continue
                try:
                    card = public_character(identity_dir)
                    card.pop("identity_path", None)
                    characters.append(card)
                except (ValueError, OSError, json.JSONDecodeError):
                    continue
            self._send_json({"characters": characters})

        elif path == "/api/runtime/container":
            query = parse_qs(parsed_url.query)
            engine = str((query.get("engine") or ["docker"])[0]).lower()
            if engine not in {"docker", "podman"}:
                self._send_error("engine must be docker or podman", 400)
                return
            from process_backends import container_runtime_status

            self._send_json(container_runtime_status(engine))

        elif path == "/api/packages/installed":
            self._send_json({"packages": list_installed_packages(_PROJECT_ROOT_FOR_IMPORTS)})

        elif path == "/api/packages":
            query = parse_qs(parsed_url.query)
            self._send_json({"packages": _get_package_registry().search(
                (query.get("query") or [""])[0],
                component=(query.get("component") or [None])[0],
                trust=(query.get("trust") or [None])[0],
            )})

        elif path.startswith("/api/packages/"):
            parts = [unquote(value) for value in path.split("/") if value][2:]
            if not parts:
                self._send_error("Package name is required", 400)
                return
            item = _get_package_registry().get(parts[0], parts[1] if len(parts) > 1 else None)
            if item is None:
                self._send_error("Package not found", 404)
                return
            self._send_json(item)

        elif path == "/api/runs/compare":
            query = parse_qs(parsed_url.query)
            left_id = str((query.get("left") or [""])[0])
            right_id = str((query.get("right") or [""])[0])
            queue = _get_durable_run_queue()
            left, right = queue.get(left_id), queue.get(right_id)
            if left is None or right is None:
                self._send_error("Both comparison runs must exist", 404)
                return
            self._send_json(_compare_durable_runs(left, right, queue))

        elif path == "/api/runs":
            query = parse_qs(parsed_url.query)
            status = (query.get("status") or [None])[0]
            try:
                limit = int((query.get("limit") or [100])[0])
            except (TypeError, ValueError):
                limit = 100
            records = _get_durable_run_queue().list(status=status, limit=limit)
            self._send_json({"runs": [record.as_dict(include_payload=True) for record in records]})

        elif path == "/api/runs/recovery":
            queue = _get_durable_run_queue()
            records = queue.list(status="interrupted", limit=500)
            self._send_json({
                "runs": [
                    {
                        **record.as_dict(include_payload=False),
                        "checkpoint": queue.checkpoint_preview(record.id),
                        "actions": ["resume", "inspect", "discard"],
                    }
                    for record in records
                ]
            })

        elif path.startswith("/api/runs/") and path.endswith("/handoff"):
            run_id = unquote(path.split("/api/runs/", 1)[1].rsplit("/handoff", 1)[0]).strip("/")
            record = _get_durable_run_queue().get(run_id)
            if record is None:
                self._send_error("Run not found", 404)
                return
            isolation = record.payload.get("isolation") or {}
            if not isolation.get("workspace") or not isolation.get("source_workspace"):
                self._send_error("Run does not use an isolated workspace", 409)
                return
            try:
                self._send_json(preview_handoff(
                    isolation["source_workspace"], isolation["workspace"], run_id
                ))
            except (OSError, ValueError) as error:
                self._send_error(str(error), 409)

        elif path.startswith("/api/runs/") and path.endswith("/events"):
            run_id = unquote(path.split("/api/runs/", 1)[1].rsplit("/events", 1)[0]).strip("/")
            query = parse_qs(parsed_url.query)
            try:
                after = int((query.get("after") or [0])[0])
                limit = int((query.get("limit") or [1000])[0])
            except (TypeError, ValueError):
                self._send_error("after and limit must be integers", 400)
                return
            record = _get_durable_run_queue().get(run_id)
            if record is None:
                self._send_error("Run not found", 404)
                return
            self._send_json({"run_id": run_id, "events": _get_durable_run_queue().events(run_id, after, limit)})

        elif path.startswith("/api/runs/"):
            run_id = unquote(path.split("/api/runs/", 1)[1]).strip("/")
            queue = _get_durable_run_queue()
            record = queue.get(run_id)
            if record is None:
                self._send_error("Run not found", 404)
                return
            self._send_json({**record.as_dict(), "checkpoint": queue.checkpoint_preview(run_id)})

        elif path == "/api/harnesses":
            harnesses = [
                d.name for d in HARNESS_DIR.iterdir()
                if d.is_dir() and (d / "config.json").exists()
            ]
            self._send_json(sorted(harnesses))

        elif path == "/api/harnesses/detailed":
            result = []
            for d in sorted(HARNESS_DIR.iterdir(), key=lambda x: x.name):
                if d.is_dir() and (d / "config.json").exists():
                    try:
                        cfg = json.loads((d / "config.json").read_text(encoding="utf-8"))
                        slots = cfg.get("slots", {})
                        result.append({
                            "name": d.name,
                            "description": cfg.get("description", ""),
                            "slot_count": len(slots),
                            "slots": list(slots.keys()),
                            "component": cfg.get("component") if isinstance(cfg.get("component"), dict) else None,
                        })
                    except Exception:
                        result.append({"name": d.name, "description": "", "slot_count": 0, "slots": [], "component": None})
            self._send_json(result)

        elif path == "/api/knowledge":
            result = []
            if IDENTITY_DIR.is_dir():
                for idir in sorted(IDENTITY_DIR.iterdir()):
                    if not idir.is_dir():
                        continue
                    kb_dir = idir / "ego" / "knowledge"
                    if not kb_dir.is_dir():
                        continue
                    for kdir in sorted(kb_dir.iterdir()):
                        if not kdir.is_dir():
                            continue
                        meta_file = kdir / "meta.json"
                        content_file = kdir / "content.md"
                        entry = {
                            "identity": idir.name,
                            "name": kdir.name,
                            "description": "",
                            "content_preview": "",
                        }
                        if meta_file.exists():
                            try:
                                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                                entry["description"] = meta.get("description", "")
                            except:
                                pass
                        if content_file.exists():
                            try:
                                txt = content_file.read_text(encoding="utf-8")
                                entry["content_preview"] = txt[:200]
                            except:
                                pass
                        result.append(entry)
            self._send_json(result)

        elif path.startswith("/api/harness/") and path.endswith("/blueprint"):
            name = self._resource_name(
                path.split("/api/harness/", 1)[1].rsplit("/blueprint", 1)[0].strip("/"),
                "harness name",
            )
            try:
                loaded = HarnessBlueprintService(_PROJECT_ROOT_FOR_IMPORTS).load(name)
                loaded.pop("config", None)
                loaded["ok"] = True
                self._send_json(loaded)
            except BlueprintError as error:
                self._send_error(str(error), 404)

        elif path == "/api/harness-blueprint/guide":
            self._send_json({"ok": True, "guide": blueprint_guide()})

        elif path == "/api/dag/contracts":
            self._send_json(dag_contract_catalog())

        elif path.startswith("/api/harness/"):
            name = self._resource_name(path.split("/api/harness/", 1)[1], "harness name")
            config_path = self._resource_path(HARNESS_DIR, name, "config.json", label="harness path")
            if not config_path.exists():
                self._send_error(f"Harness not found: {name}", 404)
                return
            config = json.loads(config_path.read_text(encoding="utf-8"))
            self._send_json(config)

        elif path == "/api/identities":
            identities = []
            for d in sorted(IDENTITY_DIR.iterdir(), key=lambda x: x.name):
                if d.is_dir() and (d / "id.json").exists():
                    try:
                        id_data = json.loads((d / "id.json").read_text(encoding="utf-8"))
                        skills = _get_identity_skills(d.name)
                        llm = id_data.get("llm", {}) or {}
                        personality = id_data.get("personality", {}) or {}
                        identities.append({
                            "name": d.name,
                            "description": id_data.get("description", ""),
                            "model": llm.get("model", "") or id_data.get("model", ""),
                            "skill_count": len(skills),
                            "traits": personality.get("traits", []) or id_data.get("traits", []),
                            "role": id_data.get("role", ""),
                        })
                    except Exception:
                        identities.append({"name": d.name, "description": "", "model": "", "skill_count": 0, "traits": []})
            self._send_json(identities)

        elif path.startswith("/api/identity/") and not any(
            x in path for x in ["/skill/", "/knowledge/", "/superego"]
        ):
            name = self._resource_name(path.split("/api/identity/", 1)[1], "identity name")
            identity_dir = self._resource_path(IDENTITY_DIR, name, label="identity path")
            id_path = identity_dir / "id.json"
            if not id_path.exists():
                self._send_error(f"Identity not found: {name}", 404)
                return

            id_data = json.loads(id_path.read_text(encoding="utf-8"))

            superego_path = identity_dir / "superego" / "config.json"
            superego = None
            if superego_path.exists():
                superego = json.loads(superego_path.read_text(encoding="utf-8"))

            self._send_json({
                "name": name,
                "id": id_data,
                "superego": superego,
                "skills": _get_identity_skills(name),
                "knowledge": _get_identity_knowledge(name),
            })

        elif "/superego" in path and path.startswith("/api/identity/"):
            parts = path.split("/")
            name_idx = parts.index("identity") + 1
            name = self._resource_name(parts[name_idx], "identity name")
            superego_path = self._resource_path(
                IDENTITY_DIR, name, "superego", "config.json", label="identity path"
            )
            if superego_path.exists():
                self._send_json(json.loads(superego_path.read_text(encoding="utf-8")))
            else:
                self._send_json({})

        elif "/skill/" in path and path.startswith("/api/identity/"):
            parts = path.split("/")
            name_idx = parts.index("identity") + 1
            skill_idx = parts.index("skill") + 1
            name = self._resource_name(parts[name_idx], "identity name")
            sname = self._resource_name(parts[skill_idx], "skill name")

            skill_dir = self._resource_path(
                IDENTITY_DIR, name, "ego", "skills", sname, label="skill path"
            )
            meta_path = skill_dir / "meta.json"
            if not meta_path.exists():
                self._send_error(f"Skill not found: {sname}", 404)
                return

            meta = json.loads(meta_path.read_text(encoding="utf-8"))

            scripts = {}
            scripts_dir = skill_dir / "scripts"
            if scripts_dir.exists():
                for sf in scripts_dir.iterdir():
                    if sf.suffix == ".py":
                        scripts[sf.name] = sf.read_text(encoding="utf-8")

            self._send_json({"meta": meta, "scripts": scripts})

        elif "/knowledge/" in path and path.startswith("/api/identity/"):
            parts = path.split("/")
            name_idx = parts.index("identity") + 1
            know_idx = parts.index("knowledge") + 1
            name = self._resource_name(parts[name_idx], "identity name")
            kname = self._resource_name(parts[know_idx], "knowledge name")

            content_dir = self._resource_path(
                IDENTITY_DIR, name, "ego", "knowledge", kname, label="knowledge path"
            )
            meta_path = content_dir / "meta.json"
            if not meta_path.exists():
                self._send_error(f"Knowledge not found: {kname}", 404)
                return

            meta = json.loads(meta_path.read_text(encoding="utf-8"))

            content = ""
            for cf in content_dir.iterdir():
                if cf.suffix == ".txt":
                    content = cf.read_text(encoding="utf-8")
                    break

            self._send_json({"meta": meta, "content": content})

        elif path == "/api/environments":
            envs = _find_env_dirs()
            result = []
            for ep in envs:
                epath = Path(ep)
                tools = _get_env_tools(ep)
                knowledge = _get_env_knowledge(ep)
                result.append({
                    "path": ep,
                    "path_b64": base64.urlsafe_b64encode(ep.encode()).decode(),
                    "name": epath.parent.name if epath.name == ".environment" else epath.name,
                    "tools": tools,
                    "tool_count": len(tools),
                    "knowledge": knowledge,
                    "knowledge_count": len(knowledge),
                })
            self._send_json(result)

        elif "/tool/" in path and path.startswith("/api/environment/"):
            parts = path.split("/")
            env_idx = parts.index("environment") + 1
            tool_idx = parts.index("tool") + 1
            path_b64 = parts[env_idx]
            tname = self._resource_name(parts[tool_idx], "tool name")
            environment_dir = self._environment_dir(path_b64)
            tool_dir = self._resource_path(
                environment_dir, "tools", tname, label="environment tool path"
            )
            meta_path = tool_dir / "meta.json"
            if not meta_path.exists():
                self._send_error(f"Tool not found: {tname}", 404)
                return

            meta = json.loads(meta_path.read_text(encoding="utf-8"))

            scripts = {}
            scripts_dir = tool_dir / "scripts"
            if scripts_dir.exists():
                for sf in scripts_dir.iterdir():
                    if sf.suffix == ".py":
                        scripts[sf.name] = sf.read_text(encoding="utf-8")

            self._send_json({"meta": meta, "scripts": scripts})

        elif "/knowledge/" in path and path.startswith("/api/environment/"):
            parts = path.split("/")
            env_idx = parts.index("environment") + 1
            know_idx = parts.index("knowledge") + 1
            path_b64 = parts[env_idx]
            kname = self._resource_name(parts[know_idx], "knowledge name")
            environment_dir = self._environment_dir(path_b64)
            kdir = self._resource_path(
                environment_dir, "knowledge", kname, label="environment knowledge path"
            )
            if not kdir.exists():
                self._send_error(f"Knowledge not found: {kname}", 404)
                return

            meta = {}
            meta_path = kdir / "meta.json"
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))

            content = ""
            for cf in kdir.iterdir():
                if cf.suffix in (".md", ".txt"):
                    content = cf.read_text(encoding="utf-8")
                    break

            self._send_json({"meta": meta, "content": content})

        elif path.startswith("/api/environment/"):
            path_b64 = unquote(path.split("/api/environment/", 1)[1])
            epath = self._environment_dir(path_b64)
            if not epath.exists():
                self._send_error(f"Environment not found: {epath}", 404)
                return

            self._send_json({
                "path": str(epath),
                "path_b64": path_b64,
                "tools": _get_env_tools(str(epath)),
                "knowledge": _get_env_knowledge(str(epath)),
            })

        elif path == "/api/trajectory/settings":
            self._send_json({
                "settings": load_collection_settings(),
                "native_collection": {
                    "enabled": True,
                    "description": "Every new session is always recorded to sessions/<session>/trajectory.jsonl.",
                },
            })

        elif path == "/api/training/annotations":
            query = parse_qs(parsed_url.query)
            session = (query.get("session") or [None])[0]
            target_type = (query.get("target_type") or [None])[0]
            try:
                store = TrainingAnnotationStore(TRAINING_ANNOTATIONS_PATH)
                self._send_json({
                    "annotations": store.list(session=session, target_type=target_type),
                    "summary": store.summary(),
                })
            except (OSError, ValueError) as error:
                self._send_error(f"Unable to read training annotations: {error}", 500)

        elif path.startswith("/api/session/") and "/trajectory" in path:
            suffixes = ("/trajectory/summary", "/trajectory/events", "/trajectory/model-calls")
            suffix = next((value for value in suffixes if path.endswith(value)), None)
            if suffix is None:
                self._send_error("Unknown trajectory endpoint", 404)
                return
            name = path.split("/api/session/", 1)[1].rsplit(suffix, 1)[0]
            try:
                session_dir, reader = self._trajectory_reader(name)
            except ValueError as error:
                self._send_error(str(error), 400)
                return
            except FileNotFoundError as error:
                self._send_error(str(error), 404)
                return
            if suffix == "/trajectory/summary":
                summary = reader.summary()
                summary["session"] = session_dir.name
                self._send_json(summary)
                return
            if suffix == "/trajectory/model-calls":
                query = parse_qs(parsed_url.query)
                include_incomplete = str((query.get("include_incomplete") or [""])[0]).lower() in {"1", "true", "yes"}
                self._send_json({
                    "session": session_dir.name,
                    "model_calls": reader.model_calls(include_incomplete=include_incomplete),
                })
                return
            query = parse_qs(parsed_url.query)
            try:
                after = max(0, int((query.get("after") or [0])[0]))
                limit = max(1, min(2000, int((query.get("limit") or [500])[0])))
            except (TypeError, ValueError):
                self._send_error("after and limit must be integers", 400)
                return
            event_types = [item for raw in query.get("types", []) for item in str(raw).split(",") if item]
            agents = [item for raw in query.get("agents", []) for item in str(raw).split(",") if item]
            selected = reader.events(
                after=after,
                limit=limit + 1,
                event_types=event_types,
                agents=agents,
            )
            has_more = len(selected) > limit
            selected = selected[:limit]
            self._send_json({
                "session": session_dir.name,
                "events": selected,
                "after": after,
                "next_after": int(selected[-1].get("sequence", after)) if selected else after,
                "has_more": has_more,
            })

        elif path == "/api/projects":
            query = parse_qs(parsed_url.query)
            current_workspace = (query.get("workspace") or [None])[0]
            include_archived = (query.get("include_archived") or ["0"])[0] == "1"
            try:
                projects = _project_portfolio().list_projects(
                    current_workspace=current_workspace,
                    include_archived=include_archived,
                )
            except (OSError, ValueError, TypeError) as error:
                self._send_error(f"Unable to load project portfolio: {error}", 400)
                return
            runs = interactive_execution.list()
            by_workspace = {}
            for run in runs:
                key = workspace_key(run.get("workspace"))
                if not key:
                    continue
                by_workspace.setdefault(key, []).append(run)
            for project in projects:
                project_runs = by_workspace.get(workspace_key(project.get("workspace")), [])
                project["run_count"] = len(project_runs)
                project["running_count"] = sum(bool(run.get("running")) for run in project_runs)
                project["waiting_count"] = sum(bool(run.get("waiting_for_input") or run.get("pending_approval")) for run in project_runs)
                project["recent_runs"] = project_runs[:8]
            self._send_json({"schema": "ego.project-portfolio.view.v1", "projects": projects})

        elif path == "/api/projects/sessions":
            query = parse_qs(parsed_url.query)
            try:
                sessions = _project_portfolio().list_sessions(
                    workspace=(query.get("workspace") or [None])[0],
                    project_id=(query.get("project_id") or [""])[0],
                    include_archived=(query.get("include_archived") or ["0"])[0] == "1",
                    limit=int((query.get("limit") or [500])[0]),
                )
            except (OSError, ValueError, TypeError) as error:
                self._send_error(f"Unable to load project Sessions: {error}", 400)
                return
            for session in sessions:
                lineage = read_session_lineage(Path(session["path"]))
                if lineage:
                    session["lineage"] = {
                        "operation": lineage.get("operation"),
                        "merge_mode": lineage.get("merge_mode"),
                        "parents": [
                            str(parent.get("name") or "")
                            for parent in lineage.get("parents", [])
                            if isinstance(parent, dict) and parent.get("name")
                        ],
                        "created_at": lineage.get("created_at"),
                    }
            self._send_json({"schema": "ego.project-session-list.v1", "sessions": sessions})

        elif path == "/api/sessions":
            query = parse_qs(parsed_url.query)
            self._send_json(self._get_sessions_history(
                workspace=(query.get("workspace") or [None])[0],
                project_id=(query.get("project_id") or [""])[0],
                include_archived=(query.get("include_archived") or ["0"])[0] == "1",
            ))

        elif path.startswith("/api/session/") and path.endswith("/lineage"):
            name = path.split("/api/session/", 1)[1].rsplit("/lineage", 1)[0]
            try:
                session_dir = self._resolve_session_dir(name)
            except ValueError as error:
                self._send_error(str(error), 400)
                return
            except FileNotFoundError:
                self._send_error(f"Session not found: {unquote(name)}", 404)
                return
            self._send_json({"session": session_dir.name, "lineage": read_session_lineage(session_dir)})

        elif path.startswith("/api/session/") and path.endswith("/cached-report"):
            name = path.split("/api/session/", 1)[1].rsplit("/cached-report", 1)[0]
            name = self._resource_name(name, "session id")
            # 查找 sessions 目录中是否有对该 session 的分析结果
            # 分析结果保存在 session_analyzer 的 session 目录下
            report = None
            for sd in sorted(SESSIONS_DIR.iterdir(), key=lambda x: x.name, reverse=True):
                if not sd.is_dir():
                    continue
                msgs_file = sd / "messages.json"
                if msgs_file.exists():
                    try:
                        msgs = json.loads(msgs_file.read_text(encoding="utf-8"))
                        # 检查是否有对目标 session 的分析（第一条 user 消息包含 session 名）
                        if len(msgs) >= 2 and name in str(msgs[0].get("content", "")):
                            # 找最后一条 assistant 消息作为 report
                            for m in reversed(msgs):
                                if m.get("role") == "assistant" and m.get("content") and len(m["content"]) > 50:
                                    report = m["content"]
                                    break
                            if report:
                                break
                    except:
                        pass
            if report:
                self._send_json({"report": report, "session_name": name})
            else:
                self._send_json({})

        elif path.startswith("/api/session/") and path.endswith("/evaluate"):
            name = path.split("/api/session/", 1)[1].rsplit("/evaluate", 1)[0]
            try:
                session_dir = self._resolve_session_dir(name)
            except ValueError as error:
                self._send_error(str(error), 400)
                return
            except FileNotFoundError:
                name = unquote(name)
                self._send_error(f"Session not found: {name}", 404)
                return
            name = session_dir.name
            import sys
            eval_script = IDENTITY_DIR / "dante" / "ego" / "skills" / "evaluate_session" / "scripts"
            sys.path.insert(0, str(eval_script))
            try:
                from evaluate_session import evaluate_session
                report = evaluate_session(str(session_dir))
                self._send_json({"report": report, "session_name": name})
            finally:
                sys.path.pop(0)

        elif path.startswith("/api/session/") and path.endswith("/messages"):
            name = path.split("/api/session/", 1)[1].rsplit("/messages", 1)[0]
            try:
                session_dir = self._resolve_session_dir(name)
            except ValueError as error:
                self._send_error(str(error), 400)
                return
            except FileNotFoundError:
                self._send_error(f"Session not found: {unquote(name)}", 404)
                return
            name = session_dir.name
            msgs_file = session_dir / "full_messages.json"
            if not msgs_file.exists():
                msgs_file = session_dir / "messages.json"
            msgs = annotated_session_messages(session_dir) if msgs_file.exists() else []
            self._send_json({"id": name, "messages": msgs})

        elif path.startswith("/api/script/"):
            # GET /api/script/<harness_name>/<script_name>
            parts = path.split("/api/script/", 1)[1].split("/", 1)
            if len(parts) != 2:
                self._send_error("Usage: /api/script/<harness>/<script_name>", 400)
                return
            harness_name = self._resource_name(parts[0], "harness name")
            script_name = self._resource_name(parts[1], "script name")
            script_path = self._resource_path(
                HARNESS_DIR,
                harness_name,
                "scripts",
                f"{script_name}.py",
                label="harness script path",
            )
            if not script_path.exists():
                self._send_json({"code": "def run(ctx):\n    response = ctx[\"response\"]\n    # 处理逻辑\n    return {\"response\": response}\n"})
            else:
                self._send_json({"code": script_path.read_text(encoding="utf-8")})

        elif path == "/api/execution/state":
            query = parse_qs(parsed_url.query)
            lookup = {
                "run_id": (query.get("run_id") or [None])[0],
                "workspace": (query.get("workspace") or [None])[0],
            }
            try:
                self._send_json(interactive_execution.state(lookup, include_outputs=True))
            except InteractiveExecutionError as error:
                self._send_error(str(error), error.status)

        elif path == "/api/execution/runs":
            query = parse_qs(parsed_url.query)
            workspace = (query.get("workspace") or [None])[0]
            self._send_json({"runs": interactive_execution.list(workspace)})

        elif path.startswith("/api/analyze-status/"):
            task_id = path.split("/")[-1]
            if task_id not in _async_tasks:
                self._send_error("Task not found", 404)
                return
            task = _async_tasks[task_id]
            response = {"task_id": task_id, "status": task["status"]}
            if task.get("progress"):
                response["progress"] = task["progress"]
            if task["status"] == "completed":
                response["result"] = task["result"]
            elif task["status"] == "error":
                response["error"] = task["error"]
            self._send_json(response)

        # ---- Change Tracking: GET /api/session/changes ----
        elif path == "/api/session/changes/content":
            qs = parse_qs(urlparse(self.path).query)
            selector = qs.get("id", [None])[0]
            content = get_change_content(selector)
            if content is None:
                self._send_error("Change not found", 404)
            else:
                self._send_json(content)

        elif path == "/api/session/changes":
            qs = parse_qs(urlparse(self.path).query)
            transaction_id = qs.get("transaction_id", [None])[0]
            workspace = qs.get("workspace", [None])[0]
            changes = get_changes(
                transaction_id,
                workspace=workspace,
                live_only=bool(workspace) and qs.get("include_stale", ["0"])[0] != "1",
                exclude_internal=bool(workspace) and qs.get("include_internal", ["0"])[0] != "1",
            )
            self._send_json(changes)

        # ---- File Search: GET /api/files/search?q=<query>&workspace=<path> ----
        elif path == "/api/files/search":
            qs = parse_qs(urlparse(self.path).query)
            query = qs.get("q", [""])[0]
            workspace = qs.get("workspace", [str(Path(__file__).resolve().parent.parent)])[0]

            if not query:
                self._send_json([])
                return

            workspace_path = Path(workspace)
            if not workspace_path.is_dir():
                self._send_error(f"Workspace not found: {workspace}", 404)
                return

            # Walk the workspace and fuzzy-match file names
            results = []
            query_lower = query.lower()
            try:
                for p in workspace_path.rglob("*"):
                    if not p.is_file():
                        continue
                    # Skip hidden dirs and common non-code dirs
                    parts = p.relative_to(workspace_path).parts
                    if any(part.startswith(".") or part in ("node_modules", "__pycache__", "dist", ".git") for part in parts):
                        continue
                    name = p.name.lower()
                    rel = str(p.relative_to(workspace_path))
                    # Match: query is substring of name or relative path, or fnmatch pattern
                    if query_lower in name or query_lower in rel.lower() or _fnmatch.fnmatch(name, query):
                        results.append({"path": str(p), "relative": rel, "name": p.name})
                    if len(results) >= 50:
                        break
            except Exception:
                pass

            self._send_json(results)

        # ---- File Content: GET /api/files/content?path=<filepath> ----
        elif path == "/api/files/content":
            qs = parse_qs(urlparse(self.path).query)
            file_path = qs.get("path", [""])[0]

            if not file_path:
                self._send_error("Missing 'path' query parameter", 400)
                return

            fp = Path(file_path)
            if not fp.exists():
                self._send_error(f"File not found: {file_path}", 404)
                return
            if not fp.is_file():
                self._send_error(f"Not a file: {file_path}", 400)
                return

            try:
                content = fp.read_text(encoding="utf-8")
                self._send_json({"path": str(fp), "content": content, "size": fp.stat().st_size})
            except UnicodeDecodeError:
                self._send_error("File is not UTF-8 text", 400)
            except Exception as e:
                self._send_error(f"Cannot read file: {e}", 500)

        # ---- OpenAI-Compatible: GET /v1/models ----
        elif path == "/v1/models":
            self._send_json({"object": "list", "data": EGOAGENT_MODELS})

        # ---- Model-backed IDE features: GET /api/ai/status ----
        elif path == "/api/ai/status":
            query = parse_qs(urlparse(self.path).query)
            self._send_json(get_ai_status(query.get("role", ["chat"])[0]))

        # ---- Typed codebase context: GET status/search ----
        elif path == "/api/context/index/status":
            query = parse_qs(urlparse(self.path).query)
            try:
                self._send_json(index_status(query.get("workspace", [""])[0]))
            except ValueError as error:
                self._send_error(str(error), 400)

        elif path == "/api/context/search":
            query = parse_qs(urlparse(self.path).query)
            try:
                self._send_json(retrieve(
                    query.get("workspace", [""])[0],
                    query.get("query", [""])[0],
                    limit=int(query.get("limit", [16])[0]),
                    mode=query.get("mode", ["auto"])[0],
                ))
            except (TypeError, ValueError) as error:
                self._send_error(str(error), 400)

        # ---- Checkpoints: GET /api/checkpoints ----
        elif path == "/api/checkpoints":
            if list_checkpoints:
                qs = parse_qs(urlparse(self.path).query)
                self._send_json(list_checkpoints(workspace=qs.get("workspace", [None])[0]))
            else:
                self._send_json([])

        # ---- Checkpoints: GET /api/checkpoints/<id> ----
        elif path.startswith("/api/checkpoints/") and path != "/api/checkpoints/create" and path != "/api/checkpoints/rollback" and path != "/api/checkpoints/clear":
            cp_id = unquote(path.split("/api/checkpoints/", 1)[1])
            if get_checkpoint:
                found = get_checkpoint(cp_id)
                if found:
                    self._send_json(found)
                else:
                    self._send_error(f"Checkpoint not found: {cp_id}", 404)
            else:
                self._send_error("Checkpoints module not available", 500)

        # ---- Agent Templates: GET /api/agent/templates ----
        elif path == "/api/agent/templates":
            if list_agent_templates:
                self._send_json(list_agent_templates())
            else:
                self._send_json([])

        # ---- Sessions History: GET /api/sessions/history ----
        elif path == "/api/sessions/history":
            query = parse_qs(parsed_url.query)
            sessions = self._get_sessions_history(
                workspace=(query.get("workspace") or [None])[0],
                project_id=(query.get("project_id") or [""])[0],
                include_archived=(query.get("include_archived") or ["0"])[0] == "1",
            )
            self._send_json(sessions)

        # ---- Project Rules: GET /api/rules ----
        elif path == "/api/rules":
            if get_rules:
                self._send_json(get_rules())
            else:
                self._send_json([])

        # ---- Project Rules: GET /api/rules/<name> ----
        elif path.startswith("/api/rules/") and "/api/rules/" in path:
            rule_name = unquote(path.split("/api/rules/", 1)[1])
            if get_rules:
                rules = get_rules()
                found = None
                for r in rules:
                    if r.get("name") == rule_name or r.get("name") == rule_name + ".md":
                        found = r
                        break
                if found:
                    self._send_json(found)
                else:
                    self._send_error(f"Rule not found: {rule_name}", 404)
            else:
                self._send_error("Rules module not available", 500)

        # ---- Memory: GET /api/memory ----
        elif path == "/api/memory":
            if get_memories:
                self._send_json(get_memories())
            else:
                self._send_json([])

        # ---- Memory Search: GET /api/memory/search?q=... ----
        elif path == "/api/memory/search":
            qs = parse_qs(urlparse(self.path).query)
            query = qs.get("q", [""])[0]
            if search_memories and query:
                self._send_json(search_memories(query=query))
            else:
                self._send_json([])

        elif path == "/api/workspace":
            requested = parse_qs(urlparse(self.path).query).get("workspace", [""])[0]
            workspace = os.path.abspath(requested) if requested else os.environ.get("EGOAGENT_WORKSPACE", os.getcwd())
            if requested and not os.path.isdir(workspace):
                self._send_error("Workspace directory does not exist", 404)
            else:
                self._send_json({"workspace": workspace, "name": os.path.basename(workspace)})

        # ---- Model Endpoints: GET /api/model-endpoints ----
        elif path == "/api/model-endpoints":
            if list_model_endpoints:
                self._send_json(list_model_endpoints())
            else:
                self._send_json([])

        elif path == "/api/model-profiles":
            if list_model_profiles:
                self._send_json({"profiles": list_model_profiles(), "roles": get_role_assignments()})
            else:
                self._send_json({"profiles": [], "roles": {}})

        # ---- Experiments: GET /api/experiments ----
        elif path.rstrip("/") == "/api/experiments":
            if list_experiments:
                self._send_json(list_experiments())
            else:
                self._send_json([])

        # ---- Experiment Detail: GET /api/experiments/<id> ----
        elif path.startswith("/api/experiments/") and "/stats" not in path:
            exp_id = path.split("/api/experiments/", 1)[1].strip("/")
            if get_experiment and exp_id:
                result = get_experiment(exp_id)
                self._send_json(result)
            else:
                self._send_error("Experiment not found", 404)

        # ---- Experiment Stats: GET /api/experiments/<id>/stats ----
        elif path.startswith("/api/experiments/") and path.endswith("/stats"):
            exp_id = path.split("/api/experiments/", 1)[1].rsplit("/stats", 1)[0]
            if get_experiment_stats and exp_id:
                self._send_json(get_experiment_stats(exp_id))
            else:
                self._send_error("Experiment not found", 404)

        else:
            # Try extended API routes first
            ext_resp, ext_code = _handle_ext_api("GET", path)
            if ext_resp is not None:
                self._send_json(ext_resp, ext_code or 200)
                return
            # Fall through to static files
            # Serve static files from dist/
            dist_dir = Path(__file__).resolve().parent / "dist"
            # Map / to /index.html
            file_path = path.lstrip("/") or "index.html"
            full_path = dist_dir / file_path
            # SPA fallback: if not found, serve index.html
            if not full_path.exists() or not full_path.is_file():
                full_path = dist_dir / "index.html"
            if full_path.exists() and full_path.is_file():
                content = full_path.read_bytes()
                content_type = "text/html"
                suffix = full_path.suffix.lower()
                mime_map = {
                    ".js": "application/javascript",
                    ".css": "text/css",
                    ".json": "application/json",
                    ".svg": "image/svg+xml",
                    ".png": "image/png",
                    ".ico": "image/x-icon",
                    ".woff2": "font/woff2",
                    ".woff": "font/woff",
                    ".ttf": "font/ttf",
                }
                content_type = mime_map.get(suffix, "text/html")
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(content)))
                self._send_security_headers(cors=True)
                self.end_headers()
                self.wfile.write(content)
            else:
                self._send_error("Not found", 404)

    # ==================== PUT ====================

    def do_PUT(self):
        if not self._guard_browser_request(require_json=True):
            return
        path = urlparse(self.path).path

        if path.startswith("/api/script/"):
            # PUT /api/script/<harness_name>/<script_name> — save script code
            parts = path.split("/api/script/", 1)[1].split("/", 1)
            if len(parts) != 2:
                self._send_error("Usage: /api/script/<harness>/<script_name>", 400)
                return
            harness_name = self._resource_name(parts[0], "harness name")
            script_name = self._resource_name(parts[1], "script name")
            scripts_dir = self._resource_path(
                HARNESS_DIR, harness_name, "scripts", label="harness script path"
            )
            scripts_dir.mkdir(parents=True, exist_ok=True)
            script_path = self._resource_path(
                scripts_dir, f"{script_name}.py", label="script file"
            )
            data = self._read_body()
            code = data.get("code", "")
            script_path.write_text(code, encoding="utf-8")
            self._send_json({"ok": True, "path": str(script_path)})

        elif path.startswith("/api/harness/"):
            name = self._resource_name(path.split("/api/harness/", 1)[1], "harness name")
            data = self._read_body()
            pipeline = data.get("pipeline") if isinstance(data, dict) else None
            if pipeline and pipeline.get("nodes"):
                from pipeline_schema import validate_component_manifest, validate_pipeline
                validation_errors = validate_pipeline(pipeline)
                validation_errors.extend(validate_component_manifest(data.get("component")))
                if validation_errors:
                    self._send_json({"error": "Invalid DAG", "details": validation_errors}, 400)
                    return
            config_dir = self._resource_path(HARNESS_DIR, name, label="harness path")
            config_dir.mkdir(parents=True, exist_ok=True)
            config_path = config_dir / "config.json"

            config_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self._send_json({"ok": True, "name": name})

        elif path.startswith("/api/identity/") and not any(
            x in path for x in ["/skill/", "/knowledge/", "/superego", "/clone"]
        ):
            name = self._resource_name(path.split("/api/identity/", 1)[1], "identity name")
            identity_dir = self._resource_path(IDENTITY_DIR, name, label="identity path")
            identity_dir.mkdir(parents=True, exist_ok=True)
            (identity_dir / "ego" / "skills").mkdir(parents=True, exist_ok=True)
            (identity_dir / "ego" / "knowledge").mkdir(parents=True, exist_ok=True)
            (identity_dir / "superego").mkdir(parents=True, exist_ok=True)

            data = self._read_body()
            id_path = identity_dir / "id.json"
            id_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self._send_json({"ok": True, "name": name})

        elif "/superego" in path and path.startswith("/api/identity/"):
            parts = path.split("/")
            name_idx = parts.index("identity") + 1
            name = self._resource_name(parts[name_idx], "identity name")

            identity_dir = self._resource_path(IDENTITY_DIR, name, label="identity path")
            identity_dir.mkdir(parents=True, exist_ok=True)
            (identity_dir / "superego").mkdir(parents=True, exist_ok=True)

            data = self._read_body()
            superego_path = identity_dir / "superego" / "config.json"
            superego_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self._send_json({"ok": True})

        elif "/skill/" in path and path.startswith("/api/identity/"):
            parts = path.split("/")
            name_idx = parts.index("identity") + 1
            skill_idx = parts.index("skill") + 1
            name = self._resource_name(parts[name_idx], "identity name")
            sname = self._resource_name(parts[skill_idx], "skill name")

            skill_dir = self._resource_path(
                IDENTITY_DIR, name, "ego", "skills", sname, label="skill path"
            )
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "scripts").mkdir(parents=True, exist_ok=True)

            data = self._read_body()
            meta = data.get("meta", {})
            scripts = data.get("scripts", {})

            (skill_dir / "meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            for script_name, script_content in scripts.items():
                script_path = self._resource_path(
                    skill_dir / "scripts", script_name, label="skill script file"
                )
                script_path.write_text(
                    script_content, encoding="utf-8"
                )

            self._send_json({"ok": True})

        elif "/knowledge/" in path and path.startswith("/api/identity/"):
            parts = path.split("/")
            name_idx = parts.index("identity") + 1
            know_idx = parts.index("knowledge") + 1
            name = self._resource_name(parts[name_idx], "identity name")
            kname = self._resource_name(parts[know_idx], "knowledge name")

            know_dir = self._resource_path(
                IDENTITY_DIR, name, "ego", "knowledge", kname, label="knowledge path"
            )
            know_dir.mkdir(parents=True, exist_ok=True)

            data = self._read_body()
            meta = data.get("meta", {})
            content = data.get("content", "")

            (know_dir / "meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (know_dir / f"{kname}.txt").write_text(content, encoding="utf-8")

            self._send_json({"ok": True})

        elif "/tool/" in path and path.startswith("/api/environment/"):
            parts = path.split("/")
            env_idx = parts.index("environment") + 1
            tool_idx = parts.index("tool") + 1
            path_b64 = parts[env_idx]
            tname = self._resource_name(parts[tool_idx], "tool name")
            environment_dir = self._environment_dir(path_b64)
            tool_dir = self._resource_path(
                environment_dir, "tools", tname, label="environment tool path"
            )
            tool_dir.mkdir(parents=True, exist_ok=True)
            (tool_dir / "scripts").mkdir(parents=True, exist_ok=True)

            data = self._read_body()
            meta = data.get("meta", {})
            scripts = data.get("scripts", {})

            (tool_dir / "meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            for script_name, script_content in scripts.items():
                script_path = self._resource_path(
                    tool_dir / "scripts", script_name, label="environment tool script"
                )
                script_path.write_text(
                    script_content, encoding="utf-8"
                )

            self._send_json({"ok": True})

        elif "/knowledge/" in path and path.startswith("/api/environment/"):
            parts = path.split("/")
            env_idx = parts.index("environment") + 1
            know_idx = parts.index("knowledge") + 1
            path_b64 = parts[env_idx]
            kname = self._resource_name(parts[know_idx], "knowledge name")
            environment_dir = self._environment_dir(path_b64)
            know_dir = self._resource_path(
                environment_dir, "knowledge", kname, label="environment knowledge path"
            )
            know_dir.mkdir(parents=True, exist_ok=True)

            data = self._read_body()
            meta = data.get("meta", {})
            content = data.get("content", "")

            (know_dir / "meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (know_dir / f"{kname}.txt").write_text(content, encoding="utf-8")

            self._send_json({"ok": True})

        # ---- Checkpoints: PUT /api/checkpoints/<id> ----
        elif path.startswith("/api/checkpoints/") and path.count("/") == 3:
            cp_id = path.split("/api/checkpoints/", 1)[1].strip("/")
            data = self._read_body()
            from checkpoint_manager import _checkpoints
            found = False
            for cp in _checkpoints:
                if cp.get("id") == cp_id:
                    if "label" in data:
                        cp["label"] = data["label"]
                    if "description" in data:
                        cp["description"] = data["description"]
                    found = True
                    break
            if found:
                self._send_json({"ok": True})
            else:
                self._send_error(f"Checkpoint not found: {cp_id}", 404)

        # ---- Rules: PUT /api/rules/<name> ----
        elif path.startswith("/api/rules/"):
            rule_name = unquote(path.split("/api/rules/", 1)[1])
            data = self._read_body()
            content = data.get("content", "")
            if create_rule:
                result = create_rule(name=rule_name, content=content)
                self._send_json(result)
            else:
                self._send_error("Rules module not available", 500)

        # ---- Experiments: PUT /api/experiments/<id> ----
        elif path.startswith("/api/experiments/"):
            exp_id = path.split("/api/experiments/", 1)[1].strip("/")
            data = self._read_body()
            # Update experiment in experiments.json
            exp_file = Path(__file__).resolve().parent.parent / "experiments" / "ab_experiments.json"
            if exp_file.exists():
                experiments = json.loads(exp_file.read_text(encoding="utf-8"))
            else:
                experiments = []
            found = False
            for exp in experiments:
                if exp.get("id") == exp_id:
                    exp.update(data)
                    found = True
                    break
            if found:
                exp_file.write_text(json.dumps(experiments, ensure_ascii=False, indent=2), encoding="utf-8")
                self._send_json({"ok": True})
            else:
                self._send_error(f"Experiment not found: {exp_id}", 404)

        else:
            self._send_error("Not found", 404)

    # ==================== POST ====================

    def do_POST(self):
        if not self._guard_browser_request(require_json=True):
            return
        path = urlparse(self.path).path

        if heart_flow_api and heart_flow_api.handle_post(
            self,
            path,
            service=heart_flow_api.FlowRelayService(HEART_FLOW_STATE_PATH),
            portfolio=_project_portfolio(),
            runs=interactive_runs,
        ):
            return

        if path == "/api/trajectory/settings":
            body = self._read_body()
            raw_settings = body.get("settings", body)
            if not isinstance(raw_settings, dict):
                self._send_error("settings must be an object", 400)
                return
            try:
                settings = save_collection_settings(
                    enabled=bool(raw_settings.get("enabled", False)),
                    destination=str(raw_settings.get("destination") or ""),
                    partition_by_date=bool(raw_settings.get("partition_by_date", True)),
                    partition_by_project=bool(raw_settings.get("partition_by_project", True)),
                )
            except (OSError, ValueError) as error:
                self._send_error(f"Unable to save trajectory collection settings: {error}", 400)
                return
            self._send_json({
                "ok": True,
                "settings": settings,
                "native_collection": {"enabled": True},
                "applies_to_active_run": True,
            })
            return

        if path == "/api/training/annotations":
            body = self._read_body()
            session = str(body.get("session") or "").strip()
            target_type = str(body.get("target_type") or "").strip()
            target_id = str(body.get("target_id") or "").strip()
            if not session:
                self._send_error("session is required", 400)
                return
            try:
                session_dir = self._resolve_session_dir(session)
                if target_type == "session":
                    target_id = session
                _, source_hash = resolve_target_source(session, session_dir, target_type, target_id)
                requested_hash = str(body.get("source_hash") or "").strip()
                if requested_hash and requested_hash != source_hash:
                    self._send_error("The annotated content changed; reload it before saving feedback", 409)
                    return
                annotation = TrainingAnnotationStore(TRAINING_ANNOTATIONS_PATH).upsert(
                    session=session,
                    target_type=target_type,
                    target_id=target_id,
                    source_hash=source_hash,
                    rating=str(body.get("rating") or "neutral"),
                    important=bool(body.get("important", False)),
                    include_in_training=bool(body.get("include_in_training", False)),
                    tags=body.get("tags") if isinstance(body.get("tags"), list) else [],
                    note=str(body.get("note") or ""),
                )
            except FileNotFoundError:
                self._send_error(f"Session not found: {session}", 404)
                return
            except (OSError, ValueError, TypeError) as error:
                self._send_error(str(error), 400)
                return
            self._send_json({"ok": True, "annotation": annotation})
            return

        if path == "/api/training/export":
            body = self._read_body()
            raw_sessions = body.get("sessions")
            if not isinstance(raw_sessions, list) or not raw_sessions:
                self._send_error("sessions must be a non-empty list", 400)
                return
            if len(raw_sessions) > 500:
                self._send_error("At most 500 sessions can be exported at once", 400)
                return
            destination_raw = str(body.get("destination") or "").strip()
            if destination_raw:
                destination = Path(destination_raw).expanduser().resolve()
            else:
                stamp = time.strftime("%Y%m%d_%H%M%S")
                destination = _PROJECT_ROOT_FOR_IMPORTS / ".egoagent" / "exports" / "training" / stamp
            try:
                sources = []
                seen = set()
                for raw_name in raw_sessions:
                    session = str(raw_name or "").strip()
                    if not session or session in seen:
                        continue
                    sources.append((session, self._resolve_session_dir(session)))
                    seen.add(session)
                if not sources:
                    raise ValueError("No valid session names were supplied")
                formats = body.get("formats")
                manifest = export_annotated_training_data(
                    sources,
                    destination,
                    store=TrainingAnnotationStore(TRAINING_ANNOTATIONS_PATH),
                    selection=str(body.get("selection") or "marked"),
                    formats=formats if isinstance(formats, list) else None,
                    include_reasoning=bool(body.get("include_reasoning", False)),
                )
            except FileNotFoundError as error:
                self._send_error(f"Session not found: {error}", 404)
                return
            except (OSError, ValueError, TypeError) as error:
                self._send_error(str(error), 400)
                return
            self._send_json({"ok": True, "manifest": manifest})
            return

        if path == "/api/projects/register":
            body = self._read_body()
            try:
                project = _project_portfolio().register_project(
                    body.get("workspace") or "",
                    title=body.get("title"),
                )
            except (OSError, ValueError, TypeError) as error:
                self._send_error(str(error), 400)
                return
            self._send_json({"ok": True, "project": project})
            return

        if path == "/api/projects/update":
            body = self._read_body()
            try:
                project = _project_portfolio().update_project(
                    str(body.get("project_id") or ""),
                    body.get("changes") if isinstance(body.get("changes"), dict) else {},
                )
            except KeyError as error:
                self._send_error(str(error), 404)
                return
            except (OSError, ValueError, TypeError) as error:
                self._send_error(str(error), 400)
                return
            self._send_json({"ok": True, "project": project})
            return

        if path == "/api/projects/session/update":
            body = self._read_body()
            try:
                session = _project_portfolio().update_session(
                    str(body.get("session") or ""),
                    body.get("changes") if isinstance(body.get("changes"), dict) else {},
                )
            except FileNotFoundError as error:
                self._send_error(f"Session not found: {error}", 404)
                return
            except (OSError, ValueError, TypeError) as error:
                self._send_error(str(error), 400)
                return
            self._send_json({"ok": True, "session": session})
            return

        if path.startswith("/api/session/") and path.endswith("/fork"):
            source_name = path.split("/api/session/", 1)[1].rsplit("/fork", 1)[0]
            body = self._read_body()
            try:
                result = SessionBranchService(
                    SESSIONS_DIR,
                    workspace=body.get("workspace") or _PROJECT_ROOT_FOR_IMPORTS,
                ).fork(
                    unquote(source_name),
                    destination_name=body.get("name") or body.get("destination"),
                )
            except SessionBranchError as error:
                self._send_error(str(error), 400)
                return
            except (OSError, ValueError, TypeError) as error:
                self._send_error(f"Unable to fork session: {error}", 500)
                return
            self._send_json(result)
            return

        if path == "/api/sessions/merge":
            body = self._read_body()
            try:
                left_name = str(body.get("left") or "")
                left_dir = APIHandler._resolve_session_dir(left_name)
                left_workspace, _provenance = infer_session_workspace(left_dir)
                target_workspace = str(body.get("target_workspace") or left_workspace or _PROJECT_ROOT_FOR_IMPORTS)
                result = SessionBranchService(
                    SESSIONS_DIR,
                    workspace=target_workspace,
                ).merge(
                    left_name,
                    str(body.get("right") or ""),
                    mode=str(body.get("mode") or "auto"),
                    destination_name=body.get("name") or body.get("destination"),
                    threshold_tokens=int(body.get("threshold_tokens") or 12000),
                    dialogue_rounds=int(body.get("dialogue_rounds") or 2),
                )
            except SessionBranchError as error:
                self._send_error(str(error), 400)
                return
            except (OSError, ValueError, TypeError) as error:
                self._send_error(f"Unable to merge sessions: {error}", 500)
                return
            except Exception as error:
                self._send_error(f"Model-backed merge failed: {error}", 502)
                return
            self._send_json(result)
            return

        if path.startswith("/api/session/") and path.endswith("/trajectory/export"):
            name = path.split("/api/session/", 1)[1].rsplit("/trajectory/export", 1)[0]
            body = self._read_body()
            try:
                session_dir, reader = self._trajectory_reader(name)
                destination_raw = str(body.get("destination") or "").strip()
                if destination_raw:
                    destination = Path(destination_raw).expanduser().resolve()
                else:
                    trace_id = str(reader.summary().get("trace_id") or session_dir.name)
                    safe_trace = "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in trace_id)
                    destination = _PROJECT_ROOT_FOR_IMPORTS / ".egoagent" / "exports" / "trajectories" / safe_trace
                manifest = export_training_data(
                    session_dir / "trajectory.jsonl",
                    destination,
                    include_reasoning=bool(body.get("include_reasoning", False)),
                    include_incomplete=bool(body.get("include_incomplete", False)),
                )
            except ValueError as error:
                self._send_error(str(error), 400)
                return
            except FileNotFoundError as error:
                self._send_error(str(error), 404)
                return
            except OSError as error:
                self._send_error(f"Unable to export trajectory: {error}", 500)
                return
            self._send_json({"ok": True, "manifest": manifest})
            return

        if path == "/api/security/settings":
            from security_settings import save_security_settings, sandbox_capability

            body = self._read_body()
            workspace_raw = str(body.get("workspace") or _PROJECT_ROOT_FOR_IMPORTS)
            raw_settings = body.get("settings", body)
            try:
                workspace = Path(workspace_raw).expanduser().resolve()
                settings = save_security_settings(workspace, raw_settings)
                capability = sandbox_capability(settings)
                policy = _interactive_permission_policy(workspace, "agent", {"pipeline": {}}, ())
            except (OSError, ValueError) as error:
                self._send_error(f"Unable to save security settings: {error}", 400)
                return
            self._send_json({
                "ok": True,
                "workspace": str(workspace),
                "settings": settings,
                "sandbox": capability,
                "effective_policy": policy.public(),
                "applies_to_active_run": False,
            })
            return

        if path == "/api/coc/characters":
            from tabletop.coc_identity import create_character_identity, public_character

            body = self._read_body()
            try:
                card_path = create_character_identity(
                    IDENTITY_DIR,
                    identity_name=str(body.get("identity_name", "")).strip(),
                    character_name=str(body.get("character_name", "")).strip(),
                    occupation=str(body.get("occupation", "investigator")).strip(),
                    stats=body.get("stats", {}) if isinstance(body.get("stats", {}), dict) else {},
                    skills=body.get("skills", {}) if isinstance(body.get("skills", {}), dict) else {},
                    equipment=body.get("equipment", []) if isinstance(body.get("equipment", []), list) else [],
                    description=str(body.get("description", "")).strip(),
                    age=body.get("age") if isinstance(body.get("age"), (int, float)) else None,
                    backstory=str(body.get("backstory", "")).strip(),
                    personality_traits=body.get("personality_traits", []) if isinstance(body.get("personality_traits", []), list) else [],
                )
                card = public_character(card_path)
                card.pop("identity_path", None)
                self._send_json({"ok": True, "character": card}, 201)
            except ValueError as error:
                status = 409 if "already exists" in str(error) else 400
                self._send_error(str(error), status)
            return

        if _handle_package_post(self, path):
            return

        if path in {
            "/api/harness-blueprint/validate",
            "/api/harness-blueprint/create",
            "/api/harness-blueprint/patch",
            "/api/harness-blueprint/rollback",
        }:
            body = self._read_body()
            service = HarnessBlueprintService(_PROJECT_ROOT_FOR_IMPORTS)
            try:
                if path.endswith("/validate"):
                    result = service.validate(body.get("blueprint", {}), name=body.get("harness_name"))
                elif path.endswith("/create"):
                    result = service.create(body.get("blueprint", {}), dry_run=bool(body.get("dry_run", False)))
                elif path.endswith("/patch"):
                    result = service.patch(
                        str(body.get("harness_name", "")),
                        body.get("operations", []),
                        expected_revision=body.get("expected_revision"),
                        dry_run=bool(body.get("dry_run", False)),
                        reason=str(body.get("reason", "")),
                        actor=str(body.get("actor", "studio")),
                    )
                else:
                    result = service.rollback(
                        str(body.get("transaction_id", "")),
                        expected_revision=body.get("expected_revision"),
                    )
                result.pop("config", None)
                if not result.get("dry_run", False) and path.endswith(("/create", "/patch", "/rollback")):
                    notify_output(
                        "harness_mutation",
                        {
                            "harness": result.get("harness"),
                            "action": result.get("action"),
                            "transaction_id": result.get("transaction_id"),
                            "revision": result.get("revision"),
                            "diff": result.get("diff", ""),
                        },
                    )
                self._send_json(result)
            except RevisionConflict as error:
                self._send_error(str(error), 409)
            except (BlueprintError, OSError, ValueError) as error:
                self._send_error(str(error), 400)

        elif path == "/api/runs":
            body = self._read_body()
            harness_name = self._resource_name(body.get("harness", "react_single"), "harness name")
            identity_name = self._resource_name(body.get("identity", "dante"), "identity name")
            harness_config = self._resource_path(
                HARNESS_DIR, harness_name, "config.json", label="harness path"
            )
            identity_config = self._resource_path(
                IDENTITY_DIR, identity_name, "id.json", label="identity path"
            )
            if not harness_config.is_file():
                self._send_error(f"Harness not found: {harness_name}", 404)
                return
            if not identity_config.is_file():
                self._send_error(f"Identity not found: {identity_name}", 404)
                return
            messages = body.get("messages", [])
            initial_data = body.get("initial_data", {})
            if not isinstance(messages, list) or not isinstance(initial_data, dict):
                self._send_error("messages must be an array and initial_data must be an object", 400)
                return
            mode = str(body.get("mode") or "agent").lower()
            if mode not in {"chat", "plan", "agent", "debug", "evolve", "evaluate"}:
                self._send_error("Unsupported run mode", 400)
                return
            mutation_targets = body.get("mutation_targets", [])
            if isinstance(mutation_targets, str):
                mutation_targets = [mutation_targets]
            if not isinstance(mutation_targets, list) or (mode == "evolve" and not mutation_targets):
                self._send_error("Evolve mode requires explicit mutation_targets", 400)
                return
            workspace = Path(body.get("workspace") or Path(__file__).resolve().parent.parent).resolve()
            if not workspace.is_dir():
                self._send_error(f"Workspace not found: {workspace}", 404)
                return
            run_id = _uuid.uuid4().hex
            isolation = None
            if body.get("isolate") is True:
                try:
                    isolation = create_isolated_workspace(workspace, run_id)
                except (OSError, ValueError) as error:
                    self._send_error(f"Could not create isolated workspace: {error}", 409)
                    return
            payload = {
                "harness": harness_name,
                "identity": identity_name,
                "messages": messages,
                "initial_data": initial_data,
                "workspace": isolation["workspace"] if isolation else str(workspace),
                "source_workspace": str(workspace),
                "isolation": isolation,
                "mode": mode,
                "mutation_targets": [str(value) for value in mutation_targets],
            }
            if body.get("resume_from"):
                payload["resume_from"] = str(body["resume_from"])
            try:
                record = _get_durable_run_queue().enqueue(
                    payload,
                    run_id=run_id,
                    priority=int(body.get("priority", 0)),
                    max_attempts=max(1, min(100, int(body.get("max_attempts", 3)))),
                    dedupe_key=str(body["dedupe_key"]) if body.get("dedupe_key") else None,
                )
                _start_durable_run_worker()
                self._send_json(record.as_dict(), 202)
            except (TypeError, ValueError) as error:
                self._send_error(str(error), 400)

        elif path.startswith("/api/runs/") and path.endswith(("/fork", "/replay")):
            action = "fork" if path.endswith("/fork") else "replay"
            run_id = unquote(path.split("/api/runs/", 1)[1].rsplit(f"/{action}", 1)[0]).strip("/")
            record = _get_durable_run_queue().get(run_id)
            if record is None:
                self._send_error("Run not found", 404)
                return
            body = self._read_body()
            try:
                created = _fork_durable_run(
                    record,
                    from_checkpoint=body.get("from_checkpoint", True) is True,
                    replay=action == "replay",
                    payload_overrides=body.get("payload_overrides", {}),
                )
                _start_durable_run_worker()
                self._send_json(created.as_dict(), 202)
            except (OSError, ValueError, json.JSONDecodeError) as error:
                self._send_error(str(error), 409)

        elif path.startswith("/api/runs/") and path.endswith("/handoff"):
            run_id = unquote(path.split("/api/runs/", 1)[1].rsplit("/handoff", 1)[0]).strip("/")
            record = _get_durable_run_queue().get(run_id)
            if record is None:
                self._send_error("Run not found", 404)
                return
            isolation = record.payload.get("isolation") or {}
            if not isolation.get("workspace") or not isolation.get("source_workspace"):
                self._send_error("Run does not use an isolated workspace", 409)
                return
            body = self._read_body()
            try:
                result = apply_handoff(
                    isolation["source_workspace"], isolation["workspace"], run_id,
                    body.get("paths", []), body.get("expected_revisions", {}),
                    confirm_delete=body.get("confirm_delete") is True,
                )
                self._send_json(result, 200 if result.get("ok") else 409)
            except (OSError, UnicodeError, ValueError) as error:
                self._send_error(str(error), 409)

        elif path.startswith("/api/runs/") and path.endswith("/cancel"):
            run_id = unquote(path.split("/api/runs/", 1)[1].rsplit("/cancel", 1)[0]).strip("/")
            record = _get_durable_run_queue().cancel(run_id)
            if record is None:
                self._send_error("Run not found", 404)
                return
            self._send_json(record.as_dict(include_payload=False), 202 if record.status == "running" else 200)

        elif path.startswith("/api/runs/") and path.endswith("/pause"):
            run_id = unquote(path.split("/api/runs/", 1)[1].rsplit("/pause", 1)[0]).strip("/")
            record = _get_durable_run_queue().pause(run_id)
            if record is None:
                self._send_error("Run not found", 404)
                return
            self._send_json(record.as_dict(include_payload=False), 202 if record.status == "running" else 200)

        elif path.startswith("/api/runs/") and path.endswith(("/resume", "/discard")):
            action = "resume" if path.endswith("/resume") else "discard"
            run_id = unquote(path.split("/api/runs/", 1)[1].rsplit(f"/{action}", 1)[0]).strip("/")
            body = self._read_body()
            try:
                durable_queue = _get_durable_run_queue()
                current = durable_queue.get(run_id)
                if action == "resume" and current is not None and current.status == "paused":
                    record = durable_queue.resume(run_id)
                else:
                    record = durable_queue.recover(
                        run_id,
                        action,
                        confirm_in_doubt=bool(body.get("confirm_in_doubt", False)),
                        allow_revision_conflicts=bool(body.get("allow_revision_conflicts", False)),
                    )
            except ValueError as error:
                self._send_error(str(error), 409)
                return
            if record is None:
                self._send_error("Run not found", 404)
                return
            if action == "resume":
                _start_durable_run_worker()
            self._send_json(record.as_dict(include_payload=False), 202 if action == "resume" else 200)

        elif path == "/api/execution/start":
            data = self._read_body()
            harness_name = self._resource_name(data.get("harness", ""), "harness name")
            agents = data.get("agents", {})
            if not isinstance(agents, dict):
                self._send_error("agents must be an object", 400)
                return
            agents = {
                str(slot): self._identity_reference(identity)
                for slot, identity in agents.items()
            }
            debug_mode = str(data.get("debug_mode", "auto"))
            if debug_mode not in {"auto", "paused", "step"}:
                self._send_error("debug_mode must be auto, paused or step", 400)
                return
            mode = str(data.get("mode", "agent") or "agent").lower()
            if mode not in {"chat", "plan", "agent", "debug", "evolve", "evaluate"}:
                self._send_error("mode must be chat, plan, agent, debug, evolve or evaluate", 400)
                return
            mutation_targets = data.get("mutation_targets", [])
            if isinstance(mutation_targets, str):
                mutation_targets = [mutation_targets]
            if not isinstance(mutation_targets, list):
                self._send_error("mutation_targets must be a list", 400)
                return
            mutation_targets = [str(value) for value in mutation_targets if str(value).strip()]
            if mode == "evolve" and not mutation_targets:
                self._send_error("Evolve mode requires at least one explicit mutation target", 400)
                return
            workspace_raw = str(data.get("workspace", "") or "").strip()
            try:
                workspace_path = (
                    Path(workspace_raw).expanduser().resolve()
                    if workspace_raw
                    else Path(__file__).resolve().parent.parent
                )
            except (OSError, RuntimeError, ValueError) as error:
                self._send_error(f"Invalid workspace: {error}", 400)
                return
            if not workspace_path.is_dir():
                self._send_error(f"Workspace not found: {workspace_path}", 404)
                return
            try:
                _project_portfolio().register_project(workspace_path)
            except (OSError, ValueError, TypeError) as error:
                self._send_error(f"Unable to register workspace: {error}", 400)
                return

            config_path = self._resource_path(
                HARNESS_DIR, harness_name, "config.json", label="harness path"
            )
            if not config_path.exists():
                self._send_error(f"Harness not found: {harness_name}", 404)
                return

            try:
                _security_settings, sandbox_status = _workspace_security(workspace_path)
                preview_policy = _interactive_permission_policy(
                    workspace_path,
                    mode,
                    json.loads(config_path.read_text(encoding="utf-8")),
                    mutation_targets,
                )
            except (OSError, ValueError, json.JSONDecodeError) as error:
                self._send_error(f"Unable to load workspace security policy: {error}", 400)
                return
            handle = interactive_execution.start(
                workspace=workspace_path,
                harness=harness_name,
                agents=agents,
                debug_mode=debug_mode,
                mode=mode,
                mutation_targets=mutation_targets,
                security=preview_policy.public(),
                sandbox=sandbox_status,
                worker_target=_run_harness_in_thread,
                worker_args=lambda created: (
                    harness_name,
                    agents,
                    created.input_queue,
                    created.run_id,
                    workspace_path,
                    mode,
                    mutation_targets,
                ),
            )
            self._send_json({"ok": True, "run_id": handle.run_id, "state": handle.snapshot()})

        elif path == "/api/execution/control":
            data = self._read_body()
            self._send_execution_operation(interactive_execution.control, data)

        elif path == "/api/execution/stop":
            data = self._read_body()
            self._send_execution_operation(interactive_execution.stop, data)

        elif path == "/api/execution/approval":
            data = self._read_body()
            self._send_execution_operation(interactive_execution.approval, data)

        elif path == "/api/execution/input":
            data = self._read_body()
            self._send_execution_operation(interactive_execution.input, data)

        elif path == "/api/environments":
            data = self._read_body()
            name = self._resource_name(str(data.get("name", "")).strip(), "environment name")
            # 在统一的 environment/ 目录下创建
            env_dir = self._resource_path(ENVIRONMENT_DIR, name, label="environment path")
            if env_dir.exists():
                self._send_error(f"Environment 已存在: {name}", 409)
                return
            env_dir.mkdir(parents=True, exist_ok=True)
            (env_dir / "tools").mkdir(exist_ok=True)
            (env_dir / "knowledge").mkdir(exist_ok=True)
            self._send_json({"ok": True, "name": name, "path": str(env_dir)})

        elif "/clone" in path and path.startswith("/api/identity/"):
            parts = path.split("/")
            name_idx = parts.index("identity") + 1
            name = self._resource_name(parts[name_idx], "identity name")

            data = self._read_body()
            new_name = self._resource_name(
                data.get("new_name", f"{name}_copy"), "identity name"
            )

            src = self._resource_path(IDENTITY_DIR, name, label="identity path")
            dst = self._resource_path(IDENTITY_DIR, new_name, label="identity path")

            if dst.exists():
                self._send_error(f"Identity already exists: {new_name}", 409)
                return

            shutil.copytree(str(src), str(dst))
            self._send_json({"ok": True, "name": new_name})

        elif path.startswith("/api/identity/") and path.endswith("/modify"):
            name = path.split("/api/identity/", 1)[1].rsplit("/modify", 1)[0]
            name = self._resource_name(name, "identity name")
            body = self._read_body()
            field = body.get("field", "")
            value = body.get("value", "")
            if not field or not value:
                self._send_error("Missing 'field' or 'value'")
                return
            import sys
            mod_script = IDENTITY_DIR / "dante" / "ego" / "skills" / "modify_identity" / "scripts"
            sys.path.insert(0, str(mod_script))
            try:
                from modify_identity import modify_identity
                result = modify_identity(name, field, value)
                self._send_json({"result": result})
            finally:
                sys.path.pop(0)

        elif path == "/api/analyze-session":
            body = self._read_body()
            target_session = body.get("session", "")
            target_harness = self._resource_name(
                body.get("harness", "session_analyzer"), "harness name"
            )
            target_identity = self._resource_name(
                body.get("identity", "dante"), "identity name"
            )
            
            if not target_session:
                self._send_error("Missing 'session' field")
                return

            harness_path = self._resource_path(HARNESS_DIR, target_harness, label="harness path")
            if not harness_path.exists():
                self._send_error(f"Harness '{target_harness}' not found")
                return

            identity_path = self._resource_path(IDENTITY_DIR, target_identity, label="identity path")
            if not identity_path.exists():
                self._send_error(f"Identity '{target_identity}' not found")
                return

            task_id = str(_uuid.uuid4())[:8]
            _async_tasks[task_id] = {"status": "running", "result": None, "error": None}

            def _run_analyze():
                import sys
                project_root = Path(__file__).resolve().parent.parent
                sys.path.insert(0, str(project_root))
                try:
                    from harness import Harness, runtime_scope
                    import json as _json

                    hconfig = _json.loads((harness_path / "config.json").read_text(encoding="utf-8"))
                    slots = hconfig.get("slots", {})
                    slot_name = list(slots.keys())[0] if slots else "agent"

                    agent = _identity_agent_factory.create(identity_path, name=slot_name)
                    harness = Harness(str(harness_path), agents={slot_name: agent})
                    harness._non_interactive = True
                    initial_msg = {
                        "role": "user",
                        "content": (
                            f"Analyze the session at sessions/{target_session}. "
                            f"Use evaluate_session to get metrics, then provide a structured analysis report "
                            f"covering: what the agent attempted, what went well, what went wrong, root causes, "
                            f"and concrete improvement suggestions."
                        )
                    }
                    harness.session.record(initial_msg)
                    harness.session.record_full(initial_msg)

                    with runtime_scope(harness=harness):
                        harness.run_func(harness)

                    messages = harness.session.messages
                    final_summary = ""
                    for msg in reversed(messages):
                        if msg.get("role") == "assistant" and "<tool_call>" not in msg.get("content", ""):
                            final_summary = msg.get("content", "")
                            break

                    harness.session.save()

                    _async_tasks[task_id] = {
                        "status": "completed",
                        "result": {
                            "steps": len(messages),
                            "summary": final_summary,
                            "target_session": target_session,
                            "harness_used": target_harness,
                            "identity_used": target_identity,
                            "saved_to": str(harness.session.save_dir),
                            "messages": messages,
                        },
                        "error": None,
                    }
                except Exception as e:
                    _async_tasks[task_id] = {
                        "status": "error",
                        "result": None,
                        "error": str(e),
                    }
                finally:
                    if str(project_root) in sys.path:
                        sys.path.remove(str(project_root))

            t = threading.Thread(target=_run_analyze, daemon=True)
            t.start()
            self._send_json({"task_id": task_id, "status": "running"})

        elif path in {
            "/api/evolution/capabilities/analyze",
            "/api/evolution/capabilities/inspect",
            "/api/evolution/capabilities/install",
            "/api/evolution/capabilities/rollback",
        }:
            body = self._read_body()
            from self_evolution.capability_evolution import (
                CapabilityEvolutionError,
                CapabilityEvolutionService,
                analyze_evolution_need,
            )
            service = CapabilityEvolutionService(_PROJECT_ROOT_FOR_IMPORTS)
            try:
                if path.endswith("/analyze"):
                    result = analyze_evolution_need(body.get("observations"), workspace=str(body.get("workspace", "")))
                elif path.endswith("/inspect"):
                    result = service.inspect(str(body.get("identity", "")))
                elif path.endswith("/install"):
                    result = service.install(
                        str(body.get("identity", "")),
                        str(body.get("pack", "")),
                        dry_run=bool(body.get("dry_run", False)),
                        reason=str(body.get("reason", "")),
                    )
                else:
                    result = service.rollback(str(body.get("transaction_id", "")))
                if path.endswith(("/install", "/rollback")) and not result.get("dry_run", False):
                    notify_output("identity_evolution", result)
                self._send_json(result)
            except (CapabilityEvolutionError, BlueprintError, OSError, ValueError) as error:
                self._send_error(str(error), 400)

        elif path == "/api/evolution/start":
            body = self._read_body()
            target_harness = body.get("harness", "react_single")
            target_identity = body.get("identity", "dante")
            max_iterations = body.get("iterations", 3)
            mode = body.get("mode", "engine")

            task_id = str(_uuid.uuid4())[:8]
            _async_tasks[task_id] = {"status": "running", "result": None, "error": None}

            def _run_evolution():
                import sys as _sys
                project_root = Path(__file__).resolve().parent.parent
                _sys.path.insert(0, str(project_root))

                def _progress_cb(step, detail):
                    _async_tasks[task_id]["progress"] = step + (f" — {detail}" if detail else "")

                try:
                    if mode == "v2_structural":
                        _run_evolution_v2(task_id, target_harness, target_identity, int(max_iterations), _progress_cb)
                    elif mode == "harness":
                        _run_evolution_harness(task_id, target_harness, target_identity, int(max_iterations), _progress_cb)
                    else:
                        from self_evolution.engine import run_evolution_cycle
                        report = run_evolution_cycle(
                            target_harness=target_harness,
                            target_identity=target_identity,
                            max_iterations=int(max_iterations),
                            verbose=True,
                            progress_callback=_progress_cb,
                        )
                        _async_tasks[task_id] = {"status": "completed", "result": report, "error": None}
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    _async_tasks[task_id] = {"status": "error", "result": None, "error": str(e)}

            t = threading.Thread(target=_run_evolution, daemon=True)
            t.start()
            self._send_json({"task_id": task_id, "status": "running"})

        elif path == "/api/evolution/principles":
            body = self._read_body()
            query = body.get("query", "general improvement")
            top_k = body.get("top_k", 5)
            import sys as _sys
            project_root = Path(__file__).resolve().parent.parent
            _sys.path.insert(0, str(project_root))
            from self_evolution.engine import retrieve_principles, _load_json, PRINCIPLES_FILE
            principles = _load_json(PRINCIPLES_FILE)
            self._send_json({"principles": principles})

        elif path == "/api/evolution/archive":
            body = self._read_body()
            target = body.get("target", "")
            limit = body.get("limit", 20)
            import sys as _sys
            project_root = Path(__file__).resolve().parent.parent
            _sys.path.insert(0, str(project_root))
            from self_evolution.engine import get_history, get_best_configs, _load_json, ARCHIVE_FILE
            archive = _load_json(ARCHIVE_FILE)
            self._send_json({"archive": archive, "total": len(archive)})

        # ---- Change Tracking: POST /api/session/changes/apply-text ----
        elif path == "/api/session/changes/apply-text":
            body = self._read_body()
            workspace = body.get("workspace")
            file_path = body.get("file")
            old_text = body.get("old_text")
            new_text = body.get("new_text")
            if not workspace or not file_path:
                self._send_error("workspace and file are required", 400)
                return
            if old_text is not None and not isinstance(old_text, str):
                self._send_error("old_text must be text or null", 400)
                return
            if new_text is not None and not isinstance(new_text, str):
                self._send_error("new_text must be text or null", 400)
                return
            if len((old_text or "").encode("utf-8")) > 4_000_000 or len((new_text or "").encode("utf-8")) > 4_000_000:
                self._send_error("inline edit payload exceeds the 4 MB safety limit", 413)
                return
            try:
                workspace_root = Path(workspace).resolve(strict=True)
                target = Path(file_path).resolve(strict=False)
                if not workspace_root.is_dir() or os.path.commonpath((str(workspace_root), str(target))) != str(workspace_root):
                    raise ValueError("file is outside the selected workspace")
            except (OSError, ValueError) as error:
                self._send_error(f"Invalid workspace edit target: {error}", 403)
                return

            index = apply_text_change(
                target,
                old_text,
                new_text,
                str(body.get("tool_name") or "void-inline-edit")[:160],
                transaction_id=str(body.get("transaction_id") or f"void-{_uuid.uuid4().hex}"),
            )
            if index is None:
                detail = get_last_operation_error() or {"message": "Could not apply text edit"}
                status = 409 if detail.get("code") == "revision_conflict" else 400
                self._send_json({"error": detail.get("message"), "detail": detail}, status)
                return
            change = next((item for item in get_changes() if item.get("index") == index), None)
            self._send_json({"ok": True, "change": change})

        # ---- Change Tracking: POST /api/session/changes/accept ----
        elif path == "/api/session/changes/accept":
            body = self._read_body()
            index = body.get("index")
            change_id = body.get("id")
            hunk_id = body.get("hunk_id")
            file_filter = body.get("file")

            selector = change_id if change_id is not None else index
            if selector is not None:
                ok = accept_change(selector, hunk_id=hunk_id)
                if ok:
                    self._send_json({"ok": True, "id": change_id, "index": index, "hunk_id": hunk_id})
                else:
                    detail = get_last_operation_error() or {"message": "Invalid change or hunk state"}
                    status = 409 if detail.get("code") == "revision_conflict" else 400
                    self._send_json({"error": detail.get("message"), "detail": detail}, status)
            elif file_filter:
                # Accept all pending changes for a specific file
                accepted = []
                for c in get_changes():
                    if c["file_path"] == file_filter and c["status"] in ("pending", "partial"):
                        accept_change(c["index"])
                        accepted.append(c["index"])
                self._send_json({"ok": True, "accepted": accepted})
            else:
                self._send_error("Provide 'index' or 'file'", 400)

        # ---- Change Tracking: POST /api/session/changes/reject ----
        elif path == "/api/session/changes/reject":
            body = self._read_body()
            index = body.get("index")
            change_id = body.get("id")
            hunk_id = body.get("hunk_id")
            reason = body.get("reason")
            confirm_delete = body.get("confirm_delete") is True

            selector = change_id if change_id is not None else index
            if selector is None:
                self._send_error("Missing 'id' or 'index'", 400)
                return

            ok = reject_change(selector, reason, hunk_id=hunk_id, confirm_delete=confirm_delete)
            if ok:
                self._send_json({"ok": True, "id": change_id, "index": index, "hunk_id": hunk_id})
            else:
                detail = get_last_operation_error() or {"message": "Invalid change or hunk state"}
                status = 409 if detail.get("code") in {"revision_conflict", "delete_confirmation_required"} else 400
                self._send_json({"error": detail.get("message"), "detail": detail}, status)

        # ---- Change Tracking: POST /api/session/changes/undo ----
        elif path == "/api/session/changes/undo":
            body = self._read_body()
            index = body.get("index")
            change_id = body.get("id")
            hunk_id = body.get("hunk_id")
            selector = change_id if change_id is not None else index
            if selector is None:
                self._send_error("Missing 'id' or 'index'", 400)
                return
            ok = undo_change(selector, hunk_id=hunk_id)
            if ok:
                self._send_json({"ok": True, "id": change_id, "index": index, "hunk_id": hunk_id})
            else:
                detail = get_last_operation_error() or {"message": "Decision cannot be undone"}
                self._send_json({"error": detail.get("message"), "detail": detail}, 409)

        # ---- Change Tracking: POST /api/session/changes/revert-all ----
        elif path == "/api/session/changes/revert-all":
            body = self._read_body()
            transaction_id = body.get("transaction_id")
            confirm_delete = body.get("confirm_delete") is True
            count = revert_all(transaction_id, confirm_delete=confirm_delete)
            pending_new_files = [
                change for change in get_changes(transaction_id)
                if change.get("is_new_file") and change.get("status") in {"pending", "partial", "accepted"}
            ]
            self._send_json({
                "ok": not pending_new_files,
                "reverted": count,
                "delete_confirmation_required": bool(pending_new_files),
                "pending_new_files": [change["file_path"] for change in pending_new_files],
            }, 409 if pending_new_files else 200)

        # ---- Change Tracking: POST /api/session/changes/clear-workspace ----
        elif path == "/api/session/changes/clear-workspace":
            body = self._read_body()
            workspace = body.get("workspace")
            if not workspace:
                self._send_error("workspace is required", 400)
                return
            try:
                workspace_root = Path(workspace).resolve(strict=True)
                if not workspace_root.is_dir():
                    raise ValueError("workspace is not a directory")
            except (OSError, ValueError) as error:
                self._send_error(f"Invalid workspace: {error}", 400)
                return
            removed = clear_workspace_changes(workspace_root)
            self._send_json({"ok": True, "workspace": str(workspace_root), "removed": removed})

        # ---- Checkpoint: POST /api/checkpoints/create ----
        elif path == "/api/checkpoints/create":
            if not create_checkpoint:
                self._send_error("Checkpoint module not available", 500)
                return
            body = self._read_body()
            label = body.get("label", "")
            files = body.get("files", [])
            try:
                result = create_checkpoint(
                    label=label,
                    files=files,
                    trigger=str(body.get("trigger") or "manual"),
                    workspace=body.get("workspace"),
                    metadata=body.get("metadata") if isinstance(body.get("metadata"), dict) else None,
                )
                self._send_json(result)
            except (OSError, ValueError) as error:
                self._send_error(str(error), 400)

        # ---- Checkpoint: POST /api/checkpoints/preview ----
        elif path == "/api/checkpoints/preview":
            if not preview_restore:
                self._send_error("Checkpoint module not available", 500)
                return
            body = self._read_body()
            checkpoint_id = body.get("checkpoint_id", "")
            if not checkpoint_id:
                self._send_error("checkpoint_id required", 400)
                return
            result = preview_restore(checkpoint_id, files=body.get("files"))
            self._send_json(result, 200 if result.get("ok") else 404)

        # ---- Checkpoint: POST /api/checkpoints/rollback ----
        elif path == "/api/checkpoints/rollback":
            if not rollback:
                self._send_error("Checkpoint module not available", 500)
                return
            body = self._read_body()
            cp_id = body.get("checkpoint_id", "")
            if not cp_id:
                self._send_error("checkpoint_id required", 400)
                return
            expected_revisions = body.get("expected_revisions")
            if not isinstance(expected_revisions, dict):
                preview = preview_restore(cp_id, files=body.get("files"))
                self._send_json({
                    "error": "Restore preview is required before applying a checkpoint",
                    "detail": {"code": "restore_preview_required"},
                    "preview": preview,
                }, 409)
                return
            result = rollback(
                cp_id,
                files=body.get("files"),
                expected_revisions=expected_revisions,
                confirm_delete=body.get("confirm_delete") is True,
            )
            self._send_json(result, 200 if result.get("ok") else 409)

        # ---- Checkpoint: POST /api/checkpoints/clear ----
        elif path == "/api/checkpoints/clear":
            if clear_checkpoints:
                result = clear_checkpoints()
                self._send_json(result)
            else:
                self._send_json({"status": "unavailable"})

        # ---- Agent Creator: POST /api/agent/create ----
        elif path == "/api/agent/create":
            if not create_agent_from_description:
                self._send_error("Agent creator module not available", 500)
                return
            body = self._read_body()
            description = body.get("description", "")
            spec = body.get("spec")
            name = body.get("name", None)
            if not description and not isinstance(spec, dict):
                self._send_error("description or spec is required", 400)
                return
            try:
                result = create_agent_from_spec(spec, name) if isinstance(spec, dict) else create_agent_from_description(description, name)
                notify_output("agent_system_created", {
                    "identity": result.get("identity", {}).get("name"),
                    "harness": result.get("harness"),
                    "blueprint": result.get("blueprint"),
                })
                self._send_json(result, 201)
            except (OSError, ValueError, BlueprintError) as error:
                self._send_error(str(error), 400)

        # ---- Project Rules: POST /api/rules ----
        elif path == "/api/rules":
            if not create_rule:
                self._send_error("Rules module not available", 500)
                return
            body = self._read_body()
            name = body.get("name", "")
            content = body.get("content", "")
            if not name:
                self._send_error("name is required", 400)
                return
            self._send_json(create_rule(name=name, content=content))

        # ---- Memory: POST /api/memory ----
        elif path == "/api/memory":
            if not save_memory:
                self._send_error("Memory module not available", 500)
                return
            body = self._read_body()
            session_id = body.get("session_id", "")
            summary = body.get("summary", "")
            key_facts = body.get("key_facts", [])
            if not session_id or not summary:
                self._send_error("session_id and summary are required", 400)
                return
            self._send_json(save_memory(session_id=session_id, summary=summary, key_facts=key_facts))

        # ---- Model Endpoints: POST /api/model-endpoints ----
        elif path == "/api/model-endpoints":
            if not add_model:
                self._send_error("Model router module not available", 500)
                return
            body = self._read_body()
            try:
                self._send_json(add_model(body))
            except ValueError as error:
                self._send_error(str(error), 400)

        elif path == "/api/model-profiles":
            if not upsert_model_profile:
                self._send_error("Model router not available", 500)
                return
            try:
                self._send_json(upsert_model_profile(self._read_body()))
            except ValueError as error:
                self._send_error(str(error), 400)

        elif path == "/api/model-roles":
            if not assign_model_role:
                self._send_error("Model router not available", 500)
                return
            body = self._read_body()
            try:
                self._send_json(assign_model_role(body.get("role"), body.get("profiles", [])))
            except ValueError as error:
                self._send_error(str(error), 400)

        elif path == "/api/model-route/preview":
            if not route_model:
                self._send_error("Model router not available", 500)
                return
            body = self._read_body()
            self._send_json(route_model(
                body.get("role", "chat"),
                model_id=body.get("model_id"),
                context_tokens=body.get("context_tokens", 0),
                expected_output_tokens=body.get("expected_output_tokens", 0),
                run_id=body.get("run_id"),
            ))

        elif path == "/api/model-budgets":
            if not set_run_budget:
                self._send_error("Model router not available", 500)
                return
            body = self._read_body()
            run_id = str(body.get("run_id") or "")
            if not run_id:
                self._send_error("run_id required", 400)
                return
            self._send_json(set_run_budget(run_id, body.get("limit", 0)))

        # ---- Experiments: POST /api/experiments ----
        elif path == "/api/experiments":
            if not create_experiment:
                self._send_error("Experiment module not available", 500)
                return
            body = self._read_body()
            name = body.get("name", "")
            description = body.get("description", "")
            variants = body.get("variants", [])
            if not name or not variants:
                self._send_error("name and variants are required", 400)
                return
            self._send_json(create_experiment(name=name, description=description, variants=variants))

        # ---- Experiment Result: POST /api/experiments/<id>/result ----
        elif path.startswith("/api/experiments/") and path.endswith("/result"):
            exp_id = path.split("/api/experiments/", 1)[1].rsplit("/result", 1)[0]
            if not record_result:
                self._send_error("Experiment module not available", 500)
                return
            body = self._read_body()
            variant_idx = body.get("variant_idx", 0)
            score = body.get("score", 0.0)
            metadata = body.get("metadata", None)
            self._send_json(record_result(exp_id=exp_id, variant_idx=variant_idx, score=score, metadata=metadata))

        # ---- Model-backed IDE features: POST /api/ai/<operation> ----
        elif path.startswith("/api/ai/"):
            operation = path.split("/api/ai/", 1)[1].strip("/")
            body = self._read_body()
            try:
                self._send_json(run_ai_operation(operation, body))
            except AIServiceError as error:
                self._send_error(str(error), 503)
            except Exception as error:
                self._send_error(f"AI operation failed: {error}", 500)

        # ---- Typed codebase context: POST index/catalog/plan/feedback ----
        elif path == "/api/context/index":
            body = self._read_body()
            try:
                self._send_json(build_index(body.get("workspace"), force=body.get("force") is True))
            except (OSError, ValueError) as error:
                self._send_error(str(error), 400)

        elif path == "/api/context/catalog":
            body = self._read_body()
            try:
                self._send_json({"items": build_catalog(body)})
            except (OSError, ValueError) as error:
                self._send_error(str(error), 400)

        elif path == "/api/context/plan":
            body = self._read_body()
            try:
                self._send_json(plan_context(body))
            except (OSError, ValueError) as error:
                self._send_error(str(error), 400)

        elif path == "/api/context/feedback":
            body = self._read_body()
            try:
                self._send_json(record_context_feedback(
                    body.get("workspace"), body.get("item_ids", []), body.get("decision", "")
                ))
            except (OSError, ValueError) as error:
                self._send_error(str(error), 400)

        # ---- OpenAI-Compatible: POST /v1/chat/completions ----
        elif path == "/v1/chat/completions":
            body = self._read_body()
            messages = body.get("messages", [])
            model = body.get("model", "egoagent-dag")
            stream = body.get("stream", False)
            
            # Extract harness/identity from body fields or model name
            harness_name = body.get("harness", "react_single")
            identity_name = body.get("identity", "dante")
            workspace = body.get("workspace")
            if harness_name == "react_single" and ":" in model:
                parts = model.split(":")
                if len(parts) >= 2:
                    harness_name = parts[1]
                if len(parts) >= 3:
                    identity_name = parts[2]

            harness_name = self._resource_name(harness_name, "harness name")
            identity_name = self._resource_name(identity_name, "identity name")
            
            # Determine if multi-agent
            harness_path = self._resource_path(HARNESS_DIR, harness_name, label="harness path")
            if not harness_path.exists():
                harness_path = HARNESS_DIR / "react_single"
            hconfig = json.loads((harness_path / "config.json").read_text(encoding="utf-8"))
            slots = hconfig.get("slots", {})
            is_multi_agent = len(slots) > 1
            
            if stream:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self._send_security_headers(cors=True)
                self.end_headers()
                
                completion_id = f"chatcmpl-ego-{_uuid.uuid4().hex[:8]}"
                
                def _send_sse_chunk(content, finish=False):
                    chunk = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": int(_time.time()),
                        "model": model,
                        "choices": [{
                            "index": 0,
                            "delta": {"content": content} if content else {},
                            "finish_reason": "stop" if finish else None,
                        }],
                    }
                    self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                    self.wfile.flush()
                
                if not is_multi_agent:
                    # TRUE STREAMING: Direct vLLM stream for single-agent
                    try:
                        _stream_single_agent(
                            messages, harness_name, identity_name, _send_sse_chunk, workspace=workspace
                        )
                    except Exception as e:
                        _send_sse_chunk(f"\n\n[Error: {e}]", finish=True)
                else:
                    # MULTI-AGENT: Real-time streaming per agent
                    try:
                        _run_dag_streaming(
                            messages, harness_name, identity_name, _send_sse_chunk, workspace=workspace
                        )
                        _send_sse_chunk("", finish=True)
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        pass  # Client disconnected
                    except Exception as e:
                        try:
                            _send_sse_chunk(f"\n\n[Error: {e}]", finish=True)
                        except (BrokenPipeError, ConnectionResetError, OSError):
                            pass
                
                try:
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
            else:
                # Non-streaming response
                response_text = _run_dag_completion(
                    messages,
                    harness_name,
                    identity_name,
                    stream=False,
                    workspace=workspace,
                )
                
                result = {
                    "id": f"chatcmpl-ego-{_uuid.uuid4().hex[:8]}",
                    "object": "chat.completion",
                    "created": int(_time.time()),
                    "model": model,
                    "choices": [{
                        "index": 0,
                        "message": {"role": "assistant", "content": response_text},
                        "finish_reason": "stop",
                    }],
                    "usage": {
                        "prompt_tokens": sum(len(m.get("content", "").split()) for m in messages),
                        "completion_tokens": len(response_text.split()),
                        "total_tokens": sum(len(m.get("content", "").split()) for m in messages) + len(response_text.split()),
                    },
                }
                self._send_json(result)

        else:
            # Try extended API routes
            body = self._read_body()
            ext_resp, ext_code = _handle_ext_api("POST", path, body)
            if ext_resp is not None:
                self._send_json(ext_resp, ext_code or 200)
            else:
                self._send_error("Not found", 404)

    # ==================== DELETE ====================

    def do_DELETE(self):
        if not self._guard_browser_request(require_json=True):
            return
        path = urlparse(self.path).path

        if path.startswith("/api/identity/") and not any(
            x in path for x in ["/skill/", "/knowledge/"]
        ):
            name = self._resource_name(path.split("/api/identity/", 1)[1], "identity name")
            identity_dir = self._resource_path(IDENTITY_DIR, name, label="identity path")
            if not identity_dir.exists():
                self._send_error(f"Identity not found: {name}", 404)
                return
            shutil.rmtree(str(identity_dir))
            self._send_json({"ok": True})

        elif "/skill/" in path and path.startswith("/api/identity/"):
            parts = path.split("/")
            name_idx = parts.index("identity") + 1
            skill_idx = parts.index("skill") + 1
            name = self._resource_name(parts[name_idx], "identity name")
            sname = self._resource_name(parts[skill_idx], "skill name")

            skill_dir = self._resource_path(
                IDENTITY_DIR, name, "ego", "skills", sname, label="skill path"
            )
            if skill_dir.exists():
                shutil.rmtree(str(skill_dir))
            self._send_json({"ok": True})

        elif "/knowledge/" in path and path.startswith("/api/identity/"):
            parts = path.split("/")
            name_idx = parts.index("identity") + 1
            know_idx = parts.index("knowledge") + 1
            name = self._resource_name(parts[name_idx], "identity name")
            kname = self._resource_name(parts[know_idx], "knowledge name")

            know_dir = self._resource_path(
                IDENTITY_DIR, name, "ego", "knowledge", kname, label="knowledge path"
            )
            if know_dir.exists():
                shutil.rmtree(str(know_dir))
            self._send_json({"ok": True})

        elif "/tool/" in path and path.startswith("/api/environment/"):
            parts = path.split("/")
            env_idx = parts.index("environment") + 1
            tool_idx = parts.index("tool") + 1
            path_b64 = parts[env_idx]
            tname = self._resource_name(parts[tool_idx], "tool name")
            environment_dir = self._environment_dir(path_b64)
            tool_dir = self._resource_path(
                environment_dir, "tools", tname, label="environment tool path"
            )
            if tool_dir.exists():
                shutil.rmtree(str(tool_dir))
            self._send_json({"ok": True})

        elif "/knowledge/" in path and path.startswith("/api/environment/"):
            parts = path.split("/")
            env_idx = parts.index("environment") + 1
            know_idx = parts.index("knowledge") + 1
            path_b64 = parts[env_idx]
            kname = self._resource_name(parts[know_idx], "knowledge name")
            environment_dir = self._environment_dir(path_b64)
            know_dir = self._resource_path(
                environment_dir, "knowledge", kname, label="environment knowledge path"
            )
            if know_dir.exists():
                shutil.rmtree(str(know_dir))
            self._send_json({"ok": True})

        # ---- Session: DELETE /api/session/<id> ----
        elif path.startswith("/api/session/") and not any(
            x in path for x in ["/messages", "/cached-report", "/evaluate", "/changes"]
        ):
            session_id = path.split("/api/session/", 1)[1].rstrip("/")
            try:
                session_dir = self._resolve_session_dir(session_id)
            except ValueError as error:
                self._send_error(str(error), 400)
                return
            except FileNotFoundError:
                self._send_error(f"Session not found: {unquote(session_id)}", 404)
                return
            shutil.rmtree(str(session_dir))
            self._send_json({"ok": True})

        # ---- Rules: DELETE /api/rules/<name> ----
        elif path.startswith("/api/rules/"):
            rule_name = unquote(path.split("/api/rules/", 1)[1])
            if delete_rule and rule_name:
                self._send_json(delete_rule(name=rule_name))
            else:
                self._send_error("Rules module not available", 500)

        # ---- Model Endpoints: DELETE /api/model-endpoints/<id> ----
        elif path.startswith("/api/model-endpoints/"):
            model_id = unquote(path.split("/api/model-endpoints/", 1)[1])
            if remove_model and model_id:
                self._send_json(remove_model(model_id))
            else:
                self._send_error("Model router module not available", 500)

        elif path.startswith("/api/model-profiles/"):
            model_id = unquote(path.split("/api/model-profiles/", 1)[1])
            if remove_model and model_id:
                self._send_json(remove_model(model_id))
            else:
                self._send_error("Model router module not available", 500)

        # ---- Experiments: DELETE /api/experiments/<id> ----
        elif path.startswith("/api/experiments/"):
            exp_id = path.split("/api/experiments/", 1)[1].strip("/")
            exp_file = Path(__file__).resolve().parent.parent / "experiments" / "ab_experiments.json"
            if exp_file.exists():
                experiments = json.loads(exp_file.read_text(encoding="utf-8"))
                experiments = [e for e in experiments if e.get("id") != exp_id]
                exp_file.write_text(json.dumps(experiments, ensure_ascii=False, indent=2), encoding="utf-8")
            self._send_json({"ok": True})

        else:
            self._send_error("Not found", 404)


def _run_evolution_v2(task_id, target_harness, target_identity, max_iterations, progress_cb):
    """
    V2 Structural Evolution: Evolver agent uses tool calling to modify DAG structure.
    This integrates the research experiment (run_structural_evolution_v2.py) into the frontend.
    """
    import sys as _sys
    project_root = Path(__file__).resolve().parent.parent
    _sys.path.insert(0, str(project_root))

    try:
        target_harness = validate_resource_segment(target_harness, label="harness name")
        target_identity = validate_resource_segment(target_identity, label="identity name")
    except UnsafeResourcePath as error:
        _async_tasks[task_id] = {"status": "error", "result": None, "error": str(error)}
        return

    # Load the harness config (this is the DAG to evolve)
    config_path = resolve_resource_path(
        HARNESS_DIR, target_harness, "config.json", label="harness path"
    )
    if not config_path.exists():
        _async_tasks[task_id] = {"status": "error", "result": None, "error": f"Harness not found: {target_harness}"}
        return

    blueprint_service = HarnessBlueprintService(project_root)
    loaded_blueprint = blueprint_service.load(target_harness)
    config = loaded_blueprint["config"]
    scripts_dir = resolve_resource_path(
        HARNESS_DIR, target_harness, "scripts", label="harness script path"
    )
    scripts_dir.mkdir(parents=True, exist_ok=True)

    # Import the V2 evolver module
    evo_dir = project_root / "experiments" / "self_repair"
    _sys.path.insert(0, str(evo_dir))

    try:
        from run_multi_scenario_test import DAGState, run_evolver, TOOLS, execute_tool, llm_call
    except ImportError as e:
        _async_tasks[task_id] = {"status": "error", "result": None, "error": f"Cannot import V2 evolver: {e}"}
        return

    # Build initial DAG state from harness config
    initial_prompt = ""
    for slot_name, slot_def in config.get("slots", {}).items():
        identity_name = slot_def.get("identity", "")
        if identity_name:
            try:
                id_path = resolve_resource_path(
                    IDENTITY_DIR, identity_name, "id.json", label="identity path"
                )
            except UnsafeResourcePath:
                continue
            if id_path.exists():
                id_data = json.loads(id_path.read_text(encoding="utf-8"))
                initial_prompt = id_data.get("system_prompt", "")
                break

    if not initial_prompt:
        initial_prompt = "You are a helpful assistant."

    # Create DAGState from current pipeline config
    dag_state = DAGState(initial_prompt)
    dag_state.config = config

    report = {
        "target_harness": target_harness,
        "target_identity": target_identity,
        "initial_prompt": initial_prompt,
        "iterations": [],
        "structural_changes": [],
        "final_config": None,
    }

    for iteration in range(1, max_iterations + 1):
        progress_cb(f"Round {iteration}/{max_iterations}", "Running Evolver...")

        # Build a simulated failure info (for demo purposes, just show current state)
        failure_info = f"Current DAG state:\n{dag_state.get_nodes_summary()}\nPrompt: {dag_state.system_prompt[:200]}"
        history_info = f"Round {iteration} of structural evolution."

        # Call the V2 evolver
        result = run_evolver(dag_state, failure_info, history_info,
                           "Improve the agent pipeline's robustness and output quality.")

        actions = result.get("actions", [])
        iter_report = {
            "iteration": iteration,
            "actions": [{"action": a["action"], "result": a.get("result", "")[:100]} for a in actions],
            "nodes_after": list(dag_state.config.get("pipeline", {}).get("nodes", {}).keys()),
        }
        report["iterations"].append(iter_report)

        # Check for structural changes
        for a in actions:
            if a["action"] in ("add_node", "remove_node", "rewire_edge"):
                report["structural_changes"].append(a["action"])

        progress_cb(f"Round {iteration}/{max_iterations}", f"Done. Actions: {[a['action'] for a in actions]}")

    # Compile and commit through the same revision-checked transaction boundary
    # used by weak-model tools.  The old experiment wrote config.json directly,
    # so a malformed or stale candidate could corrupt the live Harness.
    from harness_blueprint import decompile_config
    candidate_blueprint = decompile_config(dag_state.config)
    patch_result = blueprint_service.patch(
        target_harness,
        [{"op": "replace_blueprint", "blueprint": candidate_blueprint}],
        expected_revision=loaded_blueprint["revision"],
        reason="V2 structural evolution candidate",
        actor="evolution:v2_structural",
    )
    report["final_config"] = patch_result["config"]
    report["transaction_id"] = patch_result["transaction_id"]
    report["revision_before"] = patch_result["revision_before"]
    report["revision_after"] = patch_result["revision"]
    report["diff"] = patch_result["diff"]
    notify_output("harness_mutation", {
        "harness": target_harness,
        "action": "patch",
        "transaction_id": patch_result["transaction_id"],
        "revision": patch_result["revision"],
        "diff": patch_result["diff"],
    })

    # Save any scripts that were written
    for script_file in scripts_dir.iterdir():
        if script_file.suffix == ".py":
            report.setdefault("scripts_written", []).append(script_file.name)

    _async_tasks[task_id] = {"status": "completed", "result": report, "error": None}


def _run_evolution_harness(task_id, target_harness, target_identity, max_iterations, progress_cb):
    """Run evolution cycle using the harness pipeline (DAG mode)."""
    import sys as _sys
    project_root = Path(__file__).resolve().parent.parent
    _sys.path.insert(0, str(project_root))

    from harness import Harness
    from pipeline_engine import run_pipeline

    progress_cb("[1/3] Loading evolution_cycle harness...", "")

    # Load the evolution_cycle harness
    evo_harness_dir = HARNESS_DIR / "evolution_cycle"
    harness = Harness(str(evo_harness_dir), workspace=project_root)

    # Override context with user parameters
    pipeline = harness.config["pipeline"]
    ctx = pipeline.get("context", {})
    ctx["target_harness"] = target_harness
    ctx["target_identity"] = target_identity
    ctx["max_iterations"] = max_iterations
    pipeline["context"] = ctx

    # Assign a minimal evolver agent (provides LLM access for llm_call nodes)
    identity_dir = project_root / "identity" / target_identity
    if identity_dir.exists():
        agent = _identity_agent_factory.create(identity_dir, name="evolver", workspace=project_root)
    else:
        # Fallback: use first available identity
        identity_dir = project_root / "identity" / "dante"
        agent = _identity_agent_factory.create(identity_dir, name="evolver", workspace=project_root)
    harness.agents["evolver"] = agent

    # Run non-interactively
    harness._non_interactive = True
    progress_cb("[2/3] Running evolution pipeline...", f"target={target_harness}/{target_identity}")

    run_pipeline(harness)

    progress_cb("[3/3] Collecting report...", "")

    # Extract the report from the final context
    # The pipeline stores results in context via scripts;
    # we need to read the latest report file from DATA_DIR
    from self_evolution.engine import DATA_DIR, _load_json
    import glob as _glob

    report_files = sorted(_glob.glob(str(DATA_DIR / "report_*.json")), reverse=True)
    if report_files:
        report = _load_json(Path(report_files[0]))
    else:
        # Fallback: construct minimal report
        report = {
            "target_harness": target_harness,
            "target_identity": target_identity,
            "initial_score": 0.0,
            "final_score": 0.0,
            "total_accepted": 0,
            "total_rejected": 0,
            "total_rollbacks": 0,
            "iterations": [],
        }

    _async_tasks[task_id] = {"status": "completed", "result": report, "error": None}


def _run_harness_in_thread(
    harness_name, agents_dict, input_queue, run_id, workspace_path=None,
    mode="agent", mutation_targets=(),
):
    handle = interactive_runs.get(run_id)
    if handle is None:
        raise RuntimeError(f"Interactive execution no longer exists: {run_id}")
    with interactive_runs.bind(handle):
        return _run_harness_in_thread_bound(
            harness_name,
            agents_dict,
            input_queue,
            run_id,
            workspace_path,
            mode,
            mutation_targets,
        )


def _run_harness_in_thread_bound(
    harness_name, agents_dict, input_queue, run_id, workspace_path=None,
    mode="agent", mutation_targets=(),
):
    handle = _current_interactive_run()
    run_state = handle.state

    app_root = Path(__file__).resolve().parent.parent
    workspace_root = Path(workspace_path or app_root).resolve()
    sys.path.insert(0, str(app_root))

    from harness import Harness, reset_output_callback, set_output_callback
    from pipeline_engine import run_pipeline_stream

    # 设置全局 output 回调，子 harness 也能通过此推送事件
    output_callback_token = set_output_callback(notify_output)

    print(
        f"[exec] private input queue created, run_id={run_id}, "
        f"harness={harness_name}, workspace={workspace_root}, agents={agents_dict}"
    )

    harness = None
    agents = {}
    try:
        context_parts = []
        if get_effective_rules_prompt:
            context_parts.append(get_effective_rules_prompt(str(workspace_root)))
        if get_memory_prompt:
            context_parts.append(get_memory_prompt(str(workspace_root)))
        mode_prompts = {
            "chat": "Chat mode: inspect and explain, but do not write files, run processes, or mutate an Identity/Harness.",
            "plan": "Plan mode: produce an evidence-backed implementation plan. This run is read-only.",
            "agent": "Agent mode: complete the task using allowed tools and keep edits reviewable.",
            "debug": "Debug mode: reproduce, diagnose, fix, and verify the problem with explicit evidence.",
            "evolve": "Evolve mode: improve only the explicitly authorized Identity/Harness targets and preserve a reversible transaction.",
            "evaluate": "Evaluate mode: solve inside the isolated workspace; network and global Identity/Harness mutation are disabled.",
        }
        context_parts.insert(0, mode_prompts.get(mode, mode_prompts["agent"]))
        workspace_context = "\n\n".join(part for part in context_parts if part)
        agents = {}
        is_multi_agent = len(agents_dict) > 1
        safe_harness_name = validate_resource_segment(harness_name, label="harness name")
        harness_dir = resolve_resource_path(HARNESS_DIR, safe_harness_name, label="harness path")
        harness_config = json.loads((harness_dir / "config.json").read_text(encoding="utf-8"))
        configured_limit = _configured_chat_token_limit(harness_config)
        for slot_name, identity_path in agents_dict.items():
            full_identity = (app_root / identity_path).resolve()
            identity_root = (app_root / "identity").resolve()
            try:
                full_identity.relative_to(identity_root)
            except ValueError as error:
                raise ValueError(f"Identity path escapes identity root: {identity_path}") from error
            if not full_identity.is_dir():
                raise ValueError(f"Identity not found: {identity_path}")
            agents[slot_name] = _cap_chat_agent_tokens(
                _identity_agent_factory.create(full_identity, name=slot_name, workspace=workspace_root),
                multi_agent=is_multi_agent,
                configured_limit=configured_limit,
            )
            agents[slot_name].context_instructions = workspace_context
            print(f"[exec] Agent loaded: {slot_name} -> {full_identity}")

        harness = Harness(str(harness_dir), agents, workspace=workspace_root)
        # Persist each interactive Chat as an addressable Session.  The run-id
        # suffix prevents two parallel tasks using the same Harness in the same
        # second from colliding on one directory.
        import time as _time
        run_suffix = str(run_id).rsplit("_", 1)[-1][-8:]
        session_dir = app_root / "sessions" / f"{safe_harness_name}_{_time.strftime('%Y%m%d_%H%M%S')}_{run_suffix}"
        harness.session.set_save_dir(session_dir)
        run_state["session_name"] = session_dir.name
        run_state["session_id"] = harness.session.session_id
        run_state["project_id"] = project_id_for_workspace(workspace_root)
        notify_clients(run_state)
        print(f"[exec] Harness loaded, pipeline start={harness.config['pipeline']['start']}")

        def on_output(msg_type, data):
            if run_state.get("run_id") != run_id:
                return
            notify_output(msg_type, data)
            if msg_type == "node_enter":
                run_state["current_node"] = data.get("node_id", "")
                run_state["step_count"] = run_state.get("step_count", 0) + 1
                notify_clients(run_state)

        def get_input(timeout=None):
            try:
                if timeout is not None and float(timeout) <= 0:
                    return input_queue.get_nowait()
                return input_queue.get(timeout=3600 if timeout is None else max(0.0, float(timeout)))
            except queue_module.Empty:
                return None

        def is_running():
            return run_state["running"] and run_state.get("run_id") == run_id

        permission_policy = _interactive_permission_policy(
            workspace_root, mode, harness_config, mutation_targets,
        )
        run_state["security"] = permission_policy.public()
        _settings, sandbox_status = _workspace_security(workspace_root)
        run_state["sandbox"] = sandbox_status
        notify_clients(run_state)
        run_pipeline_stream(
            harness,
            on_output,
            get_input,
            is_running,
            before_node=_debug_before_node,
            on_node_error=_debug_on_node_error,
            permission_policy=permission_policy,
            initial_data={"run_mode": mode, "mutation_targets": list(mutation_targets)},
        )

    except Exception as e:
        if run_state.get("status") not in {"error", "limit_exceeded", "budget_exceeded"}:
            from run_failures import classify_run_failure
            notify_output("error", {
                "message": str(e),
                "type": type(e).__name__,
                "failure": classify_run_failure(str(e), type(e).__name__),
            })
        import traceback
        traceback.print_exc()
    finally:
        # 保存 session 记录
        try:
            if harness is not None:
                harness.session.save()
                _project_portfolio().register_project(workspace_root, touch=False)
                _project_portfolio().update_session(
                    Path(harness.session.save_dir).name,
                    {"last_opened_at": time.time()},
                )
                print(f"[exec] Session saved to {harness.session.save_dir}")
            if harness is not None and save_memory:
                messages = list(getattr(harness.session, "messages", []) or [])
                facts = [
                    f"Harness: {harness_name}",
                    f"Agents: {', '.join(agents.keys())}",
                    f"Messages: {len(messages)}",
                ]
                last_user = next((
                    msg.get("content", "") for msg in reversed(messages)
                    if msg.get("role") == "user" and "<tool_response>" not in msg.get("content", "")
                ), "")
                last_assistant = next((
                    msg.get("content", "") for msg in reversed(messages)
                    if msg.get("role") == "assistant" and "<tool_call>" not in msg.get("content", "")
                ), "")
                if last_user:
                    facts.append(f"Last user request: {last_user[:300]}")
                if last_assistant:
                    facts.append(f"Last agent result: {last_assistant[:300]}")
                session_id = Path(harness.session.save_dir).name
                save_memory(
                    session_id=session_id,
                    summary=f"{harness_name} completed with {len(messages)} recorded messages.",
                    key_facts=facts,
                    workspace_path=str(workspace_root),
                )
        except Exception:
            pass
        reset_output_callback(output_callback_token)
        if run_state.get("run_id") == run_id:
            run_state["running"] = False
            run_state["waiting_for_input"] = False
            run_state["current_node"] = None
            run_state["paused"] = False
            run_state["pause_requested"] = False
            run_state["pending_node"] = None
            handle.touch()
            with handle.debug_condition:
                handle.debug_condition.notify_all()
            notify_clients(run_state)


class WebSocketHandler:
    def __init__(self, sock):
        self.sock = sock
        # Model tokens are produced on the execution thread. A dead or slow
        # browser must never block that thread (and therefore the provider
        # stream) while the kernel waits in socket.send(). Keep one ordered
        # writer per client; the HTTP execution snapshot remains the recovery
        # path if a pathological client overflows this bounded queue.
        self._send_queue = queue_module.Queue(maxsize=4096)
        self._closed = threading.Event()
        self._sender = threading.Thread(target=self._send_loop, daemon=True)
        self._sender.start()

    def send(self, data):
        if self._closed.is_set():
            raise ConnectionError("WebSocket client is closed")
        try:
            self._send_queue.put_nowait(str(data))
        except queue_module.Full:
            raise ConnectionError("WebSocket client output queue is full")

    @staticmethod
    def _frame(data):
        frame = str(data).encode("utf-8")
        header = bytearray([0x81])
        length = len(frame)
        if length < 126:
            header.append(length)
        elif length < 65536:
            header.append(126)
            header.extend(length.to_bytes(2, "big"))
        else:
            header.append(127)
            header.extend(length.to_bytes(8, "big"))
        return bytes(header) + frame

    def _send_loop(self):
        while not self._closed.is_set():
            try:
                data = self._send_queue.get(timeout=0.25)
            except queue_module.Empty:
                continue
            if data is None:
                return
            try:
                self.sock.sendall(self._frame(data))
            except Exception:
                self._closed.set()
                return

    def close(self):
        if self._closed.is_set():
            return
        self._closed.set()
        try:
            self._send_queue.put_nowait(None)
        except queue_module.Full:
            pass

    def recv(self):
        try:
            data = self.sock.recv(4096)
            if not data:
                return None
            if len(data) < 2:
                return None
            opcode = data[0] & 0x0F
            if opcode == 0x8:
                return None
            if opcode == 0x9:
                pong = bytearray([0x8A, 0])
                self.sock.send(bytes(pong))
                return None
            mask = data[1] & 0x80
            length = data[1] & 0x7F
            offset = 2
            if length == 126:
                length = int.from_bytes(data[2:4], "big")
                offset = 4
            elif length == 127:
                length = int.from_bytes(data[2:10], "big")
                offset = 10
            if not mask or length > 1024 * 1024:
                return None
            if mask:
                mask_key = data[offset:offset + 4]
                offset += 4
                payload = bytearray(data[offset:offset + length])
                for i in range(len(payload)):
                    payload[i] ^= mask_key[i % 4]
                return bytes(payload).decode("utf-8", errors="ignore")
            return data[offset:offset + length].decode("utf-8", errors="ignore")
        except Exception:
            return None


def handle_ws(conn):
    global ws_clients
    client = WebSocketHandler(conn)
    ws_clients.add(client)

    try:
        initial = interactive_runs.latest() or _legacy_interactive_run
        client.send(json.dumps(initial.snapshot(include_outputs=True)))
        while True:
            msg = client.recv()
            if msg is None:
                break
            try:
                data = json.loads(msg)
                print(f"[WS] received: {data}")
                if data.get("type") == "input":
                    handle = interactive_runs.resolve(
                        run_id=data.get("run_id"),
                        workspace=data.get("workspace"),
                    )
                    if handle is None or not handle.state.get("running"):
                        client.send(json.dumps({
                            "type": "input_rejected",
                            "data": {"message": "The addressed interactive execution is not running."},
                        }))
                        continue
                    if handle.state.get("pending_approval"):
                        client.send(json.dumps({
                            "type": "input_rejected",
                            "data": {"message": "Use the explicit approval controls; chat input cannot approve a dangerous action."},
                        }))
                        continue
                    print(f"[WS] putting input into queue: {data.get('text', '')}")
                    handle.state["waiting_for_input"] = False
                    handle.input_queue.put(data.get("text", ""))
                    handle.touch()
            except Exception as e:
                print(f"[WS] error parsing message: {e}")
    except Exception as e:
        print(f"[WS] connection error: {e}")
    finally:
        ws_clients.discard(client)
        client.close()
        conn.close()


def main():
    import socket
    import subprocess
    import signal

    http_port = 8765
    ws_port = 8766
    bind_host = os.environ.get("EGOAGENT_HOST", "127.0.0.1")

    # Kill any process occupying our ports (works even without fuser/lsof)
    for port in [http_port, ws_port]:
        try:
            # Use /proc/net/tcp to find processes on the port
            port_hex = f"{port:04X}"
            pids_to_kill = set()
            with open("/proc/net/tcp") as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) >= 10:
                        local_addr = parts[1]
                        if local_addr.endswith(f":{port_hex}") and parts[3] == "0A":  # LISTEN state
                            inode = parts[9]
                            # Find pid by scanning /proc/*/fd
                            import glob
                            for fd_link in glob.glob("/proc/[0-9]*/fd/*"):
                                try:
                                    target = os.readlink(fd_link)
                                    if f"socket:[{inode}]" in target:
                                        pid = int(fd_link.split("/")[2])
                                        if pid != os.getpid():
                                            pids_to_kill.add(pid)
                                except (PermissionError, FileNotFoundError, ValueError):
                                    pass
            for pid in pids_to_kill:
                try:
                    os.kill(pid, signal.SIGKILL)
                    print(f"[API Server] Killed stale process {pid} on port {port}")
                except ProcessLookupError:
                    pass
            if pids_to_kill:
                import time
                time.sleep(0.5)
        except Exception:
            pass

    httpd = ThreadingHTTPServer((bind_host, http_port), APIHandler)

    ws_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    ws_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    ws_sock.bind((bind_host, ws_port))
    ws_sock.listen(5)

    print(f"[API Server] HTTP: http://localhost:{http_port}")
    print(f"[API Server] WS:   ws://localhost:{ws_port}")
    print(f"[API Server] Harness dir: {HARNESS_DIR}")
    print(f"[API Server] Identity dir: {IDENTITY_DIR}")
    durable_worker = _start_durable_run_worker()
    print(f"[API Server] Durable run worker: {durable_worker.owner}")

    def run_ws():
        while True:
            try:
                conn, addr = ws_sock.accept()
                request = conn.recv(4096).decode("utf-8", errors="ignore")
                if "Upgrade: websocket" in request:
                    key = ""
                    origin = ""
                    for line in request.split("\r\n"):
                        if line.lower().startswith("sec-websocket-key:"):
                            key = line.split(":", 1)[1].strip()
                        elif line.lower().startswith("origin:"):
                            origin = line.split(":", 1)[1].strip()
                    if origin and not is_trusted_local_origin(origin):
                        conn.sendall(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
                        conn.close()
                    elif key:
                        import hashlib
                        accept = base64.b64encode(
                            hashlib.sha1(
                                (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
                            ).digest()
                        ).decode()
                        response = (
                            "HTTP/1.1 101 Switching Protocols\r\n"
                            "Upgrade: websocket\r\n"
                            "Connection: Upgrade\r\n"
                            f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
                        )
                        conn.send(response.encode())
                        handle_ws(conn)
                    else:
                        conn.close()
                else:
                    conn.close()
            except Exception:
                pass

    ws_thread = threading.Thread(target=run_ws, daemon=True)
    ws_thread.start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[API Server] Shutting down...")
    finally:
        durable_worker.stop(timeout=2)
        httpd.server_close()
        ws_sock.close()


if __name__ == "__main__":
    main()
