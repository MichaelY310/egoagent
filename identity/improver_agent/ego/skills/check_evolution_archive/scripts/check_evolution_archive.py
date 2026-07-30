"""Query the Evolution Archive for past modification attempts."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[6]))

from self_evolution.engine import EvolutionArchive

def run(target: str, limit: int = 10) -> str:
    import json
    archive = EvolutionArchive()
    history = archive.get_history(target, limit=int(limit))
    best = archive.get_best(target)
    return json.dumps({
        "status": "ok",
        "history": history,
        "best_configs": best[:3] if best else [],
        "total_records": len(history),
    }, ensure_ascii=False, indent=2)
