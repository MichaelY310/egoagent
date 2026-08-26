import json
import tempfile
import unittest
from pathlib import Path

from harness_blueprint import (
    BlueprintError,
    HarnessBlueprintService,
    RevisionConflict,
    compile_blueprint,
    decompile_config,
    legacy_modify_harness,
)


def simple_blueprint(name="tiny_agent"):
    return {
        "version": 1,
        "name": name,
        "description": "A tiny visual and runnable Agent",
        "roles": {"worker": "main worker"},
        "start": "ask",
        "steps": [
            {"id": "ask", "type": "input", "next": "think"},
            {
                "id": "think",
                "type": "agent",
                "role": "worker",
                "on": {"tools": "act", "text": "finish"},
                "tools": "auto",
            },
            {"id": "act", "type": "tool", "role": "worker", "next": "think"},
            {"id": "finish", "type": "end", "inputs": {"value": "$last.text"}},
        ],
        "return_mode": "last",
    }


class HarnessBlueprintTests(unittest.TestCase):
    def test_compiles_friendly_vocabulary_to_runtime_config(self):
        config, warnings = compile_blueprint(simple_blueprint())
        self.assertEqual(config["pipeline"]["nodes"]["think"]["op"], "Agent")
        self.assertEqual(config["pipeline"]["nodes"]["think"]["agent"], "worker")
        self.assertEqual(
            config["pipeline"]["nodes"]["think"]["edges"],
            [
                {"condition": "has_tool_calls", "to": "act"},
                {"condition": "has_text", "to": "finish"},
            ],
        )
        self.assertEqual(warnings, [])

    def test_existing_config_round_trips_without_losing_advanced_fields(self):
        config, _ = compile_blueprint(simple_blueprint())
        config["pipeline"]["budget"] = {"max_tool_calls": 4}
        config["pipeline"]["nodes"]["think"]["retry"] = {"max_attempts": 2}
        rebuilt, _ = compile_blueprint(decompile_config(config))
        self.assertEqual(rebuilt, config)

    def test_patch_is_atomic_revision_checked_and_rollbackable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "harness").mkdir()
            service = HarnessBlueprintService(root)
            created = service.create(simple_blueprint())
            patched = service.patch(
                "tiny_agent",
                [
                    {
                        "op": "add_step",
                        "after": "think",
                        "step": {"id": "check", "type": "if", "condition": "exists(ctx.text)"},
                    },
                    {"op": "connect", "from": "think", "condition": "text", "to": "check"},
                    {"op": "connect", "from": "check", "condition": "true", "to": "finish"},
                    {"op": "connect", "from": "check", "condition": "false", "to": "think"},
                ],
                expected_revision=created["revision"],
                reason="add deterministic guard",
            )
            stored = json.loads((root / "harness" / "tiny_agent" / "config.json").read_text(encoding="utf-8"))
            self.assertIn("check", stored["pipeline"]["nodes"])
            self.assertIn('"check"', patched["diff"])
            with self.assertRaises(RevisionConflict):
                service.patch("tiny_agent", [{"op": "set_start", "id": "ask"}], expected_revision="stale")
            rolled_back = service.rollback(patched["transaction_id"])
            self.assertEqual(rolled_back["revision"], created["revision"])
            restored = service.load("tiny_agent")
            self.assertNotIn("check", restored["config"]["pipeline"]["nodes"])

    def test_invalid_target_is_rejected_before_write(self):
        with self.assertRaises(BlueprintError):
            compile_blueprint({
                **simple_blueprint(),
                "steps": [{"id": "ask", "type": "input", "next": "missing"}],
            })

    def test_legacy_mutation_is_transactional_and_rollbackable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "harness").mkdir()
            service = HarnessBlueprintService(root)
            created = service.create(simple_blueprint())
            changed = legacy_modify_harness(
                root,
                "tiny_agent",
                "add_node",
                "",
                json.dumps({
                    "id": "guard",
                    "op": "If",
                    "condition": "exists(ctx.text)",
                    "edges": [{"condition": "default", "to": "finish"}],
                }),
            )
            self.assertIn("guard", service.load("tiny_agent")["config"]["pipeline"]["nodes"])
            self.assertTrue(changed["transaction_id"])
            service.rollback(changed["transaction_id"])
            restored = service.load("tiny_agent")
            self.assertEqual(restored["revision"], created["revision"])
            self.assertNotIn("guard", restored["config"]["pipeline"]["nodes"])


if __name__ == "__main__":
    unittest.main()
