"""
Multi-Model Router and Experiment Management module.

Provides:
- Model endpoint configuration with JSON persistence
- Request routing by priority or explicit model ID
- Experiment creation, tracking, and statistical analysis
"""

import json
import os
import uuid
import math
from typing import Dict, List, Optional
from datetime import datetime


# ============================================================
# Paths
# ============================================================

_BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.egoagent')
_MODEL_CONFIG_PATH = os.path.join(_BASE_DIR, 'model_config.json')
_EXPERIMENTS_DIR = os.path.join(_BASE_DIR, 'experiments')

_DEFAULT_MODEL: Dict = {
    "id": "qwen-default",
    "name": "Qwen (vLLM)",
    "url": "http://[fdbd:dc05:10:10a::27]:9638/v1/chat/completions",
    "model_name": "qwen",
    "api_key": None,
    "max_tokens": 4096,
    "temperature": 0.7,
    "priority": 10,
}


# ============================================================
# Multi-Model Router
# ============================================================

def _ensure_dirs() -> None:
    """Ensure storage directories exist."""
    try:
        os.makedirs(_BASE_DIR, exist_ok=True)
        os.makedirs(_EXPERIMENTS_DIR, exist_ok=True)
    except IOError:
        pass


def _load_config() -> List[Dict]:
    """Load model endpoints from the JSON persistence file."""
    _ensure_dirs()
    if not os.path.exists(_MODEL_CONFIG_PATH):
        # Initialize with default model
        _save_config([_DEFAULT_MODEL])
        return [_DEFAULT_MODEL.copy()]
    try:
        with open(_MODEL_CONFIG_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return [_DEFAULT_MODEL.copy()]
    except (IOError, json.JSONDecodeError):
        return [_DEFAULT_MODEL.copy()]


def _save_config(endpoints: List[Dict]) -> None:
    """Persist model endpoints to the JSON file."""
    _ensure_dirs()
    try:
        with open(_MODEL_CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(endpoints, f, indent=2, ensure_ascii=False)
    except IOError:
        pass


def list_models() -> List[Dict]:
    """List all configured model endpoints."""
    return _load_config()


def add_model(endpoint: Dict) -> Dict:
    """
    Add a new model endpoint.

    If 'id' is not provided in the endpoint dict, one is auto-generated.
    Returns the added endpoint dict.
    """
    endpoints = _load_config()
    if 'id' not in endpoint or not endpoint['id']:
        endpoint['id'] = str(uuid.uuid4())[:8]
    # Apply defaults for optional fields
    endpoint.setdefault('api_key', None)
    endpoint.setdefault('max_tokens', 4096)
    endpoint.setdefault('temperature', 0.7)
    endpoint.setdefault('priority', 0)
    endpoints.append(endpoint)
    _save_config(endpoints)
    return endpoint


def remove_model(model_id: str) -> Dict:
    """
    Remove a model endpoint by its ID.

    Returns {"removed": True, "id": model_id} on success,
    or {"removed": False, "error": "..."} if not found.
    """
    endpoints = _load_config()
    new_endpoints = [ep for ep in endpoints if ep.get('id') != model_id]
    if len(new_endpoints) == len(endpoints):
        return {"removed": False, "error": f"Model '{model_id}' not found"}
    _save_config(new_endpoints)
    return {"removed": True, "id": model_id}


def route_request(model_id: Optional[str] = None) -> Dict:
    """
    Return the endpoint config to use for a request.

    If model_id is given, returns that specific endpoint.
    Otherwise returns the endpoint with the highest priority value.
    Returns {"error": "..."} if no matching endpoint is found.
    """
    endpoints = _load_config()
    if not endpoints:
        return {"error": "No model endpoints configured"}

    if model_id is not None:
        for ep in endpoints:
            if ep.get('id') == model_id:
                return ep
        return {"error": f"Model '{model_id}' not found"}

    # Return highest priority
    best = max(endpoints, key=lambda ep: ep.get('priority', 0))
    return best


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
