import unittest

from dag_contracts import NODE_CONTRACTS, dag_contract_catalog
from node_registry import (
    NODE_DEFINITIONS,
    NODE_REGISTRY,
    SIDE_EFFECTING_NODE_OPS,
    canonical_node_op,
)
from pipeline_engine import PipelineRunner
from pipeline_schema import SUPPORTED_OPS, canonical_op


class NodeRegistryTests(unittest.TestCase):
    def test_runtime_schema_and_authoring_catalog_share_one_operation_set(self):
        expected = set(NODE_REGISTRY)
        self.assertEqual(set(SUPPORTED_OPS), expected)
        self.assertEqual(set(NODE_CONTRACTS), expected)
        self.assertEqual(set(dag_contract_catalog()["nodes"]), expected)

    def test_every_definition_has_a_runtime_handler_and_editor_metadata(self):
        for definition in NODE_DEFINITIONS:
            with self.subTest(op=definition.op):
                self.assertTrue(hasattr(PipelineRunner, definition.handler), definition.handler)
                contract = NODE_CONTRACTS[definition.op]
                self.assertEqual(contract["handler"], definition.handler)
                self.assertTrue(contract["editor"]["category"])
                self.assertTrue(contract["editor"]["icon"])
                self.assertIsInstance(contract["editor"]["defaults"], dict)
                self.assertEqual(definition.side_effecting, definition.op in SIDE_EFFECTING_NODE_OPS)

    def test_legacy_and_weak_model_aliases_canonicalize_identically(self):
        cases = {
            "等待输入": "输入",
            "HumanApproval": "人工审批",
            "parallel-map": "映射",
            "LLMCall": "模型",
            "data_store": "保存数据",
            "处理工具": "工具审查",
            "capability_registry": "能力",
        }
        for alias, expected in cases.items():
            with self.subTest(alias=alias):
                self.assertEqual(canonical_node_op(alias), expected)
                self.assertEqual(canonical_op(alias), expected)


if __name__ == "__main__":
    unittest.main()
