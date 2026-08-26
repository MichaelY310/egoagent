from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline_engine import _apply_state_transition
from tabletop.coc7 import STATE_SCHEMA, adjudicate, enforce_player_intent, public_view, scenario
from tabletop.coc_identity import (
    apply_character_transactions,
    create_character_identity,
    load_character_party,
    propose_item_use,
)


class CoC7RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        shared = {"hp": 11, "hp_max": 11, "san": 60, "san_max": 99, "mp": 12, "luck": 50}
        skills = {"spot_hidden": 60, "library_use": 60, "listen": 50, "firearms_handgun": 50, "first_aid": 50}
        self.paths = {
            "human": create_character_identity(root, identity_name="human_card", character_name="Alex", occupation="journalist", stats=shared, skills=skills, equipment=["revolver", "flashlight"]),
            "investigator_a": create_character_identity(root, identity_name="morgan_card", character_name="Morgan", occupation="antiquarian", stats=shared, skills=skills, equipment=["camera"]),
            "investigator_b": create_character_identity(root, identity_name="elias_card", character_name="Elias", occupation="engineer", stats=shared, skills=skills, equipment=["wrench"]),
        }

    def tearDown(self):
        self.temp.cleanup()

    def cards(self):
        return load_character_party(self.paths)

    def commit(self, state, plan):
        judged = adjudicate(state, plan, self.cards())
        world = _apply_state_transition(state, judged["transition"], schema=STATE_SCHEMA)
        self.assertTrue(world["accepted"], world["reason_codes"])
        apply_character_transactions(judged["character_transactions"])
        return world["state"], judged["resolutions"], self.cards()

    def test_world_state_does_not_duplicate_character_cards(self):
        state = scenario("lightless_beacon")
        self.assertNotIn("actors", state)
        self.assertEqual(set(state["positions"]), {"human", "investigator_a", "investigator_b"})

    def test_public_view_never_exposes_keeper_or_local_identity_paths(self):
        visible = public_view(scenario("lightless_beacon"), self.cards())
        rendered = repr(visible)
        self.assertNotIn("keeper", visible)
        self.assertNotIn("rng_seed", rendered)
        self.assertNotIn("identity_path", rendered)
        self.assertIn("characters", visible)

    def test_lost_firearm_removes_identity_tool_and_cannot_be_used(self):
        state = scenario("lightless_beacon")
        state, dropped, cards = self.commit(state, {"actions": [{"actor": "human", "kind": "drop_item", "item": "revolver"}]})
        self.assertTrue(dropped[0]["accepted"])
        self.assertNotIn("revolver", cards["human"]["equipment"])
        self.assertFalse((self.paths["human"] / "ego" / "skills" / "coc_use_revolver").exists())

        after, shot, _ = self.commit(state, {"actions": [{"actor": "human", "kind": "firearm_attack", "item": "revolver", "target": "lurking_creature"}]})
        self.assertFalse(shot[0]["accepted"])
        self.assertEqual(shot[0]["reason"], "firearm_not_carried_in_identity")
        self.assertEqual(after["entities"]["lurking_creature"]["hp"], state["entities"]["lurking_creature"]["hp"])

    def test_dropped_item_can_change_identity_owner_and_tool(self):
        state = scenario("lightless_beacon")
        state, _, _ = self.commit(state, {"actions": [{"actor": "human", "kind": "drop_item", "item": "revolver"}]})
        state, picked, cards = self.commit(state, {"actions": [{"actor": "investigator_a", "kind": "pick_up", "item": "revolver"}]})
        self.assertTrue(picked[0]["accepted"])
        self.assertIn("revolver", cards["investigator_a"]["equipment"])
        self.assertNotIn("revolver", cards["human"]["equipment"])
        self.assertTrue((self.paths["investigator_a"] / "ego" / "skills" / "coc_use_revolver").is_dir())
        self.assertEqual(state["public"]["ground_items"], [])

    def test_invalid_movement_is_rejected_without_teleporting(self):
        state, resolution, _ = self.commit(scenario("the_haunting"), {"actions": [{"actor": "human", "kind": "move", "target": "basement"}]})
        self.assertFalse(resolution[0]["accepted"])
        self.assertEqual(state["positions"]["human"], "client_office")

    def test_keeper_transaction_cannot_rewrite_personality(self):
        original = json.loads((self.paths["human"] / "id.json").read_text(encoding="utf-8"))
        tx = {"identity_path": str(self.paths["human"]), "expected_revision": 0, "operations": [{"op": "set", "path": "personality", "value": {"traits": ["obedient"]}}]}
        with self.assertRaisesRegex(ValueError, "cannot modify"):
            apply_character_transactions([tx])
        current = json.loads((self.paths["human"] / "id.json").read_text(encoding="utf-8"))
        self.assertEqual(current["personality"], original["personality"])
        self.assertEqual(current["game_profiles"]["coc7"]["revision"], 0)

    def test_keeper_cannot_smuggle_an_item_definition_through_set(self):
        tx = {"identity_path": str(self.paths["human"]), "expected_revision": 0, "operations": [{"op": "set", "path": "equipment.fake_weapon.damage", "value": "99d99"}]}
        with self.assertRaisesRegex(ValueError, "item definition"):
            apply_character_transactions([tx])
        self.assertFalse((self.paths["human"] / "ego" / "skills" / "coc_use_fake_weapon").exists())

    def test_item_tool_only_proposes_action_and_requires_keeper(self):
        result = propose_item_use({"identity_path": str(self.paths["human"])}, "revolver", target="lurking_creature")
        self.assertTrue(result["ok"])
        self.assertTrue(result["keeper_adjudication_required"])
        self.assertEqual(self.cards()["human"]["equipment"]["revolver"]["ammo"], 6)

    def test_model_cannot_rewrite_human_shoot_command_as_wait(self):
        state = scenario("lightless_beacon")
        state, _, _ = self.commit(state, {"actions": [{"actor": "human", "kind": "drop_item", "item": "revolver"}]})
        visible = public_view(state, self.cards())
        guarded = enforce_player_intent(
            {"actions": [{"actor": "human", "kind": "wait", "intent": "model refused"}]},
            "我用刚才丢掉的 revolver 朝怪物开枪。",
            visible,
        )
        self.assertEqual(guarded["action_plan"]["actions"][0]["kind"], "firearm_attack")
        self.assertTrue(guarded["intent_guard"]["model_rewrite_detected"])
        judged = adjudicate(state, guarded["action_plan"], self.cards())
        self.assertFalse(judged["resolutions"][0]["accepted"])
        self.assertEqual(judged["resolutions"][0]["reason"], "firearm_not_carried_in_identity")

    def test_percentile_outcome_is_replayable_for_same_revision(self):
        state = scenario("the_haunting")
        state["positions"]["investigator_a"] = "records_hall"
        plan = {"actions": [{"actor": "investigator_a", "kind": "inspect", "skill": "library_use", "target": "ownership_chain"}]}
        first = adjudicate(copy.deepcopy(state), copy.deepcopy(plan), self.cards())
        second = adjudicate(copy.deepcopy(state), copy.deepcopy(plan), self.cards())
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
