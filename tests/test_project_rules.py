import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harness_editor.project_rules import get_effective_rules_prompt, get_scoped_agents_prompt


class ProjectRulesPromptTests(unittest.TestCase):
    def test_nested_agents_files_follow_target_scope_from_root_to_leaf(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "src" / "feature" / "module.py"
            target.parent.mkdir(parents=True)
            target.write_text("pass\n", encoding="utf-8")
            (root / "AGENTS.md").write_text("root-rule", encoding="utf-8")
            (root / "src" / "AGENTS.md").write_text("src-rule", encoding="utf-8")
            (target.parent / "AGENTS.md").write_text("feature-rule", encoding="utf-8")
            sibling = root / "docs"
            sibling.mkdir()
            (sibling / "AGENTS.md").write_text("docs-only", encoding="utf-8")

            prompt = get_scoped_agents_prompt(str(root), str(target))

            self.assertLess(prompt.index("root-rule"), prompt.index("src-rule"))
            self.assertLess(prompt.index("src-rule"), prompt.index("feature-rule"))
            self.assertNotIn("docs-only", prompt)

    def test_nested_only_prompt_does_not_duplicate_root_policy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            child = root / "child"
            child.mkdir()
            (root / "AGENTS.md").write_text("root-rule", encoding="utf-8")
            (child / "AGENTS.md").write_text("child-rule", encoding="utf-8")

            prompt = get_scoped_agents_prompt(str(root), str(child), include_root=False)

            self.assertNotIn("root-rule", prompt)
            self.assertIn("child-rule", prompt)

    def test_large_agents_file_is_bounded_and_explains_retrieval(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "AGENTS.md").write_text("important-rule\n" * 1000, encoding="utf-8")

            with patch.dict(os.environ, {"EGOAGENT_PROJECT_RULES_MAX_CHARS": "4096"}):
                prompt = get_effective_rules_prompt(str(root))

            self.assertLess(len(prompt), 4400)
            self.assertIn("important-rule", prompt)
            self.assertIn("Project instructions truncated", prompt)
            self.assertIn("read_file/search_files", prompt)


if __name__ == "__main__":
    unittest.main()
