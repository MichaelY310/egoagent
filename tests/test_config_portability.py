import unittest
from pathlib import Path

from config import CONFIG


class ConfigPortabilityTests(unittest.TestCase):
    def test_repository_paths_are_absolute_existing_and_portable(self):
        root = Path(__file__).resolve().parents[1]
        for key in ("root_environment_path", "harness_template_repository", "identity_repository"):
            path = Path(CONFIG[key])
            self.assertTrue(path.is_absolute(), key)
            self.assertTrue(path.is_dir(), key)
            self.assertTrue(path == root or root in path.parents, key)

    def test_command_blacklist_contains_only_strings(self):
        values = CONFIG.get("command_blacklist", [])
        self.assertTrue(values)
        self.assertTrue(all(isinstance(value, str) for value in values), values)
        self.assertIn(":(){ :|:& };:", values)


if __name__ == "__main__":
    unittest.main()
