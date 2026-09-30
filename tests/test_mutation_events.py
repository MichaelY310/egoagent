import unittest

from pipeline_engine import _mutation_event_for_tool, _mutation_event_payload


class MutationEventClassificationTests(unittest.TestCase):
    def test_capability_analysis_is_not_reported_as_evolution(self):
        self.assertIsNone(_mutation_event_for_tool(
            "evolve_capabilities", {"action": "analyze"}, '{"ok": true}'
        ))

    def test_capability_install_is_reported(self):
        self.assertEqual(
            _mutation_event_for_tool("evolve_capabilities", {"action": "install"}, '{"ok": true}'),
            "identity_evolution",
        )

    def test_failed_creation_is_not_reported(self):
        self.assertIsNone(_mutation_event_for_tool(
            "create_agent_system", {"name": "probe"}, '{"ok": false, "error": "bad"}'
        ))
        self.assertIsNone(_mutation_event_for_tool(
            "create_tool", {}, "Tool create_tool error: invalid JSON arguments"
        ))

    def test_agent_and_harness_mutations_are_distinct(self):
        self.assertEqual(
            _mutation_event_for_tool("create_agent_system", {"name": "probe"}, '{"ok": true}'),
            "agent_system_created",
        )
        self.assertEqual(
            _mutation_event_for_tool("manage_harness", {"action": "patch"}, {"ok": True}),
            "harness_mutation",
        )

    def test_harness_event_has_a_stable_structural_contract(self):
        payload = _mutation_event_payload(
            "manage_harness",
            {
                "action": "patch",
                "harness_name": "demo_flow",
                "operations": [{"op": "add_step", "step": {"id": "approval", "type": "人工审批"}}],
            },
            '{"ok":true,"transaction_id":"tx-7","revision":"rev-2","current_nodes":["input","approval"]}',
            agent="architect",
        )
        self.assertEqual(payload["harness"], "demo_flow")
        self.assertEqual(payload["action"], "patch")
        self.assertEqual(payload["transaction_id"], "tx-7")
        self.assertEqual(payload["revision"], "rev-2")
        self.assertEqual(payload["nodes"], ["input", "approval"])
        self.assertEqual(payload["operations"][0]["step"]["id"], "approval")


if __name__ == "__main__":
    unittest.main()
