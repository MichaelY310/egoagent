import yaml
from pathlib import Path

_config_path = Path(__file__).parent / "config.yaml"
CONFIG = yaml.safe_load(open(_config_path))
print(CONFIG)