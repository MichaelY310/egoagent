"""Unified declarative DAG runtime for EgoAgent.

One execution engine powers terminal, WebSocket and OpenAI-compatible streaming.
The original node names remain valid, while newer graphs can use explicit
inputs/outputs, safe conditions, data nodes, parallel branches and reliability
policies without falling back to Python scripts.
"""

from __future__ import annotations

import contextvars
import base64
import copy
import difflib
import fnmatch
import hashlib
import inspect
import json
import os
import queue
import re
import signal
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from agent_bus import AgentBus, AgentBusError
from llm.env_config import SecretView
from permissions import PermissionClass, RuntimePolicy
from node_registry import SIDE_EFFECTING_NODE_OPS, execute_registered_node
from process_backends import ProcessBackendError, build_container_invocation, cleanup_container
from runtime_contracts import ToolExecutionRequest
from pipeline_schema import (
    SafeExpressionError,
    assert_valid_pipeline,
    canonical_op,
    delete_path,
    evaluate_expression,
    get_path,
    resolve_reference,
    set_path,
    validate_json_schema,
)


_MEMORY_LOCKS_GUARD = threading.Lock()
_MEMORY_LOCKS: dict[str, threading.RLock] = {}
_RESOURCE_POOLS_GUARD = threading.Lock()
_RESOURCE_POOLS: dict[tuple[str, str, int], threading.BoundedSemaphore] = {}
_EVENT_LOGS_GUARD = threading.Lock()
_EVENT_LOGS: dict[str, dict[str, Any]] = {}


def _mutation_event_for_tool(name: str, arguments: Any, result: Any) -> Optional[str]:
    """Classify successful mutation tools for Studio/Task Bench traces.

    Skills remain ordinary tools and do not need to import frontend/runtime
    modules. The engine observes every completed call, so it can emit
    consistent evidence without coupling each Skill to Studio. Read-only and
    dry-run actions are deliberately excluded.
    """

    short_name = str(name or "").split(":")[-1].lower()
    args = arguments if isinstance(arguments, dict) else {}
    parsed_result = result
    if isinstance(result, str):
        lowered = result.strip().lower()
        if lowered.startswith("error") or (lowered.startswith("tool ") and " error:" in lowered[:240]):
            return None
        if result.lstrip().startswith(("{", "[")):
            try:
                parsed_result = json.loads(result)
            except (TypeError, ValueError):
                pass
    if isinstance(parsed_result, dict) and parsed_result.get("ok") is False:
        return None

    if short_name == "evolve_capabilities":
        return "identity_evolution" if str(args.get("action", "")).lower() in {"install", "rollback"} else None
    if short_name == "manage_harness":
        action = str(args.get("action", "")).lower()
        return "harness_mutation" if action in {"create", "patch", "apply", "rollback"} else None
    if short_name == "create_agent_system":
        return "agent_system_created"
    if short_name in {"design_harness", "modify_harness"}:
        return "harness_mutation"
    if short_name in {
        "copy_identity", "create_identity", "create_knowledge", "create_skill", "create_tool",
        "modify_identity", "run_evolution_cycle",
    }:
        return "identity_evolution"
    return None


def _mutation_event_payload(name: str, arguments: Any, result: Any, *, agent: str = "") -> dict[str, Any]:
    """Expose one stable mutation event contract to every runtime surface.

    The full tool request/result remain available for exact replay.  The
    normalized fields are the small interface consumed by Studio, Task Bench
    and trajectory exporters, so those clients do not need tool-specific JSON
    parsing.
    """

    args = copy.deepcopy(arguments if isinstance(arguments, dict) else {})
    parsed = result
    if isinstance(result, str) and result.lstrip().startswith("{"):
        try:
            parsed = json.loads(result)
        except (TypeError, ValueError):
            parsed = {}
    value = parsed if isinstance(parsed, dict) else {}
    blueprint = value.get("blueprint") if isinstance(value.get("blueprint"), dict) else {}
    short_name = str(name or "").split(":")[-1]
    action = args.get("action") or value.get("action")
    if not action:
        action = "create" if short_name == "create_agent_system" else "update"
    raw_identity = value.get("identity")
    identity = raw_identity.get("name") if isinstance(raw_identity, dict) else raw_identity
    return {
        "tool": name,
        "agent": agent,
        "action": str(action),
        "harness": str(args.get("harness_name") or value.get("harness") or value.get("name") or blueprint.get("name") or ""),
        "identity": str(identity or args.get("identity_name") or ""),
        "revision": str(value.get("revision") or value.get("revision_after") or ""),
        "transaction_id": str(value.get("transaction_id") or ""),
        "operations": copy.deepcopy(args.get("operations") or value.get("operations") or []),
        "diff": copy.deepcopy(value.get("diff")),
        "nodes": copy.deepcopy(value.get("current_nodes") or []),
        "arguments": _debug_value(arguments, limit=20000),
        "result": _debug_value(result, limit=50000),
    }


def _tool_result_succeeded(result: Any) -> bool:
    """Conservatively decide whether a tool observation represents success."""
    value = result
    if isinstance(result, str):
        text = result.strip()
        if text.lower().startswith(("error", "tool ", "permission denied")):
            return False
        try:
            value = json.loads(text)
        except (TypeError, ValueError):
            return True
    if isinstance(value, dict):
        if value.get("error") or value.get("ok") is False or value.get("success") is False:
            return False
        exit_code = value.get("exit_code")
        if exit_code is not None:
            try:
                if int(exit_code) != 0:
                    return False
            except (TypeError, ValueError):
                return False
        if str(value.get("status", "")).lower() in {"error", "failed", "denied", "blocked"}:
            return False
    return True


def _tool_response_call_id(message: dict[str, Any]) -> tuple[bool, Optional[str]]:
    """Identify a provider-native or EgoAgent XML tool observation."""

    if message.get("role") == "tool":
        value = str(message.get("tool_call_id") or "").strip()
        return True, value or None
    content = str(message.get("content") or "")
    if message.get("role") != "user" or "<tool_response>" not in content:
        return False, None
    match = re.search(r"<tool_response>\s*(.*?)\s*</tool_response>", content, re.DOTALL)
    if not match:
        return True, None
    try:
        payload = json.loads(match.group(1))
    except (TypeError, ValueError):
        return True, None
    value = str(payload.get("tool_call_id") or "").strip() if isinstance(payload, dict) else ""
    return True, value or None


def _is_same_agent_tool_continuation(
    messages: list[dict[str, Any]],
    agent_name: str,
    *,
    allow_unnamed_assistant: bool = False,
) -> bool:
    """Return whether history ends in this Agent's completed tool-call batch.

    A shared multi-Agent session may end in another worker's tool observation.
    Continuation policy is valid only for the assistant that authored the
    paired call; otherwise it changes the semantics of the next DAG node.
    """

    index = len(messages) - 1
    response_ids: set[str] = set()
    saw_response = False
    while index >= 0:
        message = messages[index]
        if message.get("role") == "system" or (
            message.get("role") == "user" and message.get("name") == "tool_image"
        ):
            index -= 1
            continue
        is_response, call_id = _tool_response_call_id(message)
        if not is_response:
            break
        saw_response = True
        if call_id:
            response_ids.add(call_id)
        index -= 1
    if not saw_response:
        return False
    while index >= 0 and messages[index].get("role") == "system":
        index -= 1
    if index < 0:
        return False
    request = messages[index]
    content = str(request.get("content") or "")
    if request.get("role") != "assistant":
        return False
    source_name = str(request.get("name") or "").strip()
    if source_name:
        if source_name != str(agent_name or "").strip():
            return False
    elif not allow_unnamed_assistant:
        return False
    calls = request.get("tool_calls")
    has_tool_request = bool(isinstance(calls, list) and calls) or "<tool_call>" in content
    if not has_tool_request:
        return False
    request_ids = {
        str(call.get("id") or "").strip()
        for call in (calls or [])
        if isinstance(call, dict) and str(call.get("id") or "").strip()
    }
    return not response_ids or not request_ids or response_ids.issubset(request_ids)


def _looks_like_mutation_request(value: Any) -> bool:
    text = str(value or "").lower()
    if not text.strip():
        return False
    verbs = re.compile(
        r"(?:\b(?:edit|modify|change|fix|implement|create|write|delete|replace|rename|refactor|add|remove)\b|"
        r"修改|更改|编辑|实现|创建|新增|删除|替换|重命名|重构|修复|写入)"
    )
    targets = re.compile(
        r"(?:\b(?:file|code|source|repo|repository|project|function|class|test|config)\b|"
        r"文件|代码|源码|仓库|项目|函数|类|测试|配置|[A-Za-z]:[\\/]|[\w.-]+\.[A-Za-z0-9]{1,8}\b)"
    )
    return bool(verbs.search(text) and targets.search(text))


def _process_group_options() -> dict[str, Any]:
    """Start a Process node in a group that can be terminated as one unit."""
    if os.name == "nt":
        return {
            "creationflags": (
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
                | getattr(subprocess, "CREATE_SUSPENDED", 0x00000004)
            )
        }
    return {"start_new_session": True}


def _windows_assign_kill_job_and_resume(process: subprocess.Popen) -> Optional[int]:
    """Put a suspended child in a kill-on-close Job before it can spawn."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
    ntdll.NtResumeProcess.restype = ctypes.c_long

    job = kernel32.CreateJobObjectW(None, None)
    assigned = False
    try:
        if job:
            limits = EXTENDED_LIMIT_INFORMATION()
            limits.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            configured = kernel32.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits))
            if configured:
                assigned = bool(kernel32.AssignProcessToJobObject(job, wintypes.HANDLE(int(process._handle))))
        status = int(ntdll.NtResumeProcess(wintypes.HANDLE(int(process._handle))))
        if status != 0:
            raise OSError(f"NtResumeProcess failed with status 0x{status & 0xFFFFFFFF:08x}")
        if assigned:
            return int(job)
        if job:
            kernel32.CloseHandle(job)
        return None
    except BaseException:
        if job:
            kernel32.CloseHandle(job)
        try:
            process.kill()
        except OSError:
            pass
        raise


def _windows_close_kill_job(handle: Optional[int]) -> None:
    if os.name != "nt" or not handle:
        return
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle(wintypes.HANDLE(int(handle)))


def _windows_process_descendants(ancestor_pids: set[int]) -> Optional[list[int]]:
    """Return Windows descendants in parent-first order using Toolhelp32."""
    try:
        import ctypes
        from ctypes import wintypes

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        kernel32.Process32FirstW.restype = wintypes.BOOL
        kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        kernel32.Process32NextW.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
        if snapshot == wintypes.HANDLE(-1).value:
            return None
        pairs: list[tuple[int, int]] = []
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(entry)
            ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while ok:
                pairs.append((int(entry.th32ProcessID), int(entry.th32ParentProcessID)))
                ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snapshot)

        discovered: list[int] = []
        parents = set(int(pid) for pid in ancestor_pids)
        while True:
            generation = [pid for pid, parent in pairs if parent in parents and pid not in parents]
            generation = [pid for pid in generation if pid not in discovered]
            if not generation:
                break
            discovered.extend(generation)
            parents.update(generation)
        return discovered
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def _windows_terminate_pids(pids: Iterable[int]) -> int:
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.TerminateProcess.restype = wintypes.BOOL
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        killed = 0
        for pid in pids:
            handle = kernel32.OpenProcess(0x00000001 | 0x00100000, False, int(pid))
            if not handle:
                continue
            try:
                if kernel32.TerminateProcess(handle, 1):
                    killed += 1
                kernel32.WaitForSingleObject(handle, 2000)
            finally:
                kernel32.CloseHandle(handle)
        return killed
    except (AttributeError, OSError, TypeError, ValueError):
        return 0


def _terminate_process_tree(process: subprocess.Popen, grace_seconds: float = 0.5) -> str:
    """Terminate a Process node and every descendant without invoking a shell."""
    if process.poll() is not None and os.name != "nt":
        return "already_exited"

    grace_seconds = max(0.0, float(grace_seconds))
    if os.name == "nt":
        descendants = _windows_process_descendants({process.pid}) or []
        known_order = [process.pid, *descendants]
        known = set(known_order)

        # Ask Windows to terminate the tree while the root still exists.  This
        # closes the race where killing the parent first reparents a just-spawned
        # child before the next Toolhelp snapshot.  taskkill is invoked directly
        # (never through a shell); native handles below remain defense in depth.
        try:
            completed = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=max(2.0, grace_seconds + 1.0),
                check=False,
                shell=False,
            )
            strategy = "windows_taskkill_tree" if completed.returncode == 0 else "windows_native_process_tree"
        except (OSError, subprocess.SubprocessError):
            strategy = "windows_native_process_tree"

        # Re-enumerate and retry every known descendant, not only newly seen
        # PIDs. OpenProcess/TerminateProcess can transiently fail while a process
        # is starting, which previously allowed a grandchild to survive timeout.
        for _ in range(5):
            remaining = _windows_process_descendants(known)
            if remaining is not None:
                for pid in remaining:
                    if pid not in known:
                        known.add(pid)
                        known_order.append(pid)
            _windows_terminate_pids(reversed(known_order[1:]))
            if process.poll() is None:
                process.kill()
            time.sleep(0.02)
        try:
            process.wait(timeout=max(0.1, grace_seconds))
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        return strategy

    strategy = "posix_process_group"
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except (OSError, ProcessLookupError):
        process.terminate()
    try:
        process.wait(timeout=max(0.05, grace_seconds))
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except (OSError, ProcessLookupError):
            process.kill()
        process.wait()
    return strategy


def _memory_lock(path: Path) -> threading.RLock:
    key = str(path)
    with _MEMORY_LOCKS_GUARD:
        return _MEMORY_LOCKS.setdefault(key, threading.RLock())


def _transition_condition(state: dict[str, Any], condition: dict[str, Any]) -> tuple[bool, str]:
    """Evaluate one declarative state precondition without executing code."""
    path = str(condition.get("path", "")).strip()
    if not path:
        return False, "missing_path"
    marker = object()
    actual = get_path(state, path, marker)
    operator_name = str(condition.get("operator", condition.get("op", "eq"))).lower()
    expected = condition.get("value")
    try:
        if operator_name in {"exists", "present"}:
            passed = actual is not marker
        elif operator_name in {"missing", "absent"}:
            passed = actual is marker
        elif actual is marker:
            passed = False
        elif operator_name in {"eq", "equals"}:
            passed = actual == expected
        elif operator_name in {"ne", "not_equals"}:
            passed = actual != expected
        elif operator_name in {"gte", "ge"}:
            passed = actual >= expected
        elif operator_name in {"lte", "le"}:
            passed = actual <= expected
        elif operator_name == "gt":
            passed = actual > expected
        elif operator_name == "lt":
            passed = actual < expected
        elif operator_name == "in":
            passed = actual in expected
        elif operator_name == "contains":
            passed = expected in actual
        else:
            return False, f"unsupported_operator:{operator_name}"
    except (TypeError, ValueError):
        passed = False
    return bool(passed), "ok" if passed else f"precondition_failed:{path}:{operator_name}"


def _apply_state_transition(
    current: dict[str, Any],
    transition: dict[str, Any],
    *,
    schema: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Apply a bounded, schema-checked transaction to an object copy.

    The function is pure: rejected transitions always return the untouched
    input state.  It is intentionally reusable by non-game DAGs such as
    inventory, experiment and deployment state machines.
    """
    original = copy.deepcopy(current)
    candidate = copy.deepcopy(current)
    reason_codes: list[str] = []
    current_revision = int(current.get("_revision", 0) or 0)
    expected_revision = transition.get("expected_revision")
    if expected_revision is not None and int(expected_revision) != current_revision:
        reason_codes.append("revision_conflict")

    preconditions = transition.get("preconditions", []) or []
    if not isinstance(preconditions, list) or len(preconditions) > 100:
        raise PipelineError("state_transition preconditions must be an array of at most 100 items")
    for raw_condition in preconditions:
        if not isinstance(raw_condition, dict):
            raise PipelineError("state_transition precondition must be an object")
        passed, reason = _transition_condition(candidate, raw_condition)
        if not passed:
            reason_codes.append(str(raw_condition.get("reason") or reason))

    operations = transition.get("operations", []) or []
    if not isinstance(operations, list) or len(operations) > 100:
        raise PipelineError("state_transition operations must be an array of at most 100 items")
    if not reason_codes:
        for operation in operations:
            if not isinstance(operation, dict):
                raise PipelineError("state_transition operation must be an object")
            operation_name = str(operation.get("op", "set")).lower()
            path = str(operation.get("path", "")).strip()
            if not path or path.startswith("_revision"):
                raise PipelineError("state_transition operation requires a non-revision path")
            operand = copy.deepcopy(operation.get("value"))
            if operation_name == "set":
                set_path(candidate, path, operand)
            elif operation_name in {"increment", "decrement"}:
                existing = get_path(candidate, path, 0)
                if not isinstance(existing, (int, float)) or isinstance(existing, bool):
                    raise PipelineError(f"state_transition {path!r} is not numeric")
                amount = operand if operand is not None else 1
                if not isinstance(amount, (int, float)) or isinstance(amount, bool):
                    raise PipelineError("state_transition increment value must be numeric")
                result = existing + (amount if operation_name == "increment" else -amount)
                if operation.get("minimum") is not None:
                    result = max(float(operation["minimum"]), result)
                if operation.get("maximum") is not None:
                    result = min(float(operation["maximum"]), result)
                if isinstance(existing, int) and float(result).is_integer():
                    result = int(result)
                set_path(candidate, path, result)
            elif operation_name == "append":
                existing = get_path(candidate, path, [])
                if not isinstance(existing, list):
                    raise PipelineError(f"state_transition {path!r} is not a list")
                set_path(candidate, path, [*copy.deepcopy(existing), operand])
            elif operation_name == "extend":
                existing = get_path(candidate, path, [])
                if not isinstance(existing, list) or not isinstance(operand, list):
                    raise PipelineError("state_transition extend requires two lists")
                set_path(candidate, path, [*copy.deepcopy(existing), *operand])
            elif operation_name == "merge":
                existing = get_path(candidate, path, {})
                if not isinstance(existing, dict) or not isinstance(operand, dict):
                    raise PipelineError("state_transition merge requires two objects")
                set_path(candidate, path, {**copy.deepcopy(existing), **operand})
            elif operation_name == "remove":
                existing = get_path(candidate, path, [])
                if not isinstance(existing, list):
                    raise PipelineError("state_transition remove requires a list")
                set_path(candidate, path, [item for item in existing if item != operand])
            elif operation_name == "delete":
                delete_path(candidate, path)
            else:
                raise PipelineError(f"unsupported state_transition operation: {operation_name}")

        candidate["_revision"] = current_revision + 1
        validation_errors = validate_json_schema(candidate, schema or {}, path="$state")
        if validation_errors:
            reason_codes.extend(f"schema:{error}" for error in validation_errors)

    accepted = not reason_codes
    return {
        "accepted": accepted,
        "state": candidate if accepted else original,
        "revision": current_revision + 1 if accepted else current_revision,
        "reason_codes": reason_codes,
        "metadata": copy.deepcopy(transition.get("metadata", {})),
    }


def _resource_pool(workspace: str, name: str, capacity: int) -> threading.BoundedSemaphore:
    key = (workspace, name, capacity)
    with _RESOURCE_POOLS_GUARD:
        return _RESOURCE_POOLS.setdefault(key, threading.BoundedSemaphore(capacity))


def _append_event_log(path: Path, record: dict[str, Any]) -> None:
    key = str(path)
    with _EVENT_LOGS_GUARD:
        if key not in _EVENT_LOGS:
            sequence = 0
            if path.is_file():
                for line in reversed(path.read_text(encoding="utf-8").splitlines()):
                    if line.strip():
                        try:
                            sequence = int(json.loads(line).get("sequence", 0))
                        except (TypeError, ValueError):
                            sequence = 0
                        break
            _EVENT_LOGS[key] = {"sequence": sequence}
        state = _EVENT_LOGS[key]
        state["sequence"] += 1
        payload = {**record, "sequence": state["sequence"]}
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def _redact_event_value(value: Any, key: str = "") -> Any:
    lowered = key.lower()
    normalized = lowered.replace("-", "_")
    sensitive_key = (
        any(marker in normalized for marker in ("password", "passwd", "api_key", "apikey", "secret", "authorization", "cookie"))
        or normalized in {"token", "access_token", "refresh_token", "id_token", "bearer_token"}
        or (normalized.endswith("_token") and not normalized.endswith("_tokens"))
    )
    if sensitive_key:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(child_key): _redact_event_value(child, str(child_key)) for child_key, child in value.items()}
    if isinstance(value, list):
        return [_redact_event_value(child) for child in value]
    return value


class PipelineError(RuntimeError):
    pass


class PipelineCancelled(PipelineError):
    pass


class PipelineBudgetExceeded(PipelineError):
    pass


class PipelineRevisionConflict(PipelineError):
    """A saved run no longer matches files or Agent resources on disk."""

    retryable = False

    def __init__(self, conflicts: list[dict[str, Any]]):
        self.conflicts = conflicts
        summary = ", ".join(str(item.get("resource", "unknown")) for item in conflicts[:5])
        if len(conflicts) > 5:
            summary += f" and {len(conflicts) - 5} more"
        super().__init__(f"checkpoint revision conflict: {summary}")


class PipelineInDoubt(PipelineError):
    """A worker stopped while a side-effecting node may have been running."""

    retryable = False

    def __init__(self, node_id: str, operation: str = ""):
        self.node_id = str(node_id or "")
        self.operation = str(operation or "")
        detail = f" ({self.operation})" if self.operation else ""
        super().__init__(
            f"checkpoint stopped inside node '{self.node_id}'{detail}; inspect its effects before resuming"
        )


class NodeTimeout(PipelineError):
    pass


class OutputValidationError(PipelineError):
    pass


@dataclass
class RunStats:
    started_at: float = field(default_factory=time.monotonic)
    node_steps: int = 0
    model_calls: int = 0
    tool_calls: int = 0
    process_calls: int = 0
    retries: int = 0
    input_tokens_estimated: int = 0
    output_tokens_estimated: int = 0
    cost_estimated: float = 0.0
    provider_requests: int = 0
    provider_retries: int = 0
    input_tokens_actual: int = 0
    output_tokens_actual: int = 0
    cached_input_tokens_actual: int = 0
    cost_actual: float = 0.0
    provider_request_ids: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "node_steps": self.node_steps,
            "model_calls": self.model_calls,
            "tool_calls": self.tool_calls,
            "process_calls": self.process_calls,
            "retries": self.retries,
            "input_tokens_estimated": self.input_tokens_estimated,
            "output_tokens_estimated": self.output_tokens_estimated,
            "tokens_estimated": self.input_tokens_estimated + self.output_tokens_estimated,
            "cost_estimated": round(self.cost_estimated, 8),
            "provider_requests": self.provider_requests,
            "provider_retries": self.provider_retries,
            "input_tokens_actual": self.input_tokens_actual,
            "output_tokens_actual": self.output_tokens_actual,
            "cached_input_tokens_actual": self.cached_input_tokens_actual,
            "tokens_actual": self.input_tokens_actual + self.output_tokens_actual,
            "cost_actual": round(self.cost_actual, 8),
            "provider_request_ids": list(self.provider_request_ids),
            "elapsed_seconds": round(time.monotonic() - self.started_at, 3),
        }

    def add(self, other: "RunStats") -> None:
        self.node_steps += other.node_steps
        self.model_calls += other.model_calls
        self.tool_calls += other.tool_calls
        self.process_calls += other.process_calls
        self.retries += other.retries
        self.input_tokens_estimated += other.input_tokens_estimated
        self.output_tokens_estimated += other.output_tokens_estimated
        self.cost_estimated += other.cost_estimated
        self.provider_requests += other.provider_requests
        self.provider_retries += other.provider_retries
        self.input_tokens_actual += other.input_tokens_actual
        self.output_tokens_actual += other.output_tokens_actual
        self.cached_input_tokens_actual += other.cached_input_tokens_actual
        self.cost_actual += other.cost_actual
        for request_id in other.provider_request_ids:
            if request_id not in self.provider_request_ids:
                self.provider_request_ids.append(request_id)


@dataclass
class NodeOutcome:
    output: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    next_node: Optional[str] = None
    stop: bool = False
    error: Optional[BaseException] = None


@dataclass
class RunContext:
    harness: Any
    graph: dict
    on_output: Callable[[str, dict], None]
    get_input: Callable[[], Optional[str]]
    is_running: Callable[[], bool]
    get_approval: Optional[Callable] = field(default=None, repr=False, kw_only=True)
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    data: dict[str, Any] = field(default_factory=dict)
    node_outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    last_output: dict[str, Any] = field(default_factory=dict)
    last_input: Any = None
    text: Optional[str] = None
    tool_calls: Optional[list] = None
    result: Any = None
    stats: RunStats = field(default_factory=RunStats)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    current_node: Optional[str] = None
    stop_at: set[str] = field(default_factory=set)
    last_tool_signature: Optional[str] = None
    event_log_path: Optional[Path] = None
    parent: Optional["RunContext"] = field(default=None, repr=False)
    parent_run_id: Optional[str] = None
    deadline_monotonic: Optional[float] = None
    secret_view: SecretView = field(default_factory=SecretView, repr=False)
    permission_policy: Optional[RuntimePolicy] = field(default=None, repr=False)
    change_transaction_id: Optional[str] = None
    default_change_transaction_id: str = field(init=False)
    workspace: Path = field(init=False)
    session: Any = field(init=False, repr=False)
    child_run_ids: set[str] = field(default_factory=set)
    approved_tool_call_ids: set[str] = field(default_factory=set, repr=False)
    pending_approvals: dict[str, dict[str, Any]] = field(default_factory=dict)
    artifacts: set[str] = field(default_factory=set)
    completed_steps: list[dict[str, Any]] = field(default_factory=list)
    child_run_tree: dict[str, dict[str, Any]] = field(default_factory=dict)
    _children: dict[str, "RunContext"] = field(default_factory=dict, repr=False)
    _children_lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    flow_observer: Any = field(default=None, init=False, repr=False)
    observation_error: Optional[str] = field(default=None, init=False)

    def __post_init__(self) -> None:
        self.workspace = Path(self.harness.workspace or self.harness.dir).resolve()
        self.session = self.harness.session
        if self.parent is not None:
            # Independent child Sessions keep their own working conversation,
            # but every descendant writes into the parent's root trajectory so
            # model calls can be replayed in one globally ordered stream.
            attach = getattr(self.session, "attach_trajectory", None)
            parent_recorder = getattr(getattr(self.parent, "session", None), "trajectory", None)
            if callable(attach) and parent_recorder is not None:
                attach(parent_recorder)
        self.default_change_transaction_id = f"run-{self.run_id}"
        if self.change_transaction_id is None:
            self.change_transaction_id = self.default_change_transaction_id
        recorder = getattr(self.session, "trajectory", None)
        if recorder is not None and self.parent is None:
            slot_snapshots = {}
            snapshot_payloads = []
            for slot, agent in getattr(self.harness, "agents", {}).items():
                capture = getattr(agent, "capability_snapshot", None)
                if not callable(capture):
                    continue
                snapshot = capture()
                slot_snapshots[str(slot)] = snapshot.get("snapshot_id")
                snapshot_payloads.append((str(slot), agent, snapshot))
            recorder.append(
                "trace.started",
                {
                    "workspace": str(self.workspace),
                    "harness": getattr(self.harness, "name", None),
                    "slots": {
                        str(slot): Path(getattr(getattr(agent, "identity", None), "identity_path", "")).name
                        for slot, agent in getattr(self.harness, "agents", {}).items()
                    },
                    "capability_snapshots": slot_snapshots,
                },
                session_id=getattr(self.session, "session_id", None),
                run_id=self.run_id,
                harness=getattr(self.harness, "name", None),
            )
            for slot, agent, snapshot in snapshot_payloads:
                identity_path = getattr(getattr(agent, "identity", None), "identity_path", None)
                recorder.register_capability_snapshot(
                    snapshot,
                    session_id=getattr(self.session, "session_id", None),
                    run_id=self.run_id,
                    harness=getattr(self.harness, "name", None),
                    agent=str(getattr(agent, "name", None) or slot),
                    identity=Path(identity_path).name if identity_path else None,
                )

    @property
    def event_sink(self) -> Callable[[str, dict], None]:
        return self.on_output

    def observe(self, event: str, data: dict) -> None:
        if self.observation_error is not None:
            return
        try:
            if self.flow_observer is None:
                from flow_observation import FlowObserver
                self.flow_observer = FlowObserver(self)
            self.flow_observer.emit(event, data)
        except Exception as error:
            # Telemetry failure must never re-execute a tool, fail an Agent,
            # or introduce a second control loop. Expose a bounded warning.
            self.observation_error = type(error).__name__
            import logging
            logging.getLogger(__name__).warning("Flow recording unavailable for run %s (%s)", self.run_id, self.observation_error)

    @property
    def active_child_run_ids(self) -> tuple[str, ...]:
        with self._children_lock:
            return tuple(self._children)

    def emit(self, event: str, payload: Optional[Any] = None) -> None:
        # Preview helpers intentionally collapse large structured payloads to a
        # bounded string. Preserve that event instead of trying dict(string),
        # which raises when a tool observation exceeds the preview limit.
        data = dict(payload) if isinstance(payload, dict) else ({"value": payload} if payload is not None else {})
        # A SubFlow publishes its event through each ancestor so the root UI
        # sees one live stream.  The child already persisted the canonical
        # event, however; recording again at every wrapper used to duplicate
        # a single context mutation two or three times in replay/training
        # trajectories.  Keep this transport marker out of public payloads.
        trajectory_recorded = bool(data.pop("_egoagent_trajectory_recorded", False))
        data.setdefault("run_id", self.run_id)
        if self.parent_run_id:
            data.setdefault("parent_run_id", self.parent_run_id)
        if self.current_node is not None:
            data.setdefault("node_id", self.current_node)
        safe_data = self.secret_view.redact_value(_redact_event_value(data))
        if not trajectory_recorded:
            self.observe(event, safe_data)
        recorder = getattr(self.session, "trajectory", None)
        if recorder is not None and not trajectory_recorded:
            agent_name = str(data.get("agent") or "") or None
            identity_name = None
            if agent_name:
                agent_instance = getattr(self.harness, "agents", {}).get(agent_name)
                identity_path = getattr(getattr(agent_instance, "identity", None), "identity_path", None)
                if identity_path:
                    identity_name = Path(identity_path).name
            node_op = None
            if self.current_node:
                node_spec = self.graph.get("nodes", {}).get(self.current_node, {})
                if isinstance(node_spec, dict):
                    node_op = canonical_op(node_spec.get("op", ""))
            recorder.append(
                "runtime.event",
                {"event": event, "payload": safe_data},
                session_id=getattr(self.session, "session_id", None),
                run_id=self.run_id,
                parent_run_id=self.parent_run_id,
                harness=getattr(self.harness, "name", None),
                node_id=self.current_node,
                node_op=node_op,
                agent=agent_name,
                identity=identity_name,
                model_call_id=str(data.get("model_call_id") or "") or None,
                tool_call_id=str(data.get("tool_call_id") or "") or None,
                tags=[event],
            )
            semantic_types = {
                "run_started": "run.started",
                "done": "run.completed",
                "cancelled": "run.cancelled",
                "node_enter": "node.started",
                "node_exit": "node.completed",
                "checkpoint": "checkpoint.saved",
                "resumed": "checkpoint.restored",
                "approval_required": "approval.requested",
                "approval": "approval.resolved",
                "context_compacted": "context.compacted",
                "harness_mutation": "evolution.harness.mutated",
                "identity_evolution": "evolution.identity.changed",
                "agent_system_created": "evolution.agent.created",
                "evolution_proposal": "evolution.proposed",
                "evolution_evaluated": "evolution.evaluated",
                "evolution_promoted": "evolution.promoted",
                "evolution_rollback": "evolution.rolled_back",
            }
            if event in semantic_types:
                recorder.append(
                    semantic_types[event],
                    safe_data,
                    session_id=getattr(self.session, "session_id", None),
                    run_id=self.run_id,
                    parent_run_id=self.parent_run_id,
                    harness=getattr(self.harness, "name", None),
                    node_id=self.current_node,
                    node_op=node_op,
                    agent=agent_name,
                    identity=identity_name,
                    model_call_id=str(data.get("model_call_id") or "") or None,
                    tool_call_id=str(data.get("tool_call_id") or "") or None,
                )
        if self.event_log_path is not None and not trajectory_recorded:
            try:
                _append_event_log(
                    self.event_log_path,
                    {
                        "version": 1,
                        "timestamp": time.time(),
                        "event": event,
                        "run_id": self.run_id,
                        "node_id": data.get("node_id"),
                        "payload": safe_data,
                    },
                )
            except OSError as error:
                self.data["_event_log_error"] = str(error)
        forwarded = safe_data
        if self.parent is not None or trajectory_recorded:
            forwarded = {**safe_data, "_egoagent_trajectory_recorded": True}
        # The root is the last forwarding hop; internal transport metadata
        # must never leak into Task Bench, Chat, exports, or user callbacks.
        if self.parent is None:
            forwarded.pop("_egoagent_trajectory_recorded", None)
        self.on_output(event, forwarded)

    def cancelled(self) -> bool:
        from runtime_waits import deadline_cancelled
        if deadline_cancelled():
            return True
        if self.cancel_event.is_set():
            return True
        if self.parent is not None and self.parent.cancelled():
            return True
        if self.deadline_monotonic is not None and time.monotonic() >= self.deadline_monotonic:
            return True
        return not self.is_running()

    def cancel(self, *, cascade: bool = True) -> None:
        self.cancel_event.set()
        if cascade:
            with self._children_lock:
                children = list(self._children.values())
            for child in children:
                child.cancel(cascade=True)

    def register_child(self, child: "RunContext") -> None:
        with self._children_lock:
            self.child_run_ids.add(child.run_id)
            self._children[child.run_id] = child

    def release_child(self, child: "RunContext") -> None:
        with self._children_lock:
            self._children.pop(child.run_id, None)
            self.child_run_tree[child.run_id] = {
                "run_id": child.run_id,
                "parent_run_id": child.parent_run_id,
                "result": _preview_value(child.result),
                "error": copy.deepcopy(child.data.get("_error")),
                "stats": child.stats.as_dict(),
                "children": copy.deepcopy(child.child_run_tree),
            }

    def publish(self, node_id: str, node: dict, output: dict[str, Any]) -> None:
        copied = copy.deepcopy(output)
        self.node_outputs[node_id] = copied
        self.data.setdefault("_nodes", {})[node_id] = copied
        self.last_output = copied
        raw_artifacts = output.get("artifacts")
        if isinstance(raw_artifacts, (list, tuple, set)):
            self.artifacts.update(str(value) for value in raw_artifacts if value not in (None, ""))

        if "text" in output:
            self.text = output.get("text")
            self.data["text"] = self.text
        if "tool_calls" in output:
            self.tool_calls = output.get("tool_calls")
            self.data["tool_calls"] = self.tool_calls

        for port, target in node.get("outputs", {}).items():
            if not isinstance(target, str) or not target:
                continue
            value = get_path(output, port, None)
            normalized = target[5:] if target.startswith("$ctx.") else target
            set_path(self.data, normalized, copy.deepcopy(value))

    def variables(self) -> dict[str, Any]:
        return {
            "ctx": self.data,
            "data": self.data,
            "nodes": self.node_outputs,
            "node": self.node_outputs,
            "last": self.last_output,
            "text": self.text,
            "tool_calls": self.tool_calls,
            "stats": self.stats.as_dict(),
            "session": {
                "messages": self.harness.session.messages,
                "full_messages": self.harness.session.full_messages,
                "state": self.harness.session.state,
            },
        }


class PipelineRunner:
    _POTENTIALLY_SIDE_EFFECTING_OPS = set(SIDE_EFFECTING_NODE_OPS)

    def __init__(
        self,
        harness,
        *,
        on_output: Optional[Callable[[str, dict], None]] = None,
        get_input: Optional[Callable[[], Optional[str]]] = None,
        get_approval: Optional[Callable] = None,
        is_running: Optional[Callable[[], bool]] = None,
        initial_data: Optional[dict[str, Any]] = None,
        start: Optional[str] = None,
        stop_at: Optional[Iterable[str]] = None,
        resume_from: Optional[str] = None,
        deadline_monotonic: Optional[float] = None,
        secret_names: Optional[Iterable[str]] = None,
        permission_policy: Optional[RuntimePolicy] = None,
        emit_done: bool = True,
        inject_workspace_preview: bool = True,
        before_node: Optional[Callable[[RunContext, str, dict], Optional[dict[str, Any]]]] = None,
        on_node_error: Optional[Callable[[RunContext, str, dict, BaseException], Optional[dict[str, Any]]]] = None,
        after_node: Optional[Callable[[RunContext, str, dict], None]] = None,
        auto_checkpoint: Optional[bool] = None,
        allow_revision_conflicts: bool = False,
        allow_inflight_resume: bool = False,
    ):
        graph = harness.config["pipeline"]
        assert_valid_pipeline(graph)
        data = copy.deepcopy(graph.get("context", {}))
        if initial_data is not None:
            data.update(copy.deepcopy(initial_data))
        from harness import get_current_run_context
        parent_context = get_current_run_context()
        if parent_context is not None and parent_context.deadline_monotonic is not None:
            deadline_monotonic = (
                parent_context.deadline_monotonic
                if deadline_monotonic is None
                else min(deadline_monotonic, parent_context.deadline_monotonic)
            )
        workspace = Path(harness.workspace or harness.dir).resolve()
        if permission_policy is None:
            permission_policy = (
                parent_context.permission_policy
                if parent_context is not None and parent_context.permission_policy is not None
                else RuntimePolicy.from_config(
                    workspace,
                    str(graph.get("mode", "agent")),
                    graph.get("permissions"),
                )
            )
        secret_view = (
            parent_context.secret_view
            if parent_context is not None and secret_names is None
            else SecretView(secret_names if secret_names is not None else graph.get("secret_names", ()))
        )
        self.ctx = RunContext(
            harness=harness,
            graph=graph,
            on_output=on_output or (lambda _event, _data: None),
            get_input=get_input or (lambda: None),
            get_approval=get_approval,
            is_running=is_running or (lambda: True),
            data=data,
            stop_at=set(stop_at or []),
            parent=parent_context,
            parent_run_id=getattr(parent_context, "run_id", None),
            deadline_monotonic=deadline_monotonic,
            secret_view=secret_view,
            permission_policy=permission_policy,
        )
        self.start = start or graph["start"]
        self._resume_payload = None
        self._provider_metadata_seen: set[tuple[int, int]] = set()
        self._child_harness_lock = threading.Lock()
        self._revision_cache: dict[str, tuple[int, int, str]] = {}
        self.auto_checkpoint = bool(graph.get("auto_checkpoint", False)) if auto_checkpoint is None else bool(auto_checkpoint)
        self.allow_revision_conflicts = bool(allow_revision_conflicts)
        self.allow_inflight_resume = bool(allow_inflight_resume)
        self.after_node = after_node
        if resume_from:
            self._resume_from_checkpoint(resume_from)
        self.ctx.data.setdefault("_run_id", self.ctx.run_id)
        self._configure_event_log()
        self.emit_done = emit_done
        self.inject_workspace_preview = inject_workspace_preview
        # Optional debugger gate.  It is deliberately outside node execution
        # policy/retry handling: pausing never counts as an attempt and cannot
        # duplicate a model or tool call.
        self.before_node = before_node
        self.on_node_error = on_node_error

    def _configure_event_log(self) -> None:
        config = self.ctx.graph.get("event_log")
        if not config:
            return
        if isinstance(config, dict):
            requested = config.get("path", ".egoagent/events/{run_id}.jsonl")
        elif isinstance(config, str):
            requested = config
        else:
            requested = ".egoagent/events/{run_id}.jsonl"
        requested = str(requested).replace("{run_id}", self.ctx.run_id)
        workspace = Path(self.ctx.harness.workspace or self.ctx.harness.dir).resolve()
        candidate = Path(requested)
        path = candidate.resolve() if candidate.is_absolute() else (workspace / candidate).resolve()
        if path != workspace and workspace not in path.parents:
            raise PipelineError(f"event log path escapes workspace: {requested}")
        if path.suffix.lower() != ".jsonl":
            raise PipelineError("event log path must end with .jsonl")
        self.ctx.event_log_path = path
        self.ctx.data["_event_log_path"] = path.relative_to(workspace).as_posix()

    _REVISION_IGNORES = {
        ".git", ".egoagent", ".runtime", ".runtime-logs", ".pytest_cache",
        "__pycache__", "node_modules", "dist", "build", ".next", ".venv", "venv",
    }

    def _tree_revision(self, root: Path, *, harness_files_only: bool = False) -> dict[str, Any]:
        from workspace_revisions import tree_revision

        root = Path(root).resolve()
        candidates = None
        if harness_files_only and root.is_dir():
            candidates = [root / "config.json", root / "protocol.py"]
            candidates = [path for path in candidates if path.is_file()]
            hooks = root / "hooks"
            if hooks.is_dir():
                candidates.extend(path for path in hooks.rglob("*") if path.is_file())
        try:
            return tree_revision(root, ignores=self._REVISION_IGNORES,
                                 cache=self._revision_cache, candidates=candidates,
                                 cancelled=self.ctx.cancelled)
        except InterruptedError as error:
            raise PipelineCancelled(str(error)) from error

    def _revision_snapshot(self) -> dict[str, Any]:
        harness_config = json.dumps(self.ctx.harness.config, ensure_ascii=False, sort_keys=True, default=str)
        harness_tree = self._tree_revision(Path(self.ctx.harness.dir), harness_files_only=True)
        harness_tree["config_digest"] = hashlib.sha256(harness_config.encode("utf-8")).hexdigest()
        harness_tree["digest"] = hashlib.sha256(
            f"{harness_tree['digest']}:{harness_tree['config_digest']}".encode("ascii")
        ).hexdigest()
        identities: dict[str, Any] = {}
        for slot, agent in sorted(self.ctx.harness.agents.items()):
            identity = getattr(agent, "identity", None)
            identity_path = getattr(identity, "identity_path", None)
            if identity_path:
                identities[str(slot)] = self._tree_revision(Path(identity_path))
        return {
            "workspace": self._tree_revision(self.ctx.workspace),
            "harness": harness_tree,
            "identities": identities,
        }

    @staticmethod
    def _changed_revision_files(saved: dict[str, Any], current: dict[str, Any]) -> list[str]:
        before = saved.get("files", {}) if isinstance(saved, dict) else {}
        after = current.get("files", {}) if isinstance(current, dict) else {}
        return [
            name for name in sorted(set(before) | set(after))
            if before.get(name) != after.get(name)
        ]

    def _validate_checkpoint_revisions(self, payload: dict[str, Any]) -> None:
        saved = payload.get("revisions")
        if not isinstance(saved, dict):
            return
        current = self._revision_snapshot()
        conflicts: list[dict[str, Any]] = []
        for resource in ("workspace", "harness"):
            before = saved.get(resource, {})
            after = current.get(resource, {})
            if before.get("complete") is False or after.get("complete") is False or before.get("digest") != after.get("digest"):
                conflicts.append({
                    "resource": resource,
                    "saved": before.get("digest"),
                    "current": after.get("digest"),
                    "files": self._changed_revision_files(before, after)[:100],
                })
        before_identities = saved.get("identities", {})
        after_identities = current.get("identities", {})
        for slot in sorted(set(before_identities) | set(after_identities)):
            before = before_identities.get(slot, {})
            after = after_identities.get(slot, {})
            if before.get("complete") is False or after.get("complete") is False or before.get("digest") != after.get("digest"):
                conflicts.append({
                    "resource": f"identity:{slot}",
                    "saved": before.get("digest"),
                    "current": after.get("digest"),
                    "files": self._changed_revision_files(before, after)[:100],
                })
        if conflicts and not self.allow_revision_conflicts:
            raise PipelineRevisionConflict(conflicts)
        if conflicts:
            self.ctx.data["_revision_conflicts_accepted"] = conflicts

    def _restore_checkpoint_payload(self, payload: dict[str, Any], path: Path) -> None:
        phase = str(payload.get("phase", "completed"))
        if phase == "in_flight" and not self.allow_inflight_resume:
            raise PipelineInDoubt(str(payload.get("node") or payload.get("next_node") or ""), str(payload.get("operation", "")))
        self._validate_checkpoint_revisions(payload)
        accepted_conflicts = self.ctx.data.pop("_revision_conflicts_accepted", None)
        self.ctx.run_id = str(payload.get("run_id") or self.ctx.run_id)
        self.ctx.data.clear()
        self.ctx.data.update(copy.deepcopy(payload.get("data", {})))
        if accepted_conflicts:
            self.ctx.data["_revision_conflicts_accepted"] = accepted_conflicts
        self.ctx.node_outputs.clear()
        self.ctx.node_outputs.update(copy.deepcopy(payload.get("node_outputs", {})))
        self.ctx.harness.session.state = copy.deepcopy(payload.get("session_state", {}))
        self.ctx.harness.session.apply_context_result({
            "messages": copy.deepcopy(payload.get("messages", [])),
            "full_messages": copy.deepcopy(payload.get("full_messages", [])),
            "ledger": [{
                "action": "checkpoint_restore",
                "path": self._workspace_relative(path),
                "checkpoint_run_id": payload.get("run_id"),
                "phase": phase,
            }],
            "stats": {"restored_messages": len(payload.get("messages", []))},
        })
        saved_stats = payload.get("stats", {})
        for field_name in (
            "node_steps", "model_calls", "tool_calls", "process_calls", "retries",
            "input_tokens_estimated", "output_tokens_estimated", "cost_estimated",
            "provider_requests", "provider_retries", "input_tokens_actual",
            "output_tokens_actual", "cached_input_tokens_actual", "cost_actual",
            "provider_request_ids",
        ):
            if field_name in saved_stats:
                setattr(self.ctx.stats, field_name, saved_stats[field_name])
        self.ctx.last_output = copy.deepcopy(payload.get("last_output", self.ctx.last_output))
        self.ctx.result = copy.deepcopy(payload.get("result", self.ctx.result))
        self.ctx.text = self.ctx.data.get("text")
        self.ctx.tool_calls = self.ctx.data.get("tool_calls")
        self.ctx.approved_tool_call_ids = set(str(value) for value in payload.get("approved_tool_call_ids", []))
        self.ctx.pending_approvals = copy.deepcopy(payload.get("pending_approvals", {}))
        self.ctx.artifacts = set(str(value) for value in payload.get("artifacts", []))
        self.ctx.child_run_ids = set(str(value) for value in payload.get("child_run_ids", []))
        self.ctx.child_run_tree = copy.deepcopy(payload.get("child_run_tree", {}))
        self.ctx.completed_steps = copy.deepcopy(payload.get("completed_steps", []))
        self.ctx.change_transaction_id = str(payload.get("change_transaction_id") or f"run-{self.ctx.run_id}")
        if "next_node" in payload:
            self.start = payload.get("next_node")
        else:
            self.start = payload.get("node") or self.start
        self.ctx.data["_resumed_from"] = self._workspace_relative(path)
        if phase == "in_flight":
            self.ctx.data["_resumed_in_flight"] = {
                "node": payload.get("node"),
                "operation": payload.get("operation"),
            }

    def _resume_from_checkpoint(self, requested: str) -> None:
        path = self._checkpoint_path(requested)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise PipelineError(f"cannot load checkpoint {path}: {error}") from error
        self._restore_checkpoint_payload(payload, path)
        self._resume_payload = payload

    def run(self) -> RunContext:
        from harness import runtime_scope
        from harness_editor.change_tracker import transaction_scope

        if (
            self.inject_workspace_preview
            and self.ctx.graph.get("workspace_preview")
            and self.ctx.harness.workspace
            and not getattr(self.ctx.harness, "_workspace_preview_injected", False)
        ):
            _inject_workspace_preview(self.ctx.harness)
            self.ctx.harness._workspace_preview_injected = True

        registered_with_parent = False
        try:
            if self.ctx.parent is not None:
                self.ctx.parent.register_child(self.ctx)
                registered_with_parent = True
            with runtime_scope(harness=self.ctx.harness, run_context=self.ctx):
                with transaction_scope(self.ctx.change_transaction_id):
                    return self._run_bound()
        finally:
            if registered_with_parent and self.ctx.parent is not None:
                self.ctx.parent.release_child(self.ctx)

    def _run_bound(self) -> RunContext:
        current = self.start
        status = "completed"
        try:
            self.ctx.emit(
                "run_started",
                {
                    "harness": getattr(self.ctx.harness, "name", None),
                    "start": current,
                    "change_transaction_id": self.ctx.change_transaction_id,
                    "slots": {
                        str(slot): Path(getattr(getattr(agent, "identity", None), "identity_path", "")).name
                        for slot, agent in getattr(self.ctx.harness, "agents", {}).items()
                    },
                },
            )
            if self._resume_payload is not None:
                self.ctx.emit(
                    "resumed",
                    {"checkpoint": self.ctx.data.get("_resumed_from"), "next_node": current},
                )
            while current is not None:
                if current in self.ctx.stop_at:
                    self.ctx.result = self.ctx.last_output
                    break
                self.ctx.current_node = current
                try:
                    self._check_run_limits()
                except PipelineBudgetExceeded as error:
                    finalizer = self._begin_limit_finalization(error)
                    if finalizer is None:
                        raise
                    status = "budget_exceeded"
                    current = finalizer
                    continue
                if self.ctx.cancelled():
                    raise PipelineCancelled("pipeline execution was cancelled")

                node = self.ctx.graph["nodes"][current]
                op = canonical_op(node["op"])
                self._validate_limit_finalizer_node(op, node)
                self.ctx.stats.node_steps += 1
                resolved_inputs = resolve_reference(node.get("inputs", {}), self.ctx)
                self.ctx.emit(
                    "node_input",
                    {
                        "agent": node.get("agent", ""),
                        "op": op,
                        "input": _debug_value(resolved_inputs),
                        "last_output": _debug_value(self.ctx.last_output),
                    },
                )
                self.ctx.emit("node_enter", {"agent": node.get("agent", ""), "op": op})
                debug_directive: dict[str, Any] = {}
                if self.before_node is not None:
                    returned_directive = self.before_node(self.ctx, current, node)
                    if isinstance(returned_directive, dict):
                        debug_directive = returned_directive
                    if self.ctx.cancelled():
                        raise PipelineCancelled("pipeline execution was cancelled")

                if debug_directive.get("action") == "override_inputs":
                    replacement = debug_directive.get("inputs")
                    if not isinstance(replacement, dict):
                        raise PipelineError("debug input override must be an object")
                    node = copy.deepcopy(node)
                    node["inputs"] = copy.deepcopy(replacement)
                    self.ctx.emit("node_input_override", {"op": op, "input": _debug_value(replacement)})

                if debug_directive.get("action") == "skip":
                    skipped_output = debug_directive.get("output", {})
                    if not isinstance(skipped_output, dict):
                        raise PipelineError("debug skip output must be an object")
                    outcome = NodeOutcome(output=copy.deepcopy(skipped_output), tags=["debug_skipped"])
                    self.ctx.emit("node_skipped", {"op": op, "output": _debug_value(skipped_output)})
                else:
                    if self.auto_checkpoint and op in self._POTENTIALLY_SIDE_EFFECTING_OPS:
                        self._save_checkpoint(
                            f"inflight-{current}",
                            next_node=current,
                            phase="in_flight",
                            operation=op,
                        )

                    try:
                        outcome = self._execute_with_policy(current, node, op)
                    except PipelineBudgetExceeded as error:
                        finalizer = self._begin_limit_finalization(error)
                        if finalizer is None:
                            raise
                        status = "budget_exceeded"
                        current = finalizer
                        continue
                    debug_retry_count = 0
                    while outcome.error is not None and self.on_node_error is not None:
                        retry_directive = self.on_node_error(self.ctx, current, node, outcome.error)
                        if not isinstance(retry_directive, dict) or retry_directive.get("action") != "retry":
                            break
                        debug_retry_count += 1
                        if debug_retry_count > 10:
                            raise PipelineError("debug retry limit exceeded")
                        retry_inputs = retry_directive.get("inputs")
                        if not isinstance(retry_inputs, dict):
                            raise PipelineError("debug retry inputs must be an object")
                        node = copy.deepcopy(node)
                        node["inputs"] = copy.deepcopy(retry_inputs)
                        self.ctx.stats.retries += 1
                        self.ctx.emit("debug_retry", {
                            "op": op,
                            "attempt": debug_retry_count,
                            "input": _debug_value(retry_inputs),
                            "previous_error": str(outcome.error),
                        })
                        outcome = self._execute_with_policy(current, node, op)
                self.ctx.publish(current, node, outcome.output)
                self.ctx.emit(
                    "node_output",
                    {
                        "op": op,
                        "status": "error" if outcome.error else "ok",
                        "output": _debug_value(outcome.output),
                    },
                )
                self.ctx.emit(
                    "node_exit",
                    {
                        "op": op,
                        "status": "error" if outcome.error else "ok",
                        "output": _preview_value(outcome.output),
                        "stats": self.ctx.stats.as_dict(),
                    },
                )

                if outcome.error:
                    self.ctx.data["_error"] = {
                        "node": current,
                        "type": type(outcome.error).__name__,
                        "message": str(outcome.error),
                    }
                    next_node = outcome.next_node or _follow_edge(
                        node,
                        *outcome.tags,
                        "error",
                        context=self.ctx.data,
                        variables=self.ctx.variables(),
                    )
                    if next_node is None:
                        raise outcome.error
                    self.ctx.completed_steps.append({
                        "step": self.ctx.stats.node_steps,
                        "node": current,
                        "operation": op,
                        "status": "error_routed",
                        "next_node": next_node,
                    })
                    if self.auto_checkpoint:
                        self._save_checkpoint(f"auto-{current}", next_node=next_node, operation=op)
                    if self.after_node is not None:
                        self.after_node(self.ctx, current, node)
                    current = next_node
                    continue

                if outcome.stop:
                    self.ctx.result = outcome.output.get("value", outcome.output)
                    self.ctx.completed_steps.append({
                        "step": self.ctx.stats.node_steps,
                        "node": current,
                        "operation": op,
                        "status": "completed",
                        "next_node": None,
                    })
                    if node.get("checkpoint") or self.auto_checkpoint:
                        self._save_checkpoint(
                            node.get("checkpoint_label") or (f"auto-{current}" if self.auto_checkpoint else current),
                            next_node=None,
                            operation=op,
                        )
                    if self.after_node is not None:
                        self.after_node(self.ctx, current, node)
                    break

                tags = list(outcome.tags)
                if self.ctx.tool_calls:
                    tags.extend(["has_tool_calls"])
                else:
                    tags.extend(["no_tool_calls"])
                if self.ctx.text:
                    tags.extend(["has_text"])
                next_node = outcome.next_node or _follow_edge(
                    node,
                    *tags,
                    "default",
                    context=self.ctx.data,
                    variables=self.ctx.variables(),
                )
                self.ctx.completed_steps.append({
                    "step": self.ctx.stats.node_steps,
                    "node": current,
                    "operation": op,
                    "status": "completed",
                    "next_node": next_node,
                })
                if node.get("checkpoint") or self.auto_checkpoint:
                    self._save_checkpoint(
                        node.get("checkpoint_label") or (f"auto-{current}" if self.auto_checkpoint else current),
                        next_node=next_node,
                        operation=op,
                    )
                if self.after_node is not None:
                    self.after_node(self.ctx, current, node)
                current = next_node
            if self.ctx.result is None:
                self.ctx.result = self.ctx.last_output
        except PipelineCancelled as error:
            status = "cancelled"
            self.ctx.data["_error"] = {"type": type(error).__name__, "message": str(error)}
            self.ctx.emit("cancelled", {"message": str(error)})
        except PipelineBudgetExceeded as error:
            status = "budget_exceeded"
            termination = {
                "node": self.ctx.current_node,
                "type": type(error).__name__,
                "message": str(error),
                "stats": self.ctx.stats.as_dict(),
            }
            self.ctx.data["_error"] = termination
            self.ctx.data.setdefault("_termination", termination)
            if not self.ctx.data.get("_run_limit_emitted"):
                self.ctx.emit("run_limit_exceeded", termination)
                self.ctx.data["_run_limit_emitted"] = True
            raise
        except BaseException as error:
            status = "error"
            from run_failures import classify_run_failure

            failure = classify_run_failure(str(error), type(error).__name__)
            self.ctx.data["_error"] = {
                "node": self.ctx.current_node,
                "type": type(error).__name__,
                "message": str(error),
            }
            self.ctx.emit("error", {"message": str(error), "type": type(error).__name__, "failure": failure})
            raise
        finally:
            if (
                not self.ctx.graph.get("preserve_runtime_resources", False)
                and getattr(self.ctx.harness, "parent", None) is None
            ):
                cleaned = []
                for agent in self.ctx.harness.agents.values():
                    close_resources = getattr(agent, "close_runtime_resources", None)
                    if callable(close_resources):
                        cleaned.extend(close_resources())
                if cleaned:
                    self.ctx.emit("runtime_resources_closed", {"resources": cleaned})
            if self.emit_done:
                self.ctx.emit("done", {"status": status, "result": _preview_value(self.ctx.result), "stats": self.ctx.stats.as_dict()})
            self.ctx.observe("observation_finished", {"status": status, "stats": self.ctx.stats.as_dict()})
            if self.ctx.parent is None:
                recorder = getattr(self.ctx.session, "trajectory", None)
                if recorder is not None:
                    recorder.append(
                        "trace.completed",
                        {
                            "status": status,
                            "result": self.ctx.secret_view.redact_value(_preview_value(self.ctx.result)),
                            "stats": self.ctx.stats.as_dict(),
                            "trajectory_error": recorder.last_error,
                            "mirror_error": recorder.mirror_error,
                        },
                        session_id=getattr(self.ctx.session, "session_id", None),
                        run_id=self.ctx.run_id,
                        harness=getattr(self.ctx.harness, "name", None),
                    )
        return self.ctx

    def _check_run_limits(self) -> None:
        graph = self.ctx.graph
        if self.ctx.data.get("_handling_run_limit"):
            started = int(self.ctx.data.get("_limit_finalizer_started_at_step", self.ctx.stats.node_steps))
            max_steps = max(1, int(graph.get("limit_finalizer_max_steps", 20)))
            if self.ctx.stats.node_steps - started >= max_steps:
                raise PipelineBudgetExceeded(f"run-limit finalizer exceeded {max_steps} node steps")
            return
        budget = graph.get("budget", {})
        max_node_steps = int(graph.get("max_node_steps", budget.get("max_node_steps", max(int(graph.get("max_steps", 100)) * 10, 1000))))
        if self.ctx.stats.node_steps >= max_node_steps:
            raise PipelineBudgetExceeded(f"reached max node steps ({max_node_steps})")
        timeout = graph.get("timeout_seconds", budget.get("max_elapsed_seconds"))
        if timeout and time.monotonic() - self.ctx.stats.started_at > float(timeout):
            raise PipelineBudgetExceeded(f"reached pipeline timeout ({timeout}s)")
        max_tools = budget.get("max_tool_calls")
        if max_tools is not None and self.ctx.stats.tool_calls > int(max_tools):
            raise PipelineBudgetExceeded(f"reached max tool calls ({max_tools})")
        max_processes = budget.get("max_process_calls")
        if max_processes is not None and self.ctx.stats.process_calls > int(max_processes):
            raise PipelineBudgetExceeded(f"reached process call budget ({max_processes})")
        max_tokens = budget.get("max_tokens")
        estimated = self.ctx.stats.input_tokens_estimated + self.ctx.stats.output_tokens_estimated
        actual = self.ctx.stats.input_tokens_actual + self.ctx.stats.output_tokens_actual
        if max_tokens is not None and max(estimated, actual) > int(max_tokens):
            basis = "provider-reported" if actual > estimated else "estimated"
            raise PipelineBudgetExceeded(f"reached {basis} token budget ({max_tokens})")
        max_cost = budget.get("max_cost")
        if max_cost is not None and max(self.ctx.stats.cost_estimated, self.ctx.stats.cost_actual) > float(max_cost):
            basis = "provider-reported" if self.ctx.stats.cost_actual > self.ctx.stats.cost_estimated else "estimated"
            raise PipelineBudgetExceeded(f"reached {basis} cost budget ({max_cost})")

    def _begin_limit_finalization(self, error: PipelineBudgetExceeded) -> Optional[str]:
        if self.ctx.data.get("_handling_run_limit"):
            return None
        termination = {
            "type": type(error).__name__,
            "message": str(error),
            "node": self.ctx.current_node,
            "stats": self.ctx.stats.as_dict(),
        }
        from run_failures import classify_run_failure

        termination["failure"] = classify_run_failure(str(error), type(error).__name__)
        target = self.ctx.graph.get("budget_exceeded_to") or self.ctx.graph.get("limit_exceeded_to")
        self.ctx.data["_termination"] = termination
        if not self.ctx.data.get("_run_limit_emitted"):
            self.ctx.emit("run_limit_exceeded", {**termination, "finalizer": target})
            self.ctx.data["_run_limit_emitted"] = True
        if not target:
            return None
        if target not in self.ctx.graph.get("nodes", {}):
            raise PipelineError(f"run-limit finalizer points to missing node: {target!r}") from error
        self.ctx.data["_handling_run_limit"] = True
        self.ctx.data["_limit_finalizer_started_at_step"] = self.ctx.stats.node_steps
        return str(target)

    def _validate_limit_finalizer_node(self, op: str, node: dict) -> None:
        if not self.ctx.data.get("_handling_run_limit"):
            return
        allowed = {"条件", "数据", "工作区", "人工审批", "检查点", "输出", "结束"}
        if op not in allowed:
            raise PipelineBudgetExceeded(f"run-limit finalizer cannot execute {op}")
        if op == "工作区" and node.get("action", "list") not in {
            "changes", "review_transaction", "rollback_transaction", "snapshot", "list",
            "read_text", "read_json", "read_binary",
        }:
            raise PipelineBudgetExceeded(
                f"run-limit finalizer cannot execute Workspace action {node.get('action')!r}"
            )

    def _execute_with_policy(self, node_id: str, node: dict, op: str) -> NodeOutcome:
        retry = node.get("retry", {})
        if isinstance(retry, int):
            retry = {"max_attempts": retry + 1}
        max_attempts = max(1, int(retry.get("max_attempts", 1)))
        delay = max(0.0, float(retry.get("delay_seconds", 0)))
        backoff = max(1.0, float(retry.get("backoff", 1)))
        timeout = node.get("timeout_seconds")
        last_error: Optional[BaseException] = None

        for attempt in range(1, max_attempts + 1):
            message_len = len(self.ctx.harness.session.messages)
            full_len = len(self.ctx.harness.session.full_messages)
            try:
                call = lambda: self._execute_node(node_id, node, op)
                # Process nodes enforce timeout by terminating the child. An
                # outer thread timeout would leave that child running.
                outcome = call() if op == "进程" else (_call_with_timeout(call, float(timeout)) if timeout else call())
                self._validate_output(node, outcome)
                return outcome
            except (PipelineCancelled, PipelineBudgetExceeded):
                raise
            except BaseException as error:
                last_error = error
                del self.ctx.harness.session.messages[message_len:]
                del self.ctx.harness.session.full_messages[full_len:]
                if attempt < max_attempts:
                    self.ctx.stats.retries += 1
                    self.ctx.emit(
                        "node_retry",
                        {"attempt": attempt, "max_attempts": max_attempts, "message": str(error)},
                    )
                    self._cancel_aware_wait(delay * (backoff ** (attempt - 1)))
                    continue
                tags = ["retry_exhausted"]
                if isinstance(error, NodeTimeout):
                    tags.insert(0, "timeout")
                self.ctx.emit(
                    "node_error",
                    {"attempt": attempt, "max_attempts": max_attempts, "message": str(error), "type": type(error).__name__},
                )
                return NodeOutcome(
                    output={"error": {"type": type(error).__name__, "message": str(error)}},
                    tags=tags,
                    error=error,
                    next_node=node.get("error_to"),
                )
        raise last_error or PipelineError("node execution failed")

    def _cancel_aware_wait(self, seconds: float) -> None:
        deadline = time.monotonic() + min(seconds, 300.0)
        while time.monotonic() < deadline:
            if self.ctx.cancelled():
                raise PipelineCancelled("pipeline execution was cancelled")
            time.sleep(min(0.1, deadline - time.monotonic()))

    def _validate_output(self, node: dict, outcome: NodeOutcome) -> None:
        schema = node.get("output_schema")
        if not schema:
            return
        candidate = outcome.output.get("structured")
        if candidate is None:
            candidate = outcome.output.get("value", outcome.output.get("text", outcome.output))
        if isinstance(candidate, str):
            try:
                candidate = json.loads(_strip_code_fence(candidate))
            except (TypeError, ValueError) as error:
                raise OutputValidationError(f"output is not valid JSON: {error}") from error
        errors = validate_json_schema(candidate, schema)
        if errors:
            raise OutputValidationError("; ".join(errors))
        outcome.output["structured"] = candidate

    def _execute_node(self, node_id: str, node: dict, op: str) -> NodeOutcome:
        inputs = resolve_reference(node.get("inputs", {}), self.ctx)
        try:
            return execute_registered_node(self, node_id, node, inputs)
        except KeyError as error:
            raise PipelineError(str(error)) from error

    def _input_node(self, node: dict, inputs: dict) -> NodeOutcome:
        from harness import execute_user_tool_call, parse_user_tool_call

        session = self.ctx.harness.session
        poll_mode = str(node.get("mode", "")).lower() == "poll" or bool(node.get("poll", False))
        if poll_mode:
            if getattr(self.ctx.harness, "_non_interactive", False):
                return NodeOutcome({"waiting": False, "polled": True}, ["no_input"])
            try:
                user_input = self.ctx.get_input(0)
            except TypeError:
                # Legacy blocking callbacks cannot be safely polled.
                return NodeOutcome({"waiting": False, "polled": True}, ["no_input"])
            if user_input is None or not str(user_input).strip():
                return NodeOutcome({"waiting": False, "polled": True}, ["no_input"])
            user_input = str(user_input)
            if user_input.strip().lower() in {"exit", "quit", "q"}:
                return NodeOutcome({"value": user_input}, ["exit"], stop=True)
            agent = _get_main_agent(self.ctx.harness)
            parsed = parse_user_tool_call(user_input)
            if parsed and agent:
                tool_name, arguments = parsed
                result = execute_user_tool_call(self.ctx.harness, agent, tool_name, arguments)
                self.ctx.emit("tool", {"name": f"[user] {tool_name}", "result": str(result)})
                return NodeOutcome({"value": result, "polled": True}, ["input"])
            msg = {"role": "user", "content": user_input, "steering": True}
            session.record(msg)
            session.record_full(msg.copy())
            self._reset_turn_guards()
            self.ctx.last_input = user_input
            self.ctx.emit("input_steered", {"text": _debug_value(user_input, limit=4000)})
            return NodeOutcome({"value": user_input, "text": user_input, "polled": True}, ["input"])
        # The first Input node normally consumes the latest user message.  A
        # later Input node can set reuse_last=false to explicitly request a new
        # answer (clarification, credentials, approval details, and so on).
        # Workspace previews are deliberately represented as user-compatible
        # context for providers that do not support arbitrary system messages.
        # They are not, however, a user task. Skip only these synthetic trailing
        # messages so a fresh interactive run waits for the real prompt while a
        # one-shot run can still reuse the user task recorded immediately before
        # the preview.
        message_index = len(session.messages) - 1
        while message_index >= 0:
            candidate = session.messages[message_index]
            content = str(candidate.get("content", ""))
            if candidate.get("role") == "user" and content.startswith("[System] Working directory:"):
                message_index -= 1
                continue
            break
        reusable_message = session.messages[message_index] if message_index >= 0 else None
        if node.get("reuse_last", True) and reusable_message and reusable_message.get("role") == "user":
            value = reusable_message.get("content", "")
            self._reset_turn_guards()
            self.ctx.last_input = value
            return NodeOutcome({"value": value, "text": value}, ["input"])
        if self.ctx.harness.parent or getattr(self.ctx.harness, "_non_interactive", False):
            return NodeOutcome({"waiting": True}, ["waiting"], stop=True)

        prompt = resolve_reference(node.get("prompt_text", ">>> "), self.ctx)
        self.ctx.emit("input_required", {"prompt": prompt})
        while not self.ctx.cancelled():
            user_input = self.ctx.get_input()
            if user_input is None:
                return NodeOutcome({"waiting": True}, ["waiting"], stop=True)
            if user_input.strip().lower() in {"exit", "quit", "q"}:
                return NodeOutcome({"value": user_input}, ["exit"], stop=True)
            if not user_input.strip():
                continue
            agent = _get_main_agent(self.ctx.harness)
            parsed = parse_user_tool_call(user_input)
            if parsed and agent:
                tool_name, arguments = parsed
                result = execute_user_tool_call(self.ctx.harness, agent, tool_name, arguments)
                self.ctx.emit("tool", {"name": f"[user] {tool_name}", "result": str(result)})
                continue
            msg = {"role": "user", "content": user_input}
            session.record(msg)
            session.record_full(msg.copy())
            self._reset_turn_guards()
            self.ctx.last_input = user_input
            return NodeOutcome({"value": user_input, "text": user_input}, ["input"])
        raise PipelineCancelled("pipeline execution was cancelled")

    def _reset_turn_guards(self) -> None:
        """Counters and execution evidence are scoped to one user request."""
        for key in (
            "_agent_tool_rounds", "_required_tool_retries", "_turn_executed_tools",
            "_auto_continuations", "_empty_responses",
        ):
            self.ctx.data.pop(key, None)

    def _record_synthetic_tool_response(
        self,
        call: dict,
        content: str,
        *,
        status: str,
        source: str,
    ) -> dict:
        """Close a model tool call that the runtime did not execute.

        OpenAI-compatible providers require every assistant ``tool_call`` to be
        followed by a tool response with the same ``tool_call_id``.  Runtime
        guards still need to satisfy that protocol when they reject, discard,
        or de-duplicate a call before asking the model to try again.
        """
        name = str(call.get("function", {}).get("name", ""))
        payload = {
            "tool": name,
            "tool_call_id": call.get("id"),
            "status": status,
            "content": str(content),
        }
        message = {
            "role": "user",
            "name": source,
            "content": f'<tool_response>{json.dumps(payload, ensure_ascii=False)}</tool_response>',
        }
        self.ctx.harness.session.record(message)
        self.ctx.harness.session.record_full(message.copy())
        return message

    def _agent_node(self, node_id: str, node: dict, inputs: dict) -> NodeOutcome:
        agent_name = node.get("agent") or inputs.get("agent")
        agent = self.ctx.harness.agents.get(agent_name) if agent_name else _get_main_agent(self.ctx.harness)
        if agent is None:
            raise PipelineError(f"Agent node {node_id!r} has no bound agent")
        using_session_messages = inputs.get("messages") is None
        messages = copy.deepcopy(inputs.get("messages") or self.ctx.harness.session.messages)
        pressure_source_length = len(messages)
        instructions = inputs.get("instructions")
        if instructions is None and "instructions" in node:
            instructions = resolve_reference(node.get("instructions"), self.ctx)
        if instructions is not None and str(instructions).strip():
            if isinstance(instructions, (dict, list)):
                instruction_text = json.dumps(instructions, ensure_ascii=False)
            else:
                instruction_text = str(instructions)
            messages.append(
                {
                    # DAG-authored instructions are execution policy, not a
                    # second user turn.  Keeping them in the system prefix
                    # preserves a conventional system -> conversation -> tool
                    # transcript and stops small models from treating the same
                    # repeated node instruction as a fresh user request after
                    # every tool result.
                    "role": "system",
                    "name": "dag_instruction",
                    "content": instruction_text,
                }
            )
        # A tool loop is a continuation of the assistant turn, not a new
        # answer.  Apply this hint only when the trailing tool-result batch is
        # paired with a tool call authored by *this* Agent.  Merely checking
        # for any recent tool result leaks one Agent's continuation policy into
        # the next reviewer/KP/worker in a multi-Agent DAG.
        continuation_source = (
            messages[:-1]
            if instructions is not None and str(instructions).strip()
            else messages
        )
        if _is_same_agent_tool_continuation(
            continuation_source,
            getattr(agent, "name", agent_name or ""),
            allow_unnamed_assistant=len(self.ctx.harness.agents) == 1,
        ):
            messages.append({
                "role": "system",
                "name": "runtime_tool_continuation",
                "content": (
                    "Continue the same assistant turn from the completed tool result. "
                    "Do not repeat a greeting, plan, progress sentence, or factual text "
                    "already emitted before the tool call. Emit only the next required "
                    "tool call or the new final answer."
                ),
            })
        has_tool_edge = any(edge.get("condition") == "has_tool_calls" for edge in node.get("edges", []))
        tools_mode = node.get("tools", "auto")
        expose_tools = tools_mode is True or tools_mode == "all" or (tools_mode == "auto" and has_tool_edge)
        max_tool_rounds = max(0, int(resolve_reference(node.get("max_tool_rounds", 0), self.ctx)))
        tool_round_path = f"_agent_tool_rounds.{node_id}"
        used_tool_rounds = int(get_path(self.ctx.data, tool_round_path, 0))
        tool_rounds_exhausted = bool(expose_tools and max_tool_rounds and used_tool_rounds >= max_tool_rounds)
        if tool_rounds_exhausted:
            expose_tools = False
            messages.append(
                {
                    "role": "user",
                    "name": "runtime_tool_round_limit",
                    "content": str(
                        resolve_reference(
                            node.get(
                                "tool_round_limit_prompt",
                                "The read/tool budget for this node is exhausted. Do not request more tools. "
                                "Use the observations already in the conversation and return the concrete final result now.",
                            ),
                            self.ctx,
                        )
                    ),
                }
            )
            self.ctx.emit(
                "tool_round_limit",
                {"node": node_id, "used": used_tool_rounds, "maximum": max_tool_rounds},
            )
        tools_desc = None
        visible_tools = [str(pattern) for pattern in node.get("visible_tools", []) if str(pattern)]
        hidden_tools = [str(pattern) for pattern in node.get("hidden_tools", []) if str(pattern)]
        if expose_tools:
            describe_tools = getattr(agent, "get_tools_desc", None)
            if not callable(describe_tools):
                raise PipelineError(
                    f"Agent node {node_id!r} requires get_tools_desc() to expose tools"
                )
            try:
                # Real Agents can filter before applying their global prompt
                # schema budget.  This keeps a Flow node's explicit allowlist
                # authoritative even for large composite Identities.
                described_tools = describe_tools(
                    include_tools=visible_tools or None,
                    exclude_tools=hidden_tools or None,
                )
            except TypeError:
                # Test doubles and third-party Agent adapters may still expose
                # the legacy no-argument method; retain compatibility and
                # enforce visibility below as before.
                described_tools = describe_tools()
            tools_desc = []
            hidden_names = []
            for description in described_tools:
                name = str(description.get("function", {}).get("name", ""))
                normalized = name.lower()
                included = not visible_tools or any(
                    fnmatch.fnmatchcase(normalized, pattern.lower()) for pattern in visible_tools
                )
                excluded = any(
                    fnmatch.fnmatchcase(normalized, pattern.lower()) for pattern in hidden_tools
                )
                if included and not excluded:
                    tools_desc.append(description)
                else:
                    hidden_names.append(name)
            if visible_tools or hidden_tools:
                self.ctx.emit(
                    "tool_visibility",
                    {
                        "agent": agent_name or getattr(agent, "name", "Agent"),
                        "visible": [item.get("function", {}).get("name", "") for item in tools_desc],
                        "hidden": hidden_names,
                    },
                )
        compacted_source = self._maybe_pressure_compact(
            node,
            agent,
            messages[:pressure_source_length],
            tools_desc if expose_tools else [],
            persist_session=using_session_messages,
        )
        messages = compacted_source + messages[pressure_source_length:]
        self._before_model_call()
        self.ctx.emit("label", {"agent": agent_name or getattr(agent, "name", "Agent")})

        self.ctx.emit(
            "model_request",
            {
                "agent": agent_name or getattr(agent, "name", "Agent"),
                "messages": _debug_value(messages, limit=50000),
                "tools": _debug_value(tools_desc if expose_tools else [], limit=30000),
            },
        )

        def on_token(token: str) -> None:
            if self.ctx.cancelled():
                raise PipelineCancelled("pipeline execution was cancelled")
            self.ctx.emit("token", {"agent": agent_name or getattr(agent, "name", "Agent"), "text": token})

        def on_reasoning(text: str) -> None:
            if self.ctx.cancelled():
                raise PipelineCancelled("pipeline execution was cancelled")
            self.ctx.emit("reasoning", {"agent": agent_name or getattr(agent, "name", "Agent"), "text": text})

        input_estimate = _estimate_messages_tokens(messages)
        step_kwargs = {
            "tools_desc": tools_desc if expose_tools else "",
            "on_token": on_token,
        }
        try:
            step_parameters = inspect.signature(agent.step).parameters
            accepts_step_kwargs = any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in step_parameters.values()
            )
        except (TypeError, ValueError):
            step_parameters = {}
            accepts_step_kwargs = False
        if node.get("max_tokens") is not None:
            if accepts_step_kwargs or "max_tokens" in step_parameters:
                step_kwargs["max_tokens"] = max(1, int(resolve_reference(node.get("max_tokens"), self.ctx)))
        if accepts_step_kwargs or "on_reasoning" in step_parameters:
            step_kwargs["on_reasoning"] = on_reasoning
        if node.get("temperature") is not None:
            if accepts_step_kwargs or "temperature" in step_parameters:
                step_kwargs["temperature"] = float(resolve_reference(node.get("temperature"), self.ctx))
        if node.get("compact_tool_preamble_chars") is not None:
            if accepts_step_kwargs or "compact_tool_preamble_chars" in step_parameters:
                step_kwargs["compact_tool_preamble_chars"] = max(
                    0,
                    int(resolve_reference(node.get("compact_tool_preamble_chars"), self.ctx)),
                )
        if expose_tools:
            text, tool_calls = agent.step(messages, **step_kwargs)
        else:
            text, tool_calls = agent.step(messages, **step_kwargs)
        provider_metadata = dict(getattr(getattr(agent, "llm", None), "last_response_metadata", {}) or {})
        finish_reason = provider_metadata.get("finish_reason")
        output_truncated = bool(
            provider_metadata.get("output_truncated")
            or finish_reason in {"length", "max_tokens", "max_output_tokens"}
        )
        self.ctx.emit(
            "model_response",
            {
                "agent": agent_name or getattr(agent, "name", "Agent"),
                "text": _debug_value(text, limit=50000),
                "tool_calls": _debug_value(tool_calls or [], limit=30000),
                "finish_reason": finish_reason,
                "output_truncated": output_truncated,
            },
        )
        if output_truncated:
            from run_failures import output_limit_notice

            self.ctx.emit(
                "model_output_truncated",
                {
                    "agent": agent_name or getattr(agent, "name", "Agent"),
                    "node": node_id,
                    "finish_reason": finish_reason,
                    "message": "模型达到输出长度上限；回复未完成，等待用户发送“继续”。",
                    "failure": output_limit_notice(finish_reason=finish_reason, node=node_id),
                },
            )
        self._record_model_usage(input_estimate, _estimate_tokens(text))
        self._record_provider_usage(agent)

        # Tool visibility is an execution boundary, not merely a hint for the
        # provider.  Some OpenAI-compatible models occasionally return calls
        # for tools that were present earlier in the conversation but are not
        # declared for the current node.  Passing those calls to the following
        # Tool node would both violate the DAG contract and let a narrowly
        # scoped component consume unrelated tools/budget.  Close rejected
        # calls synthetically so strict providers still see a valid
        # assistant(tool_calls) -> tool response sequence.
        rejected_tool_calls = []
        if tool_calls:
            declared_tool_names = {
                str(description.get("function", {}).get("name", "")).casefold()
                for description in (tools_desc or [])
                if str(description.get("function", {}).get("name", ""))
            } if expose_tools else set()
            allowed_tool_calls = []
            for call in tool_calls:
                called_name = str(call.get("function", {}).get("name", ""))
                if called_name.casefold() in declared_tool_names:
                    allowed_tool_calls.append(call)
                    continue
                rejected_tool_calls.append(call)
                self._record_synthetic_tool_response(
                    call,
                    (
                        f"Tool {called_name!r} is not declared for Agent node {node_id!r} "
                        "and was not executed. Use only a tool exposed by this node."
                    ),
                    status="blocked",
                    source="runtime_tool_visibility",
                )
                self.ctx.emit(
                    "undeclared_tool_call",
                    {
                        "node": node_id,
                        "tool": called_name,
                        "declared": sorted(declared_tool_names),
                        "status": "blocked",
                    },
                )
            tool_calls = allowed_tool_calls or None

        # A response that contains only undeclared calls is not a valid final
        # answer, even when the provider also emitted explanatory text.  Route
        # it back through the same Agent node so the synthetic tool responses
        # above can teach the model which boundary it crossed.  Previously the
        # text was tagged as ``has_text`` and could silently finish a DAG while
        # the requested action had been rejected.
        undeclared_retry_path = f"_undeclared_tool_retries.{node_id}"
        if rejected_tool_calls and not tool_calls:
            retry_count = int(get_path(self.ctx.data, undeclared_retry_path, 0)) + 1
            set_path(self.ctx.data, undeclared_retry_path, retry_count)
            maximum = max(0, int(node.get("max_undeclared_tool_retries", 2)))
            output = {
                "text": text,
                "tool_calls": None,
                "undeclared_tool_calls": [
                    str(call.get("function", {}).get("name", ""))
                    for call in rejected_tool_calls
                ],
                "count": retry_count,
            }
            self.ctx.emit(
                "undeclared_tool_retry",
                {
                    "node": node_id,
                    "count": retry_count,
                    "maximum": maximum,
                    "tools": output["undeclared_tool_calls"],
                },
            )
            if retry_count <= maximum:
                return NodeOutcome(
                    output,
                    ["undeclared_tool_calls", "retry"],
                    next_node=node.get("undeclared_tool_to", node_id),
                )
            return NodeOutcome(
                output,
                ["undeclared_tool_calls_exhausted"],
                error=PipelineError(
                    f"Agent requested only undeclared tools {output['undeclared_tool_calls']} "
                    f"{retry_count} times"
                ),
            )
        if not rejected_tool_calls:
            set_path(self.ctx.data, undeclared_retry_path, 0)

        empty_path = f"_empty_responses.{node_id}"
        if not tool_calls and not str(text or "").strip():
            empty_count = int(get_path(self.ctx.data, empty_path, 0)) + 1
            set_path(self.ctx.data, empty_path, empty_count)
            max_empty = max(0, int(node.get("max_empty_responses", 1)))
            prompt = resolve_reference(
                node.get(
                    "empty_response_prompt",
                    "Your previous response contained no user-visible content or tool call. Continue with a concrete action, ask for the missing information, or provide a factual final answer.",
                ),
                self.ctx,
            )
            correction = {"role": "user", "name": "runtime_empty_response", "content": str(prompt)}
            self.ctx.harness.session.record(correction)
            self.ctx.harness.session.record_full(correction.copy())
            self.ctx.emit("empty_response", {"node": node_id, "count": empty_count, "max_retries": max_empty})
            output = {"text": "", "tool_calls": None, "empty": True, "count": empty_count}
            if empty_count <= max_empty:
                return NodeOutcome(output, ["empty_response", "retry"], next_node=node.get("empty_response_to", node_id))
            return NodeOutcome(
                output,
                ["empty_response_exhausted"],
                error=PipelineError(f"Agent returned an empty response {empty_count} times"),
            )
        set_path(self.ctx.data, empty_path, 0)

        required_patterns = [
            str(pattern).lower()
            for pattern in node.get("required_tool_patterns", ["write_file", "patch_file", "multi_edit"])
            if str(pattern)
        ]
        require_tool = bool(node.get("require_tool_before_text", False))
        if node.get("require_tool_for_mutations", False):
            require_tool = require_tool or _looks_like_mutation_request(self.ctx.last_input)
        executed_tools = [str(name).lower() for name in self.ctx.data.get("_turn_executed_tools", [])]
        required_tool_seen = any(
            fnmatch.fnmatchcase(name, pattern)
            for name in executed_tools
            for pattern in required_patterns
        )
        if (
            require_tool
            and expose_tools
            and not tool_calls
            and str(text or "").strip()
            and not required_tool_seen
        ):
            retry_path = f"_required_tool_retries.{node_id}"
            retry_count = int(get_path(self.ctx.data, retry_path, 0)) + 1
            set_path(self.ctx.data, retry_path, retry_count)
            maximum = max(0, int(node.get("max_required_tool_retries", 2)))
            prompt = str(resolve_reference(node.get(
                "required_tool_prompt",
                "This request requires a real workspace change, but no successful editing tool has run in this user turn. "
                "Do not claim completion. Inspect the target if necessary, then call an editing tool and verify its result.",
            ), self.ctx))
            correction = {"role": "user", "name": "runtime_required_tool", "content": prompt}
            self.ctx.harness.session.record(correction)
            self.ctx.harness.session.record_full(correction.copy())
            self.ctx.emit("required_tool_missing", {
                "node": node_id,
                "count": retry_count,
                "maximum": maximum,
                "patterns": required_patterns,
            })
            output = {"text": text, "tool_calls": None, "required_tool_missing": True}
            if retry_count <= maximum:
                return NodeOutcome(output, ["required_tool_missing", "retry"], next_node=node.get("required_tool_to", node_id))
            return NodeOutcome(
                output,
                ["required_tool_exhausted"],
                error=PipelineError(
                    f"Agent claimed a mutation was complete without a successful tool matching {required_patterns}"
                ),
            )

        max_tool_calls = max(0, int(node.get("max_tool_calls_per_turn", 0)))
        if tool_calls and max_tool_calls and len(tool_calls) > max_tool_calls:
            prompt = resolve_reference(
                node.get(
                    "tool_call_count_error_prompt",
                    f"You returned {len(tool_calls)} tool calls. Return exactly one action for this step.",
                ),
                self.ctx,
            )
            for call in tool_calls:
                self._record_synthetic_tool_response(
                    call,
                    (
                        f"This batch contained {len(tool_calls)} tool calls, but this step allows "
                        f"at most {max_tool_calls}. No tool in the batch was executed; retry with "
                        f"at most {max_tool_calls} call."
                    ),
                    status="discarded",
                    source="runtime_tool_count_error",
                )
            correction = {"role": "user", "name": "runtime_tool_count_error", "content": str(prompt)}
            self.ctx.harness.session.record(correction)
            self.ctx.harness.session.record_full(correction.copy())
            self.ctx.emit(
                "tool_call_count_error",
                {"node": node_id, "count": len(tool_calls), "maximum": max_tool_calls},
            )
            return NodeOutcome(
                {"text": text, "tool_calls": None, "format_error": str(prompt)},
                ["tool_call_count_error", "format_error"],
                next_node=node.get("tool_call_count_error_to", node_id),
            )

        if tool_calls and expose_tools:
            set_path(self.ctx.data, tool_round_path, used_tool_rounds + 1)
            signature = json.dumps(
                [(tc.get("function", {}).get("name"), tc.get("function", {}).get("arguments")) for tc in tool_calls],
                ensure_ascii=False,
                sort_keys=True,
            )
            if node.get("reject_identical_tool_call", True) and signature == self.ctx.last_tool_signature:
                for call in tool_calls:
                    self._record_synthetic_tool_response(
                        call,
                        "Error: identical tool call repeated; choose a different action or answer directly.",
                        status="discarded",
                        source="runtime_repeated_tool_call",
                    )
                self.ctx.last_tool_signature = None
                return NodeOutcome({"text": text, "tool_calls": None, "repeated_tool_call": True}, ["retry"], next_node=node_id)
            self.ctx.last_tool_signature = signature
        else:
            self.ctx.last_tool_signature = None
            repetition_ngram_size = max(0, int(node.get("repetition_ngram_size", 0)))
            repetition_ratio_threshold = float(node.get("repetition_ratio_threshold", 1.0))
            repetition_min_tokens = max(1, int(node.get("repetition_min_tokens", 120)))
            repetition = _repeated_ngram_ratio(str(text or ""), repetition_ngram_size)
            if (
                repetition_ngram_size
                and repetition["tokens"] >= repetition_min_tokens
                and repetition["ratio"] >= repetition_ratio_threshold
            ):
                stuck_prompt = resolve_reference(
                    node.get(
                        "stuck_prompt",
                        "Your reasoning is repeating internally. Stop restating the current hypothesis, "
                        "name the contradicted assumption once, and take a different concrete action.",
                    ),
                    self.ctx,
                )
                message = {
                    "role": "user",
                    "name": "runtime_stuck_detector",
                    "content": str(stuck_prompt),
                    "_op": "stuck_guard",
                }
                self.ctx.harness.session.record(message)
                self.ctx.harness.session.record_full(message.copy())
                self.ctx.emit(
                    "agent_stuck",
                    {
                        "node": node_id,
                        "reason": "internal_ngram_repetition",
                        "ngram_size": repetition_ngram_size,
                        "repetition_ratio": repetition["ratio"],
                        "tokens": repetition["tokens"],
                    },
                )
                return NodeOutcome(
                    {"text": text, "tool_calls": None, "stuck": True, "repetition": repetition},
                    ["stuck"],
                    next_node=node.get("stuck_to", node_id),
                )
            duplicate_threshold = max(0, int(node.get("duplicate_threshold", 0)))
            if duplicate_threshold and text:
                assistant_messages = [
                    message for message in self.ctx.harness.session.messages
                    if message.get("role") == "assistant" and message.get("content") == text
                ]
                # Agent.step has already recorded the current response, so the
                # number of earlier duplicates is len(matches) - 1.
                if len(assistant_messages) - 1 >= duplicate_threshold:
                    stuck_prompt = resolve_reference(
                        node.get(
                            "stuck_prompt",
                            "You repeated the same response. Change strategy, take a different concrete action, or finish with a factual answer.",
                        ),
                        self.ctx,
                    )
                    message = {"role": "user", "content": str(stuck_prompt), "_op": "stuck_guard"}
                    self.ctx.harness.session.record(message)
                    self.ctx.harness.session.record_full(message.copy())
                    self.ctx.emit("agent_stuck", {"node": node_id, "duplicates": len(assistant_messages) - 1})
                    return NodeOutcome(
                        {"text": text, "tool_calls": None, "stuck": True},
                        ["stuck"],
                        next_node=node.get("stuck_to", node_id),
                    )
        if not tool_calls and str(text or "").strip() and "auto_continue_when" in node:
            variables = self.ctx.variables()
            variables.update(inputs)
            variables["text"] = text
            raw_condition = node.get("auto_continue_when")
            should_auto_continue = (
                bool(raw_condition)
                if isinstance(raw_condition, bool)
                else evaluate_expression(str(raw_condition), variables)
            )
            count_path = f"_auto_continuations.{node_id}"
            if should_auto_continue:
                count = int(get_path(self.ctx.data, count_path, 0)) + 1
                maximum = max(0, int(node.get("max_auto_continuations", 1)))
                if count <= maximum:
                    set_path(self.ctx.data, count_path, count)
                    prompt = str(resolve_reference(node.get("auto_continue_prompt", "continue"), self.ctx))
                    continuation = {
                        "role": "user",
                        "name": "runtime_auto_continue",
                        "content": prompt,
                    }
                    self.ctx.harness.session.record(continuation)
                    self.ctx.harness.session.record_full(continuation.copy())
                    self.ctx.emit(
                        "auto_continue",
                        {"node": node_id, "count": count, "maximum": maximum, "prompt": prompt},
                    )
                    return NodeOutcome(
                        {"text": text, "tool_calls": None, "auto_continued": True, "count": count},
                        ["auto_continue", "has_text"],
                        next_node=node.get("auto_continue_to", node_id),
                    )
            else:
                set_path(self.ctx.data, count_path, 0)
        tags = ["has_tool_calls" if tool_calls and expose_tools else "has_text"]
        if output_truncated:
            tags.insert(0, "output_truncated")
        return NodeOutcome(
            {
                "text": text,
                "tool_calls": tool_calls or None,
                "finish_reason": finish_reason,
                "output_truncated": output_truncated,
            },
            tags,
        )

    def _tool_review_node(self, node: dict, inputs: dict) -> NodeOutcome:
        calls = inputs.get("tool_calls", self.ctx.tool_calls)
        if not calls:
            return NodeOutcome({"tool_calls": None, "blocked": []}, ["no_tool_calls"])
        agent = self._node_agent(node, inputs)
        review_mode = node.get("review_mode", "agent")
        policies = node.get("policies", [])
        default_permission = str(node.get("default_permission", "allow")).lower()
        policy_match = str(node.get("policy_match", "last")).lower()
        if policy_match not in {"first", "last"}:
            raise PipelineError("Tool review policy_match must be 'first' or 'last'")
        allowed = []
        blocked = []

        if review_mode in {"policy", "both"}:
            for call in calls:
                name = call.get("function", {}).get("name", "")
                permission = default_permission
                # Later rules take precedence, matching Continue's layered
                # permissions and allowing a broad wildcard plus exceptions.
                for rule in policies:
                    if not isinstance(rule, dict):
                        continue
                    pattern = str(rule.get("tool", ""))
                    if pattern and fnmatch.fnmatchcase(name, pattern):
                        permission = str(rule.get("permission", permission)).lower()
                        if policy_match == "first":
                            break
                if permission in {"deny", "exclude", "blocked", "block"}:
                    blocked.append((call, f"Tool policy denied '{name}'."))
                    continue
                if permission == "ask":
                    question = f"Allow tool '{name}' with arguments {call.get('function', {}).get('arguments', '{}')}? [y/N]"
                    approval_id = f"{self.ctx.run_id}:{uuid.uuid4().hex}"
                    self.ctx.emit(
                        "approval_required",
                        {
                            "approval_id": approval_id,
                            "prompt": question,
                            "tool": name,
                            "arguments": call.get("function", {}).get("arguments", "{}"),
                            "default": "rejected",
                            "auto_approvable": True,
                        },
                    )
                    answer = self._approval_answer(str(node.get("ask_default", "rejected")), approval_id=approval_id)
                    if isinstance(answer, str) and answer.lstrip().startswith("{"):
                        try:
                            answer = json.loads(answer)
                        except ValueError:
                            pass
                    raw_answer = answer.get("decision", answer.get("answer", "rejected")) if isinstance(answer, dict) else answer
                    approved = str(raw_answer).strip().lower() in {
                        "y", "yes", "allow", "approve", "approved", "true", "通过", "同意"
                    }
                    self.ctx.emit("approval", {"approval_id": approval_id, "decision": "approved" if approved else "rejected", "tool": name, "answer": answer})
                    if not approved:
                        blocked.append((call, f"User did not approve tool '{name}'."))
                        continue
                allowed.append(call)
        else:
            allowed = list(calls)

        if review_mode in {"agent", "both"} and allowed:
            prompt = self.ctx.harness.prompts.get(node.get("prompt")) if node.get("prompt") else None
            self._before_model_call()
            agent_allowed, agent_blocked = agent.process_tool_calls(allowed, self.ctx.harness.session.messages, prompt)
            self._record_model_usage(_estimate_tokens(str(allowed)), _estimate_tokens(str(agent_blocked)))
            self._record_provider_usage(agent)
            allowed = agent_allowed
            blocked.extend(agent_blocked)
        for call, reason in blocked:
            name = call.get("function", {}).get("name", "")
            self._record_synthetic_tool_response(
                call,
                str(reason),
                status="blocked",
                source="runtime_tool_review",
            )
            self.ctx.emit("blocked", {"agent": getattr(agent, "name", ""), "tool": name, "reason": str(reason)})
        return NodeOutcome({"tool_calls": allowed or None, "blocked": [{"call": call, "reason": reason} for call, reason in blocked]})

    def _text_process_node(self, node: dict, inputs: dict) -> NodeOutcome:
        text = inputs.get("text", self.ctx.text)
        if text is None:
            return NodeOutcome({"text": None}, ["no_text"])
        mode = str(node.get("mode", node.get("action", "agent"))).lower()
        if mode in {"thought_action", "thought-action", "swe_action"}:
            return self._thought_action_text_node(node, str(text))
        if mode in {"aider_search_replace", "aider_editblock", "search_replace"}:
            return self._aider_search_replace_text_node(node, str(text))
        agent = self._node_agent(node, inputs)
        prompt = self.ctx.harness.prompts.get(node.get("prompt")) if node.get("prompt") else None
        self._before_model_call()
        processed = agent.process_text(str(text), self.ctx.harness.session.messages, prompt)
        self._record_model_usage(_estimate_tokens(text), _estimate_tokens(processed))
        self._record_provider_usage(agent)
        message = {"role": "assistant", "name": agent.name, "content": processed, "_op": "process_text"}
        self.ctx.harness.session.record(message)
        self.ctx.harness.session.record_full(message.copy())
        return NodeOutcome({"text": processed}, ["has_text"])

    def _aider_search_replace_text_node(self, node: dict, text: str) -> NodeOutcome:
        """Parse Aider-compatible SEARCH/REPLACE blocks without executing model text."""
        failure_path = f"_aider_edit_format_failures.{self.ctx.current_node or 'parser'}"
        valid_filenames = resolve_reference(node.get("valid_filenames", []), self.ctx)
        if valid_filenames is None:
            valid_filenames = []
        if not isinstance(valid_filenames, list):
            raise PipelineError("aider_search_replace valid_filenames must resolve to a list")
        try:
            edits, shell_commands = _parse_aider_search_replace_blocks(
                text,
                [str(value) for value in valid_filenames],
            )
            if node.get("require_edits", False) and not edits:
                raise ValueError("No SEARCH/REPLACE edit block was found.")
        except ValueError as error:
            count = int(get_path(self.ctx.data, failure_path, 0)) + 1
            set_path(self.ctx.data, failure_path, count)
            maximum = max(1, int(node.get("max_requeries", node.get("max_reflections", 3))))
            exhausted = count >= maximum
            prompt = str(
                resolve_reference(
                    node.get(
                        "format_error_prompt",
                        "Your edit response is malformed. Return filename-scoped SEARCH/REPLACE blocks using <<<<<<< SEARCH, =======, and >>>>>>> REPLACE. Include the exact existing text in SEARCH.",
                    ),
                    self.ctx,
                )
            )
            if not exhausted:
                correction = {
                    "role": "user",
                    "name": "runtime_aider_format_error",
                    "content": f"{prompt}\n\nParser error: {error}",
                }
                self.ctx.harness.session.record(correction)
                self.ctx.harness.session.record_full(correction.copy())
            self.ctx.emit(
                "aider_format_error",
                {"count": count, "maximum": maximum, "exhausted": exhausted, "message": str(error)},
            )
            value = {
                "valid": False,
                "edits": [],
                "shell_commands": [],
                "error": str(error),
                "format_failures": count,
                "exhausted": exhausted,
            }
            return NodeOutcome(
                {"text": text, **value, "value": value},
                ["format_error_exhausted" if exhausted else "format_error"],
            )

        set_path(self.ctx.data, failure_path, 0)
        value = {
            "valid": True,
            "edits": edits,
            "shell_commands": shell_commands,
            "error": "",
            "format_failures": 0,
            "exhausted": False,
        }
        self.ctx.emit(
            "aider_edits_parsed",
            {"edits": len(edits), "shell_commands": len(shell_commands)},
        )
        return NodeOutcome(
            {"text": text, **value, "value": value},
            ["editblocks_parsed", "has_edits" if edits else "no_edits"],
        )

    def _thought_action_text_node(self, node: dict, text: str) -> NodeOutcome:
        """Parse SWE-agent's one-discussion/one-fenced-action protocol."""
        failure_path = f"_action_format_failures.{self.ctx.current_node or 'parser'}"
        try:
            thought, action = _parse_thought_action(text)
        except ValueError as error:
            count = int(get_path(self.ctx.data, failure_path, 0)) + 1
            set_path(self.ctx.data, failure_path, count)
            max_requeries = max(1, int(node.get("max_requeries", 3)))
            exhausted = count >= max_requeries
            error_prompt = str(
                resolve_reference(
                    node.get(
                        "format_error_prompt",
                        "Your output was not formatted correctly. Return one discussion followed by exactly one shell action in the final fenced code block. Do not provide a final answer without an action.",
                    ),
                    self.ctx,
                )
            )
            trajectory_item = {
                "sequence": len(self.ctx.data.setdefault("_trajectory", [])) + 1,
                "timestamp": time.time(),
                "node": self.ctx.current_node,
                "phase": "action_parse",
                "action": "",
                "thought": text,
                "response": text,
                "ok": False,
                "observation": str(error),
                "format_failure": count,
            }
            self.ctx.data["_trajectory"].append(trajectory_item)
            self.ctx.data.pop("_pending_action_step", None)
            exit_status = "exit_format" if exhausted else ""
            self.ctx.emit(
                "action_format_error",
                {"count": count, "max_requeries": max_requeries, "exhausted": exhausted, "message": str(error)},
            )
            if not exhausted:
                correction = {
                    "role": "user",
                    "name": "runtime_action_format_error",
                    "content": f"{error_prompt}\n\nParser error: {error}",
                }
                self.ctx.harness.session.record(correction)
                self.ctx.harness.session.record_full(correction.copy())
            return NodeOutcome(
                {
                    "text": text,
                    "thought": text,
                    "action": "",
                    "valid": False,
                    "error": str(error),
                    "format_failures": count,
                    "exit_status": exit_status,
                    "tool_calls": None,
                    "value": {
                        "thought": text,
                        "action": "",
                        "valid": False,
                        "error": str(error),
                        "format_failures": count,
                        "exit_status": exit_status,
                    },
                },
                ["format_error_exhausted" if exhausted else "format_error"],
            )

        set_path(self.ctx.data, failure_path, 0)
        action = action.strip()
        command_name, _, command_value = action.partition(" ")
        command_name = command_name.strip().lower()
        submissions = {str(value).lower() for value in node.get("submission_commands", ["submit"])}
        exits = {str(value).lower() for value in node.get("exit_commands", ["exit"])}
        pending = {
            "parser": "thought_action",
            "thought": thought.strip(),
            "action": action,
            "response": text,
        }
        self.ctx.data["_pending_action_step"] = pending
        common = {
            "text": text,
            "thought": thought.strip(),
            "action": action,
            "valid": True,
            "error": "",
            "format_failures": 0,
            "exit_status": "",
            "value": {
                "thought": thought.strip(),
                "action": action,
                "valid": True,
                "error": "",
                "format_failures": 0,
            },
        }
        if command_name in submissions:
            summary = command_value.strip() or thought.strip() or "Submitted workspace changes"
            self.ctx.data.pop("_pending_action_step", None)
            self.ctx.emit("action_parsed", {"kind": "submission", "action": action})
            return NodeOutcome(
                {**common, "submission": summary, "tool_calls": None, "exit_status": "submitted"},
                ["action_parsed", "submission"],
            )
        if command_name in exits:
            self.ctx.data.pop("_pending_action_step", None)
            self.ctx.emit("action_parsed", {"kind": "exit", "action": action})
            return NodeOutcome(
                {**common, "tool_calls": None, "exit_status": "exit_command"},
                ["action_parsed", "exit_command"],
            )

        tool_name = str(node.get("action_tool", "run_command"))
        argument_name = str(node.get("action_argument", "command"))
        arguments = copy.deepcopy(node.get("action_arguments", {}))
        if not isinstance(arguments, dict):
            raise PipelineError("thought_action action_arguments must be an object")
        arguments[argument_name] = action
        tool_call = {
            "id": f"thought-action-{uuid.uuid4().hex[:12]}",
            "type": "function",
            "function": {
                "name": tool_name,
                "arguments": json.dumps(arguments, ensure_ascii=False),
            },
        }
        self.ctx.emit("action_parsed", {"kind": "tool", "tool": tool_name, "action": action})
        return NodeOutcome(
            {**common, "tool_calls": [tool_call]},
            ["action_parsed", "has_tool_calls"],
        )

    def _tool_node(self, node: dict, inputs: dict) -> NodeOutcome:
        from harness import EndSession

        calls = inputs.get("tool_calls", self.ctx.tool_calls)
        if not calls:
            return NodeOutcome({"results": [], "tool_calls": None}, ["no_tool_calls"])
        calls = list(calls)
        dropped_calls: list[dict] = []
        exclusive_tools = {
            str(name).lower() for name in node.get("exclusive_tools", []) if str(name)
        }
        if exclusive_tools:
            seen_exclusive: set[str] = set()
            retained_calls = []
            for call in calls:
                name = str(call.get("function", {}).get("name", "")).lower()
                if name in exclusive_tools and name in seen_exclusive:
                    dropped_calls.append(call)
                    self._record_synthetic_tool_response(
                        call,
                        "Only the first call to this exclusive tool is executed in one batch.",
                        status="discarded",
                        source="runtime_exclusive_tool_deduplication",
                    )
                    continue
                retained_calls.append(call)
                if name in exclusive_tools:
                    seen_exclusive.add(name)
            calls = retained_calls
            if dropped_calls:
                self.ctx.emit(
                    "exclusive_tool_calls_dropped",
                    {"discarded": [call.get("function", {}).get("name", "") for call in dropped_calls]},
                )
        only_first_tools = {
            str(name).lower() for name in node.get("only_first_tools", []) if str(name)
        }
        if only_first_tools:
            guarded_index = next(
                (
                    index
                    for index, call in enumerate(calls)
                    if index > 0 and str(call.get("function", {}).get("name", "")).lower() in only_first_tools
                ),
                None,
            )
            if guarded_index is not None:
                guarded = calls[guarded_index:]
                dropped_calls.extend(guarded)
                calls = calls[:guarded_index]
                for dropped in guarded:
                    self._record_synthetic_tool_response(
                        dropped,
                        "This tool is allowed only as the first action in a batch; it and later calls were not executed.",
                        status="discarded",
                        source="runtime_tool_position_guard",
                    )
                self.ctx.emit(
                    "tool_position_guard",
                    {"at": guarded_index, "discarded": [call.get("function", {}).get("name", "") for call in guarded]},
                )
        terminal_tools = {
            str(name).lower() for name in node.get("truncate_after_tools", []) if str(name)
        }
        if terminal_tools:
            terminal_index = next(
                (
                    index for index, call in enumerate(calls)
                    if str(call.get("function", {}).get("name", "")).lower() in terminal_tools
                ),
                None,
            )
            if terminal_index is not None and terminal_index + 1 < len(calls):
                dropped_calls.extend(calls[terminal_index + 1:])
                calls = calls[:terminal_index + 1]
                for dropped in dropped_calls:
                    self._record_synthetic_tool_response(
                        dropped,
                        "Discarded because an earlier terminal tool ended the batch.",
                        status="discarded",
                        source="runtime_tool_batch_truncation",
                    )
                self.ctx.emit(
                    "tool_batch_truncated",
                    {
                        "after": calls[-1].get("function", {}).get("name", ""),
                        "discarded": [call.get("function", {}).get("name", "") for call in dropped_calls],
                    },
                )
        agent = self._node_agent(node, inputs, required=False) or _get_main_agent(self.ctx.harness)
        if agent is None:
            raise PipelineError("Tool node has no agent to execute tools")

        policy_blocked = []
        policy_allowed = []
        if self.ctx.permission_policy is not None:
            for call in calls:
                name = call.get("function", {}).get("name", "")
                raw_arguments = call.get("function", {}).get("arguments", {})
                try:
                    arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else (raw_arguments or {})
                except (TypeError, ValueError):
                    arguments = {"_raw": str(raw_arguments)}
                found = agent._find_tool_or_knowledge(name) if hasattr(agent, "_find_tool_or_knowledge") else None
                metadata = getattr(found[1], "meta", {}) if found else {}
                decision = self.ctx.permission_policy.evaluate_tool(name, arguments, metadata)
                approved = decision.allowed
                if decision.decision.value == "ask":
                    prompt = f"Allow tool '{name}' for this call? [y/N]"
                    approval_id = f"{self.ctx.run_id}:{uuid.uuid4().hex}"
                    self.ctx.pending_approvals[approval_id] = {
                        "id": approval_id,
                        "kind": "tool",
                        "tool": name,
                        "arguments": copy.deepcopy(arguments),
                        "prompt": prompt,
                        "reason": decision.reason,
                        "risk": decision.risk.public(),
                    }
                    if self.auto_checkpoint:
                        self._save_checkpoint(
                            f"approval-{approval_id}",
                            next_node=self.ctx.current_node,
                            phase="in_flight",
                            operation="工具审批",
                        )
                    self.ctx.emit(
                        "approval_required",
                        {
                            "approval_id": approval_id,
                            "prompt": prompt,
                            "tool": name,
                            "arguments": arguments,
                            "reason": decision.reason,
                            "risk": decision.risk.public(),
                            "default": "rejected",
                            "auto_approvable": True,
                        },
                    )
                    answer = self._approval_answer(str(node.get("ask_default", "rejected")), approval_id=approval_id)
                    if isinstance(answer, str) and answer.lstrip().startswith("{"):
                        try:
                            answer = json.loads(answer)
                        except ValueError:
                            pass
                    raw_answer = answer.get("decision", answer.get("answer", "rejected")) if isinstance(answer, dict) else answer
                    approved = str(raw_answer).strip().lower() in {
                        "y", "yes", "allow", "approve", "approved", "true", "通过", "同意"
                    }
                    self.ctx.emit(
                        "approval",
                        {
                            "approval_id": approval_id,
                            "decision": "approved" if approved else "rejected",
                            "source": answer.get("source", "manual") if isinstance(answer, dict) else "manual",
                            "tool": name,
                        },
                    )
                    self.ctx.pending_approvals.pop(approval_id, None)
                    if approved and call.get("id"):
                        self.ctx.approved_tool_call_ids.add(str(call["id"]))
                if approved:
                    policy_allowed.append(call)
                    continue
                reason = decision.reason if decision.decision.value == "deny" else "User did not approve this tool call."
                payload = {
                    "tool": name,
                    "tool_call_id": call.get("id"),
                    "status": "denied",
                    "content": reason,
                }
                message = {
                    "role": "user",
                    "name": "runtime_permission_policy",
                    "content": f'<tool_response>{json.dumps(payload, ensure_ascii=False)}</tool_response>',
                }
                self.ctx.harness.session.record(message)
                self.ctx.harness.session.record_full(message.copy())
                self.ctx.emit("blocked", {"agent": getattr(agent, "name", ""), "tool": name, "reason": reason})
                policy_blocked.append({"name": name, "result": f"Permission denied: {reason}", "blocked": True})
            calls = policy_allowed

        max_observation_chars = node.get("max_observation_chars")
        if max_observation_chars is not None:
            max_observation_chars = max(1, int(max_observation_chars))

        def bound_observation(result: Any) -> Any:
            if max_observation_chars is None:
                return result
            serialized = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
            if len(serialized) <= max_observation_chars:
                return result
            omitted = len(serialized) - max_observation_chars
            self.ctx.emit(
                "tool_observation_truncated",
                {"limit": max_observation_chars, "omitted": omitted},
            )
            return f"{serialized[:max_observation_chars]}\n...[tool observation truncated; {omitted} characters omitted]"

        def execute_one(index_and_call):
            if self.ctx.cancelled():
                raise PipelineCancelled("pipeline execution was cancelled before tool execution")
            index, call = index_and_call
            if self.ctx.cancelled():
                raise PipelineCancelled("pipeline execution was cancelled")
            try:
                kwargs = {}
                if node.get("attach_images", False):
                    kwargs.update(
                        attach_images=True,
                        max_image_bytes=int(node.get("max_image_bytes", 8_000_000)),
                    )
                if max_observation_chars is not None:
                    kwargs["max_result_chars"] = max_observation_chars
                function = call.get("function", {})
                raw_arguments = function.get("arguments", {})
                try:
                    request_arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
                except (TypeError, ValueError):
                    request_arguments = {}
                if not isinstance(request_arguments, dict):
                    request_arguments = {}
                visible_arguments = {key: "[REDACTED]" if key in node.get("sensitive_fields", []) else value
                                     for key, value in request_arguments.items()}
                self.ctx.emit("tool_start", {
                    "tool_call_id": call.get("id"), "name": function.get("name", ""),
                    "agent": getattr(agent, "name", ""),
                    "arguments": _debug_value(visible_arguments, limit=20000),
                })
                executor = getattr(agent, "tool_executor", None)
                if executor is None:
                    from tool_pipeline import AgentToolExecutor
                    executor = AgentToolExecutor(agent)
                execution = executor.execute(ToolExecutionRequest(
                    name=str(function.get("name", "")),
                    arguments=request_arguments,
                    call_id=str(call.get("id") or f"tool_{uuid.uuid4().hex}"),
                    agent=str(getattr(agent, "name", "")),
                    workspace=self.ctx.workspace,
                    metadata={"raw_tool_call": call, "execution_options": kwargs},
                ))
                result = execution.model_observation
                result = bound_observation(result)
                self.ctx.emit("tool_end", {"tool_call_id": call.get("id"),
                    "name": function.get("name", ""), "agent": getattr(agent, "name", ""),
                    "status": "completed" if _tool_result_succeeded(result) else "error"})
            except EndSession as error:
                self.ctx.emit("tool_end", {"tool_call_id": call.get("id"),
                    "name": call.get("function", {}).get("name", ""),
                    "agent": getattr(agent, "name", ""), "status": "completed"})
                return index, call, None, error
            except Exception:
                self.ctx.emit("tool_end", {"tool_call_id": call.get("id"),
                    "name": call.get("function", {}).get("name", ""),
                    "agent": getattr(agent, "name", ""), "status": "error"})
                raise
            return index, call, result, None

        if not calls:
            self.ctx.tool_calls = None
            self.ctx.data["tool_calls"] = None
            return NodeOutcome(
                {"results": policy_blocked, "value": policy_blocked, "tool_calls": None, "dropped_calls": dropped_calls},
                ["tools_executed"],
            )

        indexed_calls = list(enumerate(calls))
        executed = []
        if node.get("parallel") and len(indexed_calls) > 1:
            workers = min(max(1, int(node.get("max_workers", len(indexed_calls)))), len(indexed_calls))
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix=f"tools-{self.ctx.run_id[:6]}") as executor:
                future_map = {
                    executor.submit(contextvars.copy_context().run, execute_one, item): item
                    for item in indexed_calls
                }
                for future in as_completed(future_map):
                    executed.append(future.result())
            executed.sort(key=lambda item: item[0])
        else:
            for item in indexed_calls:
                executed_item = execute_one(item)
                executed.append(executed_item)
                interrupt_when = node.get("interrupt_when")
                if interrupt_when and executed_item[3] is None:
                    call = executed_item[1]
                    raw_arguments = call.get("function", {}).get("arguments", {})
                    try:
                        arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
                    except (TypeError, ValueError):
                        arguments = {"_raw": str(raw_arguments)}
                    variables = self.ctx.variables()
                    variables.update({
                        "tool": call.get("function", {}).get("name", ""),
                        "arguments": arguments,
                        "result": executed_item[2],
                    })
                    expression = interrupt_when[5:] if isinstance(interrupt_when, str) and interrupt_when.startswith("expr:") else interrupt_when
                    if evaluate_expression(str(expression), variables):
                        skipped = len(indexed_calls) - len(executed)
                        self.ctx.emit("tool_batch_interrupted", {"after": variables["tool"], "skipped": skipped})
                        break

        results = list(policy_blocked)
        human_required = []
        all_succeeded = not policy_blocked
        for _index, call, result, end_error in executed:
            name = call.get("function", {}).get("name", "")
            raw_arguments = call.get("function", {}).get("arguments", {})
            try:
                arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else copy.deepcopy(raw_arguments)
            except (TypeError, ValueError):
                arguments = {"_raw": str(raw_arguments)}
            sensitive_fields = {str(field) for field in node.get("sensitive_fields", [])}
            if isinstance(arguments, dict):
                arguments = {
                    key: "[REDACTED]" if key in sensitive_fields else value
                    for key, value in arguments.items()
                }
            trajectory_item = {
                "sequence": len(self.ctx.data.setdefault("_trajectory", [])) + 1,
                "timestamp": time.time(),
                "node": self.ctx.current_node,
                "agent": getattr(agent, "name", ""),
                "action": name,
                "arguments": arguments,
                "ok": end_error is None and _tool_result_succeeded(result),
                "observation": copy.deepcopy(result) if result is not None else str(end_error or ""),
            }
            all_succeeded = all_succeeded and bool(trajectory_item["ok"])
            pending_action = self.ctx.data.get("_pending_action_step")
            if isinstance(pending_action, dict):
                trajectory_item.update(
                    {
                        "protocol": pending_action.get("parser"),
                        "thought": pending_action.get("thought", ""),
                        "response": pending_action.get("response", ""),
                        "environment_action": pending_action.get("action", ""),
                    }
                )
            self.ctx.data["_trajectory"].append(trajectory_item)
            if trajectory_item["ok"]:
                self.ctx.data.setdefault("_turn_executed_tools", []).append(name)
            self.ctx.emit("action_observation", _preview_value(trajectory_item))
            if end_error is not None:
                content = str(end_error)
                message = {"role": "assistant", "content": content}
                self.ctx.harness.session.record(message)
                self.ctx.harness.session.record_full(message.copy())
                self.ctx.stats.tool_calls += 1
                self.ctx.tool_calls = None
                self.ctx.data["tool_calls"] = None
                self.ctx.data["_submission"] = content
                self.ctx.data.pop("_pending_action_step", None)
                target = node.get("end_session_to")
                return NodeOutcome(
                    {"results": results, "text": content, "submission": content, "tool_calls": None},
                    ["end_session", "submission"],
                    next_node=target,
                    stop=not bool(target),
                )
            self.ctx.stats.tool_calls += 1
            item = {"name": name, "result": result}
            results.append(item)
            if isinstance(result, dict):
                blocked = result.get("blocked") if isinstance(result.get("blocked"), dict) else {}
                requires_human = (
                    result.get("requires_human") is True
                    or result.get("status") == "human_required"
                    or blocked.get("requires_human") is True
                )
                if requires_human:
                    human_required.append(copy.deepcopy(item))
            self.ctx.emit(
                "tool",
                {
                    "name": item["name"],
                    "tool_call_id": call.get("id"),
                    "arguments": _debug_value(arguments, limit=20000),
                    "result": _debug_value(result, limit=50000),
                    "agent": getattr(agent, "name", ""),
                },
            )
            mutation_event = _mutation_event_for_tool(name, arguments, result)
            if mutation_event:
                self.ctx.emit(
                    mutation_event,
                    {
                        **_mutation_event_payload(
                            name, arguments, result, agent=getattr(agent, "name", "")
                        ),
                        "tool_call_id": call.get("id"),
                    },
                )
            self._check_run_limits()
        self.ctx.tool_calls = None
        self.ctx.data["tool_calls"] = None
        self.ctx.data.pop("_pending_action_step", None)
        if human_required:
            handoff = {"required": True, "items": human_required}
            self.ctx.data["_human_required"] = handoff
            self.ctx.emit("human_required", _preview_value(handoff))
            return NodeOutcome(
                {"results": results, "value": results, "tool_calls": None, "human_required": handoff},
                ["human_required", "tools_executed"],
            )
        terminal_call = next(
            (
                call for _index, call, _result, end_error in executed
                if end_error is None
                and str(call.get("function", {}).get("name", "")).lower() in terminal_tools
            ),
            None,
        )
        terminal_target = node.get("terminal_tools_to")
        if terminal_call is not None and terminal_target:
            terminal_name = terminal_call.get("function", {}).get("name", "")
            terminal_info = {"tool": terminal_name, "to": terminal_target}
            self.ctx.data["_terminal_tool"] = terminal_info
            self.ctx.emit("terminal_tool", terminal_info)
            return NodeOutcome(
                {
                    "results": results,
                    "value": results,
                    "tool_calls": None,
                    "terminal_tool": terminal_info,
                    "dropped_calls": dropped_calls,
                },
                ["terminal_tool", "tools_executed"],
                next_node=str(terminal_target),
            )
        error_nudge = self._tool_error_nudge(node)
        if error_nudge:
            self.ctx.data["_tool_error_nudge"] = error_nudge
            message = {"role": "user", "name": "runtime_tool_error_nudge", "content": error_nudge["nudge"]}
            self.ctx.harness.session.record(message)
            self.ctx.harness.session.record_full(message.copy())
            self.ctx.emit("tool_error_nudge", error_nudge)
            return NodeOutcome(
                {
                    "results": results,
                    "value": results,
                    "tool_calls": None,
                    "error_nudge": error_nudge,
                    "dropped_calls": dropped_calls,
                },
                ["error_nudge", "tools_executed"],
                next_node=node.get("error_nudge_to"),
            )
        stuck_reason = self._tool_stuck_reason(node)
        if stuck_reason:
            nudge = str(
                node.get(
                    "stuck_prompt",
                    "The recent tool trajectory is repeating without progress. Review the observations and use a materially different action, arguments, or approach.",
                )
            )
            stuck_info = {"reason": stuck_reason, "nudge": nudge}
            self.ctx.data["_tool_stuck"] = stuck_info
            message = {"role": "user", "name": "runtime_stuck_detector", "content": nudge}
            self.ctx.harness.session.record(message)
            self.ctx.harness.session.record_full(message.copy())
            self.ctx.emit("tool_stuck", stuck_info)
            return NodeOutcome(
                {"results": results, "value": results, "tool_calls": None, "stuck": stuck_info},
                ["stuck", "tools_executed"],
            )
        return NodeOutcome(
            {
                "results": results,
                "value": results,
                "succeeded": all_succeeded and bool(executed),
                "tool_calls": None,
                "dropped_calls": dropped_calls,
            },
            ["tools_executed"],
        )

    def _tool_error_nudge(self, node: dict) -> Optional[dict]:
        threshold = max(0, int(node.get("error_nudge_threshold", 0)))
        trajectory = self.ctx.data.get("_trajectory", [])
        if threshold < 2 or not isinstance(trajectory, list) or len(trajectory) < threshold:
            return None
        latest = trajectory[-1]
        if not isinstance(latest, dict) or latest.get("ok", True):
            return None
        action_signature = json.dumps(
            {"action": latest.get("action"), "arguments": latest.get("arguments")},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        error_signature = json.dumps(latest.get("observation"), ensure_ascii=False, sort_keys=True, default=str)
        streak = 0
        for item in reversed(trajectory):
            if not isinstance(item, dict) or item.get("ok", True):
                break
            item_action = json.dumps(
                {"action": item.get("action"), "arguments": item.get("arguments")},
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
            item_error = json.dumps(item.get("observation"), ensure_ascii=False, sort_keys=True, default=str)
            if item_action != action_signature or item_error != error_signature:
                break
            streak += 1
        if streak != threshold:
            return None
        marker = f"{action_signature}:{error_signature}:{threshold}"
        seen = self.ctx.data.setdefault("_tool_error_nudge_markers", [])
        if marker in seen:
            return None
        seen.append(marker)
        name = str(latest.get("action", "tool"))
        observation = str(latest.get("observation", ""))
        nudge = str(
            resolve_reference(
                node.get(
                    "error_nudge_prompt",
                    f"You've called `{name}` with the same arguments {threshold} times in a row and gotten the same error each time: {observation}. Repeating the exact same call again will not work — review the error and correct the arguments or try a different approach.",
                ),
                self.ctx,
            )
        )
        return {"action": name, "streak": streak, "error": observation, "nudge": nudge}

    def _tool_stuck_reason(self, node: dict) -> Optional[str]:
        trajectory = self.ctx.data.get("_trajectory", [])
        if not isinstance(trajectory, list):
            return None

        ignored_arguments = {
            str(field) for field in node.get("stuck_ignore_arguments", [])
            if isinstance(field, (str, int, float))
        }
        retain_observation = bool(node.get("stuck_include_observation", True))

        def signature(item: dict, include_observation: bool = True) -> str:
            arguments = copy.deepcopy(item.get("arguments"))
            if isinstance(arguments, dict) and ignored_arguments:
                arguments = {key: value for key, value in arguments.items() if key not in ignored_arguments}
            value = {"action": item.get("action"), "arguments": arguments}
            if include_observation and retain_observation:
                value["observation"] = item.get("observation")
            return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)

        repeated_threshold = max(0, int(node.get("stuck_threshold", 0)))
        if repeated_threshold >= 2 and len(trajectory) >= repeated_threshold:
            recent = trajectory[-repeated_threshold:]
            if (
                all(isinstance(item, dict) for item in recent)
                and len({signature(item) for item in recent}) == 1
            ):
                return f"same action and observation repeated {repeated_threshold} times"

        error_threshold = max(0, int(node.get("error_stuck_threshold", 0)))
        if error_threshold >= 2 and len(trajectory) >= error_threshold:
            recent = trajectory[-error_threshold:]
            if (
                all(isinstance(item, dict) and not item.get("ok", False) for item in recent)
                and len({signature(item, include_observation=False) for item in recent}) == 1
            ):
                return f"same action failed {error_threshold} times"

        alternating_threshold = max(0, int(node.get("alternating_stuck_threshold", 0)))
        if alternating_threshold >= 4 and len(trajectory) >= alternating_threshold:
            recent = trajectory[-alternating_threshold:]
            if all(isinstance(item, dict) for item in recent):
                recent_signatures = [signature(item) for item in recent]
                if all(
                    recent_signatures[index] == recent_signatures[index - 2]
                    for index in range(2, alternating_threshold)
                ):
                    return f"alternating action-observation pattern repeated for {alternating_threshold} actions"
        return None

    def _approval_answer(self, default="rejected", *, approval_id=""):
        # A SubFlow must not start its own conversation Input loop, but that
        # does not make its safety approval unattended. Forward ONLY approval
        # input to the owning interactive session. Headless roots still deny.
        owner = self.ctx
        while getattr(owner, "parent", None) is not None:
            owner = owner.parent
        if self.ctx.cancelled():
            raise PipelineCancelled("pipeline execution was cancelled")
        if getattr(owner.harness, "_non_interactive", False):
            return default
        from runtime_waits import human_wait
        with human_wait():
            waiter = getattr(owner, "get_approval", None)
            answer = waiter(approval_id, self.ctx.cancelled) if waiter else owner.get_input()
        if self.ctx.cancelled():
            raise PipelineCancelled("pipeline execution was cancelled")
        return answer or default

    def _require_policy_approval(self, decision, *, tool: str, arguments: dict, prompt: str) -> None:
        """Apply one typed policy decision at a non-Agent DAG boundary."""
        if decision.decision.value == "allow":
            return
        if decision.decision.value == "deny":
            raise PipelineError(f"{tool} permission denied: {decision.reason}")

        approval_id = f"{self.ctx.run_id}:{self.ctx.current_node}:{self.ctx.stats.node_steps}:{tool}"
        self.ctx.pending_approvals[approval_id] = {
            "id": approval_id,
            "kind": "runtime",
            "tool": tool,
            "arguments": copy.deepcopy(arguments),
            "prompt": prompt,
            "reason": decision.reason,
            "risk": decision.risk.public(),
        }
        if self.auto_checkpoint:
            self._save_checkpoint(
                f"approval-{self.ctx.current_node}",
                next_node=self.ctx.current_node,
                phase="in_flight",
                operation=f"{tool} approval",
            )
        self.ctx.emit("approval_required", {
            "approval_id": approval_id,
            "prompt": prompt,
            "tool": tool,
            "arguments": arguments,
            "reason": decision.reason,
            "risk": decision.risk.public(),
            "default": "rejected",
            "auto_approvable": True,
        })
        answer = self._approval_answer(approval_id=approval_id)
        if isinstance(answer, str) and answer.lstrip().startswith("{"):
            try:
                answer = json.loads(answer)
            except ValueError:
                pass
        raw_answer = answer.get("decision", answer.get("answer", "rejected")) if isinstance(answer, dict) else answer
        approved = str(raw_answer).strip().lower() in {
            "y", "yes", "allow", "approve", "approved", "true", "通过", "同意",
        }
        self.ctx.pending_approvals.pop(approval_id, None)
        self.ctx.emit("approval", {
            "approval_id": approval_id,
            "decision": "approved" if approved else "rejected",
            "source": answer.get("source", "manual") if isinstance(answer, dict) else "manual",
            "tool": tool,
        })
        if not approved:
            raise PipelineError(f"User rejected {tool} operation")

    def _python_node(self, node: dict, inputs: dict) -> NodeOutcome:
        script_name = node.get("script")
        if not script_name or Path(script_name).name != script_name:
            raise PipelineError("Python node requires a simple script name")
        script_path = (Path(self.ctx.harness.dir) / "scripts" / f"{script_name}.py").resolve()
        scripts_root = (Path(self.ctx.harness.dir) / "scripts").resolve()
        if scripts_root not in script_path.parents or not script_path.is_file():
            raise PipelineError(f"Python script not found: {script_name}")
        policy = self.ctx.permission_policy
        if policy is not None:
            if str(policy.sandbox.get("mode", "workspace")) == "container":
                raise PipelineError(
                    "Python node is blocked while strong container sandboxing is enabled because it would execute inside the EgoAgent backend. "
                    "Replace it with typed DAG nodes or an explicit container Process node."
                )
            decision = policy.evaluate_tool(
                "python_node",
                {"script": script_name, "path": str(script_path)},
                {"permissions": ["process"]},
            )
            self._require_policy_approval(
                decision,
                tool="python_node",
                arguments={"script": script_name, "path": str(script_path)},
                prompt=f"Allow Harness Python node '{script_name}' to execute inside the EgoAgent backend?",
            )
        local_ctx = dict(inputs) if inputs else {key: self.ctx.data.get(key) for key in node.get("input_vars", [])}
        # Scripts receive only serializable runtime metadata, never live Agent
        # objects.  This lets bounded adapters (for example a CoC Keeper)
        # resolve the identities currently bound to slots without granting
        # arbitrary access to the harness internals.
        local_ctx["_runtime"] = {
            "workspace": str(self.ctx.workspace) if self.ctx.workspace else None,
            "harness_dir": str(Path(self.ctx.harness.dir).resolve()),
            "agent_identities": {
                str(slot): str(agent.identity.identity_path)
                for slot, agent in self.ctx.harness.agents.items()
                if getattr(agent, "identity", None) is not None
            },
        }
        namespace = {"__file__": str(script_path), "__name__": f"egoagent_script_{script_name}"}
        exec(script_path.read_text(encoding="utf-8"), namespace)
        if not callable(namespace.get("run")):
            raise PipelineError(f"Python script {script_name!r} must define run(ctx)")
        result = namespace["run"](local_ctx)
        if isinstance(result, dict):
            reload_slots = result.get("_reload_identity_slots", [])
            if reload_slots:
                if not isinstance(reload_slots, list):
                    raise PipelineError("_reload_identity_slots must be an array")
                for slot in reload_slots:
                    agent = self.ctx.harness.agents.get(str(slot))
                    if agent is None:
                        raise PipelineError(f"Cannot reload unknown Agent slot: {slot}")
                    agent.reload_identity()
            for key in node.get("output_vars", []):
                if key in result:
                    self.ctx.data[key] = result[key]
        self.ctx.emit("script", {"name": script_name, "result": _preview_value(result), "advanced": True})
        return NodeOutcome(result if isinstance(result, dict) else {"value": result})

    def _model_node(self, node: dict, inputs: dict) -> NodeOutcome:
        prompt_name = node.get("prompt")
        prompt_template = self.ctx.harness.prompts.get(prompt_name, "")
        values = dict(self.ctx.data)
        values.update(inputs)
        prompt = _format_prompt(prompt_template, values)
        self._before_model_call()
        agent = self._node_agent(node, inputs)
        self.ctx.emit(
            "model_request",
            {
                "agent": getattr(agent, "name", "Agent"),
                "prompt": _debug_value(prompt, limit=50000),
                "tools": [],
            },
        )
        response = _standalone_llm_call(
            prompt,
            self.ctx.harness,
            agent=agent,
            max_tokens=int(node.get("max_tokens", 2048)),
            temperature=float(node.get("temperature", 0.7)),
            on_reasoning=lambda text: self.ctx.emit("reasoning", {
                "agent": getattr(agent, "name", "Agent"), "text": text}),
        )
        self._record_model_usage(_estimate_tokens(prompt), _estimate_tokens(response))
        self._record_provider_usage(agent)
        self.ctx.emit(
            "model_response",
            {"agent": getattr(agent, "name", "Agent"), "text": _debug_value(response, limit=50000), "tool_calls": []},
        )
        value: Any = response
        parse_mode = str(node.get("parse_as", "text")).lower()
        parse_fallback = False
        if parse_mode in {"json", "json_object"}:
            try:
                candidate = _strip_code_fence(response)
                if parse_mode == "json_object":
                    match = re.search(r"\{.*\}", candidate, re.DOTALL)
                    if match:
                        candidate = match.group(0)
                value = json.loads(candidate)
                if parse_mode == "json_object" and not isinstance(value, dict):
                    raise ValueError("expected a JSON object")
            except (TypeError, ValueError) as error:
                if "json_fallback" not in node:
                    raise
                value = resolve_reference(node.get("json_fallback"), self.ctx)
                parse_fallback = True
                self.ctx.emit(
                    "model_json_fallback",
                    {"node": self.ctx.current_node, "message": str(error), "fallback": _preview_value(value)},
                )
        output_var = node.get("output_var", "_llm_result")
        self.ctx.data[output_var] = value
        return NodeOutcome(
            {
                "text": response,
                "value": value,
                "structured": value if isinstance(value, (dict, list)) else None,
                "parse_fallback": parse_fallback,
            },
            ["json_fallback", "has_text"] if parse_fallback else ["has_text"],
        )

    def _context_node(self, node: dict, inputs: dict) -> NodeOutcome:
        """Select or compact message history without a Python escape hatch."""
        action = str(node.get("action", "select"))
        # ``snapshot`` and ``apply`` are the neutral conversation ports used by
        # composable context-management DAGs.  They never call a model: a
        # normal Model node authors the plan between these two ports.  Legacy
        # curate/compact actions remain readable for old Harness files, but new
        # components should keep policy (prompt, cadence and thresholds) in the
        # graph instead of hiding it in the runtime.
        if action == "snapshot":
            return self._conversation_snapshot_node(node, inputs)
        if action == "apply":
            return self._conversation_apply_node(node, inputs)
        source = inputs.get("messages")
        if source is None:
            default_source = "$session.full_messages" if action in {"curate", "restore_full"} else "$session.messages"
            source = resolve_reference(node.get("source", default_source), self.ctx)
        if not isinstance(source, list):
            raise PipelineError("Context node source must be a list of messages")

        roles = set(node.get("roles", []))
        names = set(node.get("names", []))
        messages = [
            copy.deepcopy(message)
            for message in source
            if isinstance(message, dict)
            and (not roles or message.get("role") in roles)
            and (not names or message.get("name") in names)
        ]
        elided_observations = 0
        if action == "restore_full":
            from context_policy import restore_full_context

            restored = restore_full_context(messages)
            session = self.ctx.harness.session
            if node.get("persist_session", True):
                restoration = {
                    "messages": copy.deepcopy(restored),
                    "full_messages": copy.deepcopy(restored),
                    "ledger": [],
                    "stats": {
                        "before_tokens_estimated": _estimate_messages_tokens(restored),
                        "after_tokens_estimated": _estimate_messages_tokens(restored),
                        "saved_tokens_estimated": 0,
                        "reduction_ratio": 0,
                    },
                }
                session.apply_context_result(restoration)
                with session._lock:
                    session.state["context_governance"] = {
                        "ledger": [],
                        "stats": copy.deepcopy(restoration["stats"]),
                        "reviewed_turn_ids": [],
                        "restored_at": time.time(),
                    }
            output_var = node.get("output_var", "context_messages")
            self.ctx.data[output_var] = restored
            return NodeOutcome(
                {"messages": restored, "restored": True, "value": restored},
                ["context_restored", "context_ready"],
            )

        if action == "curate":
            from context_policy import apply_context_decisions, content_text, judge_prompt, review_batch

            session = self.ctx.harness.session
            governance = session.state.get("context_governance", {})
            existing_ledger = governance.get("ledger", []) if isinstance(governance, dict) else []
            reviewed = set(governance.get("reviewed_turn_ids", [])) if isinstance(governance, dict) else set()
            interval = max(1, int(node.get("review_interval", 5)))
            protect_recent = max(1, int(node.get("protect_recent_turns", 2)))
            batch = review_batch(messages, reviewed, interval=interval, protect_recent=protect_recent)
            pressure_history = governance.get("pressure_compactions", []) if isinstance(governance, dict) else []
            if not batch and pressure_history and node.get("persist_session", True):
                # Do not rebuild the working view from the immutable audit copy
                # on every turn after a pressure compaction. New messages are
                # already appended to session.messages. A fresh five-turn
                # relevance batch may re-derive the view, after which the
                # normal high-watermark middleware can compact it again.
                current_working = copy.deepcopy(session.messages)
                stats = copy.deepcopy(governance.get("pressure_stats", {}))
                output_var = node.get("output_var", "context_messages")
                self.ctx.data[output_var] = current_working
                self.ctx.data[node.get("stats_var", "context_stats")] = stats
                self.ctx.emit(
                    "context_curated",
                    {**stats, "reviewed_turns": 0, "pressure_view_reused": True},
                )
                return NodeOutcome(
                    {
                        "messages": current_working,
                        "full_messages": copy.deepcopy(session.full_messages),
                        "stats": stats,
                        "reviewed_turn_ids": sorted(reviewed),
                        "reviewed_now": [],
                        "pressure_view_reused": True,
                        "value": current_working,
                    },
                    ["context_waiting_interval", "context_ready"],
                )
            new_decisions: list[dict[str, Any]] = []
            judge_error = None
            if batch:
                current_task = ""
                for message in reversed(messages):
                    if message.get("role") == "user" and "<tool_response>" not in content_text(message):
                        current_task = content_text(message)
                        break
                allow_summarize = bool(node.get("allow_summarize", True))
                prompt = judge_prompt(batch, current_task=current_task, allow_summarize=allow_summarize)
                agent = self._node_agent(node, inputs)
                try:
                    self._before_model_call()
                    response = _standalone_llm_call(
                        prompt,
                        self.ctx.harness,
                        agent=agent,
                        max_tokens=int(node.get("max_tokens", 1400)),
                        temperature=float(node.get("temperature", 0.1)),
                        purpose="context_curator",
                    )
                    self._record_model_usage(_estimate_tokens(prompt), _estimate_tokens(response))
                    self._record_provider_usage(agent)
                    parsed = json.loads(_strip_code_fence(response))
                    raw_decisions = parsed.get("decisions", []) if isinstance(parsed, dict) else []
                    allowed_ids = {turn.id for turn in batch}
                    new_decisions = [
                        decision for decision in raw_decisions
                        if isinstance(decision, dict) and str(decision.get("turn_id")) in allowed_ids
                    ]
                    if not allow_summarize:
                        for decision in new_decisions:
                            if str(decision.get("action", "keep")).casefold() == "summarize":
                                decision["action"] = "keep"
                                decision["reason"] = "summary_deferred_until_token_pressure"
                except Exception as error:
                    # Context loss is worse than a missed compression cycle.
                    # Keep every candidate and make the failure observable.
                    judge_error = str(error)
                    new_decisions = [
                        {"turn_id": turn.id, "action": "keep", "reason": "curator_parse_failure"}
                        for turn in batch
                    ]
                decided_ids = {str(item.get("turn_id")) for item in new_decisions}
                new_decisions.extend(
                    {"turn_id": turn.id, "action": "keep", "reason": "curator_omitted_turn_fallback"}
                    for turn in batch if turn.id not in decided_ids
                )

            previous_decisions = [
                {
                    "turn_id": item.get("turn_id"),
                    "action": item.get("action", "keep"),
                    "reason": item.get("reason", "previous_context_decision"),
                    "summary": item.get("summary", ""),
                }
                for item in existing_ledger
                if isinstance(item, dict) and item.get("turn_id")
            ]
            combined = {str(item["turn_id"]): item for item in previous_decisions}
            combined.update({str(item["turn_id"]): item for item in new_decisions})
            max_tool_chars = int(node.get("max_tool_chars", 1800))
            result = apply_context_decisions(
                messages,
                combined.values(),
                protect_recent=protect_recent,
                max_tool_chars=max(200, max_tool_chars) if max_tool_chars > 0 else 0,
            )
            reviewed.update(turn.id for turn in batch)
            result["reviewed_turn_ids"] = sorted(reviewed)
            result["reviewed_now"] = [turn.id for turn in batch]
            result["judge_error"] = judge_error
            if node.get("persist_session", True):
                session.apply_context_result(result)
                with session._lock:
                    session.state.setdefault("context_governance", {})["reviewed_turn_ids"] = sorted(reviewed)
            output_var = node.get("output_var", "context_messages")
            self.ctx.data[output_var] = result["messages"]
            self.ctx.data[node.get("stats_var", "context_stats")] = result["stats"]
            self.ctx.emit(
                "context_curated",
                {
                    **result["stats"],
                    "reviewed_turns": len(batch),
                    "judge_error": judge_error,
                },
            )
            return NodeOutcome(
                {**result, "value": result["messages"]},
                ["context_reviewed" if batch else "context_waiting_interval", "context_ready"],
            )

        if action == "auto_compact":
            context_limit = max(1, int(node.get("context_limit_tokens", 128_000)))
            max_output = max(0, int(node.get("max_output_tokens", node.get("max_tokens", 4_096))))
            reserved = max(0, int(node.get("reserved_tokens", 0)))
            buffer_ratio = min(0.99, max(0.0, float(node.get("compaction_buffer_ratio", 0.2))))
            buffer_cap = max(0, int(node.get("compaction_buffer_cap", 15_000)))
            ratio_buffer = int((context_limit - max_output) * buffer_ratio + 0.999999)
            compaction_buffer = min(max(max_output, ratio_buffer), buffer_cap)
            threshold = context_limit - max_output - compaction_buffer
            if threshold <= 0:
                raise PipelineError("Context auto_compact requires context_limit_tokens larger than output reservation and buffer")
            input_tokens = _estimate_messages_tokens(messages) + reserved
            compacted = bool(inputs.get("force", node.get("force", False))) or input_tokens >= threshold
            summary = None
            if compacted:
                history_for_summary = copy.deepcopy(messages)
                available = max(1, context_limit - max_output - reserved - int(node.get("summary_prompt_tokens", 150)))
                while len(history_for_summary) > 1 and _estimate_messages_tokens(history_for_summary) > available:
                    history_for_summary = _prune_oldest_conversation_message(history_for_summary)
                agent = self._node_agent(node, inputs)
                template = self.ctx.harness.prompts.get(
                    node.get("prompt"),
                    "Please provide a concise summary of our conversation so far, capturing the key context, decisions made, current state, exact unfinished work, file paths, tool results, errors and constraints needed to continue. Do not recap the system message.\n\n{history}",
                )
                prompt = _format_prompt(
                    template,
                    {**self.ctx.data, **inputs, "history": json.dumps(history_for_summary, ensure_ascii=False)},
                )
                self._before_model_call()
                summary = _standalone_llm_call(
                    prompt,
                    self.ctx.harness,
                    agent=agent,
                    max_tokens=int(node.get("summary_max_tokens", min(max_output or 1024, 2048))),
                    temperature=float(node.get("temperature", 0.2)),
                    purpose="context_auto_compactor",
                )
                self._record_model_usage(_estimate_tokens(prompt), _estimate_tokens(summary))
                self._record_provider_usage(agent)
                system_messages = [message for message in messages if message.get("role") == "system"]
                summary_message = {
                    # A compaction summary is runtime-provided context, not a
                    # prior model utterance.  Keeping it system-role preserves
                    # valid user/assistant alternation for providers and SFT.
                    "role": "system",
                    "name": "context_summary",
                    "content": summary,
                    "conversation_summary": True,
                }
                messages = system_messages[:1] + [summary_message]
                if node.get("persist_session", True):
                    session = self.ctx.harness.session
                    session.apply_context_result({
                        "messages": copy.deepcopy(messages),
                        "full_messages": copy.deepcopy(session.full_messages),
                        "ledger": [{
                            "action": "summarize",
                            "source": "context_auto_compactor",
                            "node": self.ctx.current_node,
                        }],
                        "stats": {
                            "before_tokens_estimated": input_tokens,
                            "after_tokens_estimated": _estimate_tokens(messages),
                            "threshold": threshold,
                        },
                    })
            output_var = node.get("output_var", "context_messages")
            self.ctx.data[output_var] = messages
            self.ctx.data[node.get("compacted_var", "context_compacted")] = compacted
            return NodeOutcome(
                {
                    "messages": messages,
                    "summary": summary,
                    "compacted": compacted,
                    "input_tokens_estimated": input_tokens,
                    "compaction_threshold": threshold,
                    "value": messages,
                },
                ["context_compacted" if compacted else "context_unchanged", "context_ready"],
            )
        if action == "last_n_observations":
            n = max(1, int(node.get("observation_last_n", node.get("last_n", 5))))
            polling = max(1, int(node.get("polling", 1)))
            observation_indices = [
                index
                for index, message in enumerate(messages)
                if message.get("message_type") == "observation"
                or message.get("role") == "tool"
                or (
                    message.get("role") == "user"
                    and message.get("name") not in {"dag_instruction"}
                )
            ]
            last_removed_index = max(0, (len(observation_indices) // polling) * polling - n)
            # As in SWE-agent, the first observation is the instance prompt and
            # is never elided.
            omit = set(observation_indices[1:last_removed_index])
            for index in omit:
                content = str(messages[index].get("content", ""))
                line_count = len(content.splitlines())
                messages[index]["content"] = f"Old environment output: ({line_count} lines omitted)"
                messages[index]["elided"] = True
            elided_observations = len(omit)
        else:
            last_n = node.get("last_n")
            if last_n is not None:
                messages = messages[-max(0, int(last_n)):]

        max_chars = node.get("max_chars")
        if max_chars is not None and int(max_chars) >= 0:
            kept: list[dict[str, Any]] = []
            used = 0
            for message in reversed(messages):
                size = len(str(message.get("content", "")))
                if kept and used + size > int(max_chars):
                    break
                kept.append(message)
                used += size
            messages = list(reversed(kept))

        summary = None
        if action == "compact" and len(messages) > int(node.get("keep_last", 6)):
            keep_last = max(0, int(node.get("keep_last", 6)))
            older = messages[:-keep_last] if keep_last else messages
            recent = messages[-keep_last:] if keep_last else []
            if node.get("summarize", True) and older:
                agent = self._node_agent(node, inputs)
                template = self.ctx.harness.prompts.get(
                    node.get("prompt"),
                    "Compress the following history into a concise factual memory. Preserve decisions, constraints, file paths, tool results, and unresolved work.\n\n{history}",
                )
                prompt = _format_prompt(template, {**self.ctx.data, **inputs, "history": json.dumps(older, ensure_ascii=False)})
                self._before_model_call()
                summary = _standalone_llm_call(
                    prompt,
                    self.ctx.harness,
                    agent=agent,
                    max_tokens=int(node.get("max_tokens", 1024)),
                    temperature=float(node.get("temperature", 0.2)),
                    purpose="context_compactor",
                )
                self._record_model_usage(_estimate_tokens(prompt), _estimate_tokens(summary))
                self._record_provider_usage(agent)
            else:
                summary = "\n".join(str(message.get("content", "")) for message in older)
            messages = ([{"role": "system", "name": "context_summary", "content": summary}] if summary else []) + recent

        output_var = node.get("output_var", "context_messages")
        self.ctx.data[output_var] = messages
        return NodeOutcome(
            {
                "messages": messages,
                "summary": summary,
                "elided_observations": elided_observations,
                "value": messages,
            },
            ["context_ready"],
        )

    def _conversation_snapshot_node(self, node: dict, inputs: dict) -> NodeOutcome:
        """Expose an immutable, model-friendly conversation snapshot.

        This is deliberately a data adapter, not a summarizer.  It partitions
        messages into stable turns and protocol-safe blocks and optionally
        computes a declared pressure budget.  The DAG decides what to do with
        that metadata.
        """

        from context_policy import (
            content_text,
            context_blocks,
            conversation_turns,
            estimate_tokens,
            pressure_budget,
            review_batch,
        )

        session = self.ctx.harness.session
        working_source = inputs.get("messages")
        if working_source is None:
            working_source = resolve_reference(node.get("source", "$session.messages"), self.ctx)
        full_source = inputs.get("full_messages")
        if full_source is None:
            full_source = resolve_reference(node.get("full_source", "$session.full_messages"), self.ctx)
        if not isinstance(working_source, list):
            raise PipelineError("Conversation snapshot messages must be a list")
        if not isinstance(full_source, list):
            raise PipelineError("Conversation snapshot full_messages must be a list")

        working = copy.deepcopy(working_source)
        full = copy.deepcopy(full_source or working_source)
        protect_recent = max(
            1,
            int(resolve_reference(node.get("protect_recent_turns", 2), self.ctx)),
        )
        turns = conversation_turns(full)
        blocks = context_blocks(working, protect_recent_turns=protect_recent)
        governance = session.state.get("context_governance", {})
        if not isinstance(governance, dict):
            governance = {}
        reviewed = set(governance.get("reviewed_turn_ids", []))
        raw_interval = resolve_reference(node.get("review_interval", 0), self.ctx)
        interval = max(0, int(raw_interval or 0))
        due_turns = (
            review_batch(full, reviewed, interval=interval, protect_recent=protect_recent)
            if interval
            else []
        )

        current_task = ""
        for message in reversed(full):
            if message.get("role") == "user" and "<tool_response>" not in content_text(message):
                current_task = content_text(message)
                break

        pressure = {
            "configured": False,
            "triggered": False,
            "message_tokens_estimated": estimate_tokens(working),
        }
        raw_limit = inputs.get(
            "context_limit_tokens",
            resolve_reference(node.get("context_limit_tokens"), self.ctx),
        )
        if raw_limit not in (None, "", 0, "0"):
            pressure = {
                "configured": True,
                **pressure_budget(
                    working,
                    context_limit_tokens=int(raw_limit),
                    high_watermark=float(resolve_reference(node.get("high_watermark", 0.82), self.ctx)),
                    target_ratio=float(resolve_reference(node.get("target_ratio", 0.62), self.ctx)),
                    reserved_output_tokens=int(
                        resolve_reference(node.get("reserved_output_tokens", 4096), self.ctx)
                    ),
                    extra_input_tokens=int(
                        resolve_reference(node.get("extra_input_tokens", 0), self.ctx)
                    ),
                ),
            }

        usage_summary = None
        if bool(resolve_reference(node.get("include_usage", False), self.ctx)):
            # Evolution and governance components need observed cost rather
            # than a language model's guess about how expensive prior work
            # was.  Read only compact usage fields from the durable trajectory;
            # no message or tool payload is copied into this summary.
            usage_summary = {
                "source": "current_run",
                "model_calls": int(self.ctx.stats.model_calls),
                "tool_calls": int(self.ctx.stats.tool_calls),
                "input_tokens_actual": int(self.ctx.stats.input_tokens_actual),
                "cached_input_tokens_actual": int(self.ctx.stats.cached_input_tokens_actual),
                "output_tokens_actual": int(self.ctx.stats.output_tokens_actual),
                "tokens_actual": int(self.ctx.stats.input_tokens_actual + self.ctx.stats.output_tokens_actual),
                "by_harness": {},
            }
            native_path = getattr(getattr(session, "trajectory", None), "native_path", None)
            if native_path:
                try:
                    from trajectory import TrajectoryReader

                    seen_calls: set[str] = set()
                    model_calls = 0
                    tool_calls = 0
                    input_tokens = 0
                    cached_tokens = 0
                    output_tokens = 0
                    first_timestamp = None
                    last_timestamp = None
                    by_harness: dict[str, dict[str, int]] = {}
                    for event in TrajectoryReader(native_path).iter_events(strict=False) or []:
                        timestamp = event.get("timestamp")
                        if isinstance(timestamp, (int, float)):
                            first_timestamp = timestamp if first_timestamp is None else min(first_timestamp, timestamp)
                            last_timestamp = timestamp if last_timestamp is None else max(last_timestamp, timestamp)
                        event_type = str(event.get("type") or "")
                        if event_type == "tool.result":
                            tool_calls += 1
                            continue
                        if event_type != "model.response":
                            continue
                        call_id = str(event.get("model_call_id") or event.get("event_id") or "")
                        if call_id in seen_calls:
                            continue
                        seen_calls.add(call_id)
                        model_calls += 1
                        payload = event.get("data") if isinstance(event.get("data"), dict) else {}
                        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
                        prompt_tokens = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
                        completion_tokens = int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0)
                        details = usage.get("prompt_tokens_details", usage.get("input_tokens_details", {})) or {}
                        cached = int(
                            details.get(
                                "cached_tokens",
                                usage.get("cached_tokens", usage.get("cache_read_input_tokens", 0)),
                            )
                            or 0
                        )
                        input_tokens += max(0, prompt_tokens)
                        output_tokens += max(0, completion_tokens)
                        cached_tokens += min(max(0, cached), max(0, prompt_tokens))
                        harness_name = str(event.get("harness") or "unknown")
                        bucket = by_harness.setdefault(
                            harness_name,
                            {"model_calls": 0, "input_tokens": 0, "output_tokens": 0},
                        )
                        bucket["model_calls"] += 1
                        bucket["input_tokens"] += max(0, prompt_tokens)
                        bucket["output_tokens"] += max(0, completion_tokens)
                    usage_summary = {
                        "source": "session_trajectory",
                        "model_calls": model_calls,
                        "tool_calls": tool_calls,
                        "input_tokens_actual": input_tokens,
                        "cached_input_tokens_actual": cached_tokens,
                        "uncached_input_tokens_actual": max(0, input_tokens - cached_tokens),
                        "output_tokens_actual": output_tokens,
                        "tokens_actual": input_tokens + output_tokens,
                        "elapsed_seconds": round(max(0.0, float(last_timestamp or 0) - float(first_timestamp or 0)), 3),
                        "by_harness": dict(
                            sorted(
                                by_harness.items(),
                                key=lambda item: item[1]["input_tokens"] + item[1]["output_tokens"],
                                reverse=True,
                            )[:12]
                        ),
                    }
                except (OSError, TypeError, ValueError):
                    # The current-run counters remain valid when durable trace
                    # reading is unavailable. Snapshot must stay non-mutating.
                    pass

        snapshot = {
            "version": 1,
            "working_messages": working,
            "full_messages": full,
            "message_count": len(working),
            "full_message_count": len(full),
            "turn_count": len(turns),
            "turns": [turn.preview(max_chars=int(node.get("turn_preview_chars", 2400))) for turn in turns],
            "review_batch": [turn.preview(max_chars=int(node.get("turn_preview_chars", 2400))) for turn in due_turns],
            "review_turn_ids": [turn.id for turn in due_turns],
            "review_triggered": bool(due_turns),
            "blocks": [block.preview(max_chars=int(node.get("block_preview_chars", 3200))) for block in blocks],
            "pressure": pressure,
            "usage": usage_summary,
            "current_task": current_task,
            "governance": copy.deepcopy(governance),
        }
        # Model prompts can consume this field directly without relying on the
        # language-specific string representation of Python/JavaScript objects.
        snapshot["model_payload"] = json.dumps(
            {
                "current_task": current_task,
                "review_batch": snapshot["review_batch"],
                "blocks": snapshot["blocks"],
                "pressure": pressure,
                "usage": usage_summary,
            },
            ensure_ascii=False,
        )
        output_var = node.get("output_var", "conversation_snapshot")
        if output_var:
            set_path(self.ctx.data, output_var, copy.deepcopy(snapshot))
        self.ctx.emit(
            "conversation_snapshot",
            {
                "messages": len(working),
                "turns": len(turns),
                "review_due": len(due_turns),
                "pressure": pressure,
                "usage": usage_summary,
            },
        )
        tags = ["conversation_ready"]
        tags.append("review_due" if due_turns else "review_not_due")
        tags.append("pressure_due" if pressure.get("triggered") else "pressure_ok")
        return NodeOutcome({"value": snapshot, **snapshot}, tags)

    def _conversation_apply_node(self, node: dict, inputs: dict) -> NodeOutcome:
        """Validate and commit a model-authored working-context transformation."""

        from context_policy import (
            apply_context_decisions,
            apply_pressure_compaction,
            apply_tool_result_pruning,
            restore_full_context,
        )

        session = self.ctx.harness.session
        mode = str(inputs.get("mode", node.get("apply_mode", "turn_plan"))).casefold()
        raw_plan = inputs.get("plan", resolve_reference(node.get("plan", {}), self.ctx))
        plan = raw_plan if isinstance(raw_plan, dict) else {}
        protect_recent = max(
            1,
            int(resolve_reference(node.get("protect_recent_turns", 2), self.ctx)),
        )
        working = inputs.get("messages")
        if working is None:
            working = resolve_reference(node.get("source", "$session.messages"), self.ctx)
        full = inputs.get("full_messages")
        if full is None:
            full = resolve_reference(node.get("full_source", "$session.full_messages"), self.ctx)
        if not isinstance(working, list) or not isinstance(full, list):
            raise PipelineError("Conversation apply requires message arrays")
        full = copy.deepcopy(full or working)
        working = copy.deepcopy(working)

        if mode in {"turn_plan", "turns", "curate"}:
            raw_decisions = plan.get("decisions", [])
            if not isinstance(raw_decisions, list):
                raise PipelineError("Conversation turn plan decisions must be a list")
            governance = session.state.get("context_governance", {})
            previous_ledger = governance.get("ledger", []) if isinstance(governance, dict) else []
            decisions = {
                str(item.get("turn_id")): {
                    "turn_id": item.get("turn_id"),
                    "action": item.get("action", "keep"),
                    "reason": item.get("reason", "previous_context_decision"),
                    "summary": item.get("summary", ""),
                }
                for item in previous_ledger
                if isinstance(item, dict) and item.get("turn_id")
            }
            decisions.update(
                {
                    str(item.get("turn_id")): copy.deepcopy(item)
                    for item in raw_decisions
                    if isinstance(item, dict) and item.get("turn_id")
                }
            )
            result = apply_context_decisions(
                full,
                decisions.values(),
                protect_recent=protect_recent,
                max_tool_chars=max(
                    0,
                    int(resolve_reference(node.get("max_tool_chars", 1800), self.ctx)),
                ),
            )
            reviewed = set(governance.get("reviewed_turn_ids", [])) if isinstance(governance, dict) else set()
            declared_reviewed = inputs.get(
                "reviewed_turn_ids",
                resolve_reference(node.get("reviewed_turn_ids", []), self.ctx),
            )
            if isinstance(declared_reviewed, list):
                reviewed.update(str(value) for value in declared_reviewed)
            reviewed.update(
                str(item.get("turn_id"))
                for item in raw_decisions
                if isinstance(item, dict) and item.get("turn_id")
            )
            result["reviewed_turn_ids"] = sorted(reviewed)
            tags = ["conversation_applied", "turn_plan_applied"]
        elif mode in {"block_plan", "blocks", "compact"}:
            if not isinstance(raw_plan, dict):
                raise PipelineError("Conversation block plan must be an object")
            raw_target = inputs.get(
                "target_tokens",
                resolve_reference(node.get("target_tokens"), self.ctx),
            )
            if raw_target in (None, "", 0, "0"):
                raise PipelineError("Conversation block plan requires target_tokens")
            result = apply_pressure_compaction(
                working,
                plan,
                target_tokens=max(1, int(raw_target)),
                protect_recent_turns=protect_recent,
                full_messages=full,
                minimum_savings_tokens=max(
                    0,
                    int(resolve_reference(node.get("minimum_savings_tokens", 0), self.ctx) or 0),
                ),
            )
            tags = ["conversation_applied", "block_plan_applied"]
        elif mode in {"tool_prune", "prune_tool_results"}:
            governance = session.state.get("context_governance", {})
            previous_ledger = governance.get("ledger", []) if isinstance(governance, dict) else []
            result = apply_tool_result_pruning(
                working,
                full,
                threshold_chars=int(resolve_reference(node.get("threshold_chars", 8192), self.ctx)),
                head_chars=int(resolve_reference(node.get("head_chars", 4096), self.ctx)),
                tail_chars=int(resolve_reference(node.get("tail_chars", 1024), self.ctx)),
                previous_ledger=previous_ledger,
            )
            tags = ["conversation_applied", "tool_results_pruned"]
        elif mode in {"restore", "restore_full"}:
            restored = restore_full_context(full)
            result = {
                "messages": restored,
                "full_messages": copy.deepcopy(restored),
                "ledger": [],
                "stats": {
                    "before_tokens_estimated": _estimate_messages_tokens(restored),
                    "after_tokens_estimated": _estimate_messages_tokens(restored),
                    "saved_tokens_estimated": 0,
                    "reduction_ratio": 0,
                },
            }
            tags = ["conversation_applied", "context_restored"]
        else:
            raise PipelineError(f"unknown Conversation apply mode: {mode}")

        if node.get("persist_session", True):
            session.apply_context_result(result)
            with session._lock:
                governance = session.state.setdefault("context_governance", {})
                if "reviewed_turn_ids" in result:
                    governance["reviewed_turn_ids"] = copy.deepcopy(result["reviewed_turn_ids"])
                governance["last_component"] = str(node.get("component_name", "conversation_apply"))
                governance["last_mode"] = mode
            session.save()
        output_var = node.get("output_var", "conversation_result")
        if output_var:
            set_path(self.ctx.data, output_var, copy.deepcopy(result))
        self.ctx.emit(
            "conversation_applied",
            {"mode": mode, **copy.deepcopy(result.get("stats", {}))},
        )
        return NodeOutcome({"value": result, **result}, tags)

    def _memory_node(self, node: dict, inputs: dict) -> NodeOutcome:
        """Persistent episodic/semantic/skill memory with deterministic retrieval."""
        namespace = str(resolve_reference(node.get("namespace", "default"), self.ctx))
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", namespace):
            raise PipelineError("Memory namespace may contain only letters, numbers, dot, dash and underscore")
        requested = node.get("path", f".egoagent/memory/{namespace}.json")
        path = self._safe_runtime_path(requested)
        action = node.get("action", "search")
        lock = _memory_lock(path)
        with lock:
            store = self._load_memory(path)
            items = store["items"]
            now = time.time()

            if action in {"add", "add_unique", "upsert"}:
                raw = inputs.get("memory", inputs.get("value", resolve_reference(node.get("value"), self.ctx)))
                payload = copy.deepcopy(raw) if isinstance(raw, dict) else {"text": str(raw or "")}
                text_value = str(payload.get("text", payload.get("content", ""))).strip()
                if not text_value:
                    raise PipelineError(f"Memory {action} requires non-empty text")
                created_at = payload.get("created_at")
                last_accessed = payload.get("last_accessed")
                access_count = payload.get("access_count")
                importance_value = payload.get("importance")
                if importance_value is None:
                    importance_value = inputs.get("importance", node.get("importance", 1.0))
                item = {
                    "id": str(payload.get("id") or uuid.uuid4().hex),
                    "type": str(payload.get("type", node.get("memory_type", "episodic"))),
                    "text": text_value,
                    "created_at": float(now if created_at is None else created_at),
                    "last_accessed": float(now if last_accessed is None else last_accessed),
                    "access_count": int(0 if access_count is None else access_count),
                    "importance": float(1.0 if importance_value is None else importance_value),
                    "keywords": list(payload.get("keywords", inputs.get("keywords", node.get("keywords", []))) or []),
                    "metadata": payload.get("metadata", inputs.get("metadata", resolve_reference(node.get("metadata", {}), self.ctx))) or {},
                    "evidence": payload.get("evidence", inputs.get("evidence", resolve_reference(node.get("evidence", []), self.ctx))) or [],
                }
                if action == "add_unique":
                    retention = max(0, int(inputs.get("retention", node.get("retention", 5))))
                    dedupe_key = str(inputs.get("dedupe_key", node.get("dedupe_key", "text")) or "text")
                    incoming_key = _nested_value(item, dedupe_key)
                    recent = [candidate for candidate in items if candidate.get("type") == item.get("type")]
                    duplicate = next(
                        (
                            candidate
                            for candidate in reversed(recent[-retention:] if retention else [])
                            if _nested_value(candidate, dedupe_key) == incoming_key
                        ),
                        None,
                    )
                    if duplicate is not None:
                        result = copy.deepcopy(duplicate)
                        tags = ["memory_duplicate"]
                    else:
                        items.append(item)
                        self._save_memory(path, store)
                        result = item
                        tags = ["memory_added"]
                elif action == "upsert":
                    upsert_key = str(inputs.get("upsert_key", node.get("upsert_key", "id")) or "id")
                    incoming_key = _nested_value(item, upsert_key)
                    if incoming_key in (None, ""):
                        raise PipelineError(f"Memory upsert requires a non-empty {upsert_key}")
                    match_index = next(
                        (
                            index
                            for index, candidate in enumerate(items)
                            if candidate.get("type") == item.get("type")
                            and _nested_value(candidate, upsert_key) == incoming_key
                        ),
                        None,
                    )
                    if match_index is None:
                        items.append(item)
                        tags = ["memory_added"]
                    else:
                        previous = items[match_index]
                        item["created_at"] = float(previous.get("created_at") or item["created_at"])
                        item["access_count"] = int(previous.get("access_count") or item["access_count"])
                        items[match_index] = item
                        tags = ["memory_updated"]
                    self._save_memory(path, store)
                    result = item
                else:
                    items.append(item)
                    self._save_memory(path, store)
                    result = item
                    tags = ["memory_added"]
            elif action == "search":
                query = str(inputs.get("query", resolve_reference(node.get("query", ""), self.ctx)) or "")
                memory_type = inputs.get("type", node.get("memory_type"))
                candidates = [item for item in items if not memory_type or item.get("type") == memory_type]
                query_tokens = _memory_tokens(query)
                scored = []
                weights = node.get("weights", {})
                relevance_w = float(weights.get("relevance", 3.0))
                recency_w = float(weights.get("recency", 0.5))
                importance_w = float(weights.get("importance", 2.0))
                minimum_overlap = max(0, int(inputs.get("minimum_overlap", node.get("minimum_overlap", 0))))
                minimum_relevance = max(0.0, float(inputs.get("minimum_relevance", node.get("minimum_relevance", 0.0))))
                minimum_score = float(inputs.get("minimum_score", node.get("minimum_score", float("-inf"))))
                half_life = max(1.0, float(node.get("recency_half_life_seconds", 86400)))
                for item in candidates:
                    item_tokens = _memory_tokens(item.get("text", "") + " " + " ".join(item.get("keywords", [])))
                    overlap = len(query_tokens & item_tokens)
                    relevance = overlap / max(1.0, (len(query_tokens) * len(item_tokens)) ** 0.5) if query_tokens else 0.0
                    age = max(0.0, now - float(item.get("last_accessed") or item.get("created_at") or now))
                    recency = 0.5 ** (age / half_life)
                    importance = max(0.0, min(float(item.get("importance") or 0.0) / 10.0, 1.0))
                    score = relevance_w * relevance + recency_w * recency + importance_w * importance
                    if overlap < minimum_overlap or relevance < minimum_relevance or score < minimum_score:
                        continue
                    scored.append((score, item))
                scored.sort(key=lambda pair: (pair[0], pair[1].get("created_at", 0)), reverse=True)
                result = []
                for score, item in scored[:max(0, int(node.get("top_k", 8)))]:
                    item["last_accessed"] = now
                    item["access_count"] = int(item.get("access_count", 0)) + 1
                    result.append({**copy.deepcopy(item), "score": round(score, 6)})
                self._save_memory(path, store)
                tags = ["memory_found" if result else "memory_empty"]
            elif action == "list":
                memory_type = inputs.get("type", node.get("memory_type"))
                listed = [item for item in items if not memory_type or item.get("type") == memory_type]
                result = copy.deepcopy(listed[-max(0, int(node.get("top_k", 100))):])
                tags = ["memory_found" if result else "memory_empty"]
            elif action == "delete":
                memory_id = str(inputs.get("memory_id", node.get("memory_id", "")))
                before = len(items)
                store["items"] = [item for item in items if item.get("id") != memory_id]
                result = len(store["items"]) != before
                self._save_memory(path, store)
                tags = ["memory_deleted" if result else "memory_missing"]
            elif action == "clear":
                count = len(items)
                store = {"version": 1, "items": [], "reflection_cursor": 0}
                self._save_memory(path, store)
                result = count
                tags = ["memory_cleared"]
            elif action == "needs_reflection":
                cursor = max(0, int(store.get("reflection_cursor", 0)))
                importance_sum = sum(float(item.get("importance") or 0.0) for item in items[cursor:])
                threshold = float(inputs.get("threshold", node.get("threshold", 20.0)))
                due = bool(items[cursor:]) and importance_sum >= threshold
                result = {"due": due, "importance": importance_sum, "count": len(items) - cursor}
                tags = ["reflection_due" if due else "reflection_not_due"]
            elif action == "mark_reflected":
                store["reflection_cursor"] = len(items)
                self._save_memory(path, store)
                result = store["reflection_cursor"]
                tags = ["reflection_marked"]
            else:
                raise PipelineError(f"unknown Memory action: {action}")

        output_var = node.get("output_var", "memory_result")
        if output_var:
            set_path(self.ctx.data, output_var, copy.deepcopy(result))
        self.ctx.emit("memory", {"action": action, "namespace": namespace, "count": len(store.get("items", []))})
        return NodeOutcome({"value": result, "items": result if isinstance(result, list) else None, "path": str(path)}, tags)

    @staticmethod
    def _capability_id_from_evidence(value: Any) -> Optional[str]:
        """Extract a successful activation ID from a Tool-node observation.

        Capability discovery normally runs in an isolated SubFlow.  Its raw
        activation observation is deliberately passed through a typed port so
        the parent can activate the same item on its own Agent instance.  This
        parser accepts the native Tool-node envelope but does not infer IDs
        from arbitrary prose.
        """

        if isinstance(value, str):
            text = value.strip()
            if not text.startswith(("{", "[")):
                return None
            try:
                return PipelineRunner._capability_id_from_evidence(json.loads(text))
            except (TypeError, ValueError):
                return None
        if isinstance(value, list):
            for item in value:
                found = PipelineRunner._capability_id_from_evidence(item)
                if found:
                    return found
            return None
        if not isinstance(value, dict):
            return None

        tool_name = str(value.get("name") or value.get("tool") or "").split(":")[-1]
        if tool_name == "activate_capability" and "result" in value:
            return PipelineRunner._capability_id_from_evidence(value.get("result"))
        if value.get("ok") is True:
            capability_id = value.get("id") or value.get("capability_id")
            if isinstance(capability_id, str) and capability_id.strip():
                return capability_id.strip()
        return None

    @staticmethod
    def _capability_path_from_mutation_evidence(value: Any) -> Optional[str]:
        """Extract a persisted capability path from successful Tool evidence."""

        if isinstance(value, str):
            text = value.strip()
            if not text.startswith(("{", "[")):
                return None
            try:
                return PipelineRunner._capability_path_from_mutation_evidence(json.loads(text))
            except (TypeError, ValueError):
                return None
        if isinstance(value, list):
            for item in value:
                found = PipelineRunner._capability_path_from_mutation_evidence(item)
                if found:
                    return found
            return None
        if not isinstance(value, dict):
            return None

        tool_name = str(value.get("name") or value.get("tool") or "").split(":")[-1]
        if tool_name in {
            "create_skill", "create_knowledge", "create_agent_system",
            "create_harness", "manage_harness",
        } and "result" in value:
            return PipelineRunner._capability_path_from_mutation_evidence(value.get("result"))
        if value.get("ok") is True:
            path = value.get("path")
            if isinstance(path, str) and path.strip():
                return path.strip()
        return None

    @staticmethod
    def _capability_search_from_evidence(value: Any) -> Optional[dict[str, Any]]:
        """Extract an actual search_capabilities result, never model prose."""

        if isinstance(value, str):
            text = value.strip()
            if not text.startswith(("{", "[")):
                return None
            try:
                return PipelineRunner._capability_search_from_evidence(json.loads(text))
            except (TypeError, ValueError):
                return None
        if isinstance(value, list):
            for item in value:
                found = PipelineRunner._capability_search_from_evidence(item)
                if found:
                    return found
            return None
        if not isinstance(value, dict):
            return None

        tool_name = str(value.get("name") or value.get("tool") or "").split(":")[-1]
        if tool_name == "search_capabilities" and "result" in value:
            return PipelineRunner._capability_search_from_evidence(value.get("result"))
        results = value.get("results")
        if isinstance(value.get("query"), str) and isinstance(results, list):
            if not results or all(isinstance(item, dict) and "id" in item for item in results):
                return value
        if isinstance(results, list):
            return PipelineRunner._capability_search_from_evidence(results)
        return None

    def _capability_node(self, node: dict, inputs: dict) -> NodeOutcome:
        """Declarative capability search/activation without an LLM round trip."""

        from capability_registry import CapabilityRegistry
        from config import CONFIG

        action = str(node.get("action", "search") or "search").strip().casefold().replace("-", "_")
        agent = self._node_agent(
            node,
            inputs,
            required=action not in {"search", "list", "quarantine_from_evidence", "quarantine_evidence"},
        )
        workspace = Path(self.ctx.harness.workspace or self.ctx.harness.dir).resolve()
        registry = CapabilityRegistry(Path(__file__).resolve().parent, workspace=workspace)
        registry.reindex()

        if action in {"quarantine_from_evidence", "quarantine_evidence"}:
            source = inputs.get("source", resolve_reference(node.get("source"), self.ctx))
            mutation_path = self._capability_path_from_mutation_evidence(source)
            if not mutation_path:
                result = {"ok": False, "status": "not_found", "message": "No successful capability mutation evidence."}
                output_var = node.get("output_var", "capability_result")
                if output_var:
                    set_path(self.ctx.data, output_var, copy.deepcopy(result))
                return NodeOutcome({"value": result}, ["not_found"])

            candidate = Path(mutation_path)
            if not candidate.is_absolute():
                candidate = (Path(__file__).resolve().parent / candidate).resolve()
            else:
                candidate = candidate.resolve()
            identity_root = Path(CONFIG["identity_repository"]).resolve()
            try:
                relative = candidate.relative_to(identity_root)
            except ValueError as error:
                raise PipelineError("Capability quarantine path is outside the Identity repository") from error
            parts = relative.parts
            if len(parts) != 4 or parts[1] != "ego" or parts[2] not in {"skills", "tools", "knowledge"}:
                raise PipelineError("Capability quarantine only accepts one persisted Identity capability directory")
            if not candidate.is_dir():
                result = {"ok": False, "status": "not_found", "message": "Persisted capability directory no longer exists."}
                output_var = node.get("output_var", "capability_result")
                if output_var:
                    set_path(self.ctx.data, output_var, copy.deepcopy(result))
                return NodeOutcome({"value": result}, ["not_found"])

            quarantine_root = identity_root / parts[0] / "ego" / ".quarantine" / parts[2]
            quarantine_root.mkdir(parents=True, exist_ok=True)
            target = quarantine_root / f"{parts[3]}.{int(time.time())}.{uuid.uuid4().hex[:8]}"
            os.replace(candidate, target)
            registry.reindex()
            result = {
                "ok": True,
                "status": "quarantined",
                "original_path": str(candidate),
                "quarantine_path": str(target),
                "reason": str(inputs.get("reason", resolve_reference(node.get("reason", "verification failed"), self.ctx))),
            }
            output_var = node.get("output_var", "capability_result")
            if output_var:
                set_path(self.ctx.data, output_var, copy.deepcopy(result))
            self.ctx.emit(
                "capability_quarantined",
                {"original_path": str(candidate), "quarantine_path": str(target), "reason": result["reason"]},
            )
            return NodeOutcome({"value": result, "quarantine": result}, ["quarantined"])

        ranked_evidence_actions = {"activate_best_from_search_evidence", "activate_search_evidence"}
        if action in {"search", "list", "search_and_activate", "search_activate_best"} | ranked_evidence_actions:
            if action in ranked_evidence_actions:
                source = inputs.get("source", resolve_reference(node.get("source"), self.ctx))
                search_result = self._capability_search_from_evidence(source)
                if search_result is None:
                    result = {"ok": False, "status": "not_found", "message": "No structured capability-search evidence."}
                    output_var = node.get("output_var", "capability_result")
                    if output_var:
                        set_path(self.ctx.data, output_var, copy.deepcopy(result))
                    return NodeOutcome({"value": result, "results": [], "activation": result}, ["not_found"])
                query = str(search_result.get("query") or "")
            else:
                query = str(inputs.get("query", resolve_reference(node.get("query", ""), self.ctx)) or "")
                kinds = inputs.get("kinds", resolve_reference(node.get("kinds", []), self.ctx))
                if not isinstance(kinds, list):
                    kinds = [kinds] if kinds else []
                search_result = registry.search(
                    query,
                    kinds=[str(kind) for kind in kinds],
                    limit=max(1, int(inputs.get("top_k", node.get("top_k", 8)))),
                    record_impressions=bool(node.get("record_impressions", True)),
                    mode=str(node.get("mode", "auto")),
                )
            results = search_result.get("results", []) if isinstance(search_result, dict) else []

            if action in {"search_and_activate", "search_activate_best"} | ranked_evidence_actions:
                top = results[0] if results else {}
                second = results[1] if len(results) > 1 else {}
                score = float(top.get("score") or 0)
                second_score = float(second.get("score") or 0)
                lexical = float(top.get("lexical_score") or 0)
                semantic = float(top.get("semantic_score") or 0)
                coverage = float(top.get("query_coverage") or 0)
                second_semantic = float(second.get("semantic_score") or 0)
                second_coverage = float(second.get("query_coverage") or 0)
                min_score = float(node.get("min_score", 2.5))
                min_margin = float(node.get("min_margin", 0.7))
                min_coverage = float(node.get("min_query_coverage", 0.6))
                min_lexical = float(node.get("min_lexical_score", 6.0))
                min_semantic = float(node.get("min_semantic_score", 0.55))
                strong_semantic = float(node.get("strong_semantic_score", 0.68))
                contrastive_match = (
                    semantic - second_semantic >= float(node.get("min_semantic_margin", 0.12))
                    and coverage - second_coverage >= float(node.get("min_coverage_margin", 0.2))
                    and coverage >= min_coverage
                    and lexical >= min_lexical
                )
                unambiguous = bool(top) and score >= min_score and (
                    score - second_score >= min_margin or contrastive_match
                )
                # Coverage is diluted by long natural-language task prompts.
                # A strong dense match plus strong lexical evidence may
                # override it, but semantic similarity alone never activates
                # executable code.
                relevant = (
                    coverage >= min_coverage and lexical >= min_lexical and semantic >= min_semantic
                ) or (
                    semantic >= strong_semantic and lexical >= min_lexical
                )
                if unambiguous and relevant:
                    capability_id = str(top.get("id") or "")
                    activation = agent.activate_capability(capability_id, registry=registry)
                    if activation.get("ok"):
                        registry.record_event(capability_id, "activate")
                    result = {
                        **activation,
                        "selection": {
                            "method": "deterministic_high_confidence",
                            "score": score,
                            "margin": round(score - second_score, 6),
                            "query_coverage": coverage,
                            "lexical_score": lexical,
                            "semantic_score": semantic,
                            "semantic_margin": round(semantic - second_semantic, 6),
                            "query_coverage_margin": round(coverage - second_coverage, 6),
                            "strong_semantic_score": strong_semantic,
                        },
                        "search": search_result,
                    }
                    output_var = node.get("output_var", "capability_result")
                    if output_var:
                        set_path(self.ctx.data, output_var, copy.deepcopy(result))
                    event = "capability_activated" if activation.get("ok") else "capability_activation_error"
                    self.ctx.emit(event, {"agent": getattr(agent, "name", ""), "capability_id": capability_id, "selection": result["selection"]})
                    return NodeOutcome(
                        {"value": result, "results": results, "activation": result},
                        ["activated" if activation.get("ok") else "error"],
                    )
                result = {
                    "ok": False,
                    "status": "not_found",
                    "message": "No unambiguous high-confidence catalog match; model selection is required.",
                    "selection": {
                        "score": score,
                        "margin": round(score - second_score, 6),
                        "query_coverage": coverage,
                        "lexical_score": lexical,
                        "semantic_score": semantic,
                        "semantic_margin": round(semantic - second_semantic, 6),
                        "query_coverage_margin": round(coverage - second_coverage, 6),
                    },
                    "search": search_result,
                }
                output_var = node.get("output_var", "capability_result")
                if output_var:
                    set_path(self.ctx.data, output_var, copy.deepcopy(result))
                self.ctx.emit("capability_match_ambiguous", {"query": query, "selection": result["selection"]})
                return NodeOutcome({"value": result, "results": results, "activation": result}, ["not_found"])

            result = search_result
            output_var = node.get("output_var", "capability_result")
            if output_var:
                set_path(self.ctx.data, output_var, copy.deepcopy(result))
            self.ctx.emit("capability_search", {"query": query, "count": len(results)})
            return NodeOutcome({"value": result, "results": results}, ["found" if results else "not_found"])

        if action in {"activate_from_evidence", "activate_evidence"}:
            source = inputs.get("source", resolve_reference(node.get("source"), self.ctx))
            capability_id = self._capability_id_from_evidence(source)
            if not capability_id:
                mutation_path = self._capability_path_from_mutation_evidence(source)
                if mutation_path:
                    item = registry.find_by_path(mutation_path)
                    capability_id = str((item or {}).get("id") or "").strip() or None
        elif action == "activate":
            capability_id = inputs.get(
                "capability_id",
                resolve_reference(node.get("capability_id", node.get("id", "")), self.ctx),
            )
            capability_id = str(capability_id or "").strip() or None
        else:
            raise PipelineError(f"unknown Capability action: {action}")

        if not capability_id:
            result = {"ok": False, "status": "not_found", "message": "No successful capability activation evidence."}
            output_var = node.get("output_var", "capability_result")
            if output_var:
                set_path(self.ctx.data, output_var, copy.deepcopy(result))
            self.ctx.emit("capability_activation_skipped", {"agent": getattr(agent, "name", "")})
            return NodeOutcome({"value": result, "activation": result}, ["not_found"])

        result = agent.activate_capability(capability_id, registry=registry)
        if result.get("ok"):
            registry.record_event(capability_id, "activate")
        output_var = node.get("output_var", "capability_result")
        if output_var:
            set_path(self.ctx.data, output_var, copy.deepcopy(result))
        self.ctx.emit(
            "capability_activated" if result.get("ok") else "capability_activation_error",
            {"agent": getattr(agent, "name", ""), "capability_id": capability_id, "result": _preview_value(result)},
        )
        return NodeOutcome(
            {"value": result, "activation": result},
            ["activated" if result.get("ok") else "error"],
        )

    def _load_memory(self, path: Path) -> dict:
        if not path.exists():
            return {"version": 1, "items": [], "reflection_cursor": 0}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise PipelineError(f"cannot read memory file {path}: {error}") from error
        if not isinstance(value, dict) or not isinstance(value.get("items", []), list):
            raise PipelineError("memory file must contain an object with an items list")
        value.setdefault("version", 1)
        value.setdefault("items", [])
        value.setdefault("reflection_cursor", 0)
        return value

    @staticmethod
    def _save_memory(path: Path, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            for attempt in range(5):
                try:
                    temporary.replace(path)
                    return
                except PermissionError:
                    if attempt == 4:
                        raise
                    time.sleep(0.02 * (attempt + 1))
        finally:
            if temporary.exists():
                try:
                    temporary.unlink()
                except OSError:
                    pass

    def _condition_node(self, node: dict, inputs: dict) -> NodeOutcome:
        expression = node.get("condition", node.get("expression"))
        if expression is None and "value" in inputs:
            result = bool(inputs["value"])
        elif isinstance(expression, bool):
            result = expression
        elif isinstance(expression, str):
            if expression.startswith("expr:"):
                expression = expression[5:]
            variables = self.ctx.variables()
            variables.update(inputs)
            result = bool(evaluate_expression(expression, variables))
        else:
            result = bool(resolve_reference(expression, self.ctx))
        output_var = node.get("output_var")
        if output_var:
            self.ctx.data[output_var] = result
        return NodeOutcome({"value": result, "result": result}, ["true" if result else "false"])

    def _flow_variant_node(self, node: dict, inputs: dict) -> NodeOutcome:
        """Validate a model-authored Flow proposal behind a typed boundary."""

        from flow_variants import (
            FlowVariantError,
            apply_flow_variant,
            validate_proposal_evidence,
            write_flow_variant,
        )

        base = inputs.get("base_config")
        if base is None:
            base = resolve_reference(node.get("base_config"), self.ctx)
        if base is None and node.get("base_path"):
            base_path = self._safe_runtime_path(resolve_reference(node.get("base_path"), self.ctx))
            try:
                base = json.loads(base_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                result = {"ok": False, "errors": [f"could not load base Flow: {error}"]}
                self.ctx.data[node.get("output_var", "flow_variant")] = result
                return NodeOutcome({"value": result, **result}, ["variant_invalid"])
        proposal = inputs.get("proposal")
        if proposal is None:
            proposal = resolve_reference(node.get("proposal"), self.ctx)
        allowed_paths = resolve_reference(node.get("allowed_paths", []), self.ctx)
        try:
            evidence = inputs.get("evidence")
            if evidence is None:
                evidence = resolve_reference(node.get("evidence"), self.ctx)
            verified_evidence = (
                validate_proposal_evidence(proposal, evidence)
                if isinstance(evidence, dict)
                else []
            )
            result = apply_flow_variant(
                base,
                proposal,
                allowed_paths=allowed_paths if isinstance(allowed_paths, list) else [],
                max_operations=int(resolve_reference(node.get("max_operations", 12), self.ctx)),
            )
            result["verified_evidence"] = verified_evidence
            result["ok"] = True
            tags = ["variant_valid"]
            if bool(resolve_reference(node.get("persist", False), self.ctx)):
                raw_output = resolve_reference(node.get("output_path"), self.ctx)
                if not raw_output:
                    raise FlowVariantError("persist=true requires output_path")
                output_path = self._safe_runtime_path(raw_output)
                write_flow_variant(result, output_path)
                result["output_path"] = str(output_path.relative_to(self.ctx.harness.workspace))
                tags.insert(0, "variant_written")
        except (FlowVariantError, TypeError, ValueError) as error:
            result = {"ok": False, "errors": [str(error)]}
            tags = ["variant_invalid"]
        self.ctx.data[node.get("output_var", "flow_variant")] = copy.deepcopy(result)
        self.ctx.emit("flow_variant", {key: value for key, value in result.items() if key != "config"})
        return NodeOutcome({"value": result, **result}, tags)

    def _search_control_node(self, node: dict, inputs: dict) -> NodeOutcome:
        """Validate beliefs and choose an information-seeking experiment."""

        from self_evolution.search_control import (
            SearchControlError,
            latest_available_actions,
            recent_action_signatures,
            reconcile_search_state,
        )

        ledger = inputs.get("ledger")
        if ledger is None:
            ledger = resolve_reference(node.get("ledger", {}), self.ctx)
        proposal = inputs.get("proposal")
        if proposal is None:
            proposal = resolve_reference(node.get("proposal", {}), self.ctx)
        trajectory = inputs.get("trajectory")
        if trajectory is None:
            trajectory = resolve_reference(node.get("trajectory", "$ctx._trajectory"), self.ctx)
        recent = inputs.get("recent_actions")
        if not isinstance(recent, list):
            recent = recent_action_signatures(
                trajectory,
                limit=int(resolve_reference(node.get("recent_action_limit", 12), self.ctx)),
            )
        allowed_actions = inputs.get("allowed_actions")
        if allowed_actions is None:
            allowed_actions = resolve_reference(node.get("allowed_actions", []), self.ctx)
        if not isinstance(allowed_actions, list):
            allowed_actions = []
        if not allowed_actions:
            allowed_actions = latest_available_actions(trajectory)
        try:
            result = reconcile_search_state(
                ledger if isinstance(ledger, dict) else {},
                proposal,
                allowed_actions=allowed_actions,
                recent_actions=recent,
                max_hypotheses=int(resolve_reference(node.get("max_hypotheses", 8), self.ctx)),
                max_experiments=int(resolve_reference(node.get("max_experiments", 12), self.ctx)),
                coordinate_min=resolve_reference(node.get("coordinate_min"), self.ctx),
                coordinate_max=resolve_reference(node.get("coordinate_max"), self.ctx),
            )
        except (SearchControlError, TypeError, ValueError) as error:
            result = {
                "ok": False,
                "ledger": copy.deepcopy(ledger if isinstance(ledger, dict) else {}),
                "selected": None,
                "errors": [str(error)],
                "audit": [],
            }
        output_var = str(node.get("output_var", "search_control"))
        self.ctx.data[output_var] = copy.deepcopy(result)
        ledger_var = str(node.get("ledger_var", "belief_ledger"))
        selected_var = str(node.get("selected_var", "selected_experiment"))
        self.ctx.data[ledger_var] = copy.deepcopy(result.get("ledger", {}))
        self.ctx.data[selected_var] = copy.deepcopy(result.get("selected"))
        self.ctx.emit(
            "search_control",
            {
                "ok": result.get("ok"),
                "selected": result.get("selected"),
                "errors": result.get("errors", []),
                "audit": result.get("audit", []),
                "revision": (result.get("ledger") or {}).get("revision"),
            },
        )
        if result.get("ok"):
            tags = ["controller_ready"]
        elif result.get("selected") is None and not result.get("errors"):
            tags = ["no_experiment"]
        else:
            tags = ["controller_invalid"]
        return NodeOutcome({"value": result, **result}, tags)

    def _loop_guard_node(self, node: dict, inputs: dict) -> NodeOutcome:
        """Apply one declarative repeated-tool reminder policy."""

        from loop_guard import LoopGuardError, observe_tool_trajectory, reset_loop_guard

        action = str(inputs.get("action", resolve_reference(node.get("action", "observe"), self.ctx))).casefold()
        trajectory = inputs.get("trajectory")
        if trajectory is None:
            trajectory = resolve_reference(node.get("trajectory", "$ctx._trajectory"), self.ctx)
        namespace = str(resolve_reference(node.get("namespace", "default"), self.ctx) or "default")
        session = self.ctx.harness.session
        with session._lock:
            # DeepSeek Harness intentionally keeps this detector in memory: a
            # resumed session should not inherit a stale consecutive-call run.
            # Put it on the live Session object instead of the persisted state.
            stores = getattr(session, "_loop_guard_state", None)
            if not isinstance(stores, dict):
                stores = {}
                setattr(session, "_loop_guard_state", stores)
            previous = copy.deepcopy(stores.get(namespace, {}))
            if action == "reset":
                state = reset_loop_guard(trajectory)
                result = {"state": state, "reminders": [], "reminded": False, "observed": 0}
                tags = ["guard_reset"]
            elif action == "observe":
                try:
                    result = observe_tool_trajectory(
                        previous,
                        trajectory,
                        thresholds=resolve_reference(node.get("thresholds", [3, 5, 8]), self.ctx),
                        include=resolve_reference(node.get("include", []), self.ctx),
                        exclude=resolve_reference(node.get("exclude", []), self.ctx),
                        arguments_preview_chars=int(resolve_reference(node.get("arguments_preview_chars", 500), self.ctx)),
                    )
                except LoopGuardError as error:
                    raise PipelineError(str(error)) from error
                state = result["state"]
                tags = ["guard_reminder" if result["reminded"] else "guard_clear"]
            else:
                raise PipelineError(f"unknown Loop Guard action: {action}")
            stores[namespace] = copy.deepcopy(state)
        reminders = result.get("reminders", [])
        if reminders and bool(resolve_reference(node.get("inject_message", True), self.ctx)):
            for reminder in reminders:
                message = {
                    "role": "user",
                    "name": "runtime_repeat_tool_reminder",
                    "content": str(reminder["text"]),
                    "_op": "loop_guard",
                    "_guard": {
                        "namespace": namespace,
                        "tool": reminder["tool"],
                        "count": reminder["count"],
                        "signature_sha256": reminder["signature_sha256"],
                    },
                }
                session.record(message)
                session.record_full(copy.deepcopy(message))
                self.ctx.emit("loop_guard_reminder", copy.deepcopy(message["_guard"]))
        output = {"value": result, **copy.deepcopy(result), "namespace": namespace}
        output_var = node.get("output_var", "loop_guard")
        if output_var:
            set_path(self.ctx.data, str(output_var), copy.deepcopy(result))
        return NodeOutcome(output, tags)

    def _data_node(self, node: dict, inputs: dict, op: str) -> NodeOutcome:
        action = node.get("action", "set")
        tags: list[str] = []
        if op == "保存数据":
            action = "set"
        elif op == "读取数据":
            action = "get"
        if action in {
            "agent_register",
            "agent_heartbeat",
            "agent_unregister",
            "agent_list",
            "message_publish",
            "message_receive",
            "message_ack",
            "message_nack",
            "message_list",
        }:
            return self._agent_bus_data_node(node, inputs, action)
        scope = node.get("scope", "run")
        key = resolve_reference(node.get("key", inputs.get("key", "")), self.ctx)
        if not isinstance(key, str) or not key:
            raise PipelineError("Data node requires a non-empty key")
        value = inputs.get("value", resolve_reference(node.get("value"), self.ctx))

        # A state transition is deliberately handled as one storage operation:
        # load, verify preconditions, apply every mutation to a copy, validate,
        # and atomically replace the stored value.  This prevents an LLM or a
        # parallel branch from partially changing authoritative state.
        if action == "state_transition":
            transition = inputs.get("transition", value)
            if not isinstance(transition, dict):
                raise PipelineError("Data state_transition requires a transition object")
            lock = nullcontext()
            if scope == "file":
                lock = _memory_lock(self._safe_runtime_path(node.get("path", ".egoagent/dag-data.json")))
            with lock:
                store, save = self._data_store(scope, node)
                current = get_path(store, key, resolve_reference(node.get("default", {}), self.ctx))
                if not isinstance(current, dict):
                    raise PipelineError("Data state_transition current state must be an object")
                schema = inputs.get("schema", resolve_reference(node.get("schema", {}), self.ctx))
                if not isinstance(schema, dict):
                    raise PipelineError("Data state_transition schema must be a JSON Schema object")
                result = _apply_state_transition(current, transition, schema=schema)
                if result["accepted"]:
                    set_path(store, key, copy.deepcopy(result["state"]))
                    if save:
                        save(store)
            output_var = node.get("output_var")
            if output_var:
                set_path(self.ctx.data, output_var, copy.deepcopy(result))
            self.ctx.emit(
                "state_transition",
                {
                    "accepted": result["accepted"],
                    "revision": result["revision"],
                    "reason_codes": result["reason_codes"],
                    "operation_count": len(transition.get("operations", [])),
                },
            )
            tags = ["transition_committed" if result["accepted"] else "transition_rejected"]
            return NodeOutcome({"value": result, "key": key, "action": action, "scope": scope}, tags)

        store, save = self._data_store(scope, node)

        if action in {"set", "save"}:
            set_path(store, key, copy.deepcopy(value))
            result = value
        elif action in {"get", "load"}:
            result = get_path(store, key, resolve_reference(node.get("default"), self.ctx))
        elif action == "delete":
            result = delete_path(store, key)
        elif action == "append":
            current = get_path(store, key, [])
            if not isinstance(current, list):
                raise PipelineError(f"Data key {key!r} is not a list")
            current = list(current)
            current.append(copy.deepcopy(value))
            set_path(store, key, current)
            result = current
        elif action == "extend":
            current = get_path(store, key, [])
            if not isinstance(current, list) or not isinstance(value, list):
                raise PipelineError("Data extend requires two lists")
            result = list(current) + copy.deepcopy(value)
            set_path(store, key, result)
        elif action == "merge":
            current = get_path(store, key, {})
            if not isinstance(current, dict) or not isinstance(value, dict):
                raise PipelineError("Data merge requires two objects")
            result = {**current, **copy.deepcopy(value)}
            set_path(store, key, result)
        elif action == "increment":
            current = get_path(store, key, resolve_reference(node.get("default", 0), self.ctx))
            delta = inputs.get("delta", resolve_reference(node.get("delta", 1), self.ctx))
            if isinstance(current, bool) or not isinstance(current, (int, float)):
                raise PipelineError("Data increment requires a numeric stored value")
            if isinstance(delta, bool) or not isinstance(delta, (int, float)):
                raise PipelineError("Data increment requires a numeric delta")
            result = current + delta
            set_path(store, key, result)
        elif action == "range":
            raw_start = inputs.get("start", resolve_reference(node.get("range_start", 0), self.ctx))
            raw_stop = inputs.get("stop", resolve_reference(node.get("range_stop"), self.ctx))
            raw_step = inputs.get("step", resolve_reference(node.get("range_step", 1), self.ctx))
            if raw_stop is None:
                raise PipelineError("Data range requires range_stop")
            try:
                start = int(raw_start)
                stop = int(raw_stop)
                step = int(raw_step)
            except (TypeError, ValueError) as error:
                raise PipelineError("Data range bounds must be integers") from error
            if step == 0:
                raise PipelineError("Data range step cannot be zero")
            max_items = max(0, int(node.get("max_items", 10_000)))
            candidate = range(start, stop, step)
            if len(candidate) > max_items:
                raise PipelineError(f"Data range would create {len(candidate)} items (limit {max_items})")
            result = list(candidate)
            set_path(store, key, result)
        elif action == "evaluate":
            expression = inputs.get("expression", node.get("expression", node.get("condition")))
            if not isinstance(expression, str) or not expression.strip():
                raise PipelineError("Data evaluate requires a non-empty expression")
            if expression.startswith("expr:"):
                expression = expression[5:]
            variables = self.ctx.variables()
            variables.update(inputs)
            result = evaluate_expression(expression, variables)
            set_path(store, key, copy.deepcopy(result))
        elif action == "slice":
            source = inputs.get("source", resolve_reference(node.get("source", value), self.ctx))
            if not isinstance(source, (str, list, tuple)):
                raise PipelineError("Data slice requires a string, list or tuple source")
            raw_start = inputs.get("start", resolve_reference(node.get("start_index"), self.ctx))
            raw_end = inputs.get("end", resolve_reference(node.get("end_index"), self.ctx))
            raw_step = inputs.get("step", resolve_reference(node.get("step"), self.ctx))
            try:
                start = int(raw_start) if raw_start is not None else None
                end = int(raw_end) if raw_end is not None else None
                step = int(raw_step) if raw_step is not None else None
            except (TypeError, ValueError) as error:
                raise PipelineError("Data slice indexes must be integers") from error
            if step == 0:
                raise PipelineError("Data slice step cannot be zero")
            result = source[slice(start, end, step)]
            if isinstance(result, tuple):
                result = list(result)
            set_path(store, key, copy.deepcopy(result))
        elif action == "trim_words":
            source = inputs.get("source", resolve_reference(node.get("source", value), self.ctx))
            raw_limit = inputs.get("max_words", resolve_reference(node.get("max_words", 25_000), self.ctx))
            try:
                max_words = max(0, int(raw_limit))
            except (TypeError, ValueError) as error:
                raise PipelineError("Data trim_words max_words must be an integer") from error
            if isinstance(source, str):
                result = " ".join(source.split()[:max_words])
            elif isinstance(source, list):
                total_words = 0
                result = []
                for item in reversed(source):
                    text = " ".join(str(part) for part in item) if isinstance(item, list) else str(item)
                    words = len(text.split())
                    if total_words + words <= max_words:
                        result.insert(0, copy.deepcopy(item))
                        total_words += words
                    elif not result and max_words:
                        result.insert(0, " ".join(text.split()[:max_words]))
                        break
                    else:
                        break
            else:
                raise PipelineError("Data trim_words requires a string or list source")
            set_path(store, key, copy.deepcopy(result))
        elif action == "unique":
            source = inputs.get("source", resolve_reference(node.get("source", value), self.ctx))
            if not isinstance(source, list):
                raise PipelineError("Data unique requires a list source")
            result = []
            seen = set()
            for item in source:
                try:
                    marker = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
                except (TypeError, ValueError):
                    marker = repr(item)
                if marker in seen:
                    continue
                seen.add(marker)
                result.append(copy.deepcopy(item))
            set_path(store, key, result)
        elif action == "filter":
            source = inputs.get("source", resolve_reference(node.get("source", value), self.ctx))
            if not isinstance(source, list):
                raise PipelineError("Data filter requires a list source")
            expression = node.get("condition", node.get("expression", "bool(item)"))
            if not isinstance(expression, str) or not expression.strip():
                raise PipelineError("Data filter requires a condition expression")
            if expression.startswith("expr:"):
                expression = expression[5:]
            item_var = node.get("item_var", "item")
            counter_var = node.get("counter_var", "index")
            result = []
            for index, item in enumerate(source):
                variables = self.ctx.variables()
                variables.update(inputs)
                variables[item_var] = item
                variables[counter_var] = index
                try:
                    keep = evaluate_expression(expression, variables)
                except Exception as error:
                    raise PipelineError(f"Data filter failed at item {index}: {error}") from error
                if keep:
                    result.append(copy.deepcopy(item))
            set_path(store, key, result)
        elif action == "aggregate_fields":
            source = inputs.get("source", resolve_reference(node.get("source", value), self.ctx))
            if not isinstance(source, list):
                raise PipelineError("Data aggregate_fields requires a list source")
            fields = inputs.get("fields", resolve_reference(node.get("fields", []), self.ctx))
            if not isinstance(fields, list) or not fields or not all(isinstance(field, str) and field for field in fields):
                raise PipelineError("Data aggregate_fields requires a non-empty string fields list")
            limits = inputs.get("limits", resolve_reference(node.get("limits", {}), self.ctx))
            if limits is None:
                limits = {}
            if not isinstance(limits, dict):
                raise PipelineError("Data aggregate_fields limits must be an object")
            result = {}
            for field in fields:
                scores = []
                raw_limit = limits.get(field)
                if raw_limit is not None and (
                    not isinstance(raw_limit, list) or len(raw_limit) != 2
                    or not all(isinstance(bound, (int, float)) for bound in raw_limit)
                ):
                    raise PipelineError(f"Data aggregate_fields limit for {field!r} must be [min, max]")
                for item in source:
                    candidate = get_path(item, field) if isinstance(item, dict) else None
                    if not isinstance(candidate, (int, float)) or isinstance(candidate, bool):
                        continue
                    if raw_limit is not None and not (raw_limit[0] <= candidate <= raw_limit[1]):
                        continue
                    scores.append(float(candidate))
                if not scores:
                    raise PipelineError(f"Data aggregate_fields has no valid values for {field!r}")
                mean = sum(scores) / len(scores)
                result[field] = int(round(mean)) if node.get("round_to_int", True) else mean
            set_path(store, key, result)
        elif action == "topological_levels":
            source = inputs.get("source", resolve_reference(node.get("source", value), self.ctx))
            if not isinstance(source, list):
                raise PipelineError("Data topological_levels requires a list source")
            max_items = max(0, int(node.get("max_items", 10_000)))
            if len(source) > max_items:
                raise PipelineError(
                    f"Data topological_levels received {len(source)} items (limit {max_items})"
                )
            id_field = str(node.get("id_field", "id") or "id")
            dependency_field = str(node.get("dependency_field", "dependencies") or "dependencies")
            items_by_id: dict[str, Any] = {}
            order: dict[str, int] = {}
            dependencies: dict[str, list[str]] = {}
            for index, item in enumerate(source):
                if not isinstance(item, dict):
                    raise PipelineError(f"Data topological_levels item {index} must be an object")
                item_id = get_path(item, id_field)
                if not isinstance(item_id, str) or not item_id.strip():
                    raise PipelineError(
                        f"Data topological_levels item {index} requires a non-empty string {id_field!r}"
                    )
                item_id = item_id.strip()
                if item_id in items_by_id:
                    raise PipelineError(f"Data topological_levels has duplicate id {item_id!r}")
                raw_dependencies = get_path(item, dependency_field, [])
                if raw_dependencies is None:
                    raw_dependencies = []
                if not isinstance(raw_dependencies, list) or not all(
                    isinstance(dependency, str) and dependency.strip()
                    for dependency in raw_dependencies
                ):
                    raise PipelineError(
                        f"Data topological_levels dependencies for {item_id!r} must be a string list"
                    )
                items_by_id[item_id] = copy.deepcopy(item)
                order[item_id] = index
                dependencies[item_id] = list(dict.fromkeys(dependency.strip() for dependency in raw_dependencies))
            known_ids = set(items_by_id)
            for item_id, item_dependencies in dependencies.items():
                unknown = [dependency for dependency in item_dependencies if dependency not in known_ids]
                if unknown:
                    raise PipelineError(
                        f"Data topological_levels item {item_id!r} has unknown dependencies: {unknown}"
                    )
                if item_id in item_dependencies:
                    raise PipelineError(f"Data topological_levels item {item_id!r} depends on itself")
            remaining = set(items_by_id)
            completed: set[str] = set()
            result = []
            while remaining:
                ready = sorted(
                    (item_id for item_id in remaining if set(dependencies[item_id]) <= completed),
                    key=order.__getitem__,
                )
                if not ready:
                    cycle = sorted(remaining, key=order.__getitem__)
                    raise PipelineError(f"Data topological_levels detected a dependency cycle: {cycle}")
                result.append([copy.deepcopy(items_by_id[item_id]) for item_id in ready])
                completed.update(ready)
                remaining.difference_update(ready)
            set_path(store, key, result)
            tags = ["topology_ready"]
        elif action == "validate_schema":
            source = inputs.get("source", resolve_reference(node.get("source", value), self.ctx))
            schema = inputs.get("schema", resolve_reference(node.get("schema", {}), self.ctx))
            if not isinstance(schema, dict):
                raise PipelineError("Data validate_schema requires a JSON Schema object")
            errors = validate_json_schema(source, schema, path="$value")
            result = {"valid": not errors, "errors": errors, "value": copy.deepcopy(source)}
            set_path(store, key, result)
            tags = ["schema_valid" if not errors else "schema_invalid"]
        else:
            raise PipelineError(f"unknown Data action: {action}")
        if save:
            save(store)
        output_var = node.get("output_var")
        if output_var:
            set_path(self.ctx.data, output_var, copy.deepcopy(result))
        return NodeOutcome({"value": result, "key": key, "action": action, "scope": scope}, tags)

    def _agent_bus_data_node(self, node: dict, inputs: dict, action: str) -> NodeOutcome:
        """Expose durable role/message semantics through the existing Data node."""

        def option(name: str, default: Any = None) -> Any:
            if name in inputs:
                return inputs[name]
            return resolve_reference(node.get(name, default), self.ctx)

        requested_path = option("path", ".egoagent/agent-bus.sqlite3")
        path = self._safe_runtime_path(str(requested_path or ".egoagent/agent-bus.sqlite3"))
        try:
            bus = AgentBus(path, max_payload_bytes=int(option("max_payload_bytes", 1_000_000)))
            if action == "agent_register":
                result = bus.register(
                    option("agent_id"),
                    identity=option("identity", ""),
                    subscriptions=option("subscriptions", []),
                    metadata=option("metadata", {}),
                )
                tags = ["agent_registered"]
            elif action == "agent_heartbeat":
                result = bus.heartbeat(option("agent_id"))
                tags = ["agent_alive"]
            elif action == "agent_unregister":
                result = bus.unregister(option("agent_id"))
                tags = ["agent_unregistered" if result else "agent_missing"]
            elif action == "agent_list":
                result = bus.list_agents(include_inactive=bool(option("include_inactive", False)))
                tags = ["agents_found" if result else "agents_empty"]
            elif action == "message_publish":
                recipients = option("recipients") if "recipients" in inputs or "recipients" in node else None
                payload = option("payload", option("value"))
                result = bus.publish(
                    topic=option("topic"),
                    sender=option("sender"),
                    payload=payload,
                    recipients=recipients,
                    headers=option("headers", {}),
                    idempotency_key=option("idempotency_key"),
                    delay_seconds=float(option("delay_seconds", 0.0)),
                    max_attempts=int(option("max_attempts", 3)),
                )
                tags = ["message_published"]
                if result.get("deduplicated"):
                    tags.append("message_deduplicated")
                if not result.get("recipients"):
                    tags.append("message_unrouted")
            elif action == "message_receive":
                result = bus.receive(
                    agent_id=option("agent_id"),
                    owner=option("owner", self.ctx.run_id),
                    topics=option("topics") if "topics" in inputs or "topics" in node else None,
                    limit=int(option("limit", 1)),
                    lease_seconds=float(option("lease_seconds", 30.0)),
                )
                tags = ["messages_received" if result else "message_empty"]
            elif action == "message_ack":
                receipts = option("receipts", option("messages", option("value", [])))
                result = bus.acknowledge(receipts, owner=option("owner", self.ctx.run_id))
                tags = ["messages_acknowledged"]
            elif action == "message_nack":
                receipts = option("receipts", option("messages", option("value", [])))
                result = bus.reject(
                    receipts,
                    owner=option("owner", self.ctx.run_id),
                    error=str(option("error", "") or ""),
                    delay_seconds=float(option("delay_seconds", 0.0)),
                )
                tags = ["messages_dead" if result.get("dead") else "messages_requeued"]
            elif action == "message_list":
                result = bus.list_messages(
                    topic=option("topic"),
                    recipient=option("recipient"),
                    state=option("state"),
                    limit=int(option("limit", 100)),
                )
                tags = ["messages_found" if result else "message_empty"]
            else:  # pragma: no cover - the caller guards the action set.
                raise AgentBusError(f"unknown Agent bus action: {action}")
        except (AgentBusError, OSError, sqlite3.Error) as error:
            raise PipelineError(f"Agent bus {action} failed: {error}") from error

        output_var = node.get("output_var")
        if output_var:
            set_path(self.ctx.data, output_var, copy.deepcopy(result))
        count = len(result) if isinstance(result, list) else len(result.get("recipients", [])) if isinstance(result, dict) else 0
        self.ctx.emit(
            "agent_bus",
            {
                "action": action,
                "path": self._workspace_relative(path),
                "count": count,
                "tags": tags,
            },
        )
        return NodeOutcome(
            {
                "value": result,
                "items": result if isinstance(result, list) else None,
                "action": action,
                "scope": "agent_bus",
                "path": self._workspace_relative(path),
            },
            tags,
        )

    def _process_node(self, node: dict, inputs: dict) -> NodeOutcome:
        """Run one explicit, non-shell process and return typed evidence."""
        raw_command = inputs.get("command", resolve_reference(node.get("command"), self.ctx))
        raw_args = inputs.get("args", resolve_reference(node.get("args", []), self.ctx))
        if isinstance(raw_command, list):
            argv = [str(value) for value in raw_command]
        elif raw_command is not None and str(raw_command).strip():
            argv = [str(raw_command)]
        else:
            raise PipelineError("Process node requires a command")
        if not isinstance(raw_args, list):
            raise PipelineError("Process args must be a list")
        argv.extend(str(value) for value in raw_args)
        if any(self.ctx.secret_view.redact_text(argument) != argument for argument in argv):
            raise PipelineError("Process command/args contain an authorized secret value; pass it through secret_env instead")
        original_argv = list(argv)

        requested_cwd = inputs.get("cwd", resolve_reference(node.get("cwd", "."), self.ctx))
        cwd = self._safe_runtime_path(str(requested_cwd or "."))
        if not cwd.is_dir():
            raise PipelineError(f"Process working directory does not exist: {cwd}")
        if self.ctx.permission_policy is not None:
            display_command = " ".join(original_argv)
            decision = self.ctx.permission_policy.evaluate_tool(
                "run_command",
                {"command": display_command, "cwd": str(cwd)},
                {"permissions": ["process"]},
            )
            self._require_policy_approval(
                decision,
                tool="process_node",
                arguments={"command": original_argv, "cwd": str(cwd)},
                prompt=f"Allow DAG Process node to run: {display_command}?",
            )

        raw_env = inputs.get("env", resolve_reference(node.get("env", {}), self.ctx))
        if not isinstance(raw_env, dict):
            raise PipelineError("Process env must be an object")
        sensitive_markers = ("password", "passwd", "api_key", "apikey", "secret", "authorization", "cookie", "token")
        for key in raw_env:
            if any(marker in str(key).lower() for marker in sensitive_markers):
                raise PipelineError(
                    f"Process env '{key}' looks secret; reference an authorized name through secret_env instead"
                )
        explicit_env = {str(key): str(value) for key, value in raw_env.items()}
        raw_secret_env = inputs.get("secret_env", resolve_reference(node.get("secret_env", {}), self.ctx))
        if not isinstance(raw_secret_env, dict):
            raise PipelineError("Process secret_env must be an object mapping destination variables to secret names")
        for destination, secret_name in raw_secret_env.items():
            try:
                explicit_env[str(destination)] = self.ctx.secret_view.resolve(str(secret_name))
            except (KeyError, PermissionError) as error:
                raise PipelineError(str(error)) from error
        from secure_command import sanitized_subprocess_environment

        process_env = sanitized_subprocess_environment()
        process_env.update(explicit_env)
        backend = str(inputs.get("backend", resolve_reference(node.get("backend", "local"), self.ctx))).lower()
        if backend not in {"local", "container", "docker", "podman"}:
            raise PipelineError("Process backend must be local, container, docker or podman")
        enforced_sandbox = self.ctx.permission_policy.sandbox if self.ctx.permission_policy is not None else {}
        if str(enforced_sandbox.get("mode", "workspace")) == "container":
            backend = "container"
        container_invocation = None
        container_cleanup = None
        launch_cwd = cwd
        if backend != "local":
            container_config = inputs.get("container", resolve_reference(node.get("container", {}), self.ctx))
            if not isinstance(container_config, dict):
                raise PipelineError("Process container configuration must be an object")
            if str(enforced_sandbox.get("mode", "workspace")) == "container":
                container_config = {**container_config, **dict(enforced_sandbox)}
            try:
                container_invocation = build_container_invocation(
                    backend=backend,
                    workspace=Path(self.ctx.harness.workspace or self.ctx.harness.dir),
                    cwd=cwd,
                    command=original_argv[0],
                    args=original_argv[1:],
                    environment=explicit_env,
                    config=container_config,
                    run_id=self.ctx.run_id,
                    node_id=self.ctx.current_node or "process",
                )
            except ProcessBackendError as error:
                raise PipelineError(str(error)) from error
            argv = container_invocation.argv
            process_env = container_invocation.host_env
            launch_cwd = Path(self.ctx.harness.workspace or self.ctx.harness.dir).resolve()
        encoding = str(node.get("encoding", "utf-8"))
        stdin_value = inputs.get("stdin", resolve_reference(node.get("stdin"), self.ctx))
        stdin_bytes = None if stdin_value is None else str(stdin_value).encode(encoding)

        timeout = max(0.01, float(node.get("timeout_seconds", 300)))
        success_codes = node.get("success_codes", [0])
        if not isinstance(success_codes, list) or not all(isinstance(code, int) for code in success_codes):
            raise PipelineError("Process success_codes must be an integer list")
        resources = inputs.get("resources", resolve_reference(node.get("resources", {}), self.ctx))
        self._before_process_call()
        acquired = self._acquire_resources(resources)
        started = time.monotonic()
        timed_out = False
        cancelled = False
        exit_code = None
        termination_strategy = None
        windows_job = None

        try:
            with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
                process = subprocess.Popen(
                    argv,
                    cwd=str(launch_cwd),
                    env=process_env,
                    stdin=subprocess.PIPE if stdin_bytes is not None else subprocess.DEVNULL,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    shell=False,
                    **_process_group_options(),
                )
                if os.name == "nt":
                    windows_job = _windows_assign_kill_job_and_resume(process)
                if stdin_bytes is not None and process.stdin is not None:
                    process.stdin.write(stdin_bytes)
                    process.stdin.close()
                    process.stdin = None
                deadline = started + timeout
                while process.poll() is None:
                    if self.ctx.cancelled():
                        cancelled = True
                        if windows_job is not None:
                            _windows_close_kill_job(windows_job)
                            windows_job = None
                            termination_strategy = "windows_kill_on_close_job"
                        else:
                            termination_strategy = _terminate_process_tree(
                                process, node.get("termination_grace_seconds", 0.5)
                            )
                        break
                    if time.monotonic() >= deadline:
                        timed_out = True
                        if windows_job is not None:
                            _windows_close_kill_job(windows_job)
                            windows_job = None
                            termination_strategy = "windows_kill_on_close_job"
                        else:
                            termination_strategy = _terminate_process_tree(
                                process, node.get("termination_grace_seconds", 0.5)
                            )
                        break
                    time.sleep(0.05)
                exit_code = process.wait()
                if windows_job is not None:
                    _windows_close_kill_job(windows_job)
                    windows_job = None
                stdout_file.seek(0)
                stderr_file.seek(0)
                stdout = stdout_file.read().decode(encoding, errors="replace")
                stderr = stderr_file.read().decode(encoding, errors="replace")
        except OSError as error:
            raise PipelineError(f"cannot start process {argv[0]!r}: {error}") from error
        finally:
            if windows_job is not None:
                _windows_close_kill_job(windows_job)
            if container_invocation is not None:
                container_cleanup = cleanup_container(
                    container_invocation,
                    timeout=float(node.get("container_cleanup_timeout_seconds", 10)),
                )
            for semaphore in reversed(acquired):
                semaphore.release()

        stdout = self.ctx.secret_view.redact_text(stdout)
        stderr = self.ctx.secret_view.redact_text(stderr)

        max_chars = max(1000, int(node.get("max_output_chars", 100000)))
        stdout_truncated = len(stdout) > max_chars
        stderr_truncated = len(stderr) > max_chars
        if stdout_truncated:
            stdout = stdout[-max_chars:]
        if stderr_truncated:
            stderr = stderr[-max_chars:]
        artifacts = self._collect_process_artifacts(cwd, node.get("artifacts", []))
        result = {
            "command": original_argv,
            "backend": "container" if backend != "local" else "local",
            "cwd": str(cwd),
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
            "timed_out": timed_out,
            "cancelled": cancelled,
            "termination_strategy": termination_strategy,
            "duration_seconds": round(time.monotonic() - started, 3),
            "artifacts": artifacts,
            "resources": copy.deepcopy(resources),
            "container": (
                {
                    "engine": container_invocation.engine,
                    "image": container_invocation.image,
                    "name": container_invocation.container_name,
                    "workdir": container_invocation.container_workdir,
                    "security": copy.deepcopy(container_invocation.security),
                    "cleanup": container_cleanup,
                }
                if container_invocation is not None
                else None
            ),
        }
        output_var = node.get("output_var", "process_result")
        if output_var:
            set_path(self.ctx.data, output_var, copy.deepcopy(result))
        self.ctx.emit(
            "process",
            {
                "command": original_argv[0],
                "backend": "container" if container_invocation is not None else "local",
                "image": container_invocation.image if container_invocation is not None else None,
                "exit_code": exit_code,
                "timed_out": timed_out,
                "cancelled": cancelled,
                "termination_strategy": termination_strategy,
                "artifacts": artifacts,
            },
        )
        if cancelled:
            raise PipelineCancelled("process execution was cancelled")
        if timed_out:
            raise NodeTimeout(f"process exceeded timeout ({timeout}s)")
        success = exit_code in success_codes
        if not success and node.get("fail_on_error", True):
            detail = stderr.strip() or stdout.strip() or "no output"
            raise PipelineError(f"process exited with code {exit_code}: {detail[-1000:]}")
        return NodeOutcome(result | {"value": result}, ["process_succeeded" if success else "process_failed"])

    def _acquire_resources(self, raw_requests: Any) -> list[threading.BoundedSemaphore]:
        if raw_requests in (None, {}):
            return []
        if not isinstance(raw_requests, dict):
            raise PipelineError("Process resources must be an object")
        limits = self.ctx.graph.get("resource_limits", {})
        workspace = str(Path(self.ctx.harness.workspace or self.ctx.harness.dir).resolve())
        acquired: list[threading.BoundedSemaphore] = []
        try:
            for name, raw_count in sorted(raw_requests.items()):
                count = int(raw_count)
                capacity = int(limits.get(name, count))
                if count < 1 or capacity < count:
                    raise PipelineError(f"resource request {name}={count} exceeds capacity {capacity}")
                pool = _resource_pool(workspace, str(name), capacity)
                for _ in range(count):
                    while not pool.acquire(timeout=0.1):
                        if self.ctx.cancelled():
                            raise PipelineCancelled("cancelled while waiting for a process resource")
                    acquired.append(pool)
            if acquired:
                self.ctx.emit("resources_acquired", {"resources": raw_requests})
            return acquired
        except BaseException:
            for semaphore in reversed(acquired):
                semaphore.release()
            raise

    def _collect_process_artifacts(self, cwd: Path, raw_patterns: Any) -> list[str]:
        if not raw_patterns:
            return []
        if not isinstance(raw_patterns, list):
            raise PipelineError("Process artifacts must be a list of relative glob patterns")
        workspace = Path(self.ctx.harness.workspace or self.ctx.harness.dir).resolve()
        found: list[str] = []
        for raw_pattern in raw_patterns:
            pattern_path = Path(str(raw_pattern))
            if pattern_path.is_absolute() or ".." in pattern_path.parts:
                raise PipelineError(f"Process artifact pattern escapes working directory: {raw_pattern}")
            for path in sorted(cwd.glob(str(raw_pattern))):
                resolved = path.resolve()
                if resolved.is_file() and (resolved == workspace or workspace in resolved.parents):
                    found.append(resolved.relative_to(workspace).as_posix())
                    if len(found) >= 200:
                        return found
        return list(dict.fromkeys(found))

    def _workspace_node(self, node: dict, inputs: dict) -> NodeOutcome:
        """Manage recoverable workspace artifacts without arbitrary scripts."""
        action = str(node.get("action", "mkdir"))
        read_actions = {"read", "read_text", "read_json", "read_binary", "list", "measure", "changes"}
        permission_class = PermissionClass.READ if action in read_actions else PermissionClass.WRITE
        if self.ctx.permission_policy is not None:
            try:
                self.ctx.permission_policy.require_class(
                    permission_class,
                    tool=f"workspace_{action}",
                    arguments={"path": inputs.get("path", node.get("path", node.get("target", ".")))},
                )
            except PermissionError as error:
                raise PipelineError(f"Workspace permission denied: {error}") from error
        if action == "begin_transaction":
            from harness_editor.change_tracker import begin_transaction

            requested_id = inputs.get("transaction_id", resolve_reference(node.get("transaction_id"), self.ctx))
            transaction_id = begin_transaction(requested_id or f"{self.ctx.run_id}-{uuid.uuid4().hex[:8]}")
            self.ctx.change_transaction_id = transaction_id
            snapshot = None
            raw_paths = inputs.get("paths", resolve_reference(node.get("paths", []), self.ctx))
            if raw_paths:
                snapshot = self._snapshot_workspace(raw_paths, node.get("label", "before-agent-edit"), node)
            result = {"action": action, "transaction_id": transaction_id, "snapshot": snapshot}
            self.ctx.data["_change_transaction"] = transaction_id
            tags = ["transaction_started"]
        elif action == "changes":
            from harness_editor.change_tracker import get_transaction_summary

            transaction_id = inputs.get("transaction_id", resolve_reference(node.get("transaction_id", "$ctx._change_transaction"), self.ctx))
            if not transaction_id:
                raise PipelineError("Workspace changes requires a transaction ID")
            result = {"action": action, **get_transaction_summary(transaction_id)}
            tags = ["changes_pending" if result["pending"] else "changes_resolved"]
        elif action == "review_transaction":
            from harness_editor.change_tracker import begin_transaction, end_transaction, get_transaction_summary, resolve_transaction

            transaction_id = inputs.get("transaction_id", resolve_reference(node.get("transaction_id", "$ctx._change_transaction"), self.ctx))
            if not transaction_id:
                raise PipelineError("Workspace review requires a transaction ID")
            summary = get_transaction_summary(transaction_id)
            if summary["pending"]:
                self.ctx.emit("changes_review_required", summary)
                if getattr(self.ctx.harness, "_non_interactive", False):
                    decision = str(node.get("pending_policy", "reject"))
                else:
                    decision = str(self.ctx.get_input() or "").strip().lower()
                if decision in {"accept", "accepted", "approve", "approved", "accept_all", "yes", "y"}:
                    resolve_transaction(transaction_id, "accept")
                elif decision in {"reject", "rejected", "reject_all", "no", "n"}:
                    resolve_transaction(transaction_id, "reject", "transaction review")
                else:
                    summary = get_transaction_summary(transaction_id)
                    if summary["pending"]:
                        raise PipelineError(f"transaction still has {summary['pending']} pending hunks")
            result = {"action": action, **get_transaction_summary(transaction_id)}
            end_transaction(transaction_id)
            self.ctx.change_transaction_id = self.ctx.default_change_transaction_id
            begin_transaction(self.ctx.change_transaction_id)
            self.ctx.data["_change_transaction"] = self.ctx.change_transaction_id
            tags = [{"accepted": "changes_accepted", "rejected": "changes_rejected", "partial": "changes_partial"}.get(result["status"], "changes_resolved")]
        elif action == "rollback_transaction":
            from harness_editor.change_tracker import begin_transaction, end_transaction, get_transaction_summary, revert_all

            transaction_id = inputs.get("transaction_id", resolve_reference(node.get("transaction_id", "$ctx._change_transaction"), self.ctx))
            if not transaction_id:
                raise PipelineError("Workspace rollback requires a transaction ID")
            reverted = revert_all(transaction_id)
            result = {"action": action, "reverted_files": reverted, **get_transaction_summary(transaction_id)}
            end_transaction(transaction_id)
            self.ctx.change_transaction_id = self.ctx.default_change_transaction_id
            begin_transaction(self.ctx.change_transaction_id)
            self.ctx.data["_change_transaction"] = self.ctx.change_transaction_id
            tags = ["transaction_rolled_back"]
        elif action in {"apply_search_replace", "apply_edits"}:
            raw_edits = inputs.get("edits", resolve_reference(node.get("edits", []), self.ctx))
            allowed_paths = inputs.get(
                "allowed_paths",
                resolve_reference(node.get("allowed_paths", []), self.ctx),
            )
            result = self._apply_search_replace_edits(raw_edits, allowed_paths, node)
            if result["failed"] and result["applied"]:
                tags = ["edits_partial"]
            elif result["failed"]:
                tags = ["edits_failed"]
            elif result["applied"]:
                tags = ["edits_applied"]
            else:
                tags = ["no_edits"]
        elif action == "mkdir":
            requested = inputs.get("target", resolve_reference(node.get("target", node.get("path")), self.ctx))
            if not requested:
                raise PipelineError("Workspace mkdir requires a target")
            target = self._safe_runtime_path(str(requested))
            target.mkdir(parents=bool(node.get("parents", True)), exist_ok=bool(node.get("exist_ok", True)))
            result = {"action": action, "path": self._workspace_relative(target)}
            tags = ["workspace_ready"]
        elif action in {"copy", "publish"}:
            raw_source = inputs.get("source", resolve_reference(node.get("source"), self.ctx))
            raw_target = inputs.get("target", resolve_reference(node.get("target"), self.ctx))
            if not raw_source or not raw_target:
                raise PipelineError("Workspace copy requires source and target")
            source = self._safe_runtime_path(str(raw_source))
            target = self._safe_runtime_path(str(raw_target))
            if not source.exists():
                raise PipelineError(f"Workspace copy source does not exist: {source}")
            if source.is_dir() and (source == target or source in target.parents):
                raise PipelineError("Workspace copy target cannot be inside its source directory")
            overwrite = bool(node.get("overwrite", False))
            if target.exists() and not overwrite:
                raise PipelineError(f"Workspace copy target already exists: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, target, dirs_exist_ok=overwrite)
            else:
                shutil.copy2(source, target)
            result = {
                "action": action,
                "source": self._workspace_relative(source),
                "target": self._workspace_relative(target),
            }
            tags = ["workspace_copied" if action == "copy" else "workspace_published"]
        elif action == "measure":
            raw_paths = inputs.get("paths", resolve_reference(node.get("paths", []), self.ctx))
            if isinstance(raw_paths, (str, Path)):
                raw_paths = [raw_paths]
            if not isinstance(raw_paths, (list, tuple)):
                raise PipelineError("Workspace measure paths must be a list")
            max_files = max(1, int(node.get("max_files", 500)))
            max_total_bytes = max(1, int(node.get("max_total_bytes", 20_000_000)))
            excluded = set(node.get("exclude_dirs", [".git", ".egoagent", "__pycache__", "node_modules"]))
            measured_paths = []
            file_count = 0
            total_bytes = 0
            truncated = False
            seen = set()
            for raw_path in raw_paths:
                target = self._safe_runtime_path(str(raw_path or "."))
                measured_paths.append(self._workspace_relative(target))
                candidates = [target] if target.is_file() else (target.rglob("*") if target.is_dir() else [])
                for path in candidates:
                    try:
                        if not path.is_file() or path.is_symlink():
                            continue
                        relative = path.relative_to(self.ctx.workspace)
                        if any(part in excluded for part in relative.parts):
                            continue
                        resolved = path.resolve()
                        if resolved in seen:
                            continue
                        seen.add(resolved)
                        size = max(0, int(path.stat().st_size))
                    except (OSError, ValueError):
                        continue
                    file_count += 1
                    total_bytes += size
                    if file_count >= max_files or total_bytes >= max_total_bytes:
                        truncated = True
                        break
                if truncated:
                    break
            result = {
                "action": action,
                "paths": measured_paths,
                "files": file_count,
                "bytes": min(total_bytes, max_total_bytes),
                "truncated": truncated,
            }
            tags = ["scope_measured" if file_count else "scope_empty"]
        elif action == "list":
            raw_base = inputs.get("path", resolve_reference(node.get("path", "."), self.ctx))
            base = self._safe_runtime_path(str(raw_base or "."))
            patterns = inputs.get("patterns", resolve_reference(node.get("patterns", ["**/*"]), self.ctx))
            files = self._collect_process_artifacts(base, patterns)
            result = {"action": action, "path": self._workspace_relative(base), "files": files}
            tags = ["workspace_listed"]
        elif action in {"read_text", "read_json", "read_binary"}:
            raw_path = inputs.get("path", resolve_reference(node.get("path"), self.ctx))
            if not raw_path:
                raise PipelineError(f"Workspace {action} requires a path")
            path = self._safe_runtime_path(str(raw_path))
            allow_missing = bool(node.get("allow_missing", False))
            if not path.exists():
                if not allow_missing:
                    raise PipelineError(f"Workspace file does not exist: {path}")
                value = resolve_reference(node.get("default", {} if action == "read_json" else ""), self.ctx)
                result = {
                    "action": action,
                    "path": self._workspace_relative(path),
                    "exists": False,
                    "size": 0,
                    "truncated": False,
                    "text": "" if action in {"read_json", "read_binary"} else str(value or ""),
                    "data": str(value or "") if action == "read_binary" else None,
                    "structured": copy.deepcopy(value) if action == "read_json" else None,
                }
                tags = ["workspace_missing"]
            else:
                if not path.is_file():
                    raise PipelineError(f"Workspace read target is not a file: {path}")
                max_bytes = max(1, int(node.get("max_bytes", 1_000_000)))
                try:
                    payload = path.read_bytes()
                except OSError as error:
                    raise PipelineError(f"cannot read Workspace file {path}: {error}") from error
                truncated = len(payload) > max_bytes
                if truncated and (action in {"read_json", "read_binary"} or not node.get("truncate", False)):
                    raise PipelineError(f"Workspace file exceeds max_bytes ({max_bytes}): {path}")
                selected = payload[:max_bytes] if truncated else payload
                encoding = str(node.get("encoding", "utf-8"))
                if action == "read_binary":
                    text_value = ""
                    binary_value = base64.b64encode(selected).decode("ascii")
                else:
                    binary_value = None
                    try:
                        text_value = selected.decode(encoding)
                    except UnicodeError as error:
                        raise PipelineError(f"cannot decode Workspace file {path} as {encoding}: {error}") from error
                structured = None
                if action == "read_json":
                    try:
                        structured = json.loads(text_value)
                    except ValueError as error:
                        raise PipelineError(f"Workspace JSON is invalid at {path}: {error}") from error
                result = {
                    "action": action,
                    "path": self._workspace_relative(path),
                    "exists": True,
                    "size": len(payload),
                    "truncated": truncated,
                    "text": text_value,
                    "data": binary_value,
                    "structured": structured,
                }
                tags = ["workspace_read"]
        elif action == "write_binary":
            from harness_editor.change_tracker import record_binary_change

            raw_path = inputs.get("path", resolve_reference(node.get("path"), self.ctx))
            if not raw_path:
                raise PipelineError("Workspace write_binary requires a path")
            path = self._safe_runtime_path(str(raw_path))
            if path.exists() and not path.is_file():
                raise PipelineError(f"Workspace binary target is not a file: {path}")
            if path.exists() and not node.get("overwrite", False):
                raise PipelineError(f"Workspace binary target already exists: {path}")
            try:
                old_bytes = path.read_bytes() if path.is_file() else None
            except OSError as error:
                raise PipelineError(f"cannot read Workspace binary target {path}: {error}") from error
            raw_value = inputs.get("data", inputs.get("value", resolve_reference(node.get("data", node.get("value", "")), self.ctx)))
            binary_encoding = str(node.get("binary_encoding", "base64")).lower()
            try:
                if isinstance(raw_value, bytes):
                    new_bytes = raw_value
                elif binary_encoding == "hex":
                    new_bytes = bytes.fromhex(str(raw_value))
                elif binary_encoding in {"utf8", "utf-8", "text"}:
                    new_bytes = str(raw_value).encode("utf-8")
                else:
                    new_bytes = base64.b64decode(str(raw_value), validate=True)
            except (ValueError, TypeError) as error:
                raise PipelineError(f"Workspace binary payload is invalid {binary_encoding}: {error}") from error
            max_bytes = max(1, int(node.get("max_bytes", 5_000_000)))
            if len(new_bytes) > max_bytes:
                raise PipelineError(f"Workspace binary write exceeds max_bytes ({max_bytes}): {path}")
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
            try:
                temporary.write_bytes(new_bytes)
                temporary.replace(path)
            except OSError as error:
                raise PipelineError(f"cannot write Workspace binary file {path}: {error}") from error
            finally:
                temporary.unlink(missing_ok=True)
            if node.get("track_change", True):
                transaction_id = resolve_reference(node.get("transaction_id", "$ctx._change_transaction"), self.ctx)
                record_binary_change(path, old_bytes, new_bytes, action, transaction_id=transaction_id)
            result = {
                "action": action,
                "path": self._workspace_relative(path),
                "size": len(new_bytes),
                "sha256": hashlib.sha256(new_bytes).hexdigest(),
                "tracked": bool(node.get("track_change", True)),
            }
            tags = ["workspace_written"]
        elif action in {"write_text", "write_json"}:
            from harness_editor.change_tracker import record_change

            raw_path = inputs.get("path", resolve_reference(node.get("path"), self.ctx))
            if not raw_path:
                raise PipelineError(f"Workspace {action} requires a path")
            path = self._safe_runtime_path(str(raw_path))
            if path.exists() and not path.is_file():
                raise PipelineError(f"Workspace write target is not a file: {path}")
            if path.exists() and not node.get("overwrite", False) and not node.get("append", False):
                raise PipelineError(f"Workspace write target already exists: {path}")
            old_text = ""
            if path.exists():
                try:
                    old_text = path.read_text(encoding=str(node.get("encoding", "utf-8")))
                except (OSError, UnicodeError) as error:
                    raise PipelineError(f"cannot read Workspace write target {path}: {error}") from error
            raw_value = inputs.get("value", inputs.get("text", resolve_reference(node.get("value", node.get("text", "")), self.ctx)))
            if action == "write_json":
                new_text = json.dumps(raw_value, ensure_ascii=False, indent=max(0, int(node.get("indent", 2))))
                if node.get("trailing_newline", True):
                    new_text += "\n"
                structured = copy.deepcopy(raw_value)
            else:
                new_text = str(raw_value or "")
                structured = None
            if node.get("append", False):
                new_text = old_text + new_text
            encoded = new_text.encode(str(node.get("encoding", "utf-8")))
            max_bytes = max(1, int(node.get("max_bytes", 5_000_000)))
            if len(encoded) > max_bytes:
                raise PipelineError(f"Workspace write exceeds max_bytes ({max_bytes}): {path}")
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
            try:
                temporary.write_bytes(encoded)
                temporary.replace(path)
            except OSError as error:
                raise PipelineError(f"cannot write Workspace file {path}: {error}") from error
            finally:
                if temporary.exists():
                    try:
                        temporary.unlink()
                    except OSError:
                        pass
            if node.get("track_change", True):
                transaction_id = resolve_reference(node.get("transaction_id", "$ctx._change_transaction"), self.ctx)
                record_change(path, old_text, new_text, action, transaction_id=transaction_id)
            result = {
                "action": action,
                "path": self._workspace_relative(path),
                "size": len(encoded),
                "text": new_text,
                "structured": structured,
                "tracked": bool(node.get("track_change", True)),
            }
            tags = ["workspace_written"]
        elif action == "delete":
            from harness_editor.change_tracker import record_binary_change, record_change

            raw_path = inputs.get("path", resolve_reference(node.get("path"), self.ctx))
            if not raw_path:
                raise PipelineError("Workspace delete requires a path")
            path = self._safe_runtime_path(str(raw_path))
            if not path.is_file():
                if node.get("allow_missing", False):
                    result = {"action": action, "path": self._workspace_relative(path), "deleted": False, "tracked": False}
                    tags = ["workspace_missing"]
                else:
                    raise PipelineError(f"Workspace delete target is not a file: {path}")
            else:
                try:
                    old_bytes = path.read_bytes()
                    path.unlink()
                except OSError as error:
                    raise PipelineError(f"cannot delete Workspace file {path}: {error}") from error
                tracked = bool(node.get("track_change", True))
                if tracked:
                    transaction_id = resolve_reference(node.get("transaction_id", "$ctx._change_transaction"), self.ctx)
                    try:
                        old_text = old_bytes.decode(str(node.get("encoding", "utf-8")))
                    except UnicodeError:
                        record_binary_change(path, old_bytes, None, action, transaction_id=transaction_id)
                    else:
                        record_change(path, old_text, None, action, transaction_id=transaction_id)
                result = {"action": action, "path": self._workspace_relative(path), "deleted": True, "tracked": tracked}
                tags = ["workspace_deleted"]
        elif action in {"move", "rename"}:
            from harness_editor.change_tracker import record_move

            raw_source = inputs.get("source", resolve_reference(node.get("source", node.get("path")), self.ctx))
            raw_target = inputs.get("target", resolve_reference(node.get("target"), self.ctx))
            if not raw_source or not raw_target:
                raise PipelineError("Workspace move requires source and target")
            source = self._safe_runtime_path(str(raw_source))
            target = self._safe_runtime_path(str(raw_target))
            if not source.is_file():
                raise PipelineError(f"Workspace move source is not a file: {source}")
            tracked = bool(node.get("track_change", True))
            if target.exists():
                if tracked:
                    raise PipelineError("Tracked Workspace move cannot overwrite an existing target")
                if not node.get("overwrite", False):
                    raise PipelineError(f"Workspace move target already exists: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                source.replace(target)
            except OSError as error:
                raise PipelineError(f"cannot move Workspace file {source} to {target}: {error}") from error
            if tracked:
                transaction_id = resolve_reference(node.get("transaction_id", "$ctx._change_transaction"), self.ctx)
                record_move(source, target, action, transaction_id=transaction_id)
            result = {
                "action": action,
                "source": self._workspace_relative(source),
                "target": self._workspace_relative(target),
                "tracked": tracked,
            }
            tags = ["workspace_moved"]
        elif action == "snapshot":
            raw_paths = inputs.get("paths", resolve_reference(node.get("paths", []), self.ctx))
            result = self._snapshot_workspace(raw_paths, node.get("label", self.ctx.current_node), node)
            tags = ["workspace_snapshotted"]
        elif action == "restore":
            raw_archive = inputs.get("path", resolve_reference(node.get("path"), self.ctx))
            result = self._restore_workspace(raw_archive, node)
            tags = ["workspace_restored"]
        else:
            raise PipelineError(f"unknown Workspace action: {action}")
        output_var = node.get("output_var", "workspace_result")
        if output_var:
            set_path(self.ctx.data, output_var, copy.deepcopy(result))
        self.ctx.emit("workspace", {"action": action, **{key: value for key, value in result.items() if key in {"path", "source", "target", "count", "backup_path"}}})
        return NodeOutcome({**result, "value": result}, tags)

    def _apply_search_replace_edits(self, raw_edits: Any, raw_allowed_paths: Any, node: dict) -> dict:
        """Apply parsed edit blocks with confinement, rollback and per-hunk review data."""
        from harness_editor.change_tracker import record_change

        if not isinstance(raw_edits, list):
            raise PipelineError("Workspace apply_search_replace requires an edits list")
        if raw_allowed_paths is None:
            raw_allowed_paths = []
        if not isinstance(raw_allowed_paths, list):
            raise PipelineError("Workspace apply_search_replace allowed_paths must be a list")

        allowed_files: list[Path] = []
        for raw_path in raw_allowed_paths:
            candidate = self._safe_runtime_path(str(raw_path))
            if candidate.is_file():
                allowed_files.append(candidate)
        allowed_files = list(dict.fromkeys(allowed_files))

        original_contents: dict[Path, Optional[str]] = {}
        staged_contents: dict[Path, str] = {}
        applied: list[dict] = []
        failed: list[dict] = []

        def current_content(path: Path) -> Optional[str]:
            if path in staged_contents:
                return staged_contents[path]
            if path not in original_contents:
                if path.exists() and not path.is_file():
                    raise PipelineError(f"edit target is not a file: {self._workspace_relative(path)}")
                try:
                    if path.exists():
                        with path.open("r", encoding="utf-8", newline="") as stream:
                            original_contents[path] = stream.read()
                    else:
                        original_contents[path] = None
                except (OSError, UnicodeError) as error:
                    raise PipelineError(f"cannot read edit target {path}: {error}") from error
            return original_contents[path]

        for index, raw_edit in enumerate(raw_edits):
            if not isinstance(raw_edit, dict):
                raise PipelineError(f"edit {index + 1} must be an object")
            requested = raw_edit.get("path", raw_edit.get("file_path"))
            if not requested:
                raise PipelineError(f"edit {index + 1} has no path")
            search = raw_edit.get("search", raw_edit.get("old_string", ""))
            replace = raw_edit.get("replace", raw_edit.get("new_string", ""))
            if not isinstance(search, str) or not isinstance(replace, str):
                raise PipelineError(f"edit {index + 1} search and replace values must be strings")
            requested_path = self._safe_runtime_path(str(requested))
            candidates = [requested_path]
            if search.strip() and bool(node.get("fallback_to_allowed_paths", True)):
                candidates.extend(path for path in allowed_files if path != requested_path)

            matched_path: Optional[Path] = None
            matched_content: Optional[str] = None
            for candidate in candidates:
                content = current_content(candidate)
                if content is None and search.strip():
                    continue
                updated = _aider_replace_chunk(content, search, replace)
                if updated is not None:
                    matched_path = candidate
                    matched_content = updated
                    break

            if matched_path is None or matched_content is None:
                content = current_content(requested_path) or ""
                failed.append(
                    {
                        "index": index,
                        "path": self._workspace_relative(requested_path),
                        "search": search,
                        "replace": replace,
                        "reason": "SEARCH block did not match",
                        "similar": _find_similar_lines(search, content),
                    }
                )
                continue

            staged_contents[matched_path] = matched_content
            applied.append(
                {
                    "index": index,
                    "path": self._workspace_relative(matched_path),
                    "requested_path": self._workspace_relative(requested_path),
                }
            )

        atomic = bool(node.get("atomic", False))
        paths_to_write = [] if atomic and failed else [
            path for path, content in staged_contents.items()
            if content != (original_contents.get(path) or "") or original_contents.get(path) is None
        ]
        written: list[Path] = []
        try:
            for path in paths_to_write:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("w", encoding="utf-8", newline="") as stream:
                    stream.write(staged_contents[path])
                written.append(path)
        except (OSError, UnicodeError) as error:
            for path in reversed(written):
                old_content = original_contents.get(path)
                try:
                    if old_content is None:
                        path.unlink(missing_ok=True)
                    else:
                        with path.open("w", encoding="utf-8", newline="") as stream:
                            stream.write(old_content)
                except OSError:
                    pass
            raise PipelineError(f"failed to write edit transaction; written files were rolled back: {error}") from error

        transaction_id = resolve_reference(
            node.get("transaction_id", "$ctx._change_transaction"),
            self.ctx,
        )
        for path in written:
            record_change(
                path,
                original_contents.get(path),
                staged_contents[path],
                "apply_search_replace",
                transaction_id=transaction_id,
            )

        if atomic and failed:
            for item in applied:
                item["committed"] = False
            applied_count = 0
        else:
            for item in applied:
                item["committed"] = True
            applied_count = len(applied)
        feedback = _format_aider_edit_failures(failed, applied_count)
        result = {
            "action": "apply_search_replace",
            "status": "partial" if failed and applied_count else "failed" if failed else "applied",
            "atomic": atomic,
            "applied": applied_count,
            "failed": len(failed),
            "edits": applied,
            "failures": failed,
            "files": [self._workspace_relative(path) for path in written],
            "feedback": feedback,
        }
        self.ctx.emit(
            "workspace_edits",
            {"status": result["status"], "applied": applied_count, "failed": len(failed), "files": result["files"]},
        )
        return result

    def _snapshot_workspace(self, raw_paths: Any, label: Any, node: dict) -> dict:
        if not isinstance(raw_paths, list) or not raw_paths:
            raise PipelineError("Workspace snapshot requires a non-empty paths list")
        workspace = Path(self.ctx.harness.workspace or self.ctx.harness.dir).resolve()
        snapshot_root = self._safe_runtime_path(self.ctx.graph.get("snapshot_dir", ".egoagent/snapshots"))
        snapshot_root.mkdir(parents=True, exist_ok=True)
        safe_label = "".join(char if char.isalnum() or char in "-_" else "_" for char in str(label or "workspace"))[:60]
        archive = snapshot_root / f"{self.ctx.run_id}-{safe_label}-{uuid.uuid4().hex[:8]}.zip"
        ignores = list(node.get("ignore", [".git/**", "node_modules/**", ".egoagent/snapshots/**"]))
        max_files = max(1, int(node.get("max_files", 20000)))
        max_bytes = max(1, int(node.get("max_bytes", 1_000_000_000)))
        roots: list[str] = []
        files: list[str] = []
        total_bytes = 0
        candidates: list[Path] = []
        for requested in raw_paths:
            path = self._safe_runtime_path(str(requested))
            roots.append(self._workspace_relative(path))
            if not path.exists():
                continue
            candidates.extend([path] if path.is_file() else (item for item in path.rglob("*") if item.is_file()))
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for path in sorted(set(candidates)):
                resolved = path.resolve()
                if path.is_symlink() or (resolved != workspace and workspace not in resolved.parents):
                    continue
                relative = resolved.relative_to(workspace).as_posix()
                if any(fnmatch.fnmatch(relative, pattern) for pattern in ignores):
                    continue
                size = resolved.stat().st_size
                if len(files) >= max_files or total_bytes + size > max_bytes:
                    raise PipelineError("Workspace snapshot exceeded its file or byte limit")
                bundle.write(resolved, relative)
                files.append(relative)
                total_bytes += size
            manifest = {"version": 1, "roots": roots, "files": files, "created_at": time.time()}
            bundle.writestr(".egoagent-workspace-manifest.json", json.dumps(manifest, ensure_ascii=False))
        return {
            "action": "snapshot",
            "path": self._workspace_relative(archive),
            "roots": roots,
            "files": files,
            "count": len(files),
            "bytes": total_bytes,
        }

    def _restore_workspace(self, raw_archive: Any, node: dict) -> dict:
        if not raw_archive:
            raise PipelineError("Workspace restore requires a snapshot path")
        archive = self._safe_runtime_path(str(raw_archive))
        if not archive.is_file() or archive.suffix.lower() != ".zip":
            raise PipelineError(f"Workspace snapshot is not a zip file: {archive}")
        workspace = Path(self.ctx.harness.workspace or self.ctx.harness.dir).resolve()
        with zipfile.ZipFile(archive, "r") as bundle:
            try:
                manifest = json.loads(bundle.read(".egoagent-workspace-manifest.json"))
            except (KeyError, ValueError) as error:
                raise PipelineError("Workspace snapshot has no valid manifest") from error
            roots = manifest.get("roots", [])
            backup_path = None
            if node.get("backup_before_restore", True) and roots:
                backup = self._snapshot_workspace(roots, "before-restore", {**node, "ignore": [".git/**", "node_modules/**", ".egoagent/snapshots/**"]})
                backup_path = backup["path"]
            restored: list[str] = []
            for member in bundle.infolist():
                if member.filename == ".egoagent-workspace-manifest.json" or member.is_dir():
                    continue
                relative = Path(member.filename)
                if relative.is_absolute() or ".." in relative.parts:
                    raise PipelineError(f"unsafe Workspace snapshot member: {member.filename}")
                target = (workspace / relative).resolve()
                if target != workspace and workspace not in target.parents:
                    raise PipelineError(f"Workspace restore target escapes workspace: {member.filename}")
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
                restored.append(relative.as_posix())
        return {
            "action": "restore",
            "path": self._workspace_relative(archive),
            "backup_path": backup_path,
            "files": restored,
            "count": len(restored),
        }

    def _workspace_relative(self, path: Path) -> str:
        workspace = Path(self.ctx.harness.workspace or self.ctx.harness.dir).resolve()
        return path.resolve().relative_to(workspace).as_posix() or "."

    def _data_store(self, scope: str, node: dict) -> tuple[dict, Optional[Callable[[dict], None]]]:
        if scope == "run":
            return self.ctx.data, None
        if scope == "session":
            return self.ctx.harness.session.state, None
        if scope != "file":
            raise PipelineError(f"unknown data scope: {scope}")
        path = self._safe_runtime_path(node.get("path", ".egoagent/dag-data.json"))
        if path.exists():
            try:
                store = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                raise PipelineError(f"cannot read data file {path}: {error}") from error
        else:
            store = {}
        if not isinstance(store, dict):
            raise PipelineError("persistent DAG data file must contain a JSON object")

        def save(value: dict) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(path)

        return store, save

    def _loop_node(self, node_id: str, node: dict, inputs: dict) -> NodeOutcome:
        list_var = node.get("list_var", "")
        items = inputs.get("items")
        if items is None:
            items = get_path(self.ctx.data, list_var, [])
        if not isinstance(items, list):
            items = []
        item_var = node.get("item_var", "_item")
        counter_var = node.get("counter_var", "_i")
        max_count = int(resolve_reference(node.get("max_count", 100), self.ctx))
        stack = self.ctx.data.setdefault("_loop_stack", [])
        state = stack[-1] if stack and stack[-1].get("loop_node") == node_id else None
        if state is None:
            state = {"loop_node": node_id, "index": 0, "results": []}
            stack.append(state)
        else:
            break_when = node.get("break_when")
            if break_when:
                expression = break_when[5:] if isinstance(break_when, str) and break_when.startswith("expr:") else break_when
                if bool(evaluate_expression(str(expression), self.ctx.variables())):
                    results = state["results"]
                    result_key = node.get("result_var", f"{list_var}_results")
                    if result_key:
                        self.ctx.data[result_key] = results
                    stack.pop()
                    return NodeOutcome({"items": items, "results": results, "count": state["index"], "broken": True}, ["loop_break"])
            if self.ctx.data.get("_loop_result") is not None:
                state["results"].append(self.ctx.data.pop("_loop_result"))
            state["index"] += 1
        index = state["index"]
        if index < len(items) and index < max_count:
            self.ctx.data[item_var] = items[index]
            self.ctx.data[counter_var] = index
            self.ctx.emit("loop", {"var": list_var, "index": index, "total": len(items)})
            return NodeOutcome({"item": items[index], "index": index}, ["loop_continue"], next_node=node.get("body_start"))
        results = state["results"]
        result_key = node.get("result_var", f"{list_var}_results")
        if result_key:
            self.ctx.data[result_key] = results
        stack.pop()
        return NodeOutcome({"items": items, "results": results, "count": min(len(items), max_count)}, ["loop_done"])

    def _parallel_node(self, node: dict, inputs: dict) -> NodeOutcome:
        raw_branches = node.get("branches", [])
        if not raw_branches:
            return NodeOutcome({"branches": []}, ["parallel_done"], next_node=node.get("join"))
        branches = []
        for index, raw in enumerate(raw_branches):
            spec = raw if isinstance(raw, dict) else {"start": raw}
            branches.append({"name": spec.get("name", f"branch_{index + 1}"), **spec})
        base_messages = list(self.ctx.harness.session.messages)
        base_full_messages = list(self.ctx.harness.session.full_messages)
        base_state = copy.deepcopy(self.ctx.harness.session.state)
        base_data = copy.deepcopy(self.ctx.data)
        join_node = node.get("join")
        max_workers = max(1, min(int(node.get("max_workers", len(branches))), len(branches)))

        def run_branch(index: int, spec: dict) -> dict:
            from harness import Session

            branch_harness = copy.copy(self.ctx.harness)
            branch_harness.children = []
            branch_harness.parent = self.ctx.harness
            branch_harness.session = Session(workspace=self.ctx.harness.workspace, save_dir=None)
            branch_harness.session.messages = copy.deepcopy(base_messages)
            branch_harness.session.full_messages = copy.deepcopy(base_full_messages)
            branch_harness.session.state = copy.deepcopy(base_state)
            events: list[tuple[str, dict]] = []
            branch_data = copy.deepcopy(base_data)
            branch_data.update(resolve_reference(spec.get("data", {}), self.ctx))
            runner = PipelineRunner(
                branch_harness,
                on_output=lambda event, payload: events.append((event, payload)),
                get_input=lambda: None,
                is_running=self.ctx.is_running,
                initial_data=branch_data,
                start=spec["start"],
                stop_at={join_node} if join_node else set(),
                emit_done=False,
                inject_workspace_preview=False,
            )
            try:
                child = runner.run()
                error = None
            except BaseException as exc:
                child = runner.ctx
                error = {"type": type(exc).__name__, "message": str(exc)}
            return {
                "index": index,
                "name": spec["name"],
                "result": child.result,
                "last": child.last_output,
                "data": child.data,
                "outputs": child.node_outputs,
                "messages": branch_harness.session.messages[len(base_messages):],
                "full_messages": branch_harness.session.full_messages[len(base_full_messages):],
                "events": events,
                "stats": child.stats,
                "error": error,
            }

        collected: list[dict] = []
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=f"dag-{self.ctx.run_id[:6]}") as executor:
            futures = {executor.submit(run_branch, index, spec): spec for index, spec in enumerate(branches)}
            for future in as_completed(futures):
                if self.ctx.cancelled():
                    for pending in futures:
                        pending.cancel()
                    raise PipelineCancelled("parallel execution was cancelled")
                collected.append(future.result())
        collected.sort(key=lambda item: item["index"])
        failures = []
        for branch in collected:
            self.ctx.stats.add(branch.pop("stats"))
            self.ctx.harness.session.messages.extend(branch.pop("messages"))
            self.ctx.harness.session.full_messages.extend(branch.pop("full_messages"))
            for event, payload in branch.pop("events"):
                if event not in {"done"}:
                    self.ctx.emit(event, {**payload, "branch": branch["name"]})
            if branch.get("error"):
                failures.append({"name": branch["name"], **branch["error"]})
        if failures and node.get("fail_fast", True):
            raise PipelineError(f"parallel branches failed: {failures}")
        output_var = node.get("output_var", "parallel_results")
        self.ctx.data[output_var] = collected
        self._apply_reducers(base_data, collected)
        return NodeOutcome({"branches": collected, "errors": failures, "value": collected}, ["parallel_done"], next_node=join_node)

    def _apply_reducers(self, base_data: dict, branches: list[dict]) -> None:
        """Deterministically merge declared branch-local state back into the run."""
        reducers = self.ctx.graph.get("reducers", {})
        for path, raw_spec in reducers.items():
            spec = raw_spec if isinstance(raw_spec, dict) else {"strategy": raw_spec}
            strategy = spec.get("strategy", "override")
            base = copy.deepcopy(get_path(base_data, path))
            values = [copy.deepcopy(get_path(branch.get("data", {}), path)) for branch in branches]
            values = [value for value in values if value is not None]
            if not values:
                continue
            if strategy in {"append", "extend", "unique"}:
                result = list(base) if isinstance(base, list) else ([] if base is None else [base])
                for value in values:
                    additions = value if isinstance(value, list) else [value]
                    if isinstance(base, list) and additions[:len(base)] == base:
                        additions = additions[len(base):]
                    for item in additions:
                        if strategy != "unique" or item not in result:
                            result.append(item)
            elif strategy == "merge":
                result = dict(base) if isinstance(base, dict) else {}
                for value in values:
                    if isinstance(value, dict):
                        result.update(value)
            elif strategy == "concat":
                separator = str(spec.get("separator", "\n"))
                result = separator.join(str(value) for value in values)
            elif strategy == "first":
                result = values[0]
            else:
                result = values[-1]
            set_path(self.ctx.data, path, result)
            self.ctx.emit("state_reduced", {"path": path, "strategy": strategy, "branches": len(values)})

    def _map_node(self, node: dict, inputs: dict) -> NodeOutcome:
        items = inputs.get("items")
        if items is None:
            source = node.get("source")
            if source is not None:
                items = resolve_reference(source, self.ctx)
            else:
                items = get_path(self.ctx.data, node.get("list_var", "items"), [])
        if not isinstance(items, list):
            raise PipelineError("Map node input must be a list")
        max_count = min(
            len(items),
            max(0, int(resolve_reference(node.get("max_count", len(items)), self.ctx))),
        )
        item_var = node.get("item_var", "_item")
        index_var = node.get("counter_var", node.get("index_var", "_i"))
        body_start = node.get("body_start") or node.get("start")
        branches = [
            {
                "name": f"item_{index}",
                "start": body_start,
                "data": {item_var: item, index_var: index},
            }
            for index, item in enumerate(items[:max_count])
        ]
        parallel_config = dict(node)
        parallel_config["branches"] = branches
        parallel_config["output_var"] = node.get("output_var", "map_results")
        outcome = self._parallel_node(parallel_config, inputs)
        outcome.tags = ["map_done"]
        outcome.output["items"] = items[:max_count]
        return outcome

    def _join_node(self, node: dict, inputs: dict) -> NodeOutcome:
        source = inputs.get("values")
        if source is None:
            source = resolve_reference(node.get("source", "$last.branches"), self.ctx)
        strategy = node.get("strategy", "list")
        values = source if isinstance(source, list) else [source]

        def unwrap(value):
            while isinstance(value, dict):
                next_value = value
                for key in ("result", "last", "value"):
                    if key in value and value[key] is not None:
                        next_value = value[key]
                        break
                if next_value is value:
                    break
                value = next_value
            return value

        if strategy == "list":
            result = values
        elif strategy == "values":
            result = [copy.deepcopy(unwrap(value)) for value in values]
        elif strategy == "flatten":
            result = []
            for value in values:
                candidate = unwrap(value)
                if isinstance(candidate, list):
                    result.extend(copy.deepcopy(candidate))
                else:
                    result.append(copy.deepcopy(candidate))
        elif strategy == "concat":
            separator = node.get("separator", "\n")
            extracted = [str(unwrap(value)) for value in values]
            result = separator.join(extracted)
        elif strategy == "merge":
            result = {}
            for value in values:
                candidate = value.get("result", value) if isinstance(value, dict) else value
                if isinstance(candidate, dict):
                    result.update(candidate)
        elif strategy == "first":
            result = values[0] if values else None
        elif strategy == "last":
            result = values[-1] if values else None
        else:
            raise PipelineError(f"unknown Join strategy: {strategy}")
        output_var = node.get("output_var", "joined")
        self.ctx.data[output_var] = result
        return NodeOutcome({"value": result, "text": result if isinstance(result, str) else None}, ["joined"])

    def _approval_node(self, node: dict, inputs: dict) -> NodeOutcome:
        prompt = inputs.get("prompt") or resolve_reference(node.get("prompt_text", "Approve this step? [y/N]"), self.ctx)
        default = node.get("default", "rejected")
        if "data" in inputs:
            review_data = inputs["data"]
        else:
            review_data = resolve_reference(node.get("data"), self.ctx)
        editable = bool(node.get("editable", True))
        review_name = resolve_reference(node.get("name", "data"), self.ctx)
        approval_id = str(node.get("approval_id") or f"{self.ctx.current_node}:{review_name}")
        self.ctx.pending_approvals[approval_id] = {
            "id": approval_id,
            "kind": "node",
            "node": self.ctx.current_node,
            "name": review_name,
            "prompt": prompt,
            "data": _preview_value(review_data),
            "editable": editable,
            "choices": copy.deepcopy(node.get("choices", ["approved", "rejected"])),
            "default": default,
        }
        if self.auto_checkpoint:
            self._save_checkpoint(
                f"approval-{self.ctx.current_node}",
                next_node=self.ctx.current_node,
                phase="in_flight",
                operation="人工审批",
            )
        self.ctx.emit(
            "approval_required",
            {
                "approval_id": approval_id,
                "prompt": prompt,
                "name": review_name,
                "data": _preview_value(review_data),
                "editable": editable,
                "choices": node.get("choices", ["approved", "rejected"]),
                "default": default,
            },
        )
        answer = self._approval_answer(str(default), approval_id=approval_id)
        if isinstance(answer, str) and answer.lstrip().startswith("{"):
            try:
                answer = json.loads(answer)
            except ValueError:
                pass
        review_message = ""
        if isinstance(answer, dict):
            raw_decision = answer.get("decision", answer.get("answer", default))
            review_message = str(answer.get("message", ""))
            if editable and "data" in answer:
                review_data = answer["data"]
        else:
            raw_decision = answer
        self.ctx.pending_approvals.pop(approval_id, None)
        normalized = str(raw_decision).strip().lower()
        approved_values = {str(value).lower() for value in node.get("approved_values", ["y", "yes", "approve", "approved", "通过", "同意"])}
        approved = normalized in approved_values or (normalized == "true")
        decision = "approved" if approved else "rejected"
        output_var = node.get("output_var", "approval")
        approval = {
            "decision": decision,
            "answer": answer,
            "data": copy.deepcopy(review_data),
            "message": review_message,
        }
        self.ctx.data[output_var] = approval
        self.ctx.emit(
            "approval",
            {
                "decision": decision,
                "data": _preview_value(review_data),
                "message": review_message,
            },
        )
        return NodeOutcome(
            {
                "decision": decision,
                "answer": answer,
                "value": approved,
                "data": review_data,
                "approved_data": review_data if approved else None,
                "rejected_data": None if approved else review_data,
                "review_message": review_message,
            },
            [decision],
        )

    def _subflow_node(self, node: dict, inputs: dict) -> NodeOutcome:
        if node.get("mode") == "port_graph" or "port_graph" in inputs or "port_graph" in node:
            return self._port_graph_subflow_node(node, inputs)
        from agent_factory import AgentFactory
        from config import CONFIG
        from harness import Harness, Session

        depth = 0
        ancestor = self.ctx.harness
        while ancestor is not None:
            depth += 1
            ancestor = getattr(ancestor, "parent", None)
        if depth >= int(node.get("max_depth", 8)):
            raise PipelineError(f"subflow nesting exceeds max_depth ({node.get('max_depth', 8)})")

        if "pipeline" in inputs:
            inline_pipeline = inputs["pipeline"]
        else:
            raw_inline = node.get("inline_pipeline")
            inline_pipeline = resolve_reference(raw_inline, self.ctx) if isinstance(raw_inline, str) else copy.deepcopy(raw_inline)
        if inline_pipeline is not None:
            if not isinstance(inline_pipeline, dict):
                raise PipelineError("inline subflow pipeline must be an object")
            if "pipeline" in inline_pipeline:
                inline_config = copy.deepcopy(inline_pipeline)
                dynamic_graph = inline_config.get("pipeline")
            else:
                dynamic_graph = copy.deepcopy(inline_pipeline)
                inline_config = {"pipeline": dynamic_graph}
            if not isinstance(dynamic_graph, dict):
                raise PipelineError("inline subflow has no pipeline graph")
            max_nodes = max(1, int(node.get("max_dynamic_nodes", 64)))
            if len(dynamic_graph.get("nodes", {})) > max_nodes:
                raise PipelineError(f"inline subflow exceeds max_dynamic_nodes ({max_nodes})")
            assert_valid_pipeline(dynamic_graph)
            if not node.get("allow_unsafe", False):
                forbidden = {
                    node_id: canonical_op(spec.get("op", ""))
                    for node_id, spec in dynamic_graph.get("nodes", {}).items()
                    if canonical_op(spec.get("op", "")) in {"Python", "进程", "工作区"}
                }
                if forbidden:
                    raise PipelineError(f"inline subflow contains unsafe operations: {forbidden}")
            raw_slots = inputs.get("slots", resolve_reference(node.get("dynamic_slots", inline_config.get("slots", {})), self.ctx))
            if not isinstance(raw_slots, dict):
                raise PipelineError("inline subflow slots must be an object")
            slots = {}
            for slot_name, raw_slot in raw_slots.items():
                slots[str(slot_name)] = (
                    {"description": "Dynamic Identity/EGO role", "required": True, "identity": raw_slot}
                    if isinstance(raw_slot, str)
                    else copy.deepcopy(raw_slot)
                )
            if not slots:
                slots = copy.deepcopy(self.ctx.harness.slots)
            raw_prompts = inputs.get("prompts", resolve_reference(node.get("dynamic_prompts", inline_config.get("prompts", {})), self.ctx))
            if not isinstance(raw_prompts, dict):
                raise PipelineError("inline subflow prompts must be an object")
            name = str(resolve_reference(node.get("dynamic_name", inline_config.get("name", "dynamic_subflow")), self.ctx))
            config = {
                "name": name,
                "description": str(inline_config.get("description", "Validated runtime-generated subflow")),
                "slots": slots,
                "prompts": raw_prompts,
                "return_mode": inline_config.get("return_mode", node.get("result_mode", "last")),
                "pipeline": dynamic_graph,
            }
            sub_harness = copy.copy(self.ctx.harness)
            sub_harness.config = config
            sub_harness.name = name
            sub_harness.slots = slots
            sub_harness.prompts = {
                prompt_name: prompt.get("default", "") if isinstance(prompt, dict) else str(prompt)
                for prompt_name, prompt in raw_prompts.items()
            }
            sub_harness.return_mode = inline_config.get("return_mode", "last")
            sub_harness.agents = {}
            sub_harness.children = []
            sub_harness.hooks = {}
            sub_harness.session = Session(workspace=self.ctx.harness.workspace, save_dir=None)
        else:
            name = resolve_reference(node.get("harness", ""), self.ctx)
            harness_dir = Path(CONFIG["harness_template_repository"]) / str(name)
            if not harness_dir.is_dir():
                raise PipelineError(f"subflow harness not found: {name}")
            sub_harness = Harness(harness_dir, workspace=self.ctx.harness.workspace)
        agent_factory = AgentFactory(identity_roots=(CONFIG["identity_repository"],))
        component = sub_harness.config.get("component", {})
        if component is not None and not isinstance(component, dict):
            raise PipelineError(f"subflow {name!r} component manifest must be an object")
        component = copy.deepcopy(component or {})
        identity_map = node.get("identity_map", {})
        agent_map = node.get("agent_map", {})
        agents = {}
        for slot_name, slot_def in sub_harness.slots.items():
            parent_slot = resolve_reference(agent_map.get(slot_name), self.ctx)
            if parent_slot in self.ctx.harness.agents:
                cloned_agent = _clone_agent_for_slot(self.ctx.harness.agents[parent_slot], slot_name)
                # The child flow addresses tools by its own slot name.  A
                # shallow clone previously kept the parent's public name (for
                # example governor), so a child request for `searcher` was
                # rejected by the executor that still believed it owned
                # `governor`.
                agents[slot_name] = cloned_agent
                continue
            identity_name = identity_map.get(slot_name, slot_def.get("identity"))
            if identity_name:
                identity_name = resolve_reference(identity_name, self.ctx)
                agents[slot_name] = agent_factory.create(
                    self._safe_identity_path(CONFIG["identity_repository"], identity_name),
                    name=slot_name,
                    workspace=self.ctx.workspace,
                )
            elif slot_name in self.ctx.harness.agents:
                cloned_agent = _clone_agent_for_slot(self.ctx.harness.agents[slot_name], slot_name)
                agents[slot_name] = cloned_agent
        sub_harness.set_agents(agents)
        share_session = bool(node.get("share_session", component.get("share_session", False)))
        if share_session:
            # Conversation-affecting components operate on the caller's
            # session only when their manifest or node explicitly declares the
            # effect. Ordinary subflows remain isolated exactly as before.
            sub_harness.session = self.ctx.harness.session
        from subagent_lifecycle import finish_subagent, link_subagent
        link_subagent(
            self.ctx.harness,
            sub_harness,
            share_session=share_session,
            purpose="subdag_component" if component else "subdag",
            agent_bindings={key: getattr(value, "name", key) for key, value in agents.items()},
            identity_bindings={
                key: Path(getattr(getattr(value, "identity", None), "identity_path", "")).name
                for key, value in agents.items()
            },
        )
        initial_message = inputs.get("message") or resolve_reference(node.get("initial_message", ""), self.ctx)
        if initial_message:
            message = {"role": "user", "content": str(initial_message)}
            sub_harness.session.record(message)
            sub_harness.session.record_full(message.copy())
        sub_harness._non_interactive = True
        input_contract = component.get("inputs", {})
        if not isinstance(input_contract, dict):
            raise PipelineError(f"subflow {name!r} component.inputs must be an object")
        component_data: dict[str, Any] = {}
        for port_name, raw_spec in input_contract.items():
            spec = raw_spec if isinstance(raw_spec, dict) else {}
            if "default" in spec:
                component_data[str(port_name)] = copy.deepcopy(spec["default"])
        raw_component_inputs = resolve_reference(node.get("component_inputs", {}), self.ctx)
        if not isinstance(raw_component_inputs, dict):
            raise PipelineError("SubDAG component_inputs must be an object")
        component_data.update(copy.deepcopy(raw_component_inputs))
        raw_data = inputs.get("data", {})
        if not isinstance(raw_data, dict):
            raise PipelineError("Subflow data input must be an object")
        component_data.update(copy.deepcopy(raw_data))
        for port_name, raw_spec in input_contract.items():
            spec = raw_spec if isinstance(raw_spec, dict) else {}
            if spec.get("required") and port_name not in component_data:
                raise PipelineError(f"SubDAG {name!r} is missing required input {port_name!r}")
            if port_name in component_data and isinstance(spec.get("schema"), dict):
                errors = validate_json_schema(component_data[port_name], spec["schema"], f"$.{port_name}")
                if errors:
                    raise PipelineError(f"SubDAG input {port_name!r} is invalid: {'; '.join(errors)}")
        runner = PipelineRunner(
            sub_harness,
            on_output=lambda event, payload: self.ctx.emit(event, {**payload, "subflow": name}),
            get_input=lambda: None,
            is_running=self.ctx.is_running,
            initial_data=component_data,
            emit_done=False,
        )
        try:
            child = runner.run()
        except Exception as error:
            finish_subagent(sub_harness, status="failed", error=error)
            raise
        self.ctx.stats.add(child.stats)
        result_mode = node.get("result_mode", "text")
        result = sub_harness.session.get_result(sub_harness.return_mode)
        if result_mode == "text":
            result = next((message.get("content", "") for message in reversed(sub_harness.session.messages) if message.get("role") == "assistant"), "")
        elif result_mode == "result":
            result = copy.deepcopy(child.result)
        elif result_mode == "data":
            result = copy.deepcopy(child.data)
        elif result_mode != "messages":
            raise PipelineError(f"unknown subflow result_mode: {result_mode}")
        output_var = node.get("output_var", "_sub_result")
        self.ctx.data[output_var] = result
        output_contract = component.get("outputs", {})
        if not isinstance(output_contract, dict):
            raise PipelineError(f"subflow {name!r} component.outputs must be an object")
        component_outputs: dict[str, Any] = {}
        for port_name, raw_spec in output_contract.items():
            spec = raw_spec if isinstance(raw_spec, dict) else {}
            path = str(spec.get("path", port_name))
            if path.startswith("$ctx."):
                path = path[5:]
            value = copy.deepcopy(get_path(child.data, path, spec.get("default")))
            if isinstance(spec.get("schema"), dict):
                errors = validate_json_schema(value, spec["schema"], f"$.{port_name}")
                if errors:
                    raise PipelineError(f"SubDAG output {port_name!r} is invalid: {'; '.join(errors)}")
            component_outputs[str(port_name)] = value
        raw_output_map = node.get("component_outputs", {})
        if not isinstance(raw_output_map, dict):
            raise PipelineError("SubDAG component_outputs must be an object")
        for port_name, target in raw_output_map.items():
            if not isinstance(target, str) or not target:
                continue
            normalized = target[5:] if target.startswith("$ctx.") else target
            set_path(self.ctx.data, normalized, copy.deepcopy(component_outputs.get(port_name)))
        finish_subagent(
            sub_harness,
            status="completed",
            result={"result_mode": result_mode, "component_outputs": component_outputs},
        )
        self.ctx.emit(
            "subdag_component",
            {
                "harness": str(name),
                "component": component.get("display_name", component.get("name", str(name))),
                "inputs": list(component_data),
                "outputs": list(component_outputs),
                "shared_session": share_session,
            },
        )
        return NodeOutcome(
            {
                "value": result,
                "text": result if isinstance(result, str) else None,
                "data": child.data,
                "component_outputs": component_outputs,
            },
            ["subflow_done", "component_done"] if component else ["subflow_done"],
        )

    def _compile_task_port_graph(self, tasks: Any, node: dict) -> dict[str, Any]:
        """Translate the simple planner task format into an event-driven port graph."""
        if not isinstance(tasks, list) or not tasks:
            raise PipelineError("port graph task compilation requires a non-empty task array")
        blocks: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for index, raw in enumerate(tasks):
            if not isinstance(raw, dict) or not raw.get("id"):
                raise PipelineError(f"task {index} must be an object with a non-empty id")
            task_id = str(raw["id"])
            if task_id in blocks:
                raise PipelineError(f"duplicate task id: {task_id}")
            task = copy.deepcopy(raw)
            dependencies = task.get("dependencies", [])
            if not isinstance(dependencies, list) or any(not isinstance(item, str) or not item for item in dependencies):
                raise PipelineError(f"task {task_id!r}.dependencies must be an array of ids")
            declared_inputs = task.get("inputs", {})
            if not isinstance(declared_inputs, dict):
                raise PipelineError(f"task {task_id!r}.inputs must be an object")
            dependency_set = set(dependencies)
            dependency_ports: dict[str, list[str]] = {dependency: [] for dependency in dependencies}
            defaults: dict[str, Any] = {}
            for name, value in declared_inputs.items():
                if isinstance(value, str) and value in dependency_set:
                    dependency_ports[value].append(str(name))
                else:
                    defaults[str(name)] = copy.deepcopy(value)
            for dependency in dependencies:
                if not dependency_ports[dependency]:
                    dependency_ports[dependency].append(dependency)
            required_inputs = [name for dependency in dependencies for name in dependency_ports[dependency]]
            blocks[task_id] = {
                "id": task_id,
                "task": task,
                "required_inputs": required_inputs,
                "defaults": defaults,
                "output_port": str(task.get("output_port", "output")),
                "output_schema": copy.deepcopy(task.get("output_schema", {})),
                "sensitive": bool(task.get("sensitive", False)),
                "rejection_port": str(task.get("rejection_port", "rejected")),
                "error_port": str(task.get("error_port", "error")),
                "_dependency_ports": dependency_ports,
            }
            order.append(task_id)
        links: list[dict[str, Any]] = []
        for task_id in order:
            block = blocks[task_id]
            task = block["task"]
            static_dependencies = set(task.get("static_dependencies", []))
            dependency_ports = block.pop("_dependency_ports")
            for dependency in task.get("dependencies", []):
                if dependency not in blocks:
                    raise PipelineError(f"task {task_id!r} references missing dependency {dependency!r}")
                for sink_name in dependency_ports[dependency]:
                    links.append({
                        "source_id": dependency,
                        "source_name": blocks[dependency]["output_port"],
                        "sink_id": task_id,
                        "sink_name": sink_name,
                        "is_static": dependency in static_dependencies,
                    })
        return {
            "blocks": blocks,
            "links": links,
            "max_workers": node.get("max_workers", 4),
            "max_executions": node.get("max_executions", 500),
            "max_events": node.get("max_events", 5000),
            "fail_fast": node.get("fail_fast", False),
        }

    def _port_graph_subflow_node(self, node: dict, inputs: dict) -> NodeOutcome:
        """Execute an event-driven block graph inside the existing Subflow node."""
        from agent_factory import AgentFactory
        from config import CONFIG
        from harness import Harness
        from port_graph import PortBlockResult, PortGraphError, PortGraphRunner, normalize_port_graph

        raw_graph = inputs.get("port_graph")
        if raw_graph is None:
            raw_graph = resolve_reference(node.get("port_graph", node.get("graph")), self.ctx)
        if isinstance(raw_graph, list):
            raw_graph = self._compile_task_port_graph(raw_graph, node)
        try:
            port_graph = normalize_port_graph(raw_graph)
        except (PortGraphError, TypeError, ValueError) as error:
            raise PipelineError(f"invalid port graph: {error}") from error
        self.ctx.emit(
            "port_graph_compiled",
            {"blocks": len(port_graph["blocks"]), "links": len(port_graph["links"]), "max_workers": port_graph["max_workers"]},
        )

        common_data = inputs.get("data", {})
        if not isinstance(common_data, dict):
            raise PipelineError("port graph Subflow data must be an object")
        common_data = copy.deepcopy(common_data)
        default_harness = resolve_reference(node.get("block_harness", node.get("harness", "")), self.ctx)
        base_agent_map = resolve_reference(node.get("agent_map", {}), self.ctx)
        base_identity_map = resolve_reference(node.get("identity_map", {}), self.ctx)
        if not isinstance(base_agent_map, dict) or not isinstance(base_identity_map, dict):
            raise PipelineError("port graph agent_map and identity_map must be objects")
        message_template = str(resolve_reference(
            node.get(
                "block_message",
                "Execute this typed block using only its declared inputs.\n\nBlock: {block}\nPort inputs: {inputs}",
            ),
            self.ctx,
        ))

        agent_factory = AgentFactory(identity_roots=(CONFIG["identity_repository"],))

        def execute_block(block: dict[str, Any], block_inputs: dict[str, Any]) -> PortBlockResult:
            harness_name = block.get("harness", default_harness)
            harness_dir = Path(CONFIG["harness_template_repository"]) / str(harness_name)
            if not harness_dir.is_dir():
                raise PipelineError(f"port graph block harness not found: {harness_name}")
            sub_harness = Harness(harness_dir, workspace=self.ctx.harness.workspace)

            agent_map = {**base_agent_map, **block.get("agent_map", {})}
            identity_map = {**base_identity_map, **block.get("identity_map", {})}
            agents = {}
            for slot_name, slot_def in sub_harness.slots.items():
                parent_slot = agent_map.get(slot_name)
                if parent_slot in self.ctx.harness.agents:
                    # Context-local sessions make the same Identity/EGO safe to use
                    # concurrently, and sharing preserves provider accounting/state.
                    agents[slot_name] = self.ctx.harness.agents[parent_slot]
                    continue
                identity_name = identity_map.get(slot_name, slot_def.get("identity"))
                if identity_name:
                    agents[slot_name] = agent_factory.create(
                        self._safe_identity_path(CONFIG["identity_repository"], identity_name),
                        name=slot_name,
                        workspace=self.ctx.workspace,
                    )
                elif slot_name in self.ctx.harness.agents:
                    agents[slot_name] = self.ctx.harness.agents[slot_name]
            sub_harness.set_agents(agents)
            from subagent_lifecycle import finish_subagent, link_subagent
            with self._child_harness_lock:
                link_subagent(
                    self.ctx.harness,
                    sub_harness,
                    share_session=False,
                    purpose="port_graph_block",
                    agent_bindings={key: getattr(value, "name", key) for key, value in agents.items()},
                    identity_bindings={
                        key: Path(getattr(getattr(value, "identity", None), "identity_path", "")).name
                        for key, value in agents.items()
                    },
                )
            task = copy.deepcopy(block.get("task", block))
            prompt_values = {
                **common_data,
                "block": json.dumps(task, ensure_ascii=False),
                "inputs": json.dumps(block_inputs, ensure_ascii=False),
                "block_id": block["id"],
                "request": common_data.get("request", self.ctx.data.get("request", "")),
            }
            message_text = _format_prompt(str(block.get("message", message_template)), prompt_values)
            message = {"role": "user", "content": message_text}
            sub_harness.session.record(message)
            sub_harness.session.record_full(message.copy())
            sub_harness._non_interactive = True
            events: list[tuple[str, dict]] = []
            runner = PipelineRunner(
                sub_harness,
                on_output=lambda event, payload: events.append((event, payload)),
                get_input=lambda: None,
                is_running=self.ctx.is_running,
                initial_data={**common_data, "block": task, "port_inputs": copy.deepcopy(block_inputs)},
                emit_done=False,
                inject_workspace_preview=False,
            )
            try:
                child = runner.run()
            except Exception as error:
                finish_subagent(sub_harness, status="failed", error=error)
                raise
            result_mode = block.get("result_mode", node.get("result_mode", "text"))
            if result_mode == "text":
                result = next(
                    (item.get("content", "") for item in reversed(sub_harness.session.messages) if item.get("role") == "assistant"),
                    "",
                )
            elif result_mode == "result":
                result = copy.deepcopy(child.result)
            elif result_mode == "data":
                result = copy.deepcopy(child.data)
            elif result_mode == "messages":
                result = sub_harness.session.get_result(sub_harness.return_mode)
            else:
                raise PipelineError(f"unknown port graph block result_mode: {result_mode}")
            structured_result = result
            if isinstance(result, str) and block.get("allow_named_outputs", True):
                try:
                    parsed_result = json.loads(_strip_code_fence(result))
                    structured_result = parsed_result
                except (TypeError, ValueError):
                    pass
            raw_events = structured_result.get("outputs") if isinstance(structured_result, dict) else None
            if isinstance(raw_events, list) and block.get("allow_named_outputs", True):
                outputs = []
                for event in raw_events:
                    if not isinstance(event, dict) or "name" not in event or "value" not in event:
                        raise PipelineError("named block outputs must contain name and value")
                    outputs.append((str(event["name"]), event["value"]))
            else:
                outputs = [(str(block.get("output_port", "output")), structured_result)]
            finish_subagent(
                sub_harness,
                status="completed",
                result={"block_id": block["id"], "outputs": outputs},
            )
            return PortBlockResult(
                outputs=outputs,
                metadata={
                    "stats": child.stats.as_dict(),
                    "events": events,
                    "messages": copy.deepcopy(sub_harness.session.messages),
                    "full_messages": copy.deepcopy(sub_harness.session.full_messages),
                    "harness": str(harness_name),
                },
            )

        def review_block(block: dict[str, Any], block_inputs: dict[str, Any]) -> dict[str, Any]:
            review = self._approval_node(
                {
                    "name": f"Port block {block['id']}",
                    "prompt_text": node.get(
                        "review_prompt",
                        "This block contains a consequential action. Approve, reject, or edit its port inputs before it runs.",
                    ),
                    "default": block.get("review_default", node.get("review_default", "rejected")),
                    "editable": True,
                },
                {"data": {"block": copy.deepcopy(block.get("task", block)), "inputs": copy.deepcopy(block_inputs)}},
            )
            reviewed = review.output.get("data", {})
            edited_inputs = reviewed.get("inputs", block_inputs) if isinstance(reviewed, dict) else block_inputs
            return {
                "approved": bool(review.output.get("value")),
                "data": edited_inputs if isinstance(edited_inputs, dict) else block_inputs,
                "message": review.output.get("review_message", ""),
            }

        state_path = None
        initial_state = None
        requested_state_path = inputs.get("state_path") or resolve_reference(node.get("state_path"), self.ctx)
        if requested_state_path:
            state_path = self._safe_runtime_path(str(requested_state_path))
            if state_path.suffix.lower() != ".json":
                raise PipelineError("port graph state_path must end with .json")
            if state_path.exists() and node.get("resume_state", True) and not inputs.get("reset_state", False):
                try:
                    initial_state = json.loads(state_path.read_text(encoding="utf-8"))
                except (OSError, ValueError) as error:
                    raise PipelineError(f"cannot load port graph state {state_path}: {error}") from error
            self.ctx.data["_port_graph_state_path"] = self._workspace_relative(state_path)

        def save_port_state(state: dict[str, Any]) -> None:
            if state_path is None:
                return
            state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = state_path.with_name(f"{state_path.name}.{uuid.uuid4().hex}.tmp")
            temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            last_error = None
            try:
                for attempt in range(6):
                    try:
                        os.replace(temporary, state_path)
                        return
                    except OSError as error:
                        last_error = error
                        if attempt == 5:
                            break
                        time.sleep(0.01 * (attempt + 1))
                raise PipelineError(f"cannot atomically persist port graph state {state_path}: {last_error}")
            finally:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

        runner = PortGraphRunner(
            port_graph,
            execute_block,
            review_block=review_block,
            is_running=lambda: not self.ctx.cancelled(),
            on_event=lambda event, payload: self.ctx.emit(event, payload),
            initial_state=initial_state,
            on_state=save_port_state if state_path is not None else None,
        )
        graph_result = runner.run()

        # Merge child effects deterministically after all concurrent executions.
        for record in graph_result["executions"]:
            metadata = record.pop("metadata", {})
            stats = metadata.pop("stats", None)
            if isinstance(stats, dict):
                restored_stats = RunStats()
                for field_name in (
                    "node_steps", "model_calls", "tool_calls", "process_calls", "retries",
                    "input_tokens_estimated", "output_tokens_estimated", "cost_estimated",
                    "provider_requests", "provider_retries", "input_tokens_actual",
                    "output_tokens_actual", "cached_input_tokens_actual", "cost_actual",
                    "provider_request_ids",
                ):
                    if field_name in stats:
                        setattr(restored_stats, field_name, stats[field_name])
                self.ctx.stats.add(restored_stats)
            self.ctx.harness.session.messages.extend(metadata.pop("messages", []))
            self.ctx.harness.session.full_messages.extend(metadata.pop("full_messages", []))
            for event, payload in metadata.pop("events", []):
                if event != "done":
                    self.ctx.emit(event, {**payload, "port_block": record["block_id"]})
            record["metadata"] = metadata

        block_results = []
        for record in graph_result["executions"]:
            output_events = record.get("outputs", [])
            output_value = output_events[-1].get("value") if output_events else None
            block = port_graph["blocks"][record["block_id"]]
            block_results.append({
                "task_id": record["block_id"],
                "execution_id": record["id"],
                "status": record["status"],
                "dependencies": copy.deepcopy(block.get("task", {}).get("dependencies", [])),
                "inputs": copy.deepcopy(record["inputs"]),
                "output": copy.deepcopy(output_value),
                "outputs": copy.deepcopy(output_events),
                "error": copy.deepcopy(record.get("error")),
                "review": copy.deepcopy(record.get("review")),
            })
        output_var = node.get("output_var", "port_graph_result")
        records_var = node.get("records_var", "block_results")
        events_var = node.get("events_var", "port_events")
        self.ctx.data[output_var] = graph_result
        self.ctx.data[records_var] = block_results
        self.ctx.data[events_var] = copy.deepcopy(graph_result["events"])
        self.ctx.data[node.get("compiled_graph_var", "compiled_port_graph")] = {
            "blocks": copy.deepcopy(port_graph["blocks"]),
            "links": copy.deepcopy(port_graph["links"]),
        }
        tags = ["subflow_done", f"port_graph_{graph_result['status']}"]
        return NodeOutcome(
            {"value": graph_result, "data": graph_result, "records": block_results, "events": graph_result["events"]},
            tags,
        )

    @staticmethod
    def _safe_identity_path(repository: Any, identity_name: Any) -> Path:
        root = Path(repository).resolve()
        candidate = (root / str(identity_name)).resolve()
        if candidate == root or root not in candidate.parents or not candidate.is_dir():
            raise PipelineError(f"Identity is outside the repository or missing: {identity_name}")
        return candidate

    def _checkpoint_node(self, node: dict, inputs: dict) -> NodeOutcome:
        action = node.get("action", "save")
        if action == "save":
            next_node = _follow_edge(
                node,
                "checkpoint_saved",
                "default",
                context=self.ctx.data,
                variables=self.ctx.variables(),
            )
            path = self._save_checkpoint(inputs.get("label") or node.get("label") or self.ctx.current_node, next_node=next_node)
            return NodeOutcome({"path": str(path), "next_node": next_node, "value": str(path)}, ["checkpoint_saved"], next_node=next_node)
        if action == "load":
            requested = inputs.get("path") or node.get("path")
            path = self._checkpoint_path(requested)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self._restore_checkpoint_payload(payload, path)
            return NodeOutcome({"path": str(path), "value": payload}, ["checkpoint_loaded"])
        if action == "replay":
            requested = inputs.get("path") or resolve_reference(node.get("path"), self.ctx)
            if not requested and self.ctx.event_log_path is not None:
                requested = str(self.ctx.event_log_path)
            if not requested:
                raise PipelineError("event replay requires a JSONL path")
            path = self._safe_runtime_path(str(requested))
            if not path.is_file() or path.suffix.lower() != ".jsonl":
                raise PipelineError(f"event log is not available: {path}")
            from_sequence = max(0, int(node.get("from_sequence", 0)))
            allowed = set(node.get("event_types", []))
            events = []
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except ValueError as error:
                    raise PipelineError(f"invalid event log line {line_number}: {error}") from error
                if int(event.get("sequence", 0)) < from_sequence:
                    continue
                if allowed and event.get("event") not in allowed:
                    continue
                events.append(event)
            output_var = node.get("output_var", "replayed_events")
            if output_var:
                set_path(self.ctx.data, output_var, copy.deepcopy(events))
            return NodeOutcome({"path": str(path), "events": events, "count": len(events), "value": events}, ["events_replayed"])
        raise PipelineError(f"unknown Checkpoint action: {action}")

    def _output_node(self, node: dict, inputs: dict, stop: bool) -> NodeOutcome:
        value = inputs.get("value")
        if value is None and "value" in node:
            value = resolve_reference(node["value"], self.ctx)
        if value is None:
            value = self.ctx.text if self.ctx.text is not None else self.ctx.last_output
        if node.get("record") and isinstance(value, str):
            message = {"role": "assistant", "name": node.get("name", "output"), "content": value}
            self.ctx.harness.session.record(message)
            self.ctx.harness.session.record_full(message.copy())
        self.ctx.result = value
        self.ctx.emit("output", {"value": _preview_value(value), "final": stop})
        return NodeOutcome({"value": value, "text": value if isinstance(value, str) else None}, ["output"], stop=stop)

    def _node_agent(self, node: dict, inputs: dict, required: bool = True):
        name = node.get("agent") or inputs.get("agent")
        agent = self.ctx.harness.agents.get(name) if name else _get_main_agent(self.ctx.harness)
        if required and agent is None:
            raise PipelineError(f"node {self.ctx.current_node!r} has no bound agent")
        return agent

    def _record_model_usage(self, input_tokens: int, output_tokens: int) -> None:
        self.ctx.stats.input_tokens_estimated += input_tokens
        self.ctx.stats.output_tokens_estimated += output_tokens
        prices = self.ctx.graph.get("budget", {}).get("prices", {})
        self.ctx.stats.cost_estimated += input_tokens * float(prices.get("input_per_million", 0)) / 1_000_000
        self.ctx.stats.cost_estimated += output_tokens * float(prices.get("output_per_million", 0)) / 1_000_000
        self._check_run_limits()

    def _record_provider_usage(self, agent) -> None:
        llm = getattr(agent, "llm", None)
        metadata = getattr(llm, "last_response_metadata", None)
        if not isinstance(metadata, dict) or not metadata:
            return
        sequence = int(metadata.get("sequence", 0) or 0)
        marker = (id(llm), sequence)
        if sequence and marker in self._provider_metadata_seen:
            return
        if sequence:
            self._provider_metadata_seen.add(marker)

        usage = metadata.get("usage") or {}
        if not isinstance(usage, dict):
            usage = {}
        input_tokens = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
        output_tokens = int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0)
        details = usage.get("prompt_tokens_details", usage.get("input_tokens_details", {})) or {}
        cached_tokens = int(
            details.get("cached_tokens", usage.get("cached_tokens", usage.get("cache_read_input_tokens", 0))) or 0
        ) if isinstance(details, dict) else 0
        cached_tokens = min(max(0, cached_tokens), max(0, input_tokens))

        stats = self.ctx.stats
        stats.provider_requests += 1
        stats.provider_retries += int(metadata.get("retries", 0) or 0) + int(metadata.get("reconnects", 0) or 0)
        stats.input_tokens_actual += max(0, input_tokens)
        stats.output_tokens_actual += max(0, output_tokens)
        stats.cached_input_tokens_actual += cached_tokens
        request_ids = metadata.get("provider_request_ids") or [metadata.get("provider_request_id")]
        for request_id in request_ids:
            if request_id and str(request_id) not in stats.provider_request_ids:
                stats.provider_request_ids.append(str(request_id))

        prices = self.ctx.graph.get("budget", {}).get("prices", {})
        input_price = float(prices.get("input_per_million", 0))
        cached_price = float(prices.get("cached_input_per_million", prices.get("cache_per_million", input_price)))
        output_price = float(prices.get("output_per_million", 0))
        uncached_tokens = max(0, input_tokens - cached_tokens)
        stats.cost_actual += uncached_tokens * input_price / 1_000_000
        stats.cost_actual += cached_tokens * cached_price / 1_000_000
        stats.cost_actual += output_tokens * output_price / 1_000_000
        self.ctx.emit(
            "provider_usage",
            {
                "model": metadata.get("model"),
                "request_ids": [str(value) for value in request_ids if value],
                "attempts": metadata.get("attempts", 1),
                "reconnects": metadata.get("reconnects", 0),
                "input_tokens": input_tokens,
                "cached_input_tokens": cached_tokens,
                "output_tokens": output_tokens,
            },
        )
        self._check_run_limits()

    def _maybe_pressure_compact(
        self,
        node: dict[str, Any],
        agent: Any,
        messages: list[dict[str, Any]],
        tools_desc: Any,
        *,
        persist_session: bool,
    ) -> list[dict[str, Any]]:
        """Runtime-owned high-watermark compaction before a model request."""

        management = self.ctx.graph.get("context_management", {})
        if management is False:
            return messages
        # Context management is a DAG policy now.  Only an explicitly declared
        # legacy middleware block keeps the pre-component behavior for older
        # Harness files; an absent/empty block no longer performs a hidden LLM
        # call before every Agent node.
        if not isinstance(management, dict) or not management:
            return messages
        if not bool(management.get("enabled", False)):
            return messages
        llm_config = getattr(getattr(agent, "llm", None), "config", {})
        if not isinstance(llm_config, dict):
            llm_config = {}
        context_limit = int(
            node.get("context_limit_tokens")
            or management.get("context_limit_tokens")
            or llm_config.get("context_window")
            or os.environ.get("EGOAGENT_CONTEXT_WINDOW", "128000")
        )
        output_reservation = int(
            node.get("max_tokens")
            or management.get("reserved_output_tokens")
            or getattr(getattr(agent, "llm", None), "max_tokens", None)
            or 4096
        )
        try:
            system_prompt = agent.build_system_prompt(has_tools=bool(tools_desc))
        except Exception:
            system_prompt = ""
        extra_tokens = _estimate_tokens(system_prompt) + _estimate_tokens(tools_desc)
        from context_policy import (
            apply_pressure_compaction,
            content_text,
            pressure_budget,
            pressure_compaction_prompt,
        )

        budget = pressure_budget(
            messages,
            context_limit_tokens=context_limit,
            high_watermark=float(management.get("high_watermark", 0.82)),
            target_ratio=float(management.get("target_ratio", 0.62)),
            reserved_output_tokens=output_reservation,
            extra_input_tokens=extra_tokens,
        )
        if not budget["triggered"]:
            return messages
        self.ctx.emit("context_pressure", {**budget, "node": self.ctx.current_node, "phase": "triggered"})
        current_task = ""
        for message in reversed(messages):
            if message.get("role") == "user" and "<tool_response>" not in content_text(message):
                current_task = content_text(message)
                break
        target_message_tokens = max(256, int(budget["target_tokens"]) - extra_tokens)
        prompt, blocks = pressure_compaction_prompt(
            messages,
            current_tokens=int(budget["message_tokens_estimated"]),
            target_tokens=target_message_tokens,
            current_task=current_task,
            protect_recent_turns=max(1, int(management.get("protect_recent_turns", 2))),
        )
        self.ctx.emit(
            "context_compaction_started",
            {
                "node": self.ctx.current_node,
                "blocks": len(blocks),
                "block_kinds": [block.kind for block in blocks],
                **budget,
            },
        )
        try:
            self._before_model_call()
            response = _standalone_llm_call(
                prompt,
                self.ctx.harness,
                agent=agent,
                max_tokens=max(256, int(management.get("compactor_max_tokens", 4096))),
                temperature=float(management.get("temperature", 0.1)),
                purpose="legacy_pressure_compactor",
            )
            self._record_model_usage(_estimate_tokens(prompt), _estimate_tokens(response))
            self._record_provider_usage(agent)
            plan = json.loads(_strip_code_fence(response))
            if not isinstance(plan, dict):
                raise ValueError("compactor response is not a JSON object")
            session = self.ctx.harness.session
            audit_source = session.full_messages or session.messages or messages
            result = apply_pressure_compaction(
                messages,
                plan,
                target_tokens=target_message_tokens,
                protect_recent_turns=max(1, int(management.get("protect_recent_turns", 2))),
                full_messages=audit_source,
            )
            if result["stats"]["after_tokens_estimated"] >= result["stats"]["before_tokens_estimated"]:
                raise ValueError("compactor plan did not reduce the working context")
            if persist_session:
                session.apply_context_result(result)
                with session._lock:
                    governance = session.state.setdefault("context_governance", {})
                    compactions = governance.setdefault("pressure_compactions", [])
                    compactions.append({
                        "created_at": time.time(),
                        "node": self.ctx.current_node,
                        "budget": copy.deepcopy(budget),
                        "stats": copy.deepcopy(result["stats"]),
                        "ledger": copy.deepcopy(result["ledger"]),
                    })
                    del compactions[:-50]
                    governance["pressure_stats"] = copy.deepcopy(result["stats"])
                    governance["last_updated_at"] = time.time()
                session.save()
            self.ctx.data["context_pressure"] = {**budget, **result["stats"], "triggered": True}
            self.ctx.emit("context_compacted", {"node": self.ctx.current_node, **budget, **result["stats"]})
            return result["messages"]
        except Exception as error:
            # A missed compaction is visible and recoverable; a lossy fallback
            # based on malformed output would not be.
            self.ctx.data["context_pressure"] = {**budget, "triggered": True, "error": str(error)}
            self.ctx.emit(
                "context_compaction_failed",
                {"node": self.ctx.current_node, **budget, "error": str(error)[:1000]},
            )
            return messages

    def _before_model_call(self) -> None:
        legacy_limit = int(self.ctx.graph.get("max_steps", 100))
        limit = int(self.ctx.graph.get("budget", {}).get("max_model_calls", legacy_limit))
        if self.ctx.stats.model_calls >= limit:
            raise PipelineBudgetExceeded(f"reached max model calls ({limit})")
        self.ctx.stats.model_calls += 1

    def _before_process_call(self) -> None:
        limit = self.ctx.graph.get("budget", {}).get("max_process_calls")
        if limit is not None and self.ctx.stats.process_calls >= int(limit):
            raise PipelineBudgetExceeded(f"reached process call budget ({limit})")
        self.ctx.stats.process_calls += 1

    def _safe_runtime_path(self, requested: str) -> Path:
        base = Path(self.ctx.harness.workspace or self.ctx.harness.dir).resolve()
        path = Path(str(resolve_reference(requested, self.ctx)))
        resolved = path.resolve() if path.is_absolute() else (base / path).resolve()
        if resolved != base and base not in resolved.parents:
            raise PipelineError(f"runtime data path escapes workspace: {requested}")
        return resolved

    def _checkpoint_root(self) -> Path:
        requested = self.ctx.graph.get("checkpoint_dir", ".egoagent/checkpoints")
        root = self._safe_runtime_path(requested)
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _checkpoint_path(self, requested: Optional[str]) -> Path:
        root = self._checkpoint_root()
        if requested:
            candidate = Path(str(requested))
            path = candidate if candidate.is_absolute() else root / candidate
            path = path.resolve()
            if root != path and root not in path.parents:
                raise PipelineError("checkpoint path escapes checkpoint directory")
            return path
        candidates = sorted(root.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
        if not candidates:
            raise PipelineError("no checkpoint is available")
        return candidates[0]

    def _save_checkpoint(
        self,
        label: Optional[str],
        next_node: Optional[str] = None,
        *,
        phase: str = "completed",
        operation: str = "",
    ) -> Path:
        safe_label = "".join(char if char.isalnum() or char in "-_" else "_" for char in str(label or "checkpoint"))[:60]
        path = self._checkpoint_root() / f"{self.ctx.run_id}-{safe_label}.json"
        try:
            from harness_editor.change_tracker import get_transaction_summary
            change_transaction = get_transaction_summary(self.ctx.change_transaction_id)
        except Exception:
            change_transaction = {"transaction_id": self.ctx.change_transaction_id, "status": "unavailable"}
        payload = {
            "version": 3,
            "run_id": self.ctx.run_id,
            "node": self.ctx.current_node,
            "next_node": next_node,
            "phase": str(phase),
            "operation": str(operation or ""),
            "created_at": time.time(),
            "data": self.ctx.data,
            "node_outputs": self.ctx.node_outputs,
            "last_output": self.ctx.last_output,
            "result": self.ctx.result,
            "messages": self.ctx.harness.session.messages,
            "full_messages": self.ctx.harness.session.full_messages,
            "session_state": self.ctx.harness.session.state,
            "stats": self.ctx.stats.as_dict(),
            "permission_policy": self.ctx.permission_policy.public() if self.ctx.permission_policy else None,
            "approved_tool_call_ids": sorted(self.ctx.approved_tool_call_ids),
            "pending_approvals": self.ctx.pending_approvals,
            "artifacts": sorted(self.ctx.artifacts),
            "change_transaction_id": self.ctx.change_transaction_id,
            "change_transaction": change_transaction,
            "child_run_ids": sorted(self.ctx.child_run_ids),
            "child_run_tree": self.ctx.child_run_tree,
            "completed_steps": self.ctx.completed_steps,
            "revisions": self._revision_snapshot(),
        }
        payload = self.ctx.secret_view.redact_value(_redact_event_value(payload))
        incomplete = [name for name in ("workspace", "harness")
                      if payload["revisions"][name].get("complete") is False]
        if incomplete:
            self.ctx.emit("checkpoint_progress", {
                "message": "检查点已保存运行状态；大项目文件校验达到扫描预算，恢复时须显式确认，不能保证完整文件一致性。",
                "incomplete": incomplete,
            })
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        temporary.replace(path)
        self.ctx.emit(
            "checkpoint",
            {
                "path": str(path),
                "label": label,
                "phase": phase,
                "operation": operation,
                "next_node": next_node,
                "revision": payload.get("revisions", {}).get("workspace", {}).get("digest"),
            },
        )
        return path


def _follow_edge(node, *conditions, context=None, variables=None):
    condition_set = set(conditions)
    fallback = None
    variables = variables or {"ctx": context or {}, "data": context or {}}
    for edge in node.get("edges", []):
        condition = edge.get("condition", "default")
        if condition == "default":
            fallback = edge.get("to")
            continue
        if condition in condition_set:
            return edge.get("to")
        expression = edge.get("when")
        if expression is None and isinstance(condition, str) and condition.startswith(("expr:", "when:")):
            expression = condition.split(":", 1)[1]
        if expression is not None:
            try:
                if evaluate_expression(str(expression), variables):
                    return edge.get("to")
            except SafeExpressionError:
                continue
    return fallback


def _call_with_timeout(call: Callable[[], NodeOutcome], timeout: float) -> NodeOutcome:
    if timeout <= 0:
        return call()
    results: queue.Queue = queue.Queue(maxsize=1)
    from runtime_waits import ActiveDeadline, active_deadlines
    deadline = ActiveDeadline(timeout)
    token = active_deadlines.set((*active_deadlines.get(), deadline))
    copied_context = contextvars.copy_context()
    active_deadlines.reset(token)

    def target() -> None:
        try:
            results.put((True, copied_context.run(call)))
        except BaseException as error:
            results.put((False, error))

    worker = threading.Thread(target=target, name="dag-node-timeout", daemon=True)
    worker.start()
    while True:
        remaining = deadline.remaining()
        if remaining <= 0:
            deadline.cancelled.set()
            raise NodeTimeout(f"node exceeded active execution timeout ({timeout}s; approval wait excluded)")
        try:
            success, value = results.get(timeout=min(0.05, remaining))
            break
        except queue.Empty:
            continue
    if success:
        return value
    raise value


def _get_main_agent(harness):
    return next(iter(harness.agents.values()), None) if harness.agents else None


def _memory_tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", str(value).lower()))


def _nested_value(value: Any, path: str) -> Any:
    """Read a dotted field from a JSON-like value without evaluating code."""
    current = value
    for part in str(path or "").split("."):
        if not part:
            continue
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, (list, tuple)) and part.isdigit():
            index = int(part)
            current = current[index] if 0 <= index < len(current) else None
        else:
            return None
    return current


def _standalone_llm_call(
    prompt,
    harness,
    *,
    agent=None,
    max_tokens=2048,
    temperature=0.7,
    purpose="model_node",
    on_reasoning=None,
):
    agent = agent or _get_main_agent(harness)
    if agent is None or not hasattr(agent, "llm"):
        raise PipelineError("Model node requires at least one Agent with an LLM")
    messages = []
    system_prompt = agent.build_system_prompt(has_tools=False) if hasattr(agent, "build_system_prompt") else ""
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    llm_config = getattr(agent.llm, "config", {}) or {}
    model_call_id = harness.session.begin_model_call(
        messages=messages,
        tools=[],
        agent=getattr(agent, "name", "Agent"),
        model=getattr(agent.llm, "model", None),
        provider=llm_config.get("provider") or type(agent.llm).__name__,
        parameters={"stream": False, "max_tokens": max_tokens, "temperature": temperature},
        purpose=purpose,
    )
    try:
        result = agent.llm.chat(
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    except BaseException as error:
        harness.session.fail_model_call(
            model_call_id,
            agent=getattr(agent, "name", "Agent"),
            error=error,
        )
        raise
    content = result["choices"][0]["message"].get("content", "")
    response_message = result["choices"][0].get("message", {})
    reasoning = str(response_message.get("reasoning_content") or "")
    filter_output = getattr(agent, "_apply_superego_output_policy", None)
    if callable(filter_output):
        reasoning, _ = filter_output(reasoning)
    if on_reasoning and reasoning:
        on_reasoning(reasoning)
    metadata = dict(getattr(agent.llm, "last_response_metadata", {}) or {})
    harness.session.finish_model_call(
        model_call_id,
        agent=getattr(agent, "name", "Agent"),
        content=content,
        reasoning=response_message.get("reasoning_content", ""),
        tool_calls=response_message.get("tool_calls") or [],
        finish_reason=metadata.get("finish_reason") or result["choices"][0].get("finish_reason"),
        usage=metadata.get("usage") or result.get("usage"),
        metadata=metadata,
    )
    if "</think>" in content:
        content = content.split("</think>")[-1].strip()
    elif "<think>" in content:
        content = ""
    return content


def _inject_workspace_preview(harness):
    workspace = Path(harness.workspace)
    try:
        items = sorted(workspace.iterdir(), key=lambda item: item.name.lower())[:30]
        preview = "\n".join(f"  {'[dir] ' if item.is_dir() else '      '}{item.name}" for item in items if not item.name.startswith("."))
    except OSError:
        preview = "(unable to list)"
    message = {"role": "user", "content": f"[System] Working directory: {workspace}\nTop-level contents:\n{preview}"}
    harness.session.record(message)
    harness.session.record_full(message.copy())


def _estimate_tokens(value: Any) -> int:
    if value is None:
        return 0
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, default=str)
    return max(1, (len(value) + 3) // 4)


def _repeated_ngram_ratio(text: str, ngram_size: int) -> dict[str, Any]:
    """Return a cheap, language-agnostic signal for pathological repetition.

    The guard is opt-in per Agent node. Character n-grams overreact to source
    code and grids, so this uses word/CJK-run tokens and exact multi-token
    phrases. Normal topical repetition stays low while degenerate model loops
    are detected without another model call.
    """

    tokens = re.findall(r"[\w]+|[\u3400-\u9fff]", str(text or "").casefold(), flags=re.UNICODE)
    size = max(0, int(ngram_size))
    total = max(0, len(tokens) - size + 1) if size else 0
    if not size or total <= 0:
        return {"ratio": 0.0, "tokens": len(tokens), "ngrams": total, "unique_ngrams": total}
    ngrams = [tuple(tokens[index:index + size]) for index in range(total)]
    unique = len(set(ngrams))
    return {
        "ratio": round(max(0.0, 1.0 - (unique / total)), 6),
        "tokens": len(tokens),
        "ngrams": total,
        "unique_ngrams": unique,
    }


def _prune_oldest_conversation_message(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop the oldest complete turn while preserving system and recent work.

    The old implementation removed from the tail, so a summary request that
    exceeded the provider context window silently discarded the latest user
    requirement.  Pruning from the first real user boundary retains the exact
    continuation state and also removes its paired tool calls/results together.
    """
    if len(messages) <= 1:
        return []
    prefix_end = 0
    while prefix_end < len(messages) and messages[prefix_end].get("role") == "system":
        prefix_end += 1
    if prefix_end >= len(messages) - 1:
        return messages[-1:]
    next_turn = None
    for index in range(prefix_end + 1, len(messages)):
        message = messages[index]
        content = str(message.get("content", ""))
        if message.get("role") == "user" and "<tool_response>" not in content:
            next_turn = index
            break
    if next_turn is None:
        return messages[:prefix_end] + messages[-1:]
    return messages[:prefix_end] + messages[next_turn:]


def _estimate_messages_tokens(messages: Any) -> int:
    if not isinstance(messages, list):
        return _estimate_tokens(messages)
    return sum(_estimate_tokens(message.get("content", "")) + 4 for message in messages if isinstance(message, dict))


def _preview_value(value: Any, limit: int = 500) -> Any:
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + "..."
    try:
        rendered = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        rendered = str(value)
    return value if len(rendered) <= limit else rendered[:limit] + "..."


def _debug_value(value: Any, limit: int = 20000) -> Any:
    """Redacted, bounded value for the interactive Studio inspector.

    Event logs already redact recursively.  WebSocket debugging must obey the
    same rule so API keys in node inputs or tool arguments never reach the UI.
    """
    return _preview_value(_redact_event_value(copy.deepcopy(value)), limit=limit)


def _strip_code_fence(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith("```"):
        first_newline = stripped.find("\n")
        if first_newline >= 0:
            stripped = stripped[first_newline + 1 :]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
    return stripped.strip()


_AIDER_HEAD = re.compile(r"^<{5,9} SEARCH>?\s*$")
_AIDER_DIVIDER = re.compile(r"^={5,9}\s*$")
_AIDER_UPDATED = re.compile(r"^>{5,9} REPLACE\s*$")
_AIDER_SHELL_FENCES = {
    "```bash", "```sh", "```shell", "```cmd", "```batch", "```powershell",
    "```ps1", "```zsh", "```fish", "```ksh", "```csh", "```tcsh",
}


def _parse_aider_search_replace_blocks(content: str, valid_filenames: Optional[list[str]] = None) -> tuple[list[dict], list[str]]:
    """Parse Aider's editblock protocol, including command-only shell fences."""
    lines = content.splitlines(keepends=True)
    valid_filenames = [str(value).replace("\\", "/") for value in (valid_filenames or [])]
    edits: list[dict] = []
    shell_commands: list[str] = []
    current_filename: Optional[str] = None
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        next_is_edit = any(
            index + offset < len(lines) and _AIDER_HEAD.match(lines[index + offset].strip())
            for offset in (1, 2)
        )
        if any(stripped.startswith(prefix) for prefix in _AIDER_SHELL_FENCES) and not next_is_edit:
            command_lines: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                command_lines.append(lines[index])
                index += 1
            shell_commands.append("".join(command_lines))
            index += int(index < len(lines))
            continue
        if not _AIDER_HEAD.match(stripped):
            index += 1
            continue

        filename = _aider_filename_from_context(lines[max(0, index - 3):index], valid_filenames)
        if not filename:
            filename = current_filename
        if not filename:
            raise ValueError(
                "Bad/missing filename. Put the filename alone on the line before <<<<<<< SEARCH."
            )
        current_filename = filename
        search_lines: list[str] = []
        index += 1
        while index < len(lines) and not _AIDER_DIVIDER.match(lines[index].strip()):
            search_lines.append(lines[index])
            index += 1
        if index >= len(lines):
            raise ValueError("Expected `=======` after SEARCH text.")
        replace_lines: list[str] = []
        index += 1
        while index < len(lines) and not (
            _AIDER_UPDATED.match(lines[index].strip()) or _AIDER_DIVIDER.match(lines[index].strip())
        ):
            replace_lines.append(lines[index])
            index += 1
        if index >= len(lines):
            raise ValueError("Expected `>>>>>>> REPLACE` after replacement text.")
        edits.append(
            {
                "path": filename,
                "search": "".join(search_lines),
                "replace": "".join(replace_lines),
            }
        )
        index += 1
    return edits, shell_commands


def _aider_filename_from_context(lines: list[str], valid_filenames: list[str]) -> Optional[str]:
    candidates: list[str] = []
    for raw_line in reversed(lines):
        value = raw_line.strip().rstrip(":").lstrip("#").strip().strip("`").strip("*").strip()
        if not value or value == "...":
            continue
        if value.lower() in {"python", "javascript", "typescript", "json", "text", "diff"}:
            continue
        candidates.append(value.replace("\\", "/"))
    for candidate in candidates:
        if candidate in valid_filenames:
            return candidate
    for candidate in candidates:
        basename_matches = [path for path in valid_filenames if Path(path).name == Path(candidate).name]
        if len(basename_matches) == 1:
            return basename_matches[0]
    for candidate in candidates:
        matches = difflib.get_close_matches(candidate, valid_filenames, n=1, cutoff=0.8)
        if matches:
            return matches[0]
    for candidate in candidates:
        if "." in Path(candidate).name:
            return candidate
    return candidates[0] if candidates else None


def _aider_prep(value: str) -> tuple[str, list[str]]:
    if value and not value.endswith("\n"):
        value += "\n"
    return value, value.splitlines(keepends=True)


def _aider_replace_chunk(content: Optional[str], search: str, replace: str) -> Optional[str]:
    if content is None:
        if search.strip():
            return None
        content = ""
    newline = "\r\n" if "\r\n" in content else "\n"
    search = search.replace("\r\n", "\n").replace("\r", "\n").replace("\n", newline)
    replace = replace.replace("\r\n", "\n").replace("\r", "\n").replace("\n", newline)
    content, whole_lines = _aider_prep(content)
    search, search_lines = _aider_prep(search)
    replace, replace_lines = _aider_prep(replace)
    if not search.strip():
        return content + replace

    result = _aider_perfect_or_whitespace(whole_lines, search_lines, replace_lines)
    if result is not None:
        return result
    if len(search_lines) > 2 and not search_lines[0].strip():
        result = _aider_perfect_or_whitespace(whole_lines, search_lines[1:], replace_lines)
        if result is not None:
            return result
    return _aider_try_ellipsis(content, search, replace)


def _aider_perfect_or_whitespace(whole_lines: list[str], search_lines: list[str], replace_lines: list[str]) -> Optional[str]:
    length = len(search_lines)
    for index in range(len(whole_lines) - length + 1):
        if whole_lines[index:index + length] == search_lines:
            return "".join(whole_lines[:index] + replace_lines + whole_lines[index + length:])

    leading = [len(line) - len(line.lstrip()) for line in search_lines + replace_lines if line.strip()]
    if leading and min(leading):
        trim = min(leading)
        search_lines = [line[trim:] if line.strip() else line for line in search_lines]
        replace_lines = [line[trim:] if line.strip() else line for line in replace_lines]
    length = len(search_lines)
    for index in range(len(whole_lines) - length + 1):
        chunk = whole_lines[index:index + length]
        if not all(chunk[offset].lstrip() == search_lines[offset].lstrip() for offset in range(length)):
            continue
        prefixes = {
            chunk[offset][:len(chunk[offset]) - len(search_lines[offset])]
            for offset in range(length) if chunk[offset].strip()
        }
        if len(prefixes) != 1:
            continue
        prefix = prefixes.pop()
        adjusted = [prefix + line if line.strip() else line for line in replace_lines]
        return "".join(whole_lines[:index] + adjusted + whole_lines[index + length:])
    return None


def _aider_try_ellipsis(content: str, search: str, replace: str) -> Optional[str]:
    dots = re.compile(r"(^\s*\.\.\.\s*\n)", re.MULTILINE)
    search_pieces = re.split(dots, search)
    replace_pieces = re.split(dots, replace)
    if len(search_pieces) == 1 or len(search_pieces) != len(replace_pieces):
        return None
    if any(search_pieces[index] != replace_pieces[index] for index in range(1, len(search_pieces), 2)):
        return None
    updated = content
    for before, after in zip(search_pieces[::2], replace_pieces[::2]):
        if not before and not after:
            continue
        if not before:
            updated = updated + ("" if updated.endswith("\n") else "\n") + after
            continue
        if updated.count(before) != 1:
            return None
        updated = updated.replace(before, after, 1)
    return updated


def _find_similar_lines(search: str, content: str, threshold: float = 0.6) -> str:
    search_lines = search.splitlines()
    content_lines = content.splitlines()
    if not search_lines or len(search_lines) > len(content_lines):
        return ""
    best_ratio = 0.0
    best_index = 0
    for index in range(len(content_lines) - len(search_lines) + 1):
        ratio = difflib.SequenceMatcher(None, search_lines, content_lines[index:index + len(search_lines)]).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_index = index
    if best_ratio < threshold:
        return ""
    start = max(0, best_index - 5)
    end = min(len(content_lines), best_index + len(search_lines) + 5)
    return "\n".join(content_lines[start:end])


def _format_aider_edit_failures(failures: list[dict], applied_count: int) -> str:
    if not failures:
        return ""
    label = "block" if len(failures) == 1 else "blocks"
    parts = [f"# {len(failures)} SEARCH/REPLACE {label} failed to match!"]
    for failure in failures:
        parts.extend(
            [
                f"## SearchReplaceNoExactMatch in {failure['path']}",
                "<<<<<<< SEARCH",
                failure["search"].rstrip("\n"),
                "=======",
                failure["replace"].rstrip("\n"),
                ">>>>>>> REPLACE",
            ]
        )
        if failure.get("similar"):
            parts.extend(["Did you mean these actual lines?", "```", failure["similar"], "```"])
    parts.append("The SEARCH section must match existing lines, including whitespace and indentation.")
    if applied_count:
        parts.append(
            f"The other {applied_count} block(s) were applied successfully. Do not resend them; only fix the failed blocks."
        )
    return "\n".join(parts)


def _parse_thought_action(message: str) -> tuple[str, str]:
    """Return discussion and the last top-level fenced action.

    This intentionally follows SWE-agent's pinned ``ThoughtActionParser``:
    nested fences are ignored and the final complete top-level block wins.
    """
    code_block_pattern = re.compile(r"^```(\S*)\s*\n|^```\s*$", re.MULTILINE)
    stack = []
    last_valid_block = None
    for match in code_block_pattern.finditer(str(message or "")):
        if stack and not match.group(1):
            start = stack.pop()
            if not stack:
                last_valid_block = (start, match)
        elif match.group(1) is not None:
            stack.append(match)
    if last_valid_block is None:
        raise ValueError("No action found in model response")
    start, end = last_valid_block
    thought = message[: start.start()] + message[end.end() :]
    action = message[start.end() : end.start()]
    if not action.strip():
        raise ValueError("Action block is empty")
    return thought, action


class _FormatValues(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def _format_prompt(template: str, values: dict) -> str:
    """Interpolate named prompt slots without treating JSON examples as slots.

    ``str.format_map`` rejects the very common combination of ``{request}``
    and a literal JSON example such as ``{"complete": true}``.  The old
    fallback then returned the *entire* prompt unchanged, so model judges saw
    the literal words ``{request}`` and ``{agent_answer}``.  Flow prompts only
    need simple named/path slots; replace those deliberately and leave all
    other braces alone.  Existing doubled braces remain supported.
    """
    text = str(template)
    left = "\u0000EGO_LEFT_BRACE\u0000"
    right = "\u0000EGO_RIGHT_BRACE\u0000"
    text = text.replace("{{", left).replace("}}", right)

    def replace(match):
        key = match.group(1)
        if key not in values:
            return match.group(0)
        value = values[key]
        if isinstance(value, (dict, list, tuple)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    text = re.sub(r"\{([A-Za-z_][A-Za-z0-9_.-]*)\}", replace, text)
    return text.replace(left, "{").replace(right, "}")


def _resolve_template(template: str, context: dict) -> str:
    """Backwards-compatible helper retained for external callers."""
    import re

    return re.sub(
        r"\$\{ctx\.([^}]+)\}",
        lambda match: str(get_path(context, match.group(1), "")),
        template,
    )


_AGENT_COLORS = {
    "创意家": "\033[95m",
    "批评家": "\033[91m",
    "裁判": "\033[93m",
    "正方": "\033[92m",
    "反方": "\033[91m",
    "guardian": "\033[94m",
    "worker": "\033[96m",
    "agent": "\033[96m",
    "coder": "\033[96m",
}
_RESET = "\033[0m"


def _clone_agent_for_slot(agent, slot_name: str):
    """Clone an Agent while rebinding adapters owned by its public slot.

    Subflows intentionally share the parent's model, activated capabilities
    and command state. A plain shallow copy also shared ``tool_executor``,
    whose owner check still referenced the parent slot. The child could be
    displayed as ``searcher`` while every tool call was rejected as targeting
    ``governor``. Recreate only slot-owned adapters and runtime identity.
    """
    cloned = copy.copy(agent)
    cloned.name = str(slot_name)
    runtime_context = getattr(agent, "_runtime_context", None)
    if isinstance(runtime_context, dict):
        cloned._runtime_context = dict(runtime_context)
        cloned._runtime_context["agent_name"] = cloned.name
        cloned._runtime_context["agent"] = cloned
    if callable(getattr(cloned, "execute_tool_call", None)):
        from tool_pipeline import AgentToolExecutor

        cloned.tool_executor = AgentToolExecutor(cloned)
        if getattr(cloned, "llm", None) is not None:
            from runtime_contracts import RuntimeServices

            cloned.runtime_services = RuntimeServices(model=cloned.llm, tools=cloned.tool_executor)
    return cloned


def _agent_label(agent):
    name = agent.name
    return f"{_AGENT_COLORS.get(name, chr(27) + '[96m')}[{name}]{_RESET}"


def _terminal_output(event: str, data: dict) -> None:
    if event == "label":
        print(f"\n[{data.get('agent', 'Agent')}] ", end="", flush=True)
    elif event == "tool":
        print(f"  [tool] {data.get('name')} -> {_preview_value(data.get('result'), 120)}")
    elif event == "blocked":
        print(f"  [blocked] {data.get('tool')} -> {data.get('reason')}")
    elif event == "node_retry":
        print(f"  [retry {data.get('attempt')}/{data.get('max_attempts')}] {data.get('message')}")
    elif event == "approval_required":
        print(data.get("prompt", "Approve?"))
    elif event == "error":
        print(f"[Pipeline error] {data.get('message')}")


def _terminal_input() -> Optional[str]:
    try:
        return input(">>> ")
    except EOFError:
        print()
        return None


def run_pipeline(harness, resume_from=None):
    """Run a pipeline interactively using the unified engine."""
    workspace = Path(getattr(harness, "workspace", None) or Path.cwd()).resolve()
    from security_settings import load_security_settings

    permission_policy = RuntimePolicy.for_interactive_run(
        workspace,
        "agent",
        graph_config=(getattr(harness, "config", {}).get("pipeline", {}).get("permissions")),
        security_settings=load_security_settings(workspace),
    )
    return PipelineRunner(
        harness,
        on_output=_terminal_output,
        get_input=_terminal_input,
        is_running=lambda: True,
        resume_from=resume_from,
        permission_policy=permission_policy,
    ).run()


def run_pipeline_stream(
    harness,
    on_output,
    get_input,
    is_running,
    resume_from=None,
    before_node=None,
    on_node_error=None,
    permission_policy=None,
    initial_data=None,
    get_approval=None,
):
    """Run the exact same engine with streaming callbacks."""
    return PipelineRunner(
        harness,
        on_output=on_output,
        get_input=get_input,
        get_approval=get_approval,
        is_running=is_running,
        resume_from=resume_from,
        before_node=before_node,
        on_node_error=on_node_error,
        permission_policy=permission_policy,
        initial_data=initial_data,
    ).run()
