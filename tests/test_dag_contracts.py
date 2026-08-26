import unittest

from dag_contracts import PORT_TYPES, dag_contract_catalog
from ego_ir import guide as egoir_guide
from harness_blueprint import blueprint_guide
from pipeline_schema import validate_component_manifest


class DagContractTests(unittest.TestCase):
    def test_catalog_covers_every_supported_visual_operation(self):
        catalog = dag_contract_catalog()
        self.assertEqual(catalog["version"], "ego.dag-contracts.v1")
        self.assertIn("Agent", catalog["nodes"])
        self.assertIn("子流程", catalog["nodes"])
        for contract in catalog["nodes"].values():
            for spec in [*contract["inputs"].values(), *contract["outputs"].values()]:
                self.assertIn(spec["type"], PORT_TYPES)

    def test_human_and_agent_authoring_surfaces_share_the_same_contract_version(self):
        version = dag_contract_catalog()["version"]
        self.assertEqual(blueprint_guide()["node_contracts"]["version"], version)
        self.assertEqual(egoir_guide()["node_contracts"]["version"], version)

    def test_component_output_schema_is_a_supported_contract(self):
        component = {
            "inputs": {"query": {"required": True, "schema": {"type": "string"}}},
            "outputs": {"score": {"path": "result.score", "schema": {"type": "number"}}},
        }
        self.assertEqual(validate_component_manifest(component), [])
        component["outputs"]["score"]["schema"] = "number"
        self.assertIn("component.outputs.score.schema must be an object", validate_component_manifest(component))


if __name__ == "__main__":
    unittest.main()
