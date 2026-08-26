import unittest
from unittest.mock import patch

from harness_editor.ai_service import AIServiceError, _completion, _next_edit


class AICompletionServiceTests(unittest.TestCase):
    @patch("harness_editor.ai_service._call_json")
    def test_completion_passes_fim_and_typed_editor_context(self, call_json):
        call_json.return_value = (
            {"completion": "return helper(value)"},
            {"model": "test", "profile_id": "fast", "role": "autocomplete"},
        )

        result = _completion({
            "prefix": "def run(value):\n    ",
            "suffix": "\n\nclass Later: pass",
            "language": "python",
            "path": "src/main.py",
            "imports": ["from helpers import helper"],
            "recent_edits": [{"path": "src/helpers.py", "inserted": "def helper(value):"}],
            "open_files": [{"path": "src/helpers.py", "excerpt": "def helper(value): return value"}],
            "trigger_kind": 0,
        })

        self.assertEqual(result["completion"], "return helper(value)")
        self.assertEqual(result["profile_id"], "fast")
        _, user_prompt = call_json.call_args.args[:2]
        self.assertIn("<PREFIX>", user_prompt)
        self.assertIn("<SUFFIX>", user_prompt)
        self.assertIn("from helpers import helper", user_prompt)
        self.assertIn("src/helpers.py", user_prompt)
        self.assertEqual(call_json.call_args.kwargs["role"], "autocomplete")

    def test_completion_rejects_unbounded_supplemental_context(self):
        with self.assertRaisesRegex(AIServiceError, "context is too large"):
            _completion({
                "prefix": "x = ",
                "suffix": "",
                "language": "python",
                "path": "x.py",
                "open_files": [{"path": "huge.py", "excerpt": "x" * 25000}],
            })

    @patch("harness_editor.ai_service._call_json")
    def test_next_edit_is_confined_to_supplied_candidates(self, call_json):
        call_json.return_value = (
            {
                "path": "src/helper.py",
                "start_line": 4,
                "end_line": 5,
                "replacement": "def normalized():\n    return True",
                "label": "Keep helper aligned",
                "confidence": 0.81,
            },
            {"model": "test", "profile_id": "editor", "role": "edit"},
        )
        result = _next_edit({
            "current_path": "src/main.py",
            "last_edit": {"line": 8, "inserted_text": "normalized()"},
            "candidates": [
                {"path": "src/main.py", "excerpt_start_line": 1, "excerpt": "normalized()"},
                {"path": "src/helper.py", "excerpt_start_line": 1, "excerpt": "def old(): pass"},
            ],
        })
        self.assertEqual(result["path"], "src/helper.py")
        self.assertEqual(result["start_line"], 4)
        self.assertEqual(result["end_line"], 5)
        self.assertEqual(result["profile_id"], "editor")
        self.assertEqual(call_json.call_args.kwargs["role"], "edit")

        call_json.return_value = (
            {"path": "outside.py", "start_line": 1, "end_line": 1, "replacement": "bad"},
            {},
        )
        with self.assertRaisesRegex(AIServiceError, "outside"):
            _next_edit({
                "current_path": "src/main.py",
                "last_edit": {},
                "candidates": [{"path": "src/main.py", "excerpt": "pass"}],
            })


if __name__ == "__main__":
    unittest.main()
