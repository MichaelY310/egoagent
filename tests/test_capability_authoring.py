from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from capability_authoring import CapabilityAuthoringError, create_executable_skill
from environment import load_tool_from_dir


ROOT = Path(__file__).resolve().parents[1]


class CapabilityAuthoringTests(unittest.TestCase):
    def test_json_encoded_schema_is_accepted_for_weak_provider_compatibility(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as temp:
            project = Path(temp)
            identity = project / "identity" / "test_identity"
            identity.mkdir(parents=True)
            (identity / "id.json").write_text('{"name":"test_identity"}', encoding="utf-8")
            result = create_executable_skill(
                project,
                identity_name="test_identity",
                skill_name="double_value",
                description="Double a numeric value.",
                parameters_schema=json.dumps({
                    "type": "object",
                    "properties": {"value": {"type": "number"}},
                    "required": ["value"],
                }),
                function_code="def double_value(value):\n    return value * 2",
            )
            self.assertTrue(result["ok"])

    def test_created_skill_is_a_loadable_runtime_tool(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as temp:
            project = Path(temp)
            identity = project / "identity" / "test_identity"
            identity.mkdir(parents=True)
            (identity / "id.json").write_text(json.dumps({"name": "test_identity"}), encoding="utf-8")

            result = create_executable_skill(
                project,
                identity_name="test_identity",
                skill_name="normalize_title",
                description="Normalize a title for repeated catalog ingestion.",
                parameters_schema="title:string:raw title",
                function_code="def normalize_title(title: str):\n    return title.strip().title()",
            )

            skill = project / "identity" / "test_identity" / "ego" / "skills" / "normalize_title"
            loaded = load_tool_from_dir(skill)
            self.assertTrue(result["ok"])
            self.assertEqual(result["kind"], "skill")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.func("  hello DAG "), "Hello Dag")
            self.assertEqual(loaded.desc["function"]["parameters"]["required"], ["title"])

    def test_capability_authoring_rejects_path_escape_and_invalid_code(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as temp:
            project = Path(temp)
            identity = project / "identity" / "safe_identity"
            identity.mkdir(parents=True)
            (identity / "id.json").write_text('{"name":"safe_identity"}', encoding="utf-8")
            with self.assertRaises(CapabilityAuthoringError):
                create_executable_skill(
                    project, identity_name="../escape", skill_name="bad", description="bad",
                    parameters_schema={}, function_code="def bad():\n    return 1",
                )
            with self.assertRaises(CapabilityAuthoringError):
                create_executable_skill(
                    project, identity_name="safe_identity", skill_name="expected", description="bad",
                    parameters_schema={}, function_code="def another_name():\n    return 1",
                )

    def test_capability_authoring_rejects_schema_signature_mismatch(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as temp:
            project = Path(temp)
            identity = project / "identity" / "safe_identity"
            identity.mkdir(parents=True)
            (identity / "id.json").write_text('{"name":"safe_identity"}', encoding="utf-8")
            with self.assertRaisesRegex(CapabilityAuthoringError, "missing from parameters_schema"):
                create_executable_skill(
                    project, identity_name="safe_identity", skill_name="broken", description="bad",
                    parameters_schema="sensor_notes:string:notes; duration:number:seconds",
                    function_code="def broken(sensor_notes, duration):\n    return duration",
                )
            with self.assertRaisesRegex(CapabilityAuthoringError, "accept _context=None"):
                create_executable_skill(
                    project, identity_name="safe_identity", skill_name="hidden_context", description="bad",
                    parameters_schema="value:string:value",
                    function_code="def hidden_context(value):\n    return _context.get('workspace')",
                )

    def test_runtime_context_is_removed_from_the_public_schema(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as temp:
            project = Path(temp)
            identity = project / "identity" / "safe_identity"
            identity.mkdir(parents=True)
            (identity / "id.json").write_text('{"name":"safe_identity"}', encoding="utf-8")
            create_executable_skill(
                project,
                identity_name="safe_identity",
                skill_name="workspace_name",
                description="Read the trusted workspace name.",
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "value": {"type": "string"},
                        "_context": {"type": "object"},
                    },
                    "required": ["value", "_context"],
                },
                function_code=(
                    "def workspace_name(value, _context=None):\n"
                    "    return {'value': value, 'workspace': (_context or {}).get('workspace')}"
                ),
            )
            meta = json.loads((
                identity / "ego" / "skills" / "workspace_name" / "meta.json"
            ).read_text(encoding="utf-8"))
            self.assertNotIn("_context", meta["parameters"]["properties"])
            self.assertEqual(meta["parameters"]["required"], ["value"])
            with self.assertRaisesRegex(CapabilityAuthoringError, "not accepted"):
                create_executable_skill(
                    project, identity_name="safe_identity", skill_name="extra_schema", description="bad",
                    parameters_schema={"type": "object", "properties": {"unknown": {"type": "string"}}},
                    function_code="def extra_schema():\n    return 1",
                )


if __name__ == "__main__":
    unittest.main()
