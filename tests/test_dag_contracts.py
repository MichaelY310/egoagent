import unittest

from dag_contracts import PORT_TYPES, dag_contract_catalog
from ego_ir import guide as egoir_guide
from harness_blueprint import blueprint_guide
from pipeline_schema import validate_component_manifest, validate_pipeline


class DagContractTests(unittest.TestCase):
    def test_catalog_covers_every_supported_visual_operation(self):
        catalog = dag_contract_catalog()
        self.assertEqual(catalog["version"], "ego.dag-contracts.v1")
        self.assertEqual(catalog["graph_schema"], "ego.flow-graph.v2")
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

    def test_typed_data_links_are_validated_without_changing_runtime_references(self):
        pipeline = {
            "start": "source",
            "nodes": {
                "source": {"op": "模型", "editor_position": {"x": 80.0, "y": 120.0}, "edges": [{"condition": "has_text", "to": "target"}]},
                "target": {"op": "文本处理", "editor_position": {"x": 420.0, "y": 120.0}, "inputs": {"text": "$node.source.text"}, "edges": []},
            },
            "data_links": [{
                "id": "source.text->target.text",
                "source": "source", "source_port": "text",
                "target": "target", "target_port": "text",
                "reroutes": [{
                    "id": "r1", "x": 250.0, "y": 140.0,
                    "angle": 0.42, "in_length": 31.0, "out_length": 44.0,
                }],
                "source_handle": 52.0,
                "target_handle": 48.0,
            }],
        }
        self.assertEqual(validate_pipeline(pipeline), [])

        pipeline["data_links"][0]["reroutes"][0]["angle"] = "horizontal"
        self.assertTrue(any("angle must be numeric" in error for error in validate_pipeline(pipeline)))
        pipeline["data_links"][0]["reroutes"][0]["angle"] = 0.42

        pipeline["data_links"].append({
            "source": "source", "source_port": "structured",
            "target": "target", "target_port": "text", "reroutes": [],
        })
        self.assertTrue(any("duplicates single input socket target.text" in error for error in validate_pipeline(pipeline)))

        pipeline["nodes"]["source"]["editor_position"]["x"] = "left"
        self.assertTrue(any("editor_position must contain numeric x/y" in error for error in validate_pipeline(pipeline)))


if __name__ == "__main__":
    unittest.main()
