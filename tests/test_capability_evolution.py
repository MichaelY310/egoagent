import json
import shutil
import tempfile
import unittest
from pathlib import Path

from environment import load_environment_from_dir
from self_evolution.capability_evolution import CapabilityEvolutionService, analyze_evolution_need
from utils import load_script


ROOT = Path(__file__).resolve().parents[1]


def write_identity(root: Path, name: str):
    identity = root / "identity" / name
    (identity / "ego" / "skills").mkdir(parents=True)
    (identity / "ego" / "knowledge").mkdir(parents=True)
    (identity / "superego").mkdir(parents=True)
    (identity / "id.json").write_text(json.dumps({
        "name": name,
        "role": "test",
        "description": "test identity",
        "personality": {"traits": [], "tone": "direct", "language": "en"},
        "llm": {"type": "custom_llm", "base_url": "http://localhost/v1", "model": "test", "api_key": "secret"},
    }), encoding="utf-8")
    (identity / "superego" / "config.json").write_text("{}", encoding="utf-8")
    return identity


class CapabilityEvolutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "tmp")
        self.root = Path(self.temp.name)
        (self.root / "harness").mkdir()
        self.target = write_identity(self.root, "target")
        self.dante = write_identity(self.root, "dante")
        for skill in ("read", "search", "create_harness"):
            source = ROOT / "identity" / "dante" / "ego" / "skills" / skill
            shutil.copytree(source, self.dante / "ego" / "skills" / skill)
        self.service = CapabilityEvolutionService(self.root)
        self.service.pack_root = ROOT / "self_evolution" / "capability_packs"

    def tearDown(self):
        self.temp.cleanup()

    def test_paper_pack_is_loadable_searches_local_text_and_rolls_back(self):
        dry = self.service.install("target", "paper_library", dry_run=True)
        self.assertFalse((self.target / "ego" / "skills" / "local_paper_search").exists())
        self.assertTrue(any(change["action"] == "create" for change in dry["changes"]))

        installed = self.service.install("target", "paper_library", reason="local papers were ignored")
        environment = load_environment_from_dir(self.target / "ego")
        self.assertTrue(any(name.endswith(":local_paper_search") for name in environment.tools))
        self.assertTrue(any(name.endswith(":local_papers_first") for name in environment.knowledges))

        workspace = self.root / "workspace"
        papers = workspace / "papers"
        papers.mkdir(parents=True)
        (papers / "important.txt").write_text(
            "The Helios method stores sparse memories and retrieves them before external search.",
            encoding="utf-8",
        )
        script = self.target / "ego" / "skills" / "local_paper_search" / "scripts" / "local_paper_search.py"
        search = load_script(script, "local_paper_search")
        result = json.loads(search("Helios sparse memories", _context={"workspace": str(workspace)}))
        self.assertTrue(result["ok"])
        self.assertEqual(result["matches"][0]["path"], "papers/important.txt")
        self.assertIn("retrieves", result["matches"][0]["snippet"])

        rolled_back = self.service.rollback(installed["transaction_id"])
        self.assertTrue(rolled_back["removed"])
        self.assertFalse((self.target / "ego" / "skills" / "local_paper_search").exists())

    def test_delegated_search_creates_isolated_identity_harness_and_parent_tool(self):
        installed = self.service.install("target", "delegated_search")

        worker = self.root / "identity" / "target_search_worker"
        harness = self.root / "harness" / "target_result_only_search" / "config.json"
        delegate = self.target / "ego" / "skills" / "delegate_search" / "meta.json"
        self.assertTrue(worker.is_dir())
        self.assertTrue(harness.is_file())
        self.assertTrue(delegate.is_file())
        worker_id = json.loads((worker / "id.json").read_text(encoding="utf-8"))
        self.assertEqual(worker_id["llm"]["api_key"], "")
        config = json.loads(harness.read_text(encoding="utf-8"))
        self.assertEqual(config["return_mode"], "last")
        self.assertEqual(config["slots"]["searcher"]["identity"], "target_search_worker")

        self.service.rollback(installed["transaction_id"])
        self.assertFalse(worker.exists())
        self.assertFalse(harness.parent.exists())
        self.assertFalse(delegate.parent.exists())

    def test_need_analyzer_distinguishes_capability_and_harness_evolution(self):
        result = analyze_evolution_need(
            "The user gave us three PDF papers. We searched twice, both searches failed and the context is too long. Next step may deploy."
        )
        packs = {item.get("pack") for item in result["recommendations"]}
        recipes = {item.get("recipe") for item in result["recommendations"]}
        self.assertIn("paper_library", packs)
        self.assertIn("delegated_search", packs)
        self.assertIn("context_guard", recipes)
        self.assertIn("risk_gate", recipes)


if __name__ == "__main__":
    unittest.main()
