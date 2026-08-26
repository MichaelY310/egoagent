import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from agent import preserve_patch_line_endings


ROOT = Path(__file__).resolve().parents[1]


def load_function(relative, name):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(f"test_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, name)


class CoderEditToolTests(unittest.TestCase):
    def test_central_patch_boundary_preserves_existing_newline_style(self):
        self.assertEqual(
            preserve_patch_line_endings("a\nb\n", "a\r\nchanged\r\n"),
            "a\nchanged\n",
        )
        self.assertEqual(
            preserve_patch_line_endings("a\r\nb\r\n", "a\nchanged\n"),
            "a\r\nchanged\r\n",
        )

    def test_multi_edit_preserves_lf_and_independent_changes(self):
        function = load_function(
            "identity/coder/ego/skills/multi_edit/scripts/multi_edit.py", "multi_edit"
        )
        original = b"def alpha():\n    return 1\n\n\ndef beta():\n    return 2\n"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.py"
            path.write_bytes(original)
            result = json.loads(function(str(path), [
                {"old_string": "return 1", "new_string": "return 10"},
                {"old_string": "return 2", "new_string": "return 20"},
            ]))
            self.assertEqual(result["status"], "ok")
            updated = path.read_bytes()
            self.assertNotIn(b"\r\n", updated)
            self.assertIn(b"return 10\n", updated)
            self.assertIn(b"return 20\n", updated)

    def test_patch_file_preserves_crlf(self):
        function = load_function(
            "identity/coder/ego/skills/patch/scripts/patch_file.py", "patch_file"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.py"
            path.write_bytes(b"value = 1\r\nnext = 2\r\n")
            result = json.loads(function(str(path), "value = 1", "value = 10"))
            self.assertEqual(result["status"], "ok")
            self.assertEqual(path.read_bytes(), b"value = 10\r\nnext = 2\r\n")


if __name__ == "__main__":
    unittest.main()
