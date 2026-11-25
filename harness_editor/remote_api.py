"""Compatibility alias; implementation lives in egoagent_server.remote_api."""
import importlib
import sys
from pathlib import Path

# Retain direct script/legacy sys.path entry points, not a second implementation.
_root = str(Path(__file__).resolve().parents[1])
if _root not in sys.path:
    sys.path.insert(0, _root)
_implementation = importlib.import_module("egoagent_server.remote_api")
sys.modules[__name__] = _implementation
