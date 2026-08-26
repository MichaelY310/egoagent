"""Deterministic CoC 7e rules for EgoAgent's Identity-backed tables.

World/session state contains only scenario facts.  Reusable investigator data
(statistics, conditions and equipment) lives in each bound Identity and is
changed through ``tabletop.coc_identity`` transactions.
"""

from __future__ import annotations

import copy
import hashlib
import random
import re
from typing import Any


QUICKSTART_URL = "https://www.chaosium.com/cthulhu-quickstart/"
FREE_ADVENTURES_URL = "https://www.chaosium.com/cthulhu-adventures/"

ACTORS = ("human", "investigator_a", "investigator_b")

_ITEM_ALIASES = {
    "左轮": "revolver", "手枪": "revolver", "枪": "revolver",
    "手电": "flashlight", "笔记本": "notebook", "相机": "camera",
    "火柴": "matches", "扳手": "wrench", "绳": "rope", "急救包": "first_aid_kit",
}

STATE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["_revision", "system", "scenario", "public", "keeper", "positions", "entities", "events"],
    "properties": {
        "_revision": {"type": "integer", "minimum": 0},
        "system": {"const": "coc7-identity-v1"},
        "scenario": {"type": "object"},
        "public": {"type": "object"},
        "keeper": {"type": "object"},
        "positions": {"type": "object"},
        "entities": {"type": "object"},
        "events": {"type": "array", "maxItems": 500},
    },
}


def scenario(scenario_id: str) -> dict[str, Any]:
    """Return fresh scenario state; it never embeds character sheets."""
    scenario_id = str(scenario_id).strip().lower()
    if scenario_id == "lightless_beacon":
        start = "rocky_shore"
        return {
            "_revision": 0,
            "system": "coc7-identity-v1",
            "scenario": {
                "id": scenario_id,
                "title": "The Lightless Beacon - structured adapter",
                "source_url": FREE_ADVENTURES_URL,
                "license_note": "Requires the official free scenario for full prose, handouts and Keeper guidance.",
            },
            "public": {
                "scene": start, "round": 0, "clock": "late evening", "weather": "violent storm",
                "objective": "Reach the lighthouse, discover why its light failed, and survive.",
                "clues": [], "ground_items": [],
            },
            "keeper": {
                "locations": {
                    "rocky_shore": {"label": "rocky shore", "exits": ["lighthouse_ground"]},
                    "lighthouse_ground": {"label": "lighthouse grounds", "exits": ["rocky_shore", "living_quarters", "oil_shed"]},
                    "living_quarters": {"label": "living quarters", "exits": ["lighthouse_ground", "tower"]},
                    "oil_shed": {"label": "oil shed", "exits": ["lighthouse_ground"]},
                    "tower": {"label": "lighthouse tower", "exits": ["living_quarters"]},
                },
                "clues": [
                    {"id": "shore_tracks", "scene": "rocky_shore", "skill": "spot_hidden", "difficulty": "regular", "summary": "Unnatural tracks lead inland from the wreckage."},
                    {"id": "damaged_radio", "scene": "living_quarters", "skill": "spot_hidden", "difficulty": "regular", "summary": "The radio was disabled during a struggle."},
                    {"id": "keeper_log", "scene": "living_quarters", "skill": "library_use", "difficulty": "hard", "summary": "A log links recent disturbances to activity around the beacon."},
                    {"id": "oil_shed_evidence", "scene": "oil_shed", "skill": "spot_hidden", "difficulty": "regular", "summary": "Evidence in the shed confirms a violent attack; seeing it risks 1 SAN.", "san_loss": [0, 1]},
                    {"id": "broken_lens", "scene": "tower", "skill": "spot_hidden", "difficulty": "regular", "summary": "The beacon mechanism was deliberately damaged."},
                ],
                "secrets": ["The danger is physical as well as investigative.", "Noise and light can change the pressure on the group."],
                "rng_seed": "egoagent-lightless-beacon-v2",
            },
            "positions": {actor: start for actor in ACTORS},
            "entities": {"lurking_creature": {"label": "lurking creature", "location": "lighthouse_ground", "hp": 12, "hp_max": 12, "alive": True}},
            "events": [],
        }
    if scenario_id == "the_haunting":
        start = "client_office"
        return {
            "_revision": 0,
            "system": "coc7-identity-v1",
            "scenario": {
                "id": scenario_id,
                "title": "The Haunting - structured adapter",
                "source_url": QUICKSTART_URL,
                "license_note": "Requires the official free Quick-Start PDF for full prose, handouts and Keeper guidance.",
            },
            "public": {
                "scene": start, "round": 0, "clock": "morning", "weather": "cold and clear",
                "objective": "Research the troubled house and determine whether it can be made safe.",
                "clues": [], "ground_items": [],
            },
            "keeper": {
                "locations": {
                    "client_office": {"label": "client office", "exits": ["records_hall", "newspaper_archive", "house_hall"]},
                    "records_hall": {"label": "records hall", "exits": ["client_office"]},
                    "newspaper_archive": {"label": "newspaper archive", "exits": ["client_office"]},
                    "house_hall": {"label": "house entrance hall", "exits": ["client_office", "bedroom", "basement"]},
                    "bedroom": {"label": "upstairs bedroom", "exits": ["house_hall"]},
                    "basement": {"label": "sealed basement", "exits": ["house_hall"]},
                },
                "clues": [
                    {"id": "ownership_chain", "scene": "records_hall", "skill": "library_use", "difficulty": "regular", "summary": "The property's ownership history contains a suspicious transfer."},
                    {"id": "old_incident", "scene": "newspaper_archive", "skill": "library_use", "difficulty": "regular", "summary": "An old report connects the house to violence and unexplained behavior."},
                    {"id": "bedroom_damage", "scene": "bedroom", "skill": "spot_hidden", "difficulty": "regular", "summary": "Damage in the bedroom does not fit an ordinary accident."},
                    {"id": "basement_signs", "scene": "basement", "skill": "spot_hidden", "difficulty": "hard", "summary": "The basement contains signs of a deliberate hidden space; discovery risks 1 SAN.", "san_loss": [0, 1]},
                ],
                "secrets": ["The basement is the decisive location.", "The hostile presence can manipulate the house before direct confrontation."],
                "rng_seed": "egoagent-the-haunting-v2",
            },
            "positions": {actor: start for actor in ACTORS},
            "entities": {"basement_presence": {"label": "basement presence", "location": "basement", "hp": 16, "hp_max": 16, "alive": True}},
            "events": [],
        }
    raise ValueError(f"Unknown CoC scenario adapter: {scenario_id}")


