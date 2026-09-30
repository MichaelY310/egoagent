import unittest

from harness_catalog import classify_harness, is_public_runnable


def config(*, start: str = "input", nodes=None, catalog=None):
    value = {"pipeline": {"start": start, "nodes": nodes if nodes is not None else {"input": {"op": "输入"}}}}
    if catalog is not None:
        value["catalog"] = catalog
    return value


class HarnessCatalogTests(unittest.TestCase):
    def test_known_product_flows_are_system(self):
        item = classify_harness("adaptive_code_agent", config())
        self.assertEqual(item["catalog_category"], "system")
        self.assertEqual(item["catalog_visibility"], "public")
        self.assertTrue(item["runnable"])

    def test_components_remain_runtime_available_but_hidden_from_main_picker(self):
        item = classify_harness("component_context_compactor", config())
        self.assertEqual(item["catalog_category"], "system")
        self.assertEqual(item["catalog_visibility"], "internal")
        self.assertFalse(is_public_runnable("component_context_compactor", config()))

    def test_unknown_saved_flow_is_custom(self):
        item = classify_harness("my_project_reviewer", config())
        self.assertEqual(item["catalog_category"], "custom")
        self.assertTrue(is_public_runnable("my_project_reviewer", config()))

    def test_empty_draft_is_not_runnable(self):
        empty = config(start="", nodes={})
        self.assertFalse(classify_harness("untitled_custom_flow", empty)["runnable"])
        self.assertFalse(is_public_runnable("untitled_custom_flow", empty))

    def test_explicit_catalog_override_wins(self):
        item = classify_harness("team_template", config(catalog={"category": "example", "visibility": "public"}))
        self.assertEqual(item["catalog_category"], "example")

    def test_product_experiment_engines_are_hidden_but_user_code_agents_are_public(self):
        internal = classify_harness("product_core_code_agent", config())
        self.assertEqual(internal["catalog_category"], "experiment")
        self.assertEqual(internal["catalog_visibility"], "internal")
        self.assertFalse(is_public_runnable("product_core_code_agent", config()))

        public = classify_harness("code_agent_auto", config(catalog={"display_name": "Code Agent · Auto"}))
        self.assertEqual(public["catalog_category"], "system")
        self.assertEqual(public["catalog_visibility"], "public")
        self.assertEqual(public["display_name"], "Code Agent · Auto")


if __name__ == "__main__":
    unittest.main()
