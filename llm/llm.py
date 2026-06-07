from .custom_llm import CustomLLM
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
    "pre_loop_hook",
    "post_loop_hook",
}

llm_map = {
    "custom_llm" : CustomLLM,
}

class Skill:
    def __init__(self, skill_path: str):
        self.skill_path = Path(skill_path)
        self.description = json.load(open(self.skill_path / "description.json"))


def load_superego(superego_dir: Path):
    superego_dir = Path(superego_dir)
    if not superego_dir.exists():
        return None
    config_file = superego_dir / "config.json"
    assert config_file.exists(), f"ERROR: Superego {superego_dir} has no config.json"
    config = json.load(open(config_file))

    # 加载 hooks
    hooks = {
        "pre_llm_hook": None,
        "post_llm_hook": None,
        "pre_tool_hook": None,
        "post_tool_hook": None,
        "pre_loop_hook": None,
        "post_loop_hook": None,
    }
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
        self.identity_path = Path(identity_path)
        self.ID = json.load(open(self.identity_path / "id.json"))
        self.EGO = load_environment_from_dir(self.identity_path / "ego")
        self.SEGO = load_superego(self.identity_path / "superego")

    def get_llm(self):
        type = self.ID["llm"]["type"]
        llm = llm_map[type](self.ID["llm"])
        return llm
