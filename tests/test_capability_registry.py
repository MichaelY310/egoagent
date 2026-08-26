import json
import os
import tempfile
import unittest
from pathlib import Path

from capability_registry import CapabilityRegistry
from agent import Agent


class FakeEmbeddings:
    provider_name = "fake-semantic"
    model_id = "fake-multilingual-v1"
    remote = False

    def __init__(self):
        self.document_calls = 0

    @staticmethod
    def _vector(text):
        value = str(text).casefold()
        if "浏览器" in value or "网页" in value or "interactive websites" in value or "web forms" in value:
            return [1.0, 0.0, 0.0]
        if "source files" in value or "代码" in value:
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]

    def embed_documents(self, texts):
        self.document_calls += len(texts)
        return [self._vector(text) for text in texts]

    def embed_query(self, text):
        return self._vector(text)

    def status(self):
        return {"available": True, "provider": self.provider_name, "model": self.model_id, "remote": False}


class CapabilityRegistryTests(unittest.TestCase):
    def setUp(self):
        self.previous_embedding_provider = os.environ.get("EGOAGENT_EMBEDDING_PROVIDER")
        os.environ["EGOAGENT_EMBEDDING_PROVIDER"] = "disabled"
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name) / "project"
        self.workspace = Path(self.temp.name) / "workspace"
        self.project.mkdir()
        self.workspace.mkdir()

        identity = self.project / "identity" / "coder"
        (identity / "ego" / "skills" / "repo_search" / "scripts").mkdir(parents=True)
        (identity / "id.json").write_text(
            json.dumps({"name": "coder", "description": "Writes Python code", "role": "engineer"}),
            encoding="utf-8",
        )
        (identity / "ego" / "skills" / "repo_search" / "meta.json").write_text(
            json.dumps({"name": "repo_search", "description": "Search source files", "tags": ["search"]}),
            encoding="utf-8",
        )
        (identity / "ego" / "skills" / "repo_search" / "scripts" / "repo_search.py").write_text(
            "def repo_search(query): return query\n", encoding="utf-8"
        )
        harness = self.project / "harness" / "coding_loop"
        harness.mkdir(parents=True)
        (harness / "config.json").write_text(
            json.dumps({
                "name": "coding_loop",
                "description": "Edit and test code",
                "slots": {"coder": {"required": True, "identity": "coder"}},
                "component": {
                    "name": "coding_loop",
                    "share_session": False,
                    "inputs": {"request": {"required": True}},
                    "outputs": {"result": {"path": "result"}},
                },
                "pipeline": {"nodes": {}},
            }),
            encoding="utf-8",
        )
        local = self.workspace / ".environment" / "tools" / "workspace_search"
        (local / "scripts").mkdir(parents=True)
        (local / "meta.json").write_text(
            json.dumps({"name": "workspace_search", "description": "Search source files in this workspace", "tags": ["search"]}),
            encoding="utf-8",
        )
        (local / "scripts" / "workspace_search.py").write_text(
            "def workspace_search(query): return query\n", encoding="utf-8"
        )

    def tearDown(self):
        self.temp.cleanup()
        if self.previous_embedding_provider is None:
            os.environ.pop("EGOAGENT_EMBEDDING_PROVIDER", None)
        else:
            os.environ["EGOAGENT_EMBEDDING_PROVIDER"] = self.previous_embedding_provider

    def test_workspace_results_are_ranked_first_and_stats_update(self):
        registry = CapabilityRegistry(self.project, workspace=self.workspace)
        report = registry.reindex()
        self.assertEqual(report["count"], 4)
        result = registry.search("search source files", kinds=["skill", "tool"])
        self.assertFalse(result["creation_recommended"])
        self.assertEqual(result["results"][0]["name"], "workspace_search")
        self.assertEqual(result["results"][0]["scope"], "workspace")

        capability_id = result["results"][0]["id"]
        self.assertTrue(registry.record_event(capability_id, "activate"))
        item = registry.get(capability_id)
        self.assertEqual(item["usage_count"], 1)
        self.assertTrue(registry.record_event(capability_id, "execute", success=True, runtime_ms=12.5))
        item = registry.get(capability_id)
        self.assertEqual(item["success_rate"], 1.0)
        self.assertEqual(item["average_runtime_ms"], 12.5)

    def test_missing_capability_recommends_creation(self):
        registry = CapabilityRegistry(self.project, workspace=self.workspace)
        registry.reindex()
        result = registry.search("quantum banana invoice reconciler")
        self.assertEqual(result["results"], [])
        self.assertTrue(result["creation_recommended"])

    def test_harness_search_returns_typed_subdag_reuse_contract(self):
        registry = CapabilityRegistry(self.project, workspace=self.workspace, embedding_backend=False)
        registry.reindex()
        result = registry.search("coding loop", kinds=["harness"], mode="lexical")
        self.assertEqual(result["results"][0]["name"], "coding_loop")
        reuse = result["results"][0]["reuse"]
        self.assertIn("typed_subdag", reuse["modes"])
        self.assertEqual(reuse["invoke"]["tool"], "create_harness")
        self.assertEqual(reuse["invoke"]["arguments"]["agents"], "coder:identity/coder")
        self.assertEqual(reuse["subflow"]["harness"], "coding_loop")
        self.assertIn("request", reuse["subflow"]["inputs"])

    def test_instruction_only_skill_activates_without_pretending_to_be_a_tool(self):
        local_skill = self.workspace / ".agents" / "skills" / "garden_evidence"
        local_skill.mkdir(parents=True)
        (local_skill / "SKILL.md").write_text(
            "# Garden evidence\nSearch local docs and cite relative paths.\n",
            encoding="utf-8",
        )
        registry = CapabilityRegistry(self.project, workspace=self.workspace, embedding_backend=False)
        registry.reindex()
        item = next(value for value in registry.list() if value["name"] == "garden_evidence")
        agent = object.__new__(Agent)
        agent.tools = {}
        agent.knowledges = {}
        agent._activated_capabilities = set()
        agent._activated_skill_instructions = {}

        result = agent.activate_capability(item["id"], registry=registry)

        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "apply_instructions")
        self.assertIn("garden_evidence", agent._activated_skill_instructions)
        self.assertEqual(agent.tools, {})

    def test_reindex_preserves_usage_and_removes_stale_entries(self):
        registry = CapabilityRegistry(self.project, workspace=self.workspace)
        registry.reindex()
        item = next(value for value in registry.list() if value["name"] == "workspace_search")
        registry.record_event(item["id"], "activate")
        local = Path(item["path"])
        for child in (local / "scripts").iterdir():
            child.unlink()
        (local / "scripts").rmdir()
        (local / "meta.json").unlink()
        local.rmdir()
        registry.reindex()
        self.assertIsNone(registry.get(item["id"]))

    def test_workspace_capabilities_never_leak_into_another_workspace(self):
        first = CapabilityRegistry(self.project, workspace=self.workspace, embedding_backend=False)
        first.reindex()
        first_result = first.search("workspace search", mode="lexical", record_impressions=False)
        self.assertIn("workspace_search", [item["name"] for item in first_result["results"]])

        other_workspace = Path(self.temp.name) / "other-workspace"
        other_workspace.mkdir()
        second = CapabilityRegistry(self.project, workspace=other_workspace, embedding_backend=False)
        second.reindex()

        self.assertNotIn("workspace_search", [item["name"] for item in second.list()])
        second_result = second.search("workspace search", mode="lexical", record_impressions=False)
        self.assertNotIn("workspace_search", [item["name"] for item in second_result["results"]])
        workspace_item = next(item for item in first.list() if item["name"] == "workspace_search")
        self.assertIsNone(second.get(workspace_item["id"]))
        self.assertFalse(second.record_event(workspace_item["id"], "activate"))

    def test_public_list_deduplicates_inherited_sources_and_omits_index_body(self):
        duplicate = self.project / "capability_packs" / "search" / "skills" / "repo_search"
        (duplicate / "scripts").mkdir(parents=True)
        (duplicate / "meta.json").write_text(
            json.dumps({"name": "repo_search", "description": "Canonical repository search"}),
            encoding="utf-8",
        )
        (duplicate / "scripts" / "repo_search.py").write_text(
            "def repo_search(query): return query\n", encoding="utf-8"
        )
        registry = CapabilityRegistry(self.project, workspace=self.workspace)
        registry.reindex()
        listed = registry.list()
        self.assertEqual(sum(item["name"] == "repo_search" for item in listed), 1)
        self.assertNotIn("search_text", listed[0])
        self.assertEqual(registry.stats()["capability_sources"], 5)
        self.assertEqual(registry.stats()["capabilities"], 4)

    def test_action_object_intent_beats_long_accidental_name_match(self):
        skills = self.project / "identity" / "coder" / "ego" / "skills"
        creator = skills / "create_harness"
        (creator / "scripts").mkdir(parents=True)
        (creator / "meta.json").write_text(
            json.dumps({"name": "create_harness", "description": "Create a reusable DAG harness"}),
            encoding="utf-8",
        )
        (creator / "scripts" / "create_harness.py").write_text(
            "def create_harness(name): return name\n", encoding="utf-8"
        )
        distracting = self.project / "identity" / "帮我创建一个agent_identity"
        distracting.mkdir(parents=True)
        (distracting / "id.json").write_text(
            json.dumps({"name": "帮我创建一个agent_identity", "description": "old generated identity"}),
            encoding="utf-8",
        )
        registry = CapabilityRegistry(self.project, workspace=self.workspace)
        registry.reindex()
        result = registry.search("创建一个新的 agent harness")
        self.assertEqual(result["results"][0]["name"], "create_harness")
        self.assertIn("task intent create_harness", result["results"][0]["match_reason"])

    def test_real_semantic_channel_finds_synonym_without_lexical_overlap_and_caches_vectors(self):
        tool = self.workspace / ".environment" / "tools" / "web_driver"
        (tool / "scripts").mkdir(parents=True)
        (tool / "meta.json").write_text(
            json.dumps({"name": "web_driver", "description": "Automates interactive websites and web forms"}),
            encoding="utf-8",
        )
        (tool / "scripts" / "web_driver.py").write_text("def web_driver(): return True\n", encoding="utf-8")
        backend = FakeEmbeddings()
        registry = CapabilityRegistry(self.project, workspace=self.workspace, embedding_backend=backend)
        registry.reindex()

        lexical = registry.search("在浏览器里填写网页表单", mode="lexical", record_impressions=False)
        hybrid = registry.search("在浏览器里填写网页表单", mode="hybrid", record_impressions=False)
        self.assertNotIn("web_driver", [item["name"] for item in lexical["results"]])
        self.assertEqual(hybrid["results"][0]["name"], "web_driver")
        self.assertEqual(hybrid["embedding"]["provider"], "fake-semantic")
        first_document_calls = backend.document_calls
        registry.search("浏览器自动操作", mode="semantic", record_impressions=False)
        self.assertEqual(backend.document_calls, first_document_calls)


if __name__ == "__main__":
    unittest.main()
