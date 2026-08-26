"""Persistent CoC 7e character cards backed by EgoAgent Identities.

The Identity directory is the character sheet.  ``id.json`` owns durable
statistics and item state, while every carried item is represented by a safe,
generated Ego tool under ``ego/skills``.  Scenario state deliberately owns
only world facts (locations, clues, NPCs and dropped items).

Keeper changes go through the bounded transactions in this module.  A Keeper
can alter the ``game_profiles.coc7`` subtree and item tools, but cannot rewrite
the character's personality, model configuration, policy hooks or arbitrary
Python code.
"""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any, Iterable


PROFILE_PATH = "game_profiles.coc7"
_LOCK = threading.RLock()
_SAFE_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


ITEM_CATALOG: dict[str, dict[str, Any]] = {
    "revolver": {"label": ".38 revolver", "action": "firearm_attack", "damage": "1d10", "ammo": 6},
    "flashlight": {"label": "flashlight", "action": "illuminate", "charges": 100},
    "notebook": {"label": "notebook", "action": "take_notes"},
    "camera": {"label": "camera", "action": "photograph", "shots": 12},
    "matches": {"label": "matches", "action": "light", "quantity": 10},
    "wrench": {"label": "heavy wrench", "action": "melee_attack", "damage": "1d6"},
    "rope": {"label": "15m rope", "action": "secure_or_climb"},
    "first_aid_kit": {"label": "first-aid kit", "action": "first_aid", "uses": 3},
    "brass_key": {"label": "brass key", "action": "unlock"},
}


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Identity JSON must be an object: {path}")
    return value


def _profile(config: dict[str, Any]) -> dict[str, Any]:
    profile = config.get("game_profiles", {}).get("coc7")
    if not isinstance(profile, dict):
        raise ValueError("Identity is not a CoC character card")
    return profile


def _identity_dir(path: str | Path) -> Path:
    resolved = Path(path).resolve()
    if not (resolved / "id.json").is_file():
        raise ValueError(f"Identity has no id.json: {resolved}")
    return resolved


def public_character(identity_path: str | Path, *, actor_id: str = "") -> dict[str, Any]:
    """Load the investigator-visible, reusable character sheet."""
    root = _identity_dir(identity_path)
    config = _json(root / "id.json")
    profile = copy.deepcopy(_profile(config))
    result = {
        "actor_id": actor_id,
        "identity": root.name,
        "identity_path": str(root),
        "name": profile.get("character", {}).get("name") or config.get("name") or root.name,
        "occupation": profile.get("character", {}).get("occupation", "investigator"),
        "revision": int(profile.get("revision", 0) or 0),
        "characteristics": profile.get("characteristics", {}),
        "derived": profile.get("derived", {}),
        "skills": profile.get("skills", {}),
        "conditions": profile.get("conditions", []),
        "equipment": profile.get("equipment", {}),
        "notes": profile.get("notes", []),
    }
    return result


def load_character_party(bindings: dict[str, str | Path]) -> dict[str, dict[str, Any]]:
    return {actor_id: public_character(path, actor_id=actor_id) for actor_id, path in bindings.items()}


def _tool_dir(identity: Path, item_id: str) -> Path:
    return identity / "ego" / "skills" / f"coc_use_{item_id}"


def _tool_meta(item_id: str, item: dict[str, Any]) -> dict[str, Any]:
    label = str(item.get("label") or ITEM_CATALOG[item_id]["label"])
    action = str(item.get("action") or ITEM_CATALOG[item_id]["action"])
    return {
        "type": "function",
        "function": {
            "name": f"coc_use_{item_id}",
            "description": f"Use the carried CoC item: {label}. Returns an action intent for Keeper adjudication; it does not bypass the Keeper.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "Target or intended use."},
                    "intent": {"type": "string", "description": "Brief in-character intent."},
                },
                "required": [],
            },
        },
        "coc_item": {"id": item_id, "label": label, "action": action},
    }


