"""Minimal real-network conformance probe for the official ARC-AGI-3 SDK."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "tmp" / "matplotlib"))

from arc_agi3_runtime import finish_arc_session, start_arc_session, step_arc_session


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--game", default="ls20")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    started = start_arc_session(ROOT, args.game, seed=args.seed)
    summary = {"start": {key: value for key, value in started.items() if key != "frame_text"}}
    if not started.get("ok"):
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 1
    actions = [name for name in started.get("available_actions", []) if name != "RESET"]
    if not actions:
        summary["error"] = "environment advertised no non-reset action"
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 2
    action = actions[0]
    acted = step_arc_session(
        started["session_id"],
        action,
        prediction="The first legal action should reveal whether it controls or transforms a visible object.",
        reasoning="One low-cost information-gaining probe with no assumed game rule.",
        x=32 if action == "ACTION6" else None,
        y=32 if action == "ACTION6" else None,
    )
    summary["action"] = {key: value for key, value in acted.items() if key != "frame_text"}
    finished = finish_arc_session(started["session_id"])
    summary["finish"] = finished
    output = ROOT / "experiments" / "arc_agi3" / "results" / "sdk_probe.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0 if acted.get("ok") and finished.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
