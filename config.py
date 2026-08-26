import yaml
from pathlib import Path

_config_path = Path(__file__).parent / "config.yaml"
with open(_config_path, encoding="utf-8") as _config_file:
    CONFIG = yaml.safe_load(_config_file)


# Historical configs used absolute paths from the original Linux machine.
# Keep valid user-supplied locations, but make a checkout portable across
# Windows, Linux and macOS when those locations do not exist.
_repo_root = _config_path.parent
_portable_paths = {
    "root_environment_path": _repo_root / ".environment",
    "harness_template_repository": _repo_root / "harness",
    "identity_repository": _repo_root / "identity",
}
for _key, _fallback in _portable_paths.items():
    _configured = Path(str(CONFIG.get(_key, ""))).expanduser()
    if not _configured.is_absolute():
        _configured = _repo_root / _configured
    if not _configured.exists():
        _configured = _fallback
    CONFIG[_key] = str(_configured.resolve())

if CONFIG.get("registry_path"):
    _registry = Path(str(CONFIG["registry_path"])).expanduser()
    if not _registry.is_absolute():
        _registry = _repo_root / _registry
    CONFIG["registry_path"] = str(_registry.resolve())
