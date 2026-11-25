"""Role-aware model profiles, routing, budgets, and experiment management.

Only secret *names* are persisted.  API key values are resolved from the
process environment at request time and are never returned by public APIs.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from llm.providers import MODEL_ROLES


# ============================================================
# Paths
# ============================================================

_BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.egoagent')
_PROFILE_CONFIG_PATH = os.path.join(_BASE_DIR, 'model_profiles.json')
_LEGACY_MODEL_CONFIG_PATH = os.path.join(_BASE_DIR, 'model_config.json')
_EXPERIMENTS_DIR = os.path.join(_BASE_DIR, 'experiments')
_lock = threading.RLock()
_run_budgets: Dict[str, Dict[str, float]] = {}
_STATE_VERSION = 2

_ROLE_DEFAULTS = {
    "chat": ("tool_use", "reasoning"),
    "tool_use": ("chat",),
    "edit": ("apply", "chat"),
    "apply": ("edit",),
    "autocomplete": ("edit", "chat"),
    "embedding": (),
    "rerank": ("embedding",),
    "vision": ("chat",),
    "reasoning": ("chat",),
    "judge": ("reasoning", "chat"),
    "evolver": ("reasoning", "tool_use", "chat"),
}


# ============================================================
# Multi-Model Router
# ============================================================

def _ensure_dirs() -> None:
    os.makedirs(_BASE_DIR, exist_ok=True)
    os.makedirs(_EXPERIMENTS_DIR, exist_ok=True)


def configure_profile_store(path=None):
    global _PROFILE_CONFIG_PATH
    with _lock:
        _PROFILE_CONFIG_PATH = str(Path(path).resolve()) if path else os.path.join(_BASE_DIR, 'model_profiles.json')
        return _PROFILE_CONFIG_PATH


def _empty_state():
    profiles = _bootstrap_profiles()
    configured = [item for item in profiles if _profile_has_secret(item) or _is_local(item)]
    ordered = configured or profiles
    return {
        "version": _STATE_VERSION,
        "profiles": profiles,
        "roles": {role: [item["id"] for item in ordered if role in item.get("roles", [])] for role in _ROLE_DEFAULTS},
        "health": {},
    }


def _bootstrap_profiles():
    profiles = []
    candidates = [
        ("deepseek-default", "DeepSeek", "deepseek", "https://api.deepseek.com", "deepseek-v4-flash", "DEEPSEEK_API_KEY"),
        ("siliconflow-default", "SiliconFlow", "siliconflow", "https://api.siliconflow.cn/v1", "Qwen/Qwen3-8B", "SILICONFLOW_API_KEY"),
    ]
    generic_url = os.environ.get("EGOAGENT_LLM_BASE_URL", "").strip()
    generic_model = os.environ.get("EGOAGENT_LLM_MODEL", "").strip()
    if generic_url and generic_model:
        generic_provider = os.environ.get("EGOAGENT_LLM_PROVIDER", "").strip() or (
            "deepseek" if "deepseek" in generic_url.lower() else
            "siliconflow" if "siliconflow" in generic_url.lower() else
            "ollama" if any(value in generic_url.lower() for value in ("localhost", "127.0.0.1", "11434")) else
            "openai_compatible"
        )
        generic_secret = "EGOAGENT_LLM_API_KEY" if os.environ.get("EGOAGENT_LLM_API_KEY", "").strip() else _default_secret_name(generic_provider)
        candidates.insert(0, ("egoagent-default", "EgoAgent provider", generic_provider, generic_url, generic_model, generic_secret))
    for profile_id, name, provider, base_url, model, secret_name in candidates:
        profiles.append(_normalize_profile({
            "id": profile_id, "name": name, "provider": provider, "base_url": base_url,
            "model": model, "api_key_env": secret_name, "priority": 50,
            "roles": list(_ROLE_DEFAULTS), "context_window": 128000,
        }))
    profiles.append(_normalize_profile({
        "id": "ollama-local", "name": "Ollama local", "provider": "ollama",
        "base_url": "http://127.0.0.1:11434/v1", "model": "qwen3:8b",
        "api_key_env": "", "priority": 10, "roles": list(_ROLE_DEFAULTS),
        "context_window": 32768,
    }))
    return profiles


def _load_state():
    with _lock:
        _ensure_dirs()
        if os.path.isfile(_PROFILE_CONFIG_PATH):
            try:
                data = json.loads(Path(_PROFILE_CONFIG_PATH).read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("profiles"), list):
                    data["profiles"] = [_normalize_profile(item) for item in data["profiles"] if isinstance(item, dict)]
                    data.setdefault("roles", {})
                    data.setdefault("health", {})
                    _refresh_generic_environment_profile(data)
                    return data
            except (OSError, ValueError, TypeError):
                pass
        state = _migrate_legacy() or _empty_state()
        _save_state(state)
        return state


def _refresh_generic_environment_profile(state):
    """Prevent a persisted temporary/test endpoint from masking current env setup.

    The generic profile is a projection of EGOAGENT_LLM_* variables, not an
    independent editable profile.  Named provider profiles remain untouched.
    """
    base_url = os.environ.get("EGOAGENT_LLM_BASE_URL", "").strip()
    model = os.environ.get("EGOAGENT_LLM_MODEL", "").strip()
    if not (base_url and model):
        return False
    provider = os.environ.get("EGOAGENT_LLM_PROVIDER", "").strip() or (
        "deepseek" if "deepseek" in base_url.lower() else
        "siliconflow" if "siliconflow" in base_url.lower() else
        "ollama" if any(value in base_url.lower() for value in ("localhost", "127.0.0.1", "11434")) else
        "openai_compatible"
    )
    secret_name = "EGOAGENT_LLM_API_KEY" if os.environ.get("EGOAGENT_LLM_API_KEY", "").strip() else _default_secret_name(provider)
    replacement = _normalize_profile({
        "id": "egoagent-default",
        "name": "EgoAgent environment provider",
        "provider": provider,
        "base_url": base_url,
        "model": model,
        "api_key_env": secret_name,
        "priority": 50,
        "roles": list(_ROLE_DEFAULTS),
        "context_window": 128000,
    })
    profiles = state.setdefault("profiles", [])
    for index, profile in enumerate(profiles):
        if profile.get("id") == "egoagent-default":
            changed = profile != replacement
            profiles[index] = replacement
            return changed
    profiles.insert(0, replacement)
    return True


def _save_state(state):
    with _lock:
        _ensure_dirs()
        sanitized = dict(state)
        sanitized["version"] = _STATE_VERSION
        sanitized["profiles"] = [_normalize_profile(item) for item in state.get("profiles", [])]
        target = Path(_PROFILE_CONFIG_PATH)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(json.dumps(sanitized, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, target)


def _migrate_legacy():
    if not os.path.isfile(_LEGACY_MODEL_CONFIG_PATH):
        return None
    try:
        legacy = json.loads(Path(_LEGACY_MODEL_CONFIG_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(legacy, list):
        return None
    profiles = []
    for raw in legacy:
        if not isinstance(raw, dict):
            continue
        provider = str(raw.get("provider") or "openai_compatible")
        profiles.append(_normalize_profile({
            "id": raw.get("id"), "name": raw.get("name"), "provider": provider,
            "base_url": raw.get("base_url") or raw.get("url"),
            "model": raw.get("model") or raw.get("model_name"),
            "api_key_env": raw.get("api_key_env") or _default_secret_name(provider),
            "max_tokens": raw.get("max_tokens"), "temperature": raw.get("temperature"),
            "priority": raw.get("priority"), "roles": raw.get("roles") or list(_ROLE_DEFAULTS),
        }))
    if not profiles:
        return None
    return {"version": _STATE_VERSION, "profiles": profiles, "roles": {role: [item["id"] for item in profiles] for role in _ROLE_DEFAULTS}, "health": {}}


def _normalize_profile(raw):
    if raw.get("api_key"):
        raise ValueError("Plaintext api_key cannot be stored in a model profile; use api_key_env")
    profile_id = str(raw.get("id") or uuid.uuid4().hex[:12])
    provider = str(raw.get("provider") or "openai_compatible").lower().replace("-", "_")
    base_url = str(raw.get("base_url") or raw.get("url") or "").rstrip("/")
    if base_url.endswith("/chat/completions"):
        base_url = base_url.rsplit("/chat/completions", 1)[0]
    roles = [str(role) for role in raw.get("roles", []) if str(role) in _ROLE_DEFAULTS]
    return {
        "id": profile_id,
        "name": str(raw.get("name") or profile_id)[:120],
        "provider": provider,
        "base_url": base_url,
        "model": str(raw.get("model") or raw.get("model_name") or ""),
        "api_key_env": str(raw.get("api_key_env") or _default_secret_name(provider)),
        "enabled": raw.get("enabled") is not False,
        "priority": int(raw.get("priority") or 0),
        "roles": roles or ["chat"],
        "context_window": max(1, int(raw.get("context_window") or 32768)),
        "max_tokens": max(1, int(raw.get("max_tokens") or 4096)),
        "temperature": float(raw.get("temperature") if raw.get("temperature") is not None else 0.2),
        "input_cost_per_m": max(0.0, float(raw.get("input_cost_per_m") or 0.0)),
        "output_cost_per_m": max(0.0, float(raw.get("output_cost_per_m") or 0.0)),
        "latency_weight": max(0.0, float(raw.get("latency_weight") if raw.get("latency_weight") is not None else 0.002)),
        "cost_weight": max(0.0, float(raw.get("cost_weight") if raw.get("cost_weight") is not None else 100.0)),
        "capabilities": dict(raw.get("capabilities") or {}),
        "enable_thinking": bool(raw.get("enable_thinking")),
    }


def _default_secret_name(provider):
    return {
        "deepseek": "DEEPSEEK_API_KEY",
        "siliconflow": "SILICONFLOW_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "anthropic_compatible": "ANTHROPIC_API_KEY",
        "ollama": "",
    }.get(str(provider).lower().replace("-", "_"), "EGOAGENT_LLM_API_KEY")


def _is_local(profile):
    url = profile.get("base_url", "").lower()
    return profile.get("provider") == "ollama" or any(host in url for host in ("127.0.0.1", "localhost", ":11434"))


def _profile_has_secret(profile):
    name = str(profile.get("api_key_env") or "")
    return bool(name and os.environ.get(name, "").strip())


def _public_profile(profile, health=None):
    value = dict(profile)
    value.pop("api_key", None)
    value["has_api_key"] = _profile_has_secret(profile)
    value["health"] = dict(health or {})
    return value


def list_model_profiles():
    state = _load_state()
    return [_public_profile(item, state.get("health", {}).get(item["id"])) for item in state["profiles"]]


def get_role_assignments():
    state = _load_state()
    return {role: list(state.get("roles", {}).get(role, [])) for role in _ROLE_DEFAULTS}


def upsert_model_profile(profile):
    normalized = _normalize_profile(dict(profile or {}))
    with _lock:
        state = _load_state()
        existing = next((i for i, item in enumerate(state["profiles"]) if item["id"] == normalized["id"]), None)
        if existing is None:
            state["profiles"].append(normalized)
        else:
            state["profiles"][existing] = normalized
        _save_state(state)
    return _public_profile(normalized, state.get("health", {}).get(normalized["id"]))


def assign_model_role(role, profile_ids):
    role = str(role)
    if role not in _ROLE_DEFAULTS:
        raise ValueError(f"Unknown model role: {role}")
    with _lock:
        state = _load_state()
        known = {item["id"] for item in state["profiles"]}
        values = []
        for profile_id in profile_ids or []:
            value = str(profile_id)
            if value not in known:
                raise ValueError(f"Unknown model profile: {value}")
            if value not in values:
                values.append(value)
        state.setdefault("roles", {})[role] = values
        _save_state(state)
    return {"role": role, "profiles": values}


def remove_model(model_id: str) -> Dict:
    with _lock:
        state = _load_state()
        before = len(state["profiles"])
        state["profiles"] = [item for item in state["profiles"] if item["id"] != model_id]
        if len(state["profiles"]) == before:
            return {"removed": False, "error": f"Model '{model_id}' not found"}
        for role in state.get("roles", {}):
            state["roles"][role] = [value for value in state["roles"][role] if value != model_id]
        state.get("health", {}).pop(model_id, None)
        _save_state(state)
        return {"removed": True, "id": model_id}


def route_model(role="chat", *, model_id=None, context_tokens=0, expected_output_tokens=0, run_id=None, include_secret=False):
    role = str(role or "chat")
    if role not in _ROLE_DEFAULTS:
        return {"error": f"Unknown model role: {role}"}
    state = _load_state()
    profiles = {item["id"]: item for item in state["profiles"]}
    if model_id:
        order = [str(model_id)]
    else:
        # A non-empty role assignment is the user's complete, ordered policy.
        # Silently appending every capable profile makes it impossible to exclude
        # an expensive or untrusted model from a role.  Capability discovery and
        # related-role fallbacks are only used for an unconfigured role.
        order = list(state.get("roles", {}).get(role, []))
        if not order:
            for fallback_role in _ROLE_DEFAULTS.get(role, ()):
                order.extend(state.get("roles", {}).get(fallback_role, []))
            order.extend(item["id"] for item in state["profiles"] if role in item.get("roles", []))
    seen, eligible = set(), []
    now = time.time()
    remaining = get_run_budget(run_id).get("remaining") if run_id else None
    for rank, profile_id in enumerate(order):
        if profile_id in seen or profile_id not in profiles:
            continue
        seen.add(profile_id)
        profile = profiles[profile_id]
        health = state.get("health", {}).get(profile_id, {})
        if os.environ.get("EGOAGENT_OFFLINE", "").strip().lower() in {"1", "true", "yes", "on"} and not _is_local(profile):
            continue
        if not profile.get("enabled") or int(profile.get("context_window", 0)) < int(context_tokens or 0):
            continue
        if not (_is_local(profile) or _profile_has_secret(profile)):
            continue
        if float(health.get("circuit_open_until", 0)) > now:
            continue
        cost = estimate_request_cost(profile, context_tokens, expected_output_tokens)
        if remaining is not None and cost > remaining:
            continue
        latency = float(health.get("ewma_latency_ms", 0))
        success_rate = float(health.get("success_rate", 1.0))
        score = float(profile.get("priority", 0)) * 100 + success_rate * 25 - rank
        score -= latency * float(profile.get("latency_weight", 0.002))
        score -= cost * float(profile.get("cost_weight", 100.0))
        eligible.append((score, cost, profile, health))
    if not eligible:
        return {"error": f"No healthy configured model is eligible for role '{role}'", "role": role}
    _, estimated_cost, selected, health = max(eligible, key=lambda item: item[0])
    result = dict(selected)
    result["selection"] = {"role": role, "estimated_cost": estimated_cost, "fallback_order": order}
    result["health"] = dict(health)
    if include_secret:
        name = result.get("api_key_env")
        result["api_key"] = os.environ.get(name, "").strip() if name else ("ollama-local" if _is_local(result) else "")
    else:
        result = _public_profile(result, health)
    return result


def estimate_request_cost(profile, input_tokens, output_tokens):
    return (
        float(input_tokens or 0) * float(profile.get("input_cost_per_m", 0))
        + float(output_tokens or 0) * float(profile.get("output_cost_per_m", 0))
    ) / 1_000_000


def report_model_result(profile_id, *, ok, latency_ms=0, usage=None, run_id=None, error=None):
    with _lock:
        state = _load_state()
        health = state.setdefault("health", {}).setdefault(str(profile_id), {})
        calls = int(health.get("calls", 0)) + 1
        successes = int(health.get("successes", 0)) + (1 if ok else 0)
        previous_latency = float(health.get("ewma_latency_ms", 0))
        health.update({
            "calls": calls,
            "successes": successes,
            "success_rate": successes / calls,
            "ewma_latency_ms": float(latency_ms) if not previous_latency else previous_latency * 0.8 + float(latency_ms) * 0.2,
            "last_checked_at": time.time(),
            "last_error": None if ok else str(error or "request failed")[:500],
        })
        failures = 0 if ok else int(health.get("consecutive_failures", 0)) + 1
        health["consecutive_failures"] = failures
        if failures >= 3:
            health["circuit_open_until"] = time.time() + min(600, 30 * (2 ** min(4, failures - 3)))
        elif ok:
            health["circuit_open_until"] = 0
        _save_state(state)
        profile = next((item for item in state["profiles"] if item["id"] == profile_id), {})
    usage = usage or {}
    cost = estimate_request_cost(profile, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
    if run_id:
        with _lock:
            budget = _run_budgets.setdefault(str(run_id), {"limit": float("inf"), "spent": 0.0})
            budget["spent"] += cost
    return {"profile_id": profile_id, "cost": cost, "health": dict(health)}


def set_run_budget(run_id, limit):
    with _lock:
        _run_budgets[str(run_id)] = {"limit": max(0.0, float(limit)), "spent": 0.0}
        return get_run_budget(run_id)


def get_run_budget(run_id):
    if not run_id:
        return {"limit": None, "spent": 0.0, "remaining": None}
    with _lock:
        value = _run_budgets.get(str(run_id), {"limit": float("inf"), "spent": 0.0})
        limit = value["limit"]
        return {"limit": None if math.isinf(limit) else limit, "spent": value["spent"], "remaining": float("inf") if math.isinf(limit) else max(0.0, limit - value["spent"])}


# Backward-compatible endpoint API.
def list_models() -> List[Dict]:
    return list_model_profiles()


def add_model(endpoint: Dict) -> Dict:
    return upsert_model_profile(endpoint)


def route_request(model_id: Optional[str] = None) -> Dict:
    return route_model("chat", model_id=model_id)


# ============================================================
# Experiment Management
# ============================================================

def _experiment_path(exp_id: str) -> str:
    """Return the file path for an experiment JSON."""
    return os.path.join(_EXPERIMENTS_DIR, f"{exp_id}.json")


def _load_experiment(exp_id: str) -> Optional[Dict]:
    """Load a single experiment by ID."""
    path = _experiment_path(exp_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError):
        return None


def _save_experiment(experiment: Dict) -> None:
    """Persist an experiment to disk."""
    _ensure_dirs()
    path = _experiment_path(experiment['id'])
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(experiment, f, indent=2, ensure_ascii=False)
    except IOError:
        pass


def create_experiment(name: str, description: str, variants: List[Dict]) -> Dict:
    """
    Create a new experiment.

    Each variant should have: {"identity": str, "harness": str, "weight": float}
    Returns the created experiment dict.
    """
    exp_id = str(uuid.uuid4())[:8]
    experiment = {
        "id": exp_id,
        "name": name,
        "description": description,
        "variants": variants,
        "results": [],
        "status": "active",
        "created_at": datetime.now().isoformat(),
    }
    _save_experiment(experiment)
    return experiment


def list_experiments() -> List[Dict]:
    """List all experiments with their status."""
    _ensure_dirs()
    experiments = []
    try:
        for filename in os.listdir(_EXPERIMENTS_DIR):
            if filename.endswith('.json'):
                exp_id = filename[:-5]
                exp = _load_experiment(exp_id)
                if exp:
                    experiments.append({
                        "id": exp["id"],
                        "name": exp.get("name", ""),
                        "status": exp.get("status", "unknown"),
                        "created_at": exp.get("created_at", ""),
                        "num_results": len(exp.get("results", [])),
                    })
    except IOError:
        pass
    return experiments


def get_experiment(exp_id: str) -> Dict:
    """
    Get full experiment details by ID.

    Returns the experiment dict or {"error": "..."} if not found.
    """
    exp = _load_experiment(exp_id)
    if exp is None:
        return {"error": f"Experiment '{exp_id}' not found"}
    return exp


def record_result(exp_id: str, variant_idx: int, score: float, metadata: Optional[Dict] = None) -> Dict:
    """
    Record an evaluation result for an experiment variant.

    Returns the recorded result entry or {"error": "..."} on failure.
    """
    exp = _load_experiment(exp_id)
    if exp is None:
        return {"error": f"Experiment '{exp_id}' not found"}

    if variant_idx < 0 or variant_idx >= len(exp.get("variants", [])):
        return {"error": f"Invalid variant_idx {variant_idx}"}

    result_entry = {
        "variant_idx": variant_idx,
        "score": score,
        "metadata": metadata or {},
        "recorded_at": datetime.now().isoformat(),
    }
    exp.setdefault("results", []).append(result_entry)
    _save_experiment(exp)
    return result_entry


def get_experiment_stats(exp_id: str) -> Dict:
    """
    Get per-variant statistics for an experiment.

    Returns {"variants": [{"variant_idx": int, "count": int, "mean": float, "std": float}, ...]}
    or {"error": "..."} if experiment not found.
    """
    exp = _load_experiment(exp_id)
    if exp is None:
        return {"error": f"Experiment '{exp_id}' not found"}

    variants = exp.get("variants", [])
    results = exp.get("results", [])

    stats = []
    for idx in range(len(variants)):
        scores = [r["score"] for r in results if r.get("variant_idx") == idx]
        count = len(scores)
        if count == 0:
            stats.append({"variant_idx": idx, "count": 0, "mean": 0.0, "std": 0.0})
        else:
            mean = sum(scores) / count
            variance = sum((s - mean) ** 2 for s in scores) / count
            std = math.sqrt(variance)
            stats.append({"variant_idx": idx, "count": count, "mean": mean, "std": std})

    return {"experiment_id": exp_id, "variants": stats}
