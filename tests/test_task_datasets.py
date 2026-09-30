import json
import tempfile
import unittest
from pathlib import Path

from task_bench.datasets import DatasetError, DatasetStore
from task_bench.engine import load_task_specs


class TaskDatasetTests(unittest.TestCase):
    def test_jsonl_mapping_materializes_reviewable_tasks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = DatasetStore(root)
            source = "\n".join([
                json.dumps({"key": "first", "question": "Return alpha", "answer": "alpha", "meta": {"split": "test"}}),
                json.dumps({"key": "second", "question": "Return beta", "answer": "beta", "meta": {"split": "test"}}),
            ])
            created = store.create({
                "id": "tiny_jsonl",
                "title": "Tiny JSONL",
                "format": "jsonl",
                "content": source,
                "mapping": {"id": "key", "prompt": "question", "expected": "answer", "metadata": "meta"},
            })

            self.assertEqual(created["row_count"], 2)
            self.assertEqual(store.list()[0]["id"], "tiny_jsonl")
            tasks = {item["id"]: item for item in load_task_specs(root / "task_bench" / "tasks")}
            first = tasks["tiny_jsonl__first"]
            self.assertEqual(first["prompt"], "Return alpha")
            self.assertEqual(first["evaluation"]["checks"][0]["value"], "alpha")
            self.assertEqual(first["dataset"]["metadata"]["split"], "test")

    def test_csv_preview_exposes_fields_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = DatasetStore(root)
            preview = store.preview({
                "format": "csv",
                "content": "id,prompt,expected\na,hello,world\n",
                "mapping": {"id": "id", "prompt": "prompt", "expected": "expected"},
            })
            self.assertEqual(preview["row_count"], 1)
            self.assertEqual(preview["fields"], ["expected", "id", "prompt"])
            self.assertEqual(preview["cases"][0]["expected"], "world")
            self.assertEqual(store.list(), [])

    def test_nested_mapping_and_typed_evaluation_template(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = DatasetStore(root)
            created = store.create({
                "id": "nested",
                "format": "json",
                "content": json.dumps([{
                    "case": {"id": "n1", "prompt": "Write answer.json", "expected": {"ready": True}},
                    "fixtures": {"input.txt": "hello"},
                }]),
                "mapping": {
                    "id": "case.id", "prompt": "case.prompt", "expected": "case.expected",
                    "workspace_files": "fixtures",
                },
                "evaluation_template": {
                    "pass_score": 1,
                    "checks": [{"type": "json_equals", "path": "answer.json", "pointer": "/ready", "expected": "${expected.ready}"}],
                },
            })
            task = json.loads((root / "task_bench" / "tasks" / f"{created['tasks'][0]}.json").read_text(encoding="utf-8"))
            self.assertIs(task["evaluation"]["checks"][0]["expected"], True)
            self.assertEqual(task["workspace"]["files"]["input.txt"], "hello")

    def test_rejects_unsafe_workspace_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            store = DatasetStore(Path(directory))
            with self.assertRaisesRegex(DatasetError, "unsafe workspace path"):
                store.preview({
                    "format": "json",
                    "content": json.dumps([{"prompt": "x", "files": {"../escape.txt": "bad"}}]),
                    "mapping": {"prompt": "prompt", "workspace_files": "files"},
                })

    def test_long_dataset_and_case_ids_get_stable_bounded_task_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            store = DatasetStore(Path(directory))
            created = store.create({
                "id": "dataset_" + "d" * 80,
                "format": "jsonl",
                "content": json.dumps({"id": "case_" + "c" * 84, "prompt": "hello"}),
                "mapping": {"id": "id", "prompt": "prompt"},
            })
            self.assertLessEqual(len(created["tasks"][0]), 96)
            self.assertRegex(created["tasks"][0], r"__[0-9a-f]{12}$")
            self.assertTrue((Path(directory) / "task_bench" / "tasks" / f"{created['tasks'][0]}.json").is_file())

    def test_overwrite_removes_owned_stale_tasks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = DatasetStore(root)
            initial = store.create({
                "id": "replaceable", "format": "jsonl",
                "content": '\n'.join((
                    json.dumps({"id": "keep", "prompt": "first"}),
                    json.dumps({"id": "remove", "prompt": "second"}),
                )),
                "mapping": {"id": "id", "prompt": "prompt"},
            })
            stale_path = root / "task_bench" / "tasks" / "replaceable__remove.json"
            self.assertTrue(stale_path.is_file())

            replaced = store.create({
                "id": "replaceable", "format": "jsonl", "overwrite": True,
                "content": json.dumps({"id": "keep", "prompt": "updated"}),
                "mapping": {"id": "id", "prompt": "prompt"},
            })

            self.assertEqual(initial["row_count"], 2)
            self.assertEqual(replaced["tasks"], ["replaceable__keep"])
            self.assertFalse(stale_path.exists())
            current = json.loads((root / "task_bench" / "tasks" / "replaceable__keep.json").read_text(encoding="utf-8"))
            self.assertEqual(current["prompt"], "updated")

    def test_invalid_defaults_do_not_create_partial_dataset(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = DatasetStore(root)
            with self.assertRaisesRegex(DatasetError, "tags must be a list"):
                store.create({
                    "id": "invalid", "format": "jsonl",
                    "content": json.dumps({"id": "one", "prompt": "hello"}),
                    "mapping": {"id": "id", "prompt": "prompt"},
                    "defaults": {"tags": "not-a-list"},
                })
            self.assertFalse((root / ".egoagent" / "datasets" / "invalid").exists())
            self.assertEqual(list((root / "task_bench" / "tasks").glob("invalid*.json")), [])


if __name__ == "__main__":
    unittest.main()
