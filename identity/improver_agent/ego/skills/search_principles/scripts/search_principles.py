"""Search the Principle Library for relevant strategic principles."""
import sys
from pathlib import Path

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).resolve().parents[6]))

from self_evolution.engine import PrincipleLibrary

def run(query: str, top_k: int = 3) -> str:
    import json
    lib = PrincipleLibrary()
    principles = lib.retrieve(query, top_k=int(top_k))
    if not principles:
        return json.dumps({"status": "empty", "message": "No principles found. The library may be empty — run some evolution cycles first."})
    return json.dumps({"status": "ok", "principles": principles}, ensure_ascii=False, indent=2)
