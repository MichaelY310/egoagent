"""Run a real multi-round CoC table through the same API used by Studio/Void."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


ROOT = Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:8765"
AGENTS = {
    "KP": "identity/coc_keeper",
    "规则裁判": "identity/coc_rules_judge",
    "人类调查员": "identity/coc_investigator_human",
    "调查员A": "identity/coc_investigator_cautious",
    "调查员B": "identity/coc_investigator_bold",
}
ACTIONS = [
    "我把随身的 revolver 放到脚边的岩石上，明确丢下它。",
    "我现在试图用刚才丢掉的 revolver 朝任何靠近的怪物开枪。",
    "我重新从当前地点捡起地上的 revolver。",
    "我用 spot_hidden 仔细检查 rocky_shore，寻找异常足迹。",
    "我带队从 rocky_shore 前往 lighthouse_ground。",
    "我从 lighthouse_ground 进入 living_quarters。",
    "我用 spot_hidden 检查 living_quarters 里的 damaged_radio。",
    "我从 living_quarters 前往 tower。",
    "我用 spot_hidden 检查 tower 里的 broken_lens，判断灯塔为何熄灭。",
]


def api(method: str, path: str, body=None, timeout=45):
    response = requests.request(method, BASE + path, json=body, timeout=timeout)
    if not response.ok:
        raise RuntimeError(f"{method} {path}: {response.status_code} {response.text[:800]}")
    return response.json()


def state():
    return api("GET", "/api/execution/state")


def stop():
    try:
        api("POST", "/api/execution/stop", {})
    except Exception:
        pass
    deadline = time.time() + 15
    while time.time() < deadline:
        if not state().get("running"):
            return
        time.sleep(0.25)


def wait_for(predicate, timeout: float, label: str):
    deadline = time.time() + timeout
    latest = None
    while time.time() < deadline:
        latest = state()
        if predicate(latest):
            return latest
        if not latest.get("running"):
            errors = [entry.get("text", "") for entry in latest.get("outputs", []) if entry.get("agent") == "system"]
            raise RuntimeError(f"run stopped during {label}: {' '.join(errors)[-1200:]}")
        time.sleep(0.5)
    raise TimeoutError(f"timeout during {label}: node={latest.get('current_node') if latest else None}")


def kp_outputs(snapshot):
    return [entry for entry in snapshot.get("outputs", []) if entry.get("agent") == "KP" and entry.get("text")]


def character_snapshot():
    result = {}
    for actor, relative in {
        "human": "identity/coc_investigator_human/id.json",
        "investigator_a": "identity/coc_investigator_cautious/id.json",
        "investigator_b": "identity/coc_investigator_bold/id.json",
    }.items():
        config = json.loads((ROOT / relative).read_text(encoding="utf-8"))
        profile = config["game_profiles"]["coc7"]
        result[actor] = {
            "revision": profile["revision"],
            "derived": profile["derived"],
            "equipment": profile["equipment"],
            "personality": config.get("personality"),
        }
    return result


def main():
    before = character_snapshot()
    rounds = []
    stop()
    api("POST", "/api/execution/start", {
        "harness": "coc_lightless_beacon", "agents": AGENTS,
        "workspace": str(ROOT), "mode": "agent", "debug_mode": "auto",
    })
    opening = wait_for(lambda item: item.get("current_node") == "human_turn" and len(kp_outputs(item)) >= 1, 180, "opening")
    print("OPENING", kp_outputs(opening)[-1]["text"].replace("\n", " ")[:500], flush=True)

    previous_kp = len(kp_outputs(opening))
    # The focused smoke keeps the card reusable by picking the weapon back up
    # after proving the intervening shot is explicitly rejected.
    selected_actions = ACTIONS[:3] if "--intent-guard-smoke" in sys.argv else ACTIONS
    for index, action in enumerate(selected_actions, 1):
        api("POST", "/api/execution/input", {"text": action})
        completed = wait_for(
            lambda item, expected=previous_kp + 1: item.get("current_node") == "human_turn" and len(kp_outputs(item)) >= expected,
            300,
            f"round {index}",
        )
        narration = kp_outputs(completed)[-1]["text"]
        rounds.append({"round": index, "human_action": action, "kp": narration, "step_count": completed.get("step_count")})
        previous_kp = len(kp_outputs(completed))
        print(f"ROUND {index} action={action}", flush=True)
        print("KP", narration.replace("\n", " ")[:900], flush=True)

    final_state = state()
    after = character_snapshot()
    report = {
        "harness": "coc_lightless_beacon", "model": "deepseek-v4-flash",
        "before": before, "after": after, "rounds": rounds,
        "node_traces": final_state.get("node_traces", []),
        "outputs": final_state.get("outputs", []),
    }
    destination = ROOT / ".runtime" / f"coc_identity_live_{time.strftime('%Y%m%d_%H%M%S')}.json"
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("CARDS", json.dumps(after, ensure_ascii=False), flush=True)
    print(f"REPORT {destination}", flush=True)
    stop()


if __name__ == "__main__":
    try:
        main()
    finally:
        try:
            stop()
        except Exception:
            pass
