from .custom_llm import CustomLLM
from .dummy_llm import DummyLLM
from model_gateway import DEFAULT_MODEL_GATEWAY
import json
import importlib.util
from pathlib import Path
from environment import load_environment_from_dir
from typing import Union
import sys
import glob
from utils import load_script



all_hook_names = {
    "pre_llm_hook",
    "post_llm_hook",
    "pre_tool_hook",
    "post_tool_hook",
}

llm_map = {
    "custom_llm": CustomLLM,
    "dummy_llm": DummyLLM,
}

class Skill:
    def __init__(self, skill_path: str):
        self.skill_path = Path(skill_path)
        with open(self.skill_path / "description.json", encoding="utf-8") as description_stream:
            self.description = json.load(description_stream)


def load_superego(superego_dir: Path):
    superego_dir = Path(superego_dir)
    if not superego_dir.exists():
        return None
    config_file = superego_dir / "config.json"
    assert config_file.exists(), f"ERROR: Superego {superego_dir} has no config.json"
    with open(config_file, encoding="utf-8") as config_stream:
        config = json.load(config_stream)

    # 加载 hooks
    hooks = {}
    for hook_name in all_hook_names:
        hook_file = superego_dir / (hook_name + ".py")
        if hook_file.exists():
            hook_func = load_script(hook_file, hook_name)
            if hook_func:
                hooks[hook_name] = hook_func
            else:
                print(f"WARNING: Hook {hook_name} not found in {hook_file}")
                hooks[hook_name] = None
    return config, hooks


class Identity:
    def __init__(self, identity_path: Union[str, Path]):
        self.identity_path = Path(identity_path).resolve()
        with open(self.identity_path / "id.json", encoding="utf-8") as identity_stream:
            self.ID = json.load(identity_stream)
        self.EGO = load_environment_from_dir(self.identity_path / "ego")
        self.EGO_INHERITS = []
        identity_root = self.identity_path.parent.resolve()
        capability_pack_root = (Path(__file__).resolve().parent.parent / "capability_packs").resolve()
        for inherited_name in self.ID.get("ego_inherits", []):
            inherited_name = str(inherited_name)
            if inherited_name.startswith("@pack/"):
                inherited_path = (capability_pack_root / inherited_name[len("@pack/"):]).resolve()
                if capability_pack_root != inherited_path and capability_pack_root not in inherited_path.parents:
                    raise ValueError(f"Inherited capability pack escapes repository: {inherited_name}")
                if not (inherited_path / "skills").is_dir() and not (inherited_path / "knowledge").is_dir():
                    raise FileNotFoundError(f"Inherited capability pack does not exist: {inherited_name}")
                self.EGO_INHERITS.append(load_environment_from_dir(inherited_path))
                continue
            inherited_path = (identity_root / inherited_name).resolve()
            if inherited_path == self.identity_path:
                raise ValueError(f"Identity cannot inherit its own EGO: {inherited_name}")
            if identity_root != inherited_path and identity_root not in inherited_path.parents:
                raise ValueError(f"Inherited EGO escapes identity repository: {inherited_name}")
            if not (inherited_path / "id.json").is_file():
                raise FileNotFoundError(f"Inherited Identity does not exist: {inherited_name}")
            self.EGO_INHERITS.append(load_environment_from_dir(inherited_path / "ego"))
        self.SEGO = load_superego(self.identity_path / "superego")

    def get_llm(self):
        type = self.ID["llm"]["type"]
        if type in {
            "openai_compatible", "deepseek", "siliconflow", "ollama",
            "anthropic", "anthropic_compatible",
        }:
            return DEFAULT_MODEL_GATEWAY.create(self.ID["llm"])
        llm = llm_map[type](self.ID["llm"])
        return llm
