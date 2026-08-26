import copy
import json
import tempfile
import unittest
from pathlib import Path

from ego_ir import (
    EgoIRError,
    EgoIRService,
    apply_operations,
    compile_document,
    decompile_config,
    dumps,
    loads,
)


def sample_config(name="typed_harness"):
    return {
        "name": name,
        "description": "typed round trip",
        "slots": {"worker": {"required": True, "description": "does work"}},
        "identity_bindings": {"worker": "dante"},
        "permissions": {"network": "ask", "process": "allow"},
        "prompts": {"system": "Be concise"},
        "return_mode": "last",
        "custom_top": {"preserve": True},
        "pipeline": {
            "start": "input", "max_steps": 20, "workspace_preview": False,
            "checkpoint_policy": {"every": 3},
            "nodes": {
                "input": {"op": "输入", "ports": {"out": {"request": "message"}}, "edges": [{"condition": "input", "to": "think", "label": "request"}]},
                "think": {"op": "Agent", "agent": "worker", "tools": "auto", "ports": {"in": {"request": "message"}, "out": {"answer": "message"}}, "edges": [{"condition": "text", "to": "finish"}]},
                "finish": {"op": "输出", "value": "$last.text", "edges": []},
            },
        },
    }


class EgoIRTests(unittest.TestCase):
    def test_config_text_round_trip_is_lossless(self):
        config = sample_config()
        document = decompile_config(config)
        text = dumps(document)
        self.assertTrue(text.startswith("EGOIR/1\n"))
        self.assertIn("node\t", text)
        self.assertEqual(compile_document(loads(text)), config)

    def test_typed_ports_and_references_are_validated(self):
        document = decompile_config(sample_config())
        document["nodes"][0]["ports"] = {"out": {"request": "made_up_type"}}
        with self.assertRaisesRegex(EgoIRError, "unknown type"):
            compile_document(document)
        document = decompile_config(sample_config())
        document["edges"][0]["to"] = "missing"
        with self.assertRaisesRegex(EgoIRError, "missing node"):
            compile_document(document)

    def test_structural_operations_cover_node_edge_binding_and_governance(self):
        document = decompile_config(sample_config())
        updated = apply_operations(document, [
            {"op": "add_node", "after": "think", "node": {"id": "approve", "op": "approval", "config": {}}},
            {"op": "disconnect", "from": "think", "to": "finish"},
            {"op": "connect", "from": "think", "condition": "text", "to": "approve"},
            {"op": "connect", "from": "approve", "condition": "approved", "to": "finish"},
            {"op": "set_ports", "id": "approve", "ports": {"in": {"proposal": "json"}, "out": {"decision": "boolean"}}},
            {"op": "rebind", "role": "worker", "identity": "researcher"},
            {"op": "set_limits", "max_steps": 40},
            {"op": "set_permissions", "permissions": {"network": "deny"}},
        ])
        config = compile_document(updated)
        self.assertIn("approve", config["pipeline"]["nodes"])
        self.assertEqual(config["identity_bindings"]["worker"], "researcher")
        self.assertEqual(config["pipeline"]["max_steps"], 40)
        self.assertEqual(config["permissions"]["network"], "deny")

    def test_weak_model_common_operation_shapes_are_normalized(self):
        document = decompile_config(sample_config())
        updated = apply_operations(document, [
            {"op": "add_node", "node": {"id": "compact", "op": "Context", "config": {}}},
            {"op": "disconnect", "edge": {"from": "input", "to": "think"}},
            {"op": "connect", "edge": {"from": "input", "condition": "input", "to": "compact"}},
            {"op": "connect", "edge": {"from": "compact", "condition": "default", "to": "think"}},
            {"op": "add_role", "role": {"id": "reviewer", "definition": {"required": True}}},
            {"op": "set_limits", "limits": {"max_steps": 31}},
        ])
        config = compile_document(updated)
        self.assertEqual(config["pipeline"]["nodes"]["compact"]["op"], "Context")
        self.assertEqual(config["pipeline"]["nodes"]["input"]["edges"][0]["to"], "compact")
        self.assertIn("reviewer", config["slots"])
        self.assertEqual(config["pipeline"]["max_steps"], 31)

    def test_transaction_dry_run_revision_commit_and_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "harness" / "typed" / "config.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(sample_config("typed"), ensure_ascii=False, indent=2), encoding="utf-8")
            service = EgoIRService(root)
            loaded = service.load("typed")
            dry = service.patch("typed", [{"op": "set_limits", "max_steps": 30}], expected_revision=loaded["revision"], dry_run=True, checks=[{"type": "no_python"}])
            self.assertTrue(dry["dry_run"])
            self.assertEqual(service.load("typed")["revision"], loaded["revision"])
            committed = service.patch("typed", [{"op": "set_limits", "max_steps": 30}], expected_revision=loaded["revision"], checks=[{"type": "node_exists", "id": "think"}])
            self.assertNotEqual(committed["revision"], loaded["revision"])
            with self.assertRaisesRegex(EgoIRError, "revision conflict"):
                service.patch("typed", [{"op": "set_limits", "max_steps": 31}], expected_revision=loaded["revision"])
            rolled = service.rollback(committed["transaction_id"], expected_revision=committed["revision"])
            self.assertEqual(rolled["revision"], loaded["revision"])
            self.assertEqual(service.load("typed")["config"], sample_config("typed"))

    def test_repository_pipeline_harnesses_round_trip(self):
        repository = Path(__file__).resolve().parents[1]
        checked = 0
        for path in sorted((repository / "harness").glob("*/config.json")):
            config = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(config.get("pipeline"), dict):
                continue
            with self.subTest(harness=path.parent.name):
                self.assertEqual(compile_document(loads(dumps(decompile_config(config)))), config)
            checked += 1
        self.assertGreater(checked, 5)


if __name__ == "__main__":
    unittest.main()
