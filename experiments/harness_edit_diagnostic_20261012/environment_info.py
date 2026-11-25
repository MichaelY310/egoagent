"""Record reproducibility metadata without reading credentials or user config."""
import importlib.metadata
import json
import platform
from pathlib import Path
import sys

root = Path(__file__).resolve().parent
value = {"python": sys.version, "platform": platform.platform(), "executable": sys.executable, "packages": dict(sorted((d.metadata["Name"], d.version) for d in importlib.metadata.distributions())), "runtime": "Dedicated WSL virtualenv, one regression cell at a time; no GPU or paid model calls", "isolation": "Fresh source/fixture copies; allowlisted process environment; external Python socket connects blocked. Not OS/container filesystem isolation."}
(root / "results/environment.json").write_text(json.dumps(value, indent=2) + "\n")
print(value["python"], value["platform"], len(value["packages"]), "packages")
