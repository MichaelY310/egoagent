"""Product release surface. Not a sandbox; trusted core libraries stay reusable.

JSON manifests are also consumed by the Workbench build. A development branch
enables its own manifest only after meeting the recorded acceptance criteria.
"""
from functools import lru_cache
from fnmatch import fnmatchcase
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


@lru_cache(maxsize=1)
def manifests():
    return {p.stem: json.loads(p.read_text(encoding="utf-8"))
            for p in sorted((ROOT / "product_features").glob("*.json"))}


def enabled(feature, flags=None, seen=()):
    flags = manifests() if flags is None else flags
    item = flags.get(feature)
    return bool(item and feature not in seen and item.get("enabled") and all(
        enabled(dep, flags, (*seen, feature)) for dep in item.get("depends", [])))


def disabled_api(path):
    if path.endswith('/trajectory/export') and not enabled('training'):
        return 'training'
    for key, item in manifests().items():
        if not enabled(key) and any(path == p or path.startswith(p + "/") for p in item.get("api_prefixes", [])):
            return key
    return None


def identity_blocker(name):
    name = str(name).replace("\\", "/").rsplit("/", 1)[-1]
    for key, item in manifests().items():
        if not enabled(key) and any(fnmatchcase(name, pattern) for pattern in item.get("identity_patterns", [])):
            return key
    return None


def flow_blocker(name, config=None, *, root=None, seen=()):
    """Check named templates AND static SubFlow dependencies, with cycle guards."""
    name = str(name).replace("\\", "/").rsplit("/", 1)[-1]
    for key, item in manifests().items():
        if not enabled(key) and (name in item.get("flows", []) or any(
                fnmatchcase(name, pattern) for pattern in item.get("flow_patterns", []))):
            return key
    if name in seen:
        return None
    root = Path(root) if root is not None else ROOT / "harness"
    if config is None:
        path = root / name / "config.json"
        if not path.is_file():
            return None
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return "invalid-flow"
    for node in (config.get("pipeline", {}).get("nodes", {}) or {}).values():
        child = node.get("harness") if isinstance(node, dict) else None
        if isinstance(child, str) and not child.startswith("$"):
            reason = flow_blocker(child, root=root, seen=(*seen, name))
            if reason:
                return reason
    return None


def require_flow(name, config=None):
    reason = flow_blocker(name, config)
    if reason:
        raise ValueError(f"Flow '{name}' requires unreleased feature '{reason}'. Use its development branch; main does not enable it.")