def _tool_script(item_id: str) -> str:
    # item_id is catalog-validated before this template is reached.
    return (
        "from tabletop.coc_identity import propose_item_use\n\n"
        f"def coc_use_{item_id}(target='', intent='', _context=None):\n"
        f"    return propose_item_use(_context, '{item_id}', target=target, intent=intent)\n"
    )


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    _write_text_atomic(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _install_item_tool(identity: Path, item_id: str, item: dict[str, Any]) -> None:
    destination = _tool_dir(identity, item_id)
    destination.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(destination / "meta.json", _tool_meta(item_id, item))
    _write_text_atomic(destination / "scripts" / f"coc_use_{item_id}.py", _tool_script(item_id))


def sync_equipment_tools(identity_path: str | Path) -> list[str]:
    """Repair generated item tools so the EGO matches the character sheet."""
    identity = _identity_dir(identity_path)
    profile = _profile(_json(identity / "id.json"))
    equipment = profile.get("equipment", {})
    if not isinstance(equipment, dict):
        raise ValueError("CoC equipment must be an object")
    with _LOCK:
        skills = identity / "ego" / "skills"
        skills.mkdir(parents=True, exist_ok=True)
        desired: list[str] = []
        for item_id, item in sorted(equipment.items()):
            if item_id not in ITEM_CATALOG or not isinstance(item, dict) or not item.get("present", True):
                continue
            _install_item_tool(identity, item_id, item)
            desired.append(f"coc_use_{item_id}")
        for child in skills.glob("coc_use_*"):
            if child.is_dir() and child.name not in desired:
                shutil.rmtree(child)
        return desired


def propose_item_use(context: dict[str, Any] | None, item_id: str, *, target: str = "", intent: str = "") -> dict[str, Any]:
    """Validate ownership and return a bounded intent for the Keeper."""
    if item_id not in ITEM_CATALOG:
        return {"ok": False, "reason": "unknown_item"}
    identity_path = (context or {}).get("identity_path")
    if not identity_path:
        return {"ok": False, "reason": "identity_context_missing"}
    card = public_character(identity_path)
    item = card.get("equipment", {}).get(item_id)
    if not isinstance(item, dict) or not item.get("present", True):
        return {"ok": False, "reason": "item_not_owned", "item": item_id}
    return {
        "ok": True,
        "action": {
            "kind": item.get("action", ITEM_CATALOG[item_id]["action"]),
            "item": item_id,
            "target": str(target)[:200],
            "intent": str(intent)[:300],
        },
        "keeper_adjudication_required": True,
        "item_state": copy.deepcopy(item),
    }


def _bounded_number(value: Any, *, minimum: int = 0, maximum: int = 999) -> int:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError("numeric character update requires a number")
    return max(minimum, min(maximum, int(value)))


def _apply_operation(profile: dict[str, Any], operation: dict[str, Any]) -> None:
    op = str(operation.get("op", "")).lower()
    path = str(operation.get("path", ""))
    if op in {"set", "increment", "decrement"}:
        allowed = {
            "derived.hp", "derived.san", "derived.mp", "derived.luck",
            "derived.alive", "derived.conscious", "conditions", "notes",
        }
        if path not in allowed and not path.startswith("equipment."):
            raise ValueError(f"Keeper cannot modify character path: {path}")
        if path.startswith("equipment."):
            parts = path.split(".")
            mutable_item_fields = {"ammo", "charges", "quantity", "shots", "uses"}
            if len(parts) != 3 or parts[1] not in profile.get("equipment", {}) or parts[2] not in mutable_item_fields:
                raise ValueError(f"Keeper cannot modify item definition path: {path}")
        from pipeline_schema import get_path, set_path
        if op == "set":
            value = copy.deepcopy(operation.get("value"))
        else:
            current = get_path(profile, path, 0)
            if not isinstance(current, (int, float)) or isinstance(current, bool):
                raise ValueError(f"Character path is not numeric: {path}")
            amount = operation.get("value", 1)
            if not isinstance(amount, (int, float)) or isinstance(amount, bool):
                raise ValueError("increment/decrement value must be numeric")
            value = current + (amount if op == "increment" else -amount)
        if path in {"derived.hp", "derived.san", "derived.mp", "derived.luck"}:
            maximum_name = {"derived.hp": "hp_max", "derived.san": "san_max", "derived.mp": "mp_max", "derived.luck": None}[path]
            maximum = int(profile.get("derived", {}).get(maximum_name, 100) or 100) if maximum_name else 100
            value = _bounded_number(value, maximum=maximum)
        elif path in {"derived.alive", "derived.conscious"} and not isinstance(value, bool):
            raise ValueError(f"Character path requires a boolean: {path}")
        elif path in {"conditions", "notes"} and not isinstance(value, list):
            raise ValueError(f"Character path requires an array: {path}")
        set_path(profile, path, value)
        return
    if op in {"grant_item", "remove_item"}:
        item_id = str(operation.get("item", ""))
        if not _SAFE_ID.fullmatch(item_id) or item_id not in ITEM_CATALOG:
            raise ValueError(f"Item is not in the safe CoC catalog: {item_id}")
        equipment = profile.setdefault("equipment", {})
        if op == "grant_item":
            supplied = operation.get("state", {})
            if supplied is not None and not isinstance(supplied, dict):
                raise ValueError("grant_item state must be an object")
            equipment[item_id] = {**copy.deepcopy(ITEM_CATALOG[item_id]), **copy.deepcopy(supplied or {}), "present": True}
        else:
            equipment.pop(item_id, None)
        return
    if op in {"add_condition", "remove_condition", "append_note"}:
        key = "notes" if op == "append_note" else "conditions"
        value = str(operation.get("value", ""))[:300]
        items = profile.setdefault(key, [])
        if not isinstance(items, list):
            raise ValueError(f"{key} must be an array")
        if op == "remove_condition":
            profile[key] = [item for item in items if item != value]
        elif value and value not in items:
            items.append(value)
        return
    raise ValueError(f"Unsupported Keeper character operation: {op}")


def apply_character_transactions(transactions: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Validate then atomically-ish commit a batch of Keeper card changes.

    Every transaction is checked before any file is written.  If a filesystem
    write subsequently fails, all touched ``id.json`` files and generated item
    tools are restored from backups.  Revisions provide optimistic concurrency.
    """
    txs = list(transactions)
    if len(txs) > 20:
        raise ValueError("A CoC round may update at most 20 character cards")
    with _LOCK:
        prepared: list[tuple[Path, dict[str, Any], dict[str, Any], str]] = []
        seen: set[Path] = set()
        for tx in txs:
            if not isinstance(tx, dict):
                raise ValueError("Character transaction must be an object")
            identity = _identity_dir(tx.get("identity_path", ""))
            if identity in seen:
                raise ValueError("Use one transaction per Identity per round")
            seen.add(identity)
            original = _json(identity / "id.json")
            candidate = copy.deepcopy(original)
            profile = _profile(candidate)
            revision = int(profile.get("revision", 0) or 0)
            if int(tx.get("expected_revision", revision)) != revision:
                raise ValueError(f"Character revision conflict: {identity.name}")
            operations = tx.get("operations", [])
            if not isinstance(operations, list) or len(operations) > 50:
                raise ValueError("Character operations must be an array of at most 50 entries")
            for operation in operations:
                if not isinstance(operation, dict):
                    raise ValueError("Character operation must be an object")
                _apply_operation(profile, operation)
            profile["revision"] = revision + 1
            prepared.append((identity, original, candidate, str(tx.get("actor_id", ""))))

        if not prepared:
            return {"accepted": True, "changed": [], "cards": {}}

        backup_root = Path(tempfile.mkdtemp(prefix="egoagent-coc-card-"))
        try:
            for identity, original, _, _ in prepared:
                backup = backup_root / identity.name
                (backup / "ego").mkdir(parents=True, exist_ok=True)
                _write_json_atomic(backup / "id.json", original)
                skills = identity / "ego" / "skills"
                if skills.exists():
                    for child in skills.glob("coc_use_*"):
                        if child.is_dir():
                            shutil.copytree(child, backup / "ego" / "skills" / child.name)
            for identity, _, candidate, _ in prepared:
                _write_json_atomic(identity / "id.json", candidate)
                sync_equipment_tools(identity)
        except Exception:
            for identity, original, _, _ in prepared:
                _write_json_atomic(identity / "id.json", original)
                skills = identity / "ego" / "skills"
                if skills.exists():
                    for child in skills.glob("coc_use_*"):
                        if child.is_dir():
                            shutil.rmtree(child)
                backed_skills = backup_root / identity.name / "ego" / "skills"
                if backed_skills.exists():
                    skills.mkdir(parents=True, exist_ok=True)
                    for child in backed_skills.iterdir():
                        shutil.copytree(child, skills / child.name)
            raise
        finally:
            shutil.rmtree(backup_root, ignore_errors=True)

        changed = [actor_id or identity.name for identity, _, _, actor_id in prepared]
        cards = {
            (actor_id or identity.name): public_character(identity, actor_id=actor_id)
            for identity, _, _, actor_id in prepared
        }
        return {"accepted": True, "changed": changed, "cards": cards}


def create_character_identity(
    identity_root: str | Path,
    *,
    identity_name: str,
    character_name: str,
    occupation: str,
    stats: dict[str, Any],
    skills: dict[str, Any],
    equipment: Iterable[str] = (),
    description: str = "",
    age: int | None = None,
    backstory: str = "",
    personality_traits: Iterable[str] = (),
) -> Path:
    """Create a reusable character-card Identity from validated sheet data."""
    if not _SAFE_ID.fullmatch(identity_name):
        raise ValueError("Identity name must use lowercase letters, digits and underscores")
    root = Path(identity_root).resolve()
    destination = (root / identity_name).resolve()
    if root not in destination.parents or destination.exists():
        raise ValueError("Identity destination is invalid or already exists")
    selected = list(dict.fromkeys(str(item) for item in equipment))
    if any(item not in ITEM_CATALOG for item in selected):
        raise ValueError("Character equipment contains an unknown item")
    hp_max = _bounded_number(stats.get("hp_max", stats.get("hp", 10)), minimum=1, maximum=99)
    san_max = _bounded_number(stats.get("san_max", 99), minimum=1, maximum=99)
    character = {"name": character_name, "occupation": occupation}
    if age is not None:
        character["age"] = _bounded_number(age, minimum=15, maximum=120)
    if backstory.strip():
        character["backstory"] = backstory.strip()[:2000]
    traits = [str(value).strip()[:80] for value in personality_traits if str(value).strip()][:12]
    config = {
        "name": identity_name,
        "role": "Call of Cthulhu investigator",
        "description": description or f"You portray {character_name}, a reusable CoC 7e investigator. Act only from public facts and your character sheet.",
        "personality": {"language": "zh", "traits": traits or ["in-character", "cooperative"]},
        "llm": {
            "type": "deepseek", "base_url": "https://api.deepseek.com",
            "api_key_env": "DEEPSEEK_API_KEY", "model": "deepseek-v4-flash",
            "temperature": 0.6, "max_tokens": 400,
        },
        "game_profiles": {
            "coc7": {
                "format": "egoagent.coc7.character/v1", "revision": 0,
                "character": character,
                "characteristics": copy.deepcopy(stats.get("characteristics", {})),
                "derived": {
                    "hp": _bounded_number(stats.get("hp", hp_max), maximum=hp_max), "hp_max": hp_max,
                    "san": _bounded_number(stats.get("san", 50), maximum=san_max), "san_max": san_max,
                    "mp": _bounded_number(stats.get("mp", 10), maximum=99), "mp_max": _bounded_number(stats.get("mp_max", stats.get("mp", 10)), maximum=99),
                    "luck": _bounded_number(stats.get("luck", 50), maximum=100),
                    "move": _bounded_number(stats.get("move", 8), minimum=1, maximum=20),
                    "build": int(stats.get("build", 0) or 0), "alive": True, "conscious": True,
                },
                "skills": {str(key): _bounded_number(value, maximum=100) for key, value in skills.items()},
                "conditions": [], "notes": [],
                "equipment": {item: {**copy.deepcopy(ITEM_CATALOG[item]), "present": True} for item in selected},
            }
        },
    }
    destination.mkdir(parents=True)
    try:
        _write_json_atomic(destination / "id.json", config)
        sync_equipment_tools(destination)
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return destination
