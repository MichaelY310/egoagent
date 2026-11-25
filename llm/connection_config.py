"""Resolve explicit model settings before global defaults, without network I/O."""

from collections.abc import Mapping
from urllib.parse import urlsplit


def _text(value):
    return str(value or "").strip()


def _origin(url):
    try:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
            return None
        return parts.scheme, parts.hostname.lower(), parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        return None


def resolve_connection(config: Mapping, environ: Mapping) -> dict[str, str]:
    """Blank URL/model fields inherit independently; explicit values never fall back.

    Global credentials may only accompany their configured endpoint (same
    scheme/host/port). Another server must explicitly configure its own secret
    or api_key_env. A keyless local server must not receive a cloud API key.
    """
    defaults = (
        ("https://api.deepseek.com", "deepseek-v4-flash", "DEEPSEEK_API_KEY"),
        ("https://api.siliconflow.cn/v1", "Qwen/Qwen3-8B", "SILICONFLOW_API_KEY"),
    )
    default_base = next((base for base, _, key in defaults if _text(environ.get(key))), "")
    global_base = _text(environ.get("EGOAGENT_LLM_BASE_URL")) or default_base
    base_url = (_text(config.get("base_url")) or global_base).rstrip("/")
    origin = _origin(base_url)
    matching_provider = next((item for item in defaults if origin and _origin(item[0]) == origin), None)
    model = (_text(config.get("model")) or _text(environ.get("EGOAGENT_LLM_MODEL"))
             or (matching_provider[1] if matching_provider else ""))
    if not base_url:
        raise ValueError("LLM base_url is not configured")
    if not model:
        raise ValueError("LLM model is not configured")

    key_env = _text(config.get("api_key_env"))
    api_key = _text(config.get("api_key")) or _text(environ.get(key_env))
    if key_env and not api_key:
        raise ValueError(f"LLM API key environment variable is not configured: {key_env}")
    if not api_key and origin and origin == _origin(global_base):
        api_key = _text(environ.get("EGOAGENT_LLM_API_KEY"))
    if not api_key and matching_provider:
        api_key = _text(environ.get(matching_provider[2]))
    return {"base_url": base_url, "model": model, "api_key": api_key}