def _redact_card(card: dict[str, Any]) -> dict[str, Any]:
    return {key: copy.deepcopy(value) for key, value in card.items() if key != "identity_path"}


def public_view(state: dict[str, Any], characters: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Return public world facts plus current Identity-backed character cards."""
    locations = state.get("keeper", {}).get("locations", {})
    positions = copy.deepcopy(state.get("positions", {}))
    scene = positions.get("human") or state.get("public", {}).get("scene")
    location = locations.get(scene, {})
    ground_items = [
        copy.deepcopy(item) for item in state.get("public", {}).get("ground_items", [])
        if isinstance(item, dict) and item.get("location") == scene
    ]
    return {
        "system": state.get("system"),
        "scenario": {key: value for key, value in state.get("scenario", {}).items() if key != "license_note"},
        "scene": scene,
        "scene_label": location.get("label", scene),
        "available_exits": list(location.get("exits", [])),
        "actor_locations": positions,
        "available_exits_by_actor": {actor: list(locations.get(place, {}).get("exits", [])) for actor, place in positions.items()},
        "round": state.get("public", {}).get("round", 0),
        "clock": state.get("public", {}).get("clock"),
        "weather": state.get("public", {}).get("weather"),
        "objective": state.get("public", {}).get("objective"),
        "discovered_clues": copy.deepcopy(state.get("public", {}).get("clues", [])),
        "items_at_scene": ground_items,
        "characters": {actor: _redact_card(card) for actor, card in (characters or {}).items()},
        "recent_events": copy.deepcopy(state.get("events", [])[-10:]),
        "revision": state.get("_revision", 0),
    }


def _rng(state: dict[str, Any], action: dict[str, Any], index: int) -> random.Random:
    material = "|".join([
        str(state.get("keeper", {}).get("rng_seed", "egoagent-coc7")), str(state.get("_revision", 0)),
        str(index), str(action.get("actor", "")), str(action.get("kind", "")),
        str(action.get("target", "")), str(action.get("skill", "")),
    ])
    return random.Random(int.from_bytes(hashlib.sha256(material.encode("utf-8")).digest()[:8], "big"))


def _percentile_roll(rng: random.Random, bonus_dice: int = 0) -> dict[str, Any]:
    bonus_dice = max(-2, min(2, int(bonus_dice)))
    units = rng.randrange(0, 10)
    tens = [rng.randrange(0, 10) for _ in range(1 + abs(bonus_dice))]
    candidates = [100 if ten == 0 and units == 0 else ten * 10 + units for ten in tens]
    roll = min(candidates) if bonus_dice > 0 else max(candidates) if bonus_dice < 0 else candidates[0]
    return {"roll": roll, "candidates": candidates, "bonus_dice": bonus_dice}


def _check(rng: random.Random, value: int, difficulty: str, bonus_dice: int = 0) -> dict[str, Any]:
    roll = _percentile_roll(rng, bonus_dice)
    value = max(0, min(100, int(value)))
    thresholds = {"regular": value, "hard": value // 2, "extreme": value // 5}
    difficulty = difficulty if difficulty in thresholds else "regular"
    number = roll["roll"]
    fumble = number == 100 or (value < 50 and number >= 96)
    critical = number == 1
    success = critical or (not fumble and number <= thresholds[difficulty])
    level = "critical" if critical else "fumble" if fumble else "extreme" if number <= thresholds["extreme"] else "hard" if number <= thresholds["hard"] else "regular" if number <= thresholds["regular"] else "failure"
    return {**roll, "skill": value, "difficulty": difficulty, "threshold": thresholds[difficulty], "success": success, "level": level}


def _dice(rng: random.Random, expression: str) -> tuple[int, list[int]]:
    match = re.fullmatch(r"\s*(\d+)d(\d+)(?:\s*([+-])\s*(\d+))?\s*", str(expression).lower())
    if not match:
        return 0, []
    count, sides = int(match.group(1)), int(match.group(2))
    if count < 1 or count > 20 or sides < 2 or sides > 100:
        return 0, []
    rolls = [rng.randint(1, sides) for _ in range(count)]
    modifier = int(match.group(4) or 0) * (-1 if match.group(3) == "-" else 1)
    return max(0, sum(rolls) + modifier), rolls


def normalize_human_action(text: str, public_state: dict[str, Any]) -> dict[str, Any]:
    """Deterministically preserve the human player's declared verb.

    An LLM may extract AI investigators' intents, but it must never replace a
    human command because it looks unsafe or inconvenient.  Unsupported or
    impossible commands still reach ``adjudicate`` and are rejected there with
    an explicit reason.
    """
    raw = str(text or "").strip()[:1000]
    lower = raw.lower()
    tokens = re.findall(r"\b[a-z][a-z0-9_]{1,63}\b", lower)
    characters = public_state.get("characters", {}) if isinstance(public_state, dict) else {}
    human = characters.get("human", {}) if isinstance(characters, dict) else {}
    carried = set(human.get("equipment", {})) if isinstance(human, dict) else set()
    ground = {
        str(item.get("id")) for item in public_state.get("items_at_scene", [])
        if isinstance(item, dict) and item.get("id")
    }
    known_items = carried | ground
    item_id = next((token for token in tokens if token in known_items or token in {"revolver", "flashlight", "notebook", "camera", "matches", "wrench", "rope", "first_aid_kit"}), "")
    if not item_id:
        item_id = next((value for alias, value in _ITEM_ALIASES.items() if alias in raw), "")
    skills = set(human.get("skills", {})) if isinstance(human, dict) else set()
    skill = next((token for token in tokens if token in skills), "")
    location_ids = {
        str(public_state.get("scene", "")),
        *[str(value) for value in public_state.get("available_exits", [])],
        *[str(value) for value in public_state.get("actor_locations", {}).values()],
    }
    location = next((token for token in tokens if token in location_ids), "")
    excluded = known_items | skills | location_ids | {"human", "investigator_a", "investigator_b", "spot_hidden", "library_use", "listen", "first_aid"}
    free_target = next((token for token in tokens if token not in excluded), "")

    result: dict[str, Any] = {"actor": "human", "intent": raw, "source": "deterministic_player_intent"}
    if any(marker in lower for marker in ("pick up", "pickup", "捡", "拾", "拿起", "取回")):
        result.update({"kind": "pick_up", "item": item_id})
    elif any(marker in lower for marker in ("fire", "shoot", "开枪", "射击", "扣动扳机")):
        result.update({"kind": "firearm_attack", "item": item_id or "revolver", "target": free_target})
    elif any(marker in lower for marker in ("drop", "discard", "丢", "扔", "放下")):
        result.update({"kind": "drop_item", "item": item_id})
    elif any(marker in lower for marker in ("first aid", "first_aid", "急救", "包扎")):
        result.update({"kind": "first_aid", "target": free_target or "human"})
    elif any(marker in lower for marker in ("检查", "调查", "搜索", "寻找", "观察", "inspect", "search")):
        result.update({"kind": "inspect", "target": free_target or location, "skill": skill or "spot_hidden"})
    elif any(marker in lower for marker in ("前往", "进入", "移动", "走向", "move", "go to")):
        result.update({"kind": "move", "target": location or free_target})
    elif item_id and any(marker in lower for marker in ("使用", "打开", "照", "拍", "记录", "use")):
        result.update({"kind": "use_item", "item": item_id, "target": free_target})
    elif any(marker in lower for marker in ("等待", "不动", "wait")):
        result["kind"] = "wait"
    else:
        result["kind"] = "say"
    return {key: value for key, value in result.items() if value != ""}


def enforce_player_intent(plan: dict[str, Any], human_text: str, public_state: dict[str, Any]) -> dict[str, Any]:
    """Replace only the human plan entry and record the attempted rewrite."""
    actions = plan.get("actions", []) if isinstance(plan, dict) else []
    actions = actions if isinstance(actions, list) else []
    model_human = next((copy.deepcopy(item) for item in actions if isinstance(item, dict) and item.get("actor") == "human"), None)
    ai_actions = [copy.deepcopy(item) for item in actions if isinstance(item, dict) and item.get("actor") in {"investigator_a", "investigator_b"}]
    enforced = normalize_human_action(human_text, public_state)
    return {
        "action_plan": {"actions": [enforced, *ai_actions[:2]]},
        "intent_guard": {
            "source_text": str(human_text)[:1000],
            "model_human_action": model_human,
            "enforced_human_action": copy.deepcopy(enforced),
            "model_rewrite_detected": model_human != enforced,
        },
    }


def adjudicate(state: dict[str, Any], plan: dict[str, Any], characters: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Produce auditable world and character transactions for one round."""
    if not isinstance(state, dict) or not isinstance(plan, dict) or not isinstance(characters, dict):
        raise ValueError("state, plan and characters must be objects")
    working = copy.deepcopy(state)
    cards = copy.deepcopy(characters)
    actions = plan.get("actions", [])
    actions = actions[:6] if isinstance(actions, list) else []
    operations: list[dict[str, Any]] = []
    resolutions: list[dict[str, Any]] = []
    card_ops: dict[str, list[dict[str, Any]]] = {}

    def set_world(path: str, value: Any) -> None:
        from pipeline_schema import set_path
        set_path(working, path, copy.deepcopy(value))
        operations.append({"op": "set", "path": path, "value": copy.deepcopy(value)})

    def append_event(event: dict[str, Any]) -> None:
        working.setdefault("events", []).append(copy.deepcopy(event))
        operations.append({"op": "append", "path": "events", "value": copy.deepcopy(event)})

    def change_card(actor_id: str, operation: dict[str, Any]) -> None:
        from pipeline_schema import get_path, set_path
        card_ops.setdefault(actor_id, []).append(copy.deepcopy(operation))
        card = cards[actor_id]
        op, path = operation["op"], operation.get("path", "")
        if op == "set":
            set_path(card, path, copy.deepcopy(operation.get("value")))
        elif op in {"increment", "decrement"}:
            current = get_path(card, path, 0)
            amount = operation.get("value", 1)
            set_path(card, path, current + (amount if op == "increment" else -amount))
        elif op == "grant_item":
            card.setdefault("equipment", {})[operation["item"]] = {**copy.deepcopy(operation.get("state", {})), "present": True}
        elif op == "remove_item":
            card.setdefault("equipment", {}).pop(operation["item"], None)

    for index, raw in enumerate(actions):
        action = raw if isinstance(raw, dict) else {}
        actor_id = str(action.get("actor", ""))
        kind = str(action.get("kind", "say")).lower()
        card = cards.get(actor_id)
        resolution: dict[str, Any] = {"actor": actor_id, "kind": kind, "accepted": False}
        derived = card.get("derived", {}) if isinstance(card, dict) else {}
        if not isinstance(card, dict):
            resolution["reason"] = "unknown_or_unbound_character_identity"
        elif not derived.get("alive", True) or not derived.get("conscious", True):
            resolution["reason"] = "character_cannot_act"
        else:
            rng = _rng(state, action, index)
            scene = working.get("positions", {}).get(actor_id)
            equipment = card.get("equipment", {})
            if kind in {"say", "wait", "assist"}:
                resolution.update({"accepted": True, "summary": str(action.get("intent", action.get("text", kind)))[:300]})
            elif kind == "move":
                target = str(action.get("target", ""))
                exits = working.get("keeper", {}).get("locations", {}).get(scene, {}).get("exits", [])
                if target not in exits:
                    resolution["reason"] = "location_not_adjacent"
                else:
                    set_world(f"positions.{actor_id}", target)
                    if actor_id == "human":
                        set_world("public.scene", target)
                    resolution.update({"accepted": True, "from": scene, "to": target})
            elif kind == "inspect":
                skill = str(action.get("skill", "spot_hidden"))
                skill_value = int(card.get("skills", {}).get(skill, 0))
                discovered = {clue.get("id") for clue in working.get("public", {}).get("clues", []) if isinstance(clue, dict)}
                clues = [clue for clue in working.get("keeper", {}).get("clues", []) if clue.get("scene") == scene and clue.get("id") not in discovered]
                requested = str(action.get("target", ""))
                clue = next((item for item in clues if item.get("id") == requested), None) if requested else next((item for item in clues if item.get("skill") == skill), None)
                if clue is None:
                    resolution["reason"] = "no_matching_undiscovered_clue"
                else:
                    check = _check(rng, skill_value, str(clue.get("difficulty", "regular")), int(action.get("bonus_dice", 0) or 0))
                    resolution.update({"accepted": True, "check": check, "clue_id": clue["id"], "success": check["success"]})
                    if check["success"]:
                        public_clue = {"id": clue["id"], "summary": clue["summary"], "scene": scene, "discovered_by": actor_id}
                        working.setdefault("public", {}).setdefault("clues", []).append(public_clue)
                        operations.append({"op": "append", "path": "public.clues", "value": public_clue})
                        if clue.get("san_loss"):
                            san = int(derived.get("san", 0))
                            san_roll = _check(rng, san, "regular")
                            loss = int(clue["san_loss"][0] if san_roll["success"] else clue["san_loss"][-1])
                            change_card(actor_id, {"op": "set", "path": "derived.san", "value": max(0, san - loss)})
                            resolution["sanity"] = {"check": san_roll, "loss": loss}
            elif kind == "drop_item":
                item_id = str(action.get("item", action.get("target", "")))
                item = equipment.get(item_id)
                if not isinstance(item, dict) or not item.get("present", True):
                    resolution["reason"] = "item_not_carried_in_identity"
                else:
                    change_card(actor_id, {"op": "remove_item", "item": item_id})
                    ground = list(working.get("public", {}).get("ground_items", []))
                    ground.append({"id": item_id, "former_owner": actor_id, "location": scene, "item": copy.deepcopy(item)})
                    set_world("public.ground_items", ground)
                    resolution.update({"accepted": True, "item": item_id, "identity_tool_removed": f"coc_use_{item_id}"})
            elif kind == "pick_up":
                item_id = str(action.get("item", action.get("target", "")))
                ground = list(working.get("public", {}).get("ground_items", []))
                position = next((i for i, entry in enumerate(ground) if isinstance(entry, dict) and entry.get("id") == item_id and entry.get("location") == scene), None)
                if position is None:
                    resolution["reason"] = "item_not_available"
                elif item_id in equipment:
                    resolution["reason"] = "item_already_carried"
                else:
                    item = copy.deepcopy(ground[position].get("item", {}))
                    change_card(actor_id, {"op": "grant_item", "item": item_id, "state": item})
                    set_world("public.ground_items", [entry for i, entry in enumerate(ground) if i != position])
                    resolution.update({"accepted": True, "item": item_id, "identity_tool_added": f"coc_use_{item_id}"})
            elif kind == "use_item":
                item_id = str(action.get("item", action.get("target", "")))
                item = equipment.get(item_id)
                if not isinstance(item, dict) or not item.get("present", True):
                    resolution["reason"] = "item_not_carried_in_identity"
                else:
                    spent = None
                    for counter in ("charges", "quantity", "shots", "uses"):
                        if counter in item:
                            if int(item[counter]) <= 0:
                                resolution["reason"] = f"no_{counter}_remaining"
                                break
                            spent = counter
                            change_card(actor_id, {"op": "set", "path": f"equipment.{item_id}.{counter}", "value": int(item[counter]) - 1})
                            break
                    if "reason" not in resolution:
                        resolution.update({"accepted": True, "item": item_id, "spent": spent, "summary": str(action.get("intent", "uses item"))[:300]})
            elif kind == "firearm_attack":
                item_id = str(action.get("item", "revolver"))
                item = equipment.get(item_id)
                target_id = str(action.get("target", ""))
                target = working.get("entities", {}).get(target_id)
                if not isinstance(item, dict) or not item.get("present", True) or item.get("action") != "firearm_attack":
                    resolution["reason"] = "firearm_not_carried_in_identity"
                elif int(item.get("ammo", 0)) <= 0:
                    resolution["reason"] = "no_ammunition"
                elif not isinstance(target, dict) or not target.get("alive", True) or target.get("location") != scene:
                    resolution["reason"] = "invalid_target"
                else:
                    ammo = int(item["ammo"]) - 1
                    change_card(actor_id, {"op": "set", "path": f"equipment.{item_id}.ammo", "value": ammo})
                    check = _check(rng, int(card.get("skills", {}).get("firearms_handgun", 0)), str(action.get("difficulty", "regular")), int(action.get("bonus_dice", 0) or 0))
                    resolution.update({"accepted": True, "check": check, "ammo_after": ammo, "success": check["success"]})
                    if check["success"]:
                        damage, rolls = _dice(rng, str(item.get("damage", "1d10")))
                        hp_after = max(0, int(target.get("hp", 0)) - damage)
                        set_world(f"entities.{target_id}.hp", hp_after)
                        if hp_after == 0:
                            set_world(f"entities.{target_id}.alive", False)
                        resolution["damage"] = {"total": damage, "rolls": rolls, "hp_after": hp_after}
            elif kind == "first_aid":
                target_id = str(action.get("target", actor_id))
                target_card = cards.get(target_id)
                if not isinstance(target_card, dict) or not target_card.get("derived", {}).get("alive", True):
                    resolution["reason"] = "invalid_target"
                elif working.get("positions", {}).get(target_id) != scene:
                    resolution["reason"] = "target_not_present"
                else:
                    check = _check(rng, int(card.get("skills", {}).get("first_aid", 0)), "regular")
                    resolution.update({"accepted": True, "check": check, "success": check["success"]})
                    if check["success"]:
                        target_derived = target_card.get("derived", {})
                        hp_after = min(int(target_derived.get("hp_max", 0)), int(target_derived.get("hp", 0)) + 1)
                        change_card(target_id, {"op": "set", "path": "derived.hp", "value": hp_after})
            else:
                resolution["reason"] = "unsupported_action"

        event = {"type": "action_resolution", "round": int(working.get("public", {}).get("round", 0)) + 1, **copy.deepcopy(resolution)}
        append_event(event)
        resolutions.append(resolution)

    next_round = int(working.get("public", {}).get("round", 0)) + 1
    set_world("public.round", next_round)
    if next_round in {2, 4, 6}:
        escalation = {"type": "keeper_pressure", "round": next_round, "cue": f"scenario_pressure_{next_round}", "summary": "The environment reacts; the Keeper should advance danger without invalidating established facts."}
        append_event(escalation)

    transactions = []
    for actor_id, actor_operations in card_ops.items():
        card = characters[actor_id]
        transactions.append({
            "actor_id": actor_id,
            "identity_path": card["identity_path"],
            "expected_revision": int(card.get("revision", 0)),
            "operations": actor_operations,
        })
    transition = {
        "expected_revision": int(state.get("_revision", 0)),
        "preconditions": [], "operations": operations,
        "metadata": {"system": "coc7-identity-v1", "round": next_round, "resolution_count": len(resolutions)},
    }
    return {
        "transition": transition,
        "character_transactions": transactions,
        "resolutions": resolutions,
        "public_state_after": public_view(working, cards),
    }
