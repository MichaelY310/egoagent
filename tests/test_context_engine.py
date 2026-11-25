import json
import tempfile
import unittest
from pathlib import Path

from egoagent_core.context_engine import (
    build_index,
    index_status,
    plan_context,
    record_context_feedback,
    retrieve,
)


class ContextEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "main.py").write_text(
            "from helpers import normalize\n\ndef run(value):\n    return normalize(value)\n",
            encoding="utf-8",
        )
        (self.root / "src" / "helpers.py").write_text(
            "def normalize(value):\n    return str(value).strip().lower()\n",
            encoding="utf-8",
        )
        (self.root / "src" / "view.ts").write_text(
            "export function renderValue(value: string) {\n  return value.trim();\n}\n",
            encoding="utf-8",
        )
        (self.root / ".env").write_text("SECRET=must-not-index", encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_incremental_index_symbols_dependencies_and_invalidation(self):
        first = build_index(self.root)
        self.assertEqual(first["files"], 3)
        self.assertGreaterEqual(first["symbols"], 3)
        self.assertFalse("must-not-index" in (self.root / ".egoagent" / "context_index.json").read_text(encoding="utf-8"))

        second = build_index(self.root)
        self.assertEqual(second["reused"], 3)
        self.assertEqual(second["indexed"], 0)

        (self.root / "src" / "helpers.py").write_text(
            "def normalize(value):\n    return str(value).strip().casefold()\n",
            encoding="utf-8",
        )
        third = build_index(self.root)
        self.assertGreaterEqual(third["indexed"], 1)
        self.assertEqual(index_status(self.root)["files"], 3)

    def test_private_hybrid_retrieval_plan_explanations_and_local_feedback(self):
        build_index(self.root)
        found = retrieve(self.root, "where is normalize implemented", limit=5)
        self.assertEqual(found["retrieval"], "hybrid-local")
        self.assertEqual(found["embedding"]["adapter"], "private-hashed-subword")
        self.assertFalse(found["embedding"]["remote_source_sent"])
        self.assertEqual(found["rerank"], "diverse-local")
        self.assertEqual(found["items"][0]["path"], "src/helpers.py")

        lexical = retrieve(self.root, "normalize", limit=5, mode="lexical")
        self.assertEqual(lexical["retrieval"], "lexical")
        self.assertIsNone(lexical["embedding"])

        plan = plan_context({
            "workspace": str(self.root),
            "query": "normalize value",
            "token_budget": 500,
            "selection": {"path": "src/main.py", "content": "normalize(value)", "start_line": 4, "end_line": 4},
            "explicit": [{"kind": "diagnostic", "title": "Type error", "content": "value may be None"}],
            "diagnostics": [{"path": "src/main.py", "content": "Argument may be None", "start_line": 4}],
        })
        self.assertLessEqual(plan["tokens_used"], plan["token_budget"])
        self.assertTrue(plan["selected"][0]["explicit"])
        self.assertIn("<context", plan["prompt"])
        self.assertIn("explicit-first", plan["explanation"]["policy"])

        candidate = next(item for item in plan["selected"] if item["provenance"] == "lexical-index")
        result = record_context_feedback(self.root, [candidate["id"]], "accepted")
        self.assertEqual(result["recorded"], 1)
        feedback = json.loads((self.root / ".egoagent" / "context_feedback.json").read_text(encoding="utf-8"))
        self.assertNotIn(candidate["content"], json.dumps(feedback))
        self.assertEqual(feedback["items"][candidate["id"]]["accepted"], 1)

    def test_pasted_editor_and_terminal_blocks_keep_typed_source_metadata(self):
        plan = plan_context({
            "workspace": str(self.root),
            "query": "explain the selected implementation and its failing command",
            "token_budget": 1000,
            "include_repo_map": False,
            "retrieval_limit": 0,
            "explicit": [
                {
                    "kind": "selection",
                    "title": "src/main.py:3-4",
                    "path": "src/main.py",
                    "start_line": 3,
                    "end_line": 4,
                    "content": "def run(value):\n    return normalize(value)",
                    "metadata": {
                        "language": "python",
                        "source": "clipboard",
                        "reference": "[代码附件: src/main.py:3-4]",
                    },
                },
                {
                    "kind": "terminal",
                    "title": "Terminal · PowerShell · 2 lines",
                    "content": "pytest tests/test_main.py\n1 failed",
                    "metadata": {"language": "shell", "source": "clipboard"},
                },
            ],
        })

        selected = {item["kind"]: item for item in plan["selected"]}
        self.assertEqual(selected["selection"]["path"], "src/main.py")
        self.assertEqual(selected["selection"]["start_line"], 3)
        self.assertEqual(selected["selection"]["end_line"], 4)
        self.assertEqual(selected["selection"]["metadata"]["language"], "python")
        self.assertEqual(selected["terminal"]["metadata"]["language"], "shell")
        self.assertIn('kind="selection"', plan["prompt"])
        self.assertIn('location="src/main.py:3-4"', plan["prompt"])
        self.assertIn('reference="[代码附件: src/main.py:3-4]"', plan["prompt"])
        self.assertIn('kind="terminal"', plan["prompt"])



if __name__ == "__main__":
    unittest.main()
