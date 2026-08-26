"""Model-backed IDE assistance with a deterministic local fallback in Void.

Secrets are read from process environment variables only.  The browser-facing
extension talks to this localhost service and never receives the provider key.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from llm.providers import probe_model
from model_gateway import DEFAULT_MODEL_GATEWAY
from harness_editor.model_router import (
    get_role_assignments,
    list_model_profiles,
    report_model_result,
    route_model,
)


_diagnostic_lock = threading.RLock()
_last_probe: Dict[str, Any] | None = None
_last_request: Dict[str, Any] | None = None


class AIServiceError(RuntimeError):
    """A safe, user-facing provider or model error."""


def _runtime_config(role="chat", run_id=None, context_tokens=0, expected_output_tokens=0) -> Dict[str, Any]:
    routed = route_model(
        role,
        context_tokens=context_tokens,
        expected_output_tokens=expected_output_tokens,
        run_id=run_id,
        include_secret=True,
    )
    if not routed.get("error"):
        return {
            "type": "custom_llm",
            **routed,
            "profile_id": routed.get("id"),
        }
    siliconflow_key = os.environ.get("SILICONFLOW_API_KEY", "").strip()
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    key = os.environ.get("EGOAGENT_LLM_API_KEY", "").strip() or deepseek_key or siliconflow_key
    base_url = os.environ.get("EGOAGENT_LLM_BASE_URL", "").strip()
    model = os.environ.get("EGOAGENT_LLM_MODEL", "").strip()
    if deepseek_key:
        base_url = base_url or "https://api.deepseek.com"
        model = model or "deepseek-v4-flash"
    elif siliconflow_key:
        base_url = base_url or "https://api.siliconflow.cn/v1"
        model = model or "Qwen/Qwen3-8B"
    return {
        "type": "custom_llm",
        "provider": os.environ.get("EGOAGENT_LLM_PROVIDER", "").strip(),
        "base_url": base_url,
        "model": model,
        "api_key": key,
        "temperature": float(os.environ.get("EGOAGENT_LLM_TEMPERATURE", "0.2")),
        "max_tokens": int(os.environ.get("EGOAGENT_LLM_MAX_TOKENS", "4096")),
        "enable_thinking": os.environ.get("EGOAGENT_LLM_ENABLE_THINKING", "false").lower()
        in {"1", "true", "yes", "on"},
    }


def get_ai_status(role="chat") -> Dict[str, Any]:
    config = _runtime_config(role)
    base_url = config.get("base_url", "")
    model = config.get("model", "")
    has_key = bool(config.get("api_key"))
    configured_provider = str(config.get("provider") or "").strip().lower().replace("-", "_")
    provider = configured_provider if configured_provider in {
        "deepseek", "siliconflow", "openai_compatible", "anthropic", "anthropic_compatible", "ollama"
    } else (
        "deepseek" if "deepseek.com" in base_url.lower()
        else "siliconflow" if "siliconflow" in base_url.lower()
        else "openai-compatible" if base_url
        else "local"
    )
    fingerprint = f"{provider}|{base_url}|{model}"
    local_provider = provider == "local" or any(host in base_url.lower() for host in ("127.0.0.1", "localhost", ":11434"))
    with _diagnostic_lock:
        last_probe = dict(_last_probe) if _last_probe and _last_probe.get("fingerprint") == fingerprint else None
        last_request = dict(_last_request) if _last_request else None
    return {
        "configured": bool(base_url and model and (has_key or local_provider)),
        "provider": provider,
        "base_url": base_url,
        "model": model,
        "has_api_key": has_key,
        "thinking": bool(config.get("enable_thinking")),
        "fallback": "deterministic-local",
        "health": last_probe.get("healthy") if last_probe else None,
        "capabilities": last_probe.get("capabilities", {}) if last_probe else {},
        "last_probe": last_probe,
        "last_request": last_request,
        "fingerprint": fingerprint,
        "active_profile": config.get("profile_id"),
        "role": role,
        "profiles": list_model_profiles(),
        "role_assignments": get_role_assignments(),
    }


def _require_client(role="chat", run_id=None, context_tokens=0, expected_output_tokens=0):
    config = _runtime_config(role, run_id, context_tokens, expected_output_tokens)
    base_url = str(config.get("base_url") or "")
    local_provider = any(host in base_url.lower() for host in ("127.0.0.1", "localhost", ":11434"))
    if not base_url or not config.get("model") or (not config.get("api_key") and not local_provider):
        raise AIServiceError(
            "AI provider is not configured. Set DEEPSEEK_API_KEY, SILICONFLOW_API_KEY, or the "
            "EGOAGENT_LLM_BASE_URL / EGOAGENT_LLM_MODEL / EGOAGENT_LLM_API_KEY variables."
        )
    try:
        return DEFAULT_MODEL_GATEWAY.create(config)
    except (TypeError, ValueError) as error:
        raise AIServiceError(str(error)) from error


def _bounded_text(value: Any, limit: int, field: str) -> str:
    text = str(value or "")
    if len(text) > limit:
        raise AIServiceError(f"{field} is too large for this request ({len(text)} > {limit} characters)")
    return text


def _extract_json(content: str) -> Dict[str, Any]:
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise AIServiceError("Model returned invalid structured output")
        try:
            value = json.loads(text[start : end + 1])
        except json.JSONDecodeError as error:
            raise AIServiceError("Model returned invalid JSON") from error
    if not isinstance(value, dict):
        raise AIServiceError("Model returned a JSON value instead of an object")
    return value


def _call_json(system: str, user: str, max_tokens: int, temperature: float = 0.1, role="chat", run_id=None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    global _last_request
    estimated_input = max(1, (len(system) + len(user)) // 4)
    config = _runtime_config(role, run_id, estimated_input, max_tokens)
    client = _require_client(role, run_id, estimated_input, max_tokens)
    profile_id = config.get("profile_id")
    started = time.perf_counter()
    try:
        response = client.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
    except Exception as error:
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        if profile_id:
            report_model_result(profile_id, ok=False, latency_ms=latency_ms, run_id=run_id, error=error)
        message = str(error).replace("\n", " ")[:700]
        with _diagnostic_lock:
            _last_request = {
                "ok": False,
                "operation": "json",
                "latency_ms": latency_ms,
                "error": message,
                "checked_at": time.time(),
            }
        raise AIServiceError(f"Provider request failed: {message}") from error
    message = response.get("choices", [{}])[0].get("message", {})
    data = _extract_json(message.get("content") or "")
    metadata = dict(getattr(client, "last_response_metadata", {}) or {})
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    if profile_id:
        report_model_result(
            profile_id,
            ok=True,
            latency_ms=latency_ms,
            usage=response.get("usage", {}),
            run_id=run_id,
        )
    with _diagnostic_lock:
        _last_request = {
            "ok": True,
            "operation": "json",
            "latency_ms": latency_ms,
            "usage": response.get("usage", {}),
            "provider_request_id": metadata.get("provider_request_id"),
            "retries": metadata.get("retries", 0),
            "checked_at": time.time(),
        }
    return data, {
        "model": response.get("model", client.model),
        "usage": response.get("usage", {}),
        "provider": get_ai_status()["provider"],
        "profile_id": profile_id,
        "role": role,
    }


def _completion(body: Dict[str, Any]) -> Dict[str, Any]:
    prefix = _bounded_text(body.get("prefix"), 12000, "prefix")
    suffix = _bounded_text(body.get("suffix"), 6000, "suffix")
    language = _bounded_text(body.get("language"), 80, "language")
    path = _bounded_text(body.get("path"), 500, "path")
    supplemental = json.dumps({
        "imports": body.get("imports", []),
        "recent_edits": body.get("recent_edits", []),
        "open_files": body.get("open_files", []),
        "trigger_kind": body.get("trigger_kind"),
    }, ensure_ascii=False)
    if len(supplemental) > 24000:
        raise AIServiceError("completion context is too large for this request")
    data, meta = _call_json(
        "You are a fast code-completion engine. Return JSON only with one key named completion. "
        "The completion must contain only text inserted at the cursor, must not repeat the prefix "
        "or suffix, and should usually be under 12 lines. Use imports, recent edits, and open-file "
        "excerpts only as supporting context; never continue text from another file.",
        f"Language: {language}\nFile: {path}\n<PREFIX>\n{prefix}\n</PREFIX>\n"
        f"<SUFFIX>\n{suffix}\n</SUFFIX>\n<SUPPLEMENTAL_CONTEXT>\n{supplemental}\n"
        "</SUPPLEMENTAL_CONTEXT>",
        max_tokens=320,
        temperature=0.05,
        role="autocomplete",
    )
    completion = str(data.get("completion") or "")
    return {"completion": completion[:6000], **meta}


def _next_edit(body: Dict[str, Any]) -> Dict[str, Any]:
    current_path = _bounded_text(body.get("current_path"), 500, "current_path")
    last_edit = body.get("last_edit") if isinstance(body.get("last_edit"), dict) else {}
    candidates = body.get("candidates")
    if not current_path or not isinstance(candidates, list) or not candidates:
        raise AIServiceError("current_path and at least one candidate file are required")
    candidates = [item for item in candidates[:6] if isinstance(item, dict)]
    allowed = {
        str(item.get("path") or "").replace("\\", "/").lower(): str(item.get("path") or "")
        for item in candidates
        if item.get("path")
    }
    serialized = json.dumps({"last_edit": last_edit, "candidates": candidates}, ensure_ascii=False)
    if len(serialized) > 48000:
        raise AIServiceError("next-edit context is too large for this request")
    data, meta = _call_json(
        "Predict the single most likely useful edit after the user's latest code edit. Return JSON "
        "only as {\"path\":\"one exact candidate path\",\"start_line\":1,\"end_line\":1,"
        "\"replacement\":\"complete replacement text\",\"label\":\"short reason\","
        "\"confidence\":0.0}. Lines are one-based and end_line is inclusive. Choose only from the "
        "provided candidate files. Prefer a small coherent edit; return confidence 0 when no edit "
        "is justified.",
        f"Current file: {current_path}\n<EDITOR_STATE>\n{serialized}\n</EDITOR_STATE>",
        max_tokens=900,
        temperature=0.05,
        role="edit",
    )
    normalized_path = str(data.get("path") or "").replace("\\", "/").lower()
    if normalized_path not in allowed:
        raise AIServiceError("Model selected a file outside the supplied next-edit candidates")
    try:
        start_line = max(1, int(data.get("start_line") or 1))
        end_line = max(start_line, int(data.get("end_line") or start_line))
        confidence = max(0.0, min(1.0, float(data.get("confidence") or 0.0)))
    except (TypeError, ValueError) as error:
        raise AIServiceError("Model returned invalid next-edit coordinates") from error
    replacement = _bounded_text(data.get("replacement"), 12000, "replacement")
    return {
        "path": allowed[normalized_path],
        "start_line": start_line,
        "end_line": end_line,
        "replacement": replacement,
        "label": str(data.get("label") or "Suggested next edit")[:180],
        "confidence": confidence,
        **meta,
    }


def _inline_edit(body: Dict[str, Any]) -> Dict[str, Any]:
    code = _bounded_text(body.get("code"), 16000, "code")
    before = _bounded_text(body.get("before"), 5000, "before")
    after = _bounded_text(body.get("after"), 5000, "after")
    instruction = _bounded_text(body.get("instruction"), 1200, "instruction")
    language = _bounded_text(body.get("language"), 80, "language")
    if not instruction:
        raise AIServiceError("instruction is required")
    data, meta = _call_json(
        "You edit a selected code region. Return JSON only as {\"replacement\": \"...\", "
        "\"label\": \"short description\"}. The replacement must contain the complete replacement "
        "for SELECTED_CODE, without Markdown fences. Preserve indentation and do not modify context.",
        f"Language: {language}\nInstruction: {instruction}\n"
        f"<CONTEXT_BEFORE>\n{before}\n</CONTEXT_BEFORE>\n"
        f"<SELECTED_CODE>\n{code}\n</SELECTED_CODE>\n"
        f"<CONTEXT_AFTER>\n{after}\n</CONTEXT_AFTER>",
        max_tokens=2400,
        temperature=0.1,
        role="edit",
    )
    if "replacement" not in data:
        raise AIServiceError("Model did not return a replacement")
    return {
        "replacement": str(data.get("replacement") or ""),
        "label": str(data.get("label") or instruction)[:180],
        **meta,
    }


def _diff_hunks(original: str, updated: str) -> Iterable[Dict[str, Any]]:
    old_lines = original.replace("\r\n", "\n").split("\n")
    new_lines = updated.replace("\r\n", "\n").split("\n")
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    for index, (tag, old_start, old_end, new_start, new_end) in enumerate(matcher.get_opcodes()):
        if tag == "equal":
            continue
        yield {
            "start": old_start,
            "end": old_end,
            "newLines": new_lines[new_start:new_end],
            "label": f"AI {tag} · lines {old_start + 1}-{max(old_start + 1, old_end)}",
            "id": index,
        }


def _edit(body: Dict[str, Any]) -> Dict[str, Any]:
    code = _bounded_text(body.get("code"), 24000, "code")
    instruction = _bounded_text(body.get("instruction"), 1600, "instruction")
    language = _bounded_text(body.get("language"), 80, "language")
    path = _bounded_text(body.get("path"), 500, "path")
    if not instruction:
        raise AIServiceError("instruction is required")
    data, meta = _call_json(
        "You are a careful coding agent editing one complete file. Return JSON only as "
        "{\"updated_code\": \"the complete updated file\"}. Implement the instruction, preserve "
        "unrelated code byte-for-byte where possible, never use Markdown fences, and never omit code.",
        f"Language: {language}\nFile: {path}\nInstruction: {instruction}\n<CURRENT_FILE>\n{code}\n</CURRENT_FILE>",
        max_tokens=4096,
        temperature=0.1,
        role="edit",
    )
    updated = str(data.get("updated_code") or "")
    if not updated:
        raise AIServiceError("Model did not return updated_code")
    hunks = list(_diff_hunks(code, updated))
    return {"hunks": hunks, "changed": bool(hunks), **meta}


def _review(body: Dict[str, Any]) -> Dict[str, Any]:
    code = _bounded_text(body.get("code"), 26000, "code")
    language = _bounded_text(body.get("language"), 80, "language")
    path = _bounded_text(body.get("path"), 500, "path")
    data, meta = _call_json(
        "You are a concise senior code reviewer. Find real correctness, security, reliability, and "
        "maintainability problems. Return JSON only as {\"issues\":[{\"line\":1,\"endLine\":1," 
        "\"severity\":\"error|warning|info\",\"message\":\"...\",\"suggestion\":\"...\"}]}. "
        "Use 1-based line numbers, report at most 12 issues, and do not invent problems.",
        f"Language: {language}\nFile: {path}\n<CODE>\n{code}\n</CODE>",
        max_tokens=1800,
        temperature=0.1,
        role="chat",
    )
    line_count = max(1, code.count("\n") + 1)
    issues = []
    for raw in data.get("issues", []) if isinstance(data.get("issues"), list) else []:
        if not isinstance(raw, dict):
            continue
        line = min(line_count, max(1, int(raw.get("line", 1))))
        end_line = min(line_count, max(line, int(raw.get("endLine", line))))
        severity = str(raw.get("severity", "warning")).lower()
        if severity not in {"error", "warning", "info", "hint"}:
            severity = "warning"
        message = str(raw.get("message") or "").strip()
        if not message:
            continue
        issues.append({
            "line": line,
            "endLine": end_line,
            "severity": severity,
            "message": message[:500],
            "suggestion": str(raw.get("suggestion") or "")[:800],
            "code": "ai.review",
        })
    return {"issues": issues[:12], **meta}


def _commit_message(body: Dict[str, Any]) -> Dict[str, Any]:
    changes = _bounded_text(body.get("changes"), 18000, "changes")
    if not changes.strip():
        raise AIServiceError("changes is required")
    data, meta = _call_json(
        "Generate one concise Conventional Commit subject. Return JSON only as {\"message\":\"...\"}. "
        "Use an appropriate type such as feat, fix, refactor, docs, test, chore, or perf. Keep it under 72 characters.",
        f"<CHANGES>\n{changes}\n</CHANGES>",
        max_tokens=120,
        temperature=0.1,
        role="chat",
    )
    message = str(data.get("message") or "").strip().splitlines()[0][:120]
    if not re.match(r"^(feat|fix|refactor|docs|test|chore|perf|build|ci|style)(\([^)]+\))?!?:\s+\S", message):
        raise AIServiceError("Model did not return a Conventional Commit subject")
    return {"message": message, **meta}


def _test_provider(_: Dict[str, Any]) -> Dict[str, Any]:
    data, meta = _call_json(
        "Return JSON only.",
        'Return exactly {"ok": true, "message": "调用成功"}.',
        max_tokens=40,
        temperature=0.0,
        role="chat",
    )
    return {"ok": bool(data.get("ok")), "message": str(data.get("message") or ""), **meta}


def _probe_provider(_: Dict[str, Any]) -> Dict[str, Any]:
    global _last_probe
    client = _require_client("chat")
    result = probe_model(client).as_dict()
    result["checked_at"] = time.time()
    config = _runtime_config("chat")
    status = get_ai_status("chat")
    result["fingerprint"] = f"{status['provider']}|{config.get('base_url', '')}|{config.get('model', '')}"
    if config.get("profile_id"):
        checks = result.get("checks", {})
        latencies = [float(value.get("latency_ms", 0)) for value in checks.values() if isinstance(value, dict)] if isinstance(checks, dict) else []
        report_model_result(
            config["profile_id"],
            ok=bool(result.get("healthy")),
            latency_ms=sum(latencies) / len(latencies) if latencies else 0,
            error=None if result.get("healthy") else "capability probe failed",
        )
    with _diagnostic_lock:
        _last_probe = result
    return result


OPERATIONS = {
    "completion": _completion,
    "next-edit": _next_edit,
    "inline-edit": _inline_edit,
    "edit": _edit,
    "review": _review,
    "commit-message": _commit_message,
    "test": _test_provider,
    "probe": _probe_provider,
}


_OPERATION_ROLES = {
    "completion": "autocomplete",
    "next-edit": "edit",
    "inline-edit": "edit",
    "edit": "edit",
    "review": "chat",
    "commit-message": "chat",
    "test": "chat",
}


def run_ai_operation(operation: str, body: Dict[str, Any]) -> Dict[str, Any]:
    handler = OPERATIONS.get(operation)
    if handler is None:
        raise AIServiceError(f"Unsupported AI operation: {operation}")
    required_role = _OPERATION_ROLES.get(operation)
    with _diagnostic_lock:
        probe = dict(_last_probe) if _last_probe else None
    if probe is not None and probe.get("fingerprint") != get_ai_status().get("fingerprint"):
        probe = None
    if required_role and probe is not None:
        if not probe.get("healthy"):
            raise AIServiceError("The configured model failed its health probe. Run the probe again after fixing provider settings.")
        if not probe.get("capabilities", {}).get(required_role, False):
            raise AIServiceError(f"The configured model does not support the required '{required_role}' role.")
    result = handler(body or {})
    result["operation"] = operation
    return result
