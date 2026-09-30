import json
import tempfile
import time
import unittest
import sys
from pathlib import Path

from task_bench.engine import (
    CodexCliTaskRun,
    TaskBenchError,
    TaskBenchManager,
    evaluate_task,
    evolution_context_instructions,
    load_task_specs,
    _resolve_slot_identity,
)


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _task(task_id: str = "offline_write") -> dict:
    return {
        "version": "ego.task.v1",
        "id": task_id,
        "title": "Offline write",
        "description": "real deterministic DAG smoke task",
        "prompt": "Create the expected answer artifact.",
        "workspace": {"files": {}},
        "selection": {},
        "environment": {"backend": "local", "network": "disabled"},
        "execution": {"timeout_seconds": 15},
        "evolution": {"allowed": False},
        "evaluation": {
            "pass_score": 1,
            "checks": [
                {"type": "file_contains", "path": "answer.txt", "value": "task bench"},
                {"type": "node_visited", "node": "write"},
                {"type": "op_visited", "op": "工作区"},
            ],
        },
    }


def _identity(root: Path, name: str) -> None:
    _write_json(root / "identity" / name / "id.json", {
        "name": name,
        "role": "offline fixture agent",
        "llm": {"type": "dummy_llm", "mode": "scripted", "script": []},
    })


def _harness(root: Path, name: str, text: str = "task bench passed") -> None:
    _write_json(root / "harness" / name / "config.json", {
        "name": name,
        "description": "deterministic Task Bench integration harness",
        "slots": {},
        "prompts": {},
        "return_mode": "last",
        "pipeline": {
            "start": "write",
            "max_steps": 5,
            "workspace_preview": False,
            "nodes": {
                "write": {
                    "id": "write",
                    "op": "工作区",
                    "action": "write_text",
                    "path": "answer.txt",
                    "value": text,
                    "edges": [{"condition": "default", "to": "finish"}],
                },
                "finish": {"id": "finish", "op": "输出", "value": "done", "edges": []},
            },
        },
    })


def _waiting_harness(root: Path, name: str) -> None:
    _write_json(root / "harness" / name / "config.json", {
        "name": name,
        "description": "waits for a second interactive input",
        "slots": {}, "prompts": {}, "return_mode": "last",
        "pipeline": {
            "start": "initial", "max_steps": 3, "workspace_preview": False,
            "nodes": {
                "initial": {"id": "initial", "op": "输入", "edges": [{"condition": "input", "to": "wait"}]},
                "wait": {"id": "wait", "op": "输入", "reuse_last": False, "edges": []},
            },
        },
    })


def _recoverable_harness(root: Path, name: str) -> None:
    _write_json(root / "harness" / name / "config.json", {
        "name": name,
        "description": "checkpoint then finish without replaying the write",
        "slots": {}, "prompts": {}, "return_mode": "last",
        "pipeline": {
            "start": "write", "max_steps": 4, "workspace_preview": False,
            "checkpoint_dir": ".egoagent/checkpoints",
            "nodes": {
                "write": {
                    "id": "write", "op": "工作区", "action": "write_text",
                    "path": "answer.txt", "value": "task bench",
                    # The same recoverable Flow is exercised by every task
                    # episode.  Make the fixture write idempotent so a later
                    # episode tests checkpoint recovery rather than the
                    # Workspace node's safe no-overwrite default.
                    "overwrite": True,
                    "checkpoint": True, "checkpoint_label": "after-write",
                    "edges": [{"condition": "default", "to": "finish"}],
                },
                "finish": {"id": "finish", "op": "输出", "value": "done", "edges": []},
            },
        },
    })


class TaskBenchTests(unittest.TestCase):
    def test_codex_runner_projects_upstream_jsonl_into_common_traces(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            manager = TaskBenchManager(project, task_dir=project / "tasks", runs_dir=project / "runs")
            run = CodexCliTaskRun(manager, _task(), {
                "runner": "codex_cli", "harness": "original_codex",
                "harness_version": "resolved_at_run", "identity": "codex_native",
                "environments": [], "slot_bindings": {}, "ide_context": [],
            }, "auto")
            run._external_trace({
                "type": "item.completed",
                "item": {"id": "msg-1", "type": "agent_message", "text": "finished"},
            })
            run._external_trace({
                "type": "turn.completed",
                "usage": {"input_tokens": 9, "cached_input_tokens": 3, "output_tokens": 4},
            })
            run._external_trace({
                "type": "item.completed",
                "item": {"id": "cmd-1", "type": "command_execution", "command": "python -V", "status": "completed"},
            })
            run._external_trace({
                "type": "turn.completed",
                "usage": {"input_tokens": 2, "cached_input_tokens": 1, "output_tokens": 1},
            })
            self.assertEqual(run.state["node_traces"][0]["op"], "Model")
            self.assertEqual(run.state["node_traces"][0]["model"]["response"], "finished")
            self.assertEqual(run.state["outputs"][0]["agent"], "original_codex")
            self.assertEqual(run.state["stats"]["input_tokens"], 11)
            self.assertEqual(run.state["stats"]["output_tokens"], 5)
            self.assertEqual(run.state["stats"]["total_tokens"], 16)
            self.assertEqual(run.state["stats"]["model_calls"], 2)
            self.assertEqual(run.state["stats"]["tool_calls"], 1)
            run.state["started_at"] = 100.0
            self.assertEqual(run._record_elapsed_seconds(112.5), 12.5)
            self.assertEqual(run.state["stats"]["elapsed_seconds"], 12.5)

    def test_single_slot_uses_selected_identity_and_multi_slot_keeps_defaults(self):
        self.assertEqual(
            _resolve_slot_identity(
                {"evolver": {"identity": "dante"}}, "evolver", "coder", {}
            ),
            "coder",
        )
        slots = {
            "coder": {"identity": "coder"},
            "reviewer": {"identity": "sharp_critic"},
        }
        self.assertEqual(_resolve_slot_identity(slots, "reviewer", "dante", {}), "sharp_critic")
        self.assertEqual(
            _resolve_slot_identity(slots, "reviewer", "dante", {"reviewer": "privacy_guard"}),
            "privacy_guard",
        )

    def test_workspace_environment_is_listed_and_loadable(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "demo_project"
            task_dir = project / "task_bench" / "tasks"
            _write_json(task_dir / "offline_write.json", _task())
            _identity(project, "fixture")
            _harness(project, "writer")
            tool = project / ".environment" / "tools" / "demo_tool"
            _write_json(tool / "meta.json", {
                "type": "tool", "name": "demo_tool", "description": "workspace tool",
                "parameters": {"type": "object", "properties": {}},
            })
            script = tool / "scripts" / "demo_tool.py"
            script.parent.mkdir(parents=True, exist_ok=True)
            script.write_text("def demo_tool():\n    return 'ok'\n", encoding="utf-8")

            manager = TaskBenchManager(project, task_dir=task_dir, runs_dir=project / "runs")
            self.assertIn("demo_project", [item["name"] for item in manager.options()["environments"]])
            created = manager.start({
                "task_id": "offline_write", "harness": "writer", "identity": "fixture",
                "environments": ["demo_project"],
            })
            state = self._wait(manager, created["id"])
            self.assertEqual(state["status"], "passed", state.get("error"))

    def test_evolution_context_is_generic_and_requires_real_installation(self):
        disabled = evolution_context_instructions("dante", {"allowed": False})
        enabled = evolution_context_instructions(
            "dante",
            {"allowed": True, "targets": ["identity", "harness", "skill"]},
            ["create_agent_system", "create_harness"],
        )
        self.assertNotIn("Governed evolution", disabled)
        self.assertIn("Governed evolution is enabled", enabled)
        self.assertIn("actually install the artifact", enabled)
        self.assertIn("not an installed evolution", enabled)
        self.assertIn("create_agent_system", enabled)
        self.assertIn("select_evolution_artifact", enabled)
        self.assertIn("does not disable the governed mutation tools", enabled)
        self.assertIn("confirmed these mutation tools are callable", enabled)
        self.assertIn("`create_harness`", enabled)
        self.assertNotIn("evaluation", enabled.lower())

    def test_task_spec_loader_rejects_workspace_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = _task()
            task["workspace"]["files"] = {"../outside.txt": "bad"}
            _write_json(root / "bad.json", task)
            with self.assertRaisesRegex(TaskBenchError, "unsafe fixture path"):
                load_task_specs(root)

    def test_task_spec_loader_rejects_json_equals_without_expected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = _task("bad_json_check")
            task["evaluation"]["checks"] = [
                {"type": "json_equals", "path": "answer.json", "pointer": "/ok", "value": True}
            ]
            _write_json(root / "bad_json_check.json", task)
            with self.assertRaisesRegex(TaskBenchError, "requires expected"):
                load_task_specs(root)

    def test_weighted_evaluator_uses_files_json_traces_and_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "answer.txt").write_text("Hello Task Bench", encoding="utf-8")
            _write_json(root / "answer.json", {"ready": True})
            spec = _task()
            spec["evaluation"] = {
                "pass_score": 1,
                "checks": [
                    {"id": "text", "type": "file_contains", "path": "answer.txt", "value": "Task Bench", "weight": 2},
                    {"id": "json", "type": "json_equals", "path": "answer.json", "pointer": "/ready", "expected": True},
                    {"id": "node", "type": "node_visited", "node": "agent"},
                    {"id": "tool", "type": "tool_called", "name": "read_file"},
                ],
            }
            result = evaluate_task(spec, root, traces=[{
                "node_id": "agent", "op": "Agent", "tools": [{"name": "read_file"}],
            }])
            self.assertTrue(result["passed"])
            self.assertEqual(result["score"], 1)
            self.assertTrue(all(check["passed"] for check in result["checks"]))

    def test_command_evaluator_runs_without_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec = _task()
            spec["evaluation"] = {"pass_score": 1, "checks": [{
                "id": "command", "type": "command",
                "command": [sys.executable, "-c", "from pathlib import Path; assert Path('marker.txt').read_text() == 'ok'"],
            }]}
            (root / "marker.txt").write_text("ok", encoding="utf-8")
            result = evaluate_task(spec, root)
            self.assertTrue(result["passed"], result)
            self.assertEqual(result["checks"][0]["details"]["exit_code"], 0)

    def test_response_not_contains_supports_confidentiality_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            spec = _task()
            spec["evaluation"] = {"pass_score": 1, "checks": [
                {"type": "response_not_contains", "value": "sk-private-token"},
                {"type": "response_contains", "value": "REDACTED"},
            ]}
            result = evaluate_task(
                spec,
                Path(directory),
                messages=[{"role": "assistant", "content": "Token: [REDACTED]"}],
            )
            self.assertTrue(result["passed"], result)
            self.assertTrue(all(check["passed"] for check in result["checks"]))

    def test_real_task_runner_isolated_across_harness_identity_combinations(self):
        for harness_name, identity_name in (("writer_linear", "fixture_alpha"), ("writer_compact", "fixture_beta")):
            with self.subTest(harness=harness_name, identity=identity_name), tempfile.TemporaryDirectory() as directory:
                project = Path(directory) / "project"
                task_dir = project / "task_bench" / "tasks"
                run_dir = project / ".egoagent" / "task_runs"
                _write_json(task_dir / "offline_write.json", _task())
                _identity(project, identity_name)
                _harness(project, harness_name)
                manager = TaskBenchManager(project, task_dir=task_dir, runs_dir=run_dir)
                created = manager.start({
                    "task_id": "offline_write", "harness": harness_name,
                    "identity": identity_name, "debug_mode": "auto",
                })
                state = self._wait(manager, created["id"])
                self.assertEqual(state["status"], "passed", state.get("error"))
                self.assertEqual(state["evaluation"]["score"], 1)
                self.assertEqual(state["selection"]["harness"], harness_name)
                self.assertEqual(state["selection"]["identity"], identity_name)
                self.assertEqual([trace["node_id"] for trace in state["node_traces"]], ["write", "finish"])
                self.assertEqual([step["status"] for step in state["task_steps"]], ["passed"])
                self.assertIsNotNone(state["task_steps"][0]["completed_at"])
                self.assertEqual(state["task_steps"][0]["evaluation"]["score"], 1)
                self.assertIn(run_dir.resolve(), Path(state["workspace"]).resolve().parents)
                self.assertEqual((Path(state["workspace"]) / "answer.txt").read_text(encoding="utf-8"), "task bench passed")

    def test_run_comparison_keeps_exact_flow_versions_and_aligned_traces(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            task_dir = project / "task_bench" / "tasks"
            _write_json(task_dir / "offline_write.json", _task())
            _identity(project, "fixture")
            _harness(project, "writer")
            manager = TaskBenchManager(project, task_dir=task_dir, runs_dir=project / "runs")
            first = self._wait(manager, manager.start({
                "task_id": "offline_write", "harness": "writer", "identity": "fixture",
            })["id"])
            second = self._wait(manager, manager.start({
                "task_id": "offline_write", "harness": "writer", "identity": "fixture",
            })["id"])
            compared = manager.compare_runs([first["id"], second["id"]])
            self.assertEqual(compared["schema"], "ego.task-run-comparison.v1")
            self.assertTrue(compared["same_task"])
            self.assertEqual(len(compared["runs"]), 2)
            self.assertTrue(all(item["harness_version"].startswith("v") for item in compared["runs"]))
            self.assertEqual([row["diverged"] for row in compared["trace_rows"]], [False, False])

    def test_ide_context_is_copied_into_run_without_leaking_content_in_public_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            task_dir = project / "task_bench" / "tasks"
            _write_json(task_dir / "offline_write.json", _task())
            _identity(project, "fixture")
            _harness(project, "writer")
            manager = TaskBenchManager(project, task_dir=task_dir, runs_dir=project / "runs")
            attached_content = "def attached():\n    return 'immutable'\n"
            created = manager.start({
                "task_id": "offline_write",
                "harness": "writer",
                "identity": "fixture",
                "ide_context": [{
                    "kind": "selection",
                    "path": str(project / "src" / "example.py"),
                    "relativePath": "src/example.py",
                    "language": "python",
                    "startLine": 3,
                    "endLine": 4,
                    "content": attached_content,
                }],
            })
            state = self._wait(manager, created["id"])
            public_context = state["selection"]["ide_context"][0]
            self.assertNotIn("content", public_context)
            self.assertEqual(public_context["content_bytes"], len(attached_content.encode("utf-8")))
            manifest = state["ide_context"][0]
            self.assertEqual(manifest["kind"], "selection")
            self.assertEqual(manifest["start_line"], 3)
            attached = Path(state["workspace"]) / manifest["relative_path"]
            self.assertEqual(attached.read_text(encoding="utf-8"), attached_content)

    def test_ide_context_limits_are_enforced_before_a_run_is_created(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            task_dir = project / "task_bench" / "tasks"
            _write_json(task_dir / "offline_write.json", _task())
            manager = TaskBenchManager(project, task_dir=task_dir, runs_dir=project / "runs")
            with self.assertRaisesRegex(TaskBenchError, "at most 20"):
                manager.start({
                    "task_id": "offline_write",
                    "ide_context": [{"content": "x"} for _ in range(21)],
                })

    def test_task_runner_pauses_before_first_side_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            task_dir = project / "task_bench" / "tasks"
            _write_json(task_dir / "offline_write.json", _task())
            _identity(project, "fixture")
            _harness(project, "writer")
            manager = TaskBenchManager(project, task_dir=task_dir, runs_dir=project / "runs")
            created = manager.start({"task_id": "offline_write", "harness": "writer", "identity": "fixture", "debug_mode": "paused"})
            state = self._wait_for(manager, created["id"], lambda item: item["paused"])
            workspace = Path(state["workspace"])
            self.assertEqual(state["pending_node"], "write")
            self.assertFalse((workspace / "answer.txt").exists())
            manager.control(created["id"], "step")
            state = self._wait_for(manager, created["id"], lambda item: item["paused"] and item["pending_node"] == "finish")
            self.assertTrue((workspace / "answer.txt").exists())
            self.assertEqual(state["pending_node"], "finish")
            manager.control(created["id"], "auto")
            self.assertEqual(self._wait(manager, created["id"])["status"], "passed")

    def test_task_timeout_interrupts_a_node_waiting_for_input(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            task_dir = project / "task_bench" / "tasks"
            task = _task()
            task["execution"]["timeout_seconds"] = 1
            task["execution"]["interactive"] = True
            _write_json(task_dir / "offline_write.json", task)
            _identity(project, "fixture")
            _waiting_harness(project, "waiter")
            manager = TaskBenchManager(project, task_dir=task_dir, runs_dir=project / "runs")
            created = manager.start({"task_id": "offline_write", "harness": "waiter", "identity": "fixture"})
            state = self._wait(manager, created["id"], timeout=4)
            self.assertEqual(state["status"], "timeout")
            self.assertIn("exceeded", state["error"])

    def test_stopped_task_recovers_in_new_workspace_without_replaying_completed_write(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            task_dir = project / "task_bench" / "tasks"
            task = _task("checkpoint_recovery")
            task["evaluation"] = {
                "pass_score": 1,
                "checks": [{"type": "file_contains", "path": "answer.txt", "value": "task bench"}],
            }
            _write_json(task_dir / "checkpoint_recovery.json", task)
            _identity(project, "fixture")
            _recoverable_harness(project, "recoverable")
            manager = TaskBenchManager(project, task_dir=task_dir, runs_dir=project / "runs")

            created = manager.start({
                "task_id": "checkpoint_recovery", "harness": "recoverable",
                "identity": "fixture", "debug_mode": "paused",
            })
            first_pause = self._wait_for(manager, created["id"], lambda item: item["paused"])
            self.assertEqual(first_pause["pending_node"], "write")
            manager.control(created["id"], "step")
            after_write = self._wait_for(
                manager, created["id"],
                lambda item: item["paused"] and item["pending_node"] == "finish",
            )
            source_workspace = Path(after_write["workspace"])
            self.assertEqual((source_workspace / "answer.txt").read_text(encoding="utf-8"), "task bench")
            manager.control(created["id"], "stop")
            stopped = self._wait(manager, created["id"])
            self.assertEqual(stopped["status"], "stopped")
            history_item = next(item for item in manager.list_runs() if item["id"] == created["id"])
            self.assertTrue(history_item["recovery_available"])
            tampered = json.loads(json.dumps(stopped))
            tampered["workspace"] = str(project)
            with self.assertRaisesRegex(TaskBenchError, "confined Task run directory"):
                manager._recovery_checkpoint(tampered)

            recovered = manager.recover(created["id"])
            finished = self._wait(manager, recovered["id"])
            recovered_workspace = Path(finished["workspace"])
            self.assertEqual(finished["status"], "passed", finished.get("error"))
            self.assertNotEqual(recovered_workspace, source_workspace)
            self.assertEqual((recovered_workspace / "answer.txt").read_text(encoding="utf-8"), "task bench")
            self.assertEqual([trace["node_id"] for trace in finished["node_traces"]], ["finish"])
            self.assertEqual(finished["recovery"]["source_run_id"], created["id"])
            self.assertEqual(finished["recovery"]["source_step"], "main")
            self.assertTrue(any(event["type"] == "resumed" for event in finished["events"]))

    def test_multistep_recovery_inherits_completed_step_scores(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            task_dir = project / "task_bench" / "tasks"
            task = _task("multistep_recovery")
            task["steps"] = [
                {
                    "id": step_id, "title": step_id, "prompt": f"complete {step_id}",
                    "workspace": {"files": {}}, "resume_trajectory": False,
                    "evaluation": {
                        "pass_score": 1,
                        "checks": [{"type": "file_contains", "path": "answer.txt", "value": "task bench"}],
                    },
                }
                for step_id in ("one", "two")
            ]
            _write_json(task_dir / "multistep_recovery.json", task)
            _identity(project, "fixture")
            _recoverable_harness(project, "recoverable")
            manager = TaskBenchManager(project, task_dir=task_dir, runs_dir=project / "runs")

            created = manager.start({
                "task_id": "multistep_recovery", "harness": "recoverable",
                "identity": "fixture", "debug_mode": "paused",
            })
            self._wait_for(manager, created["id"], lambda item: item["paused"] and item["task_step"] == "one")
            manager.control(created["id"], "step")
            self._wait_for(manager, created["id"], lambda item: item["paused"] and item["pending_node"] == "finish")
            manager.control(created["id"], "step")
            self._wait_for(manager, created["id"], lambda item: item["paused"] and item["task_step"] == "two" and item["pending_node"] == "write")
            manager.control(created["id"], "step")
            self._wait_for(manager, created["id"], lambda item: item["paused"] and item["task_step"] == "two" and item["pending_node"] == "finish")
            manager.control(created["id"], "stop")
            stopped = self._wait(manager, created["id"])
            self.assertEqual([step["status"] for step in stopped["task_steps"]], ["passed", "stopped"])
            checkpoint_steps = sorted(
                str(((json.loads(path.read_text(encoding="utf-8")).get("data") or {}).get("task") or {}).get("step"))
                for path in (Path(stopped["workspace"]) / ".egoagent" / "checkpoints").glob("*.json")
                if json.loads(path.read_text(encoding="utf-8")).get("phase", "completed") == "completed"
            )
            self.assertEqual(
                checkpoint_steps,
                ["one", "two"],
                {
                    "traces": [(trace["node_id"], trace["status"]) for trace in stopped["node_traces"]],
                    "checkpoints": [event["data"] for event in stopped["events"] if event["type"] == "checkpoint"],
                },
            )

            recovered = self._wait(manager, manager.recover(created["id"])["id"])
            self.assertEqual(recovered["status"], "passed", recovered.get("error"))
            self.assertEqual([step["status"] for step in recovered["task_steps"]], ["passed", "passed"])
            self.assertEqual(recovered["evaluation"]["score"], 1.0)
            self.assertTrue(recovered["evaluation"]["passed"])
            self.assertEqual(recovered["recovery"]["inherited_steps"], 1, recovered["recovery"])
            self.assertEqual([trace["node_id"] for trace in recovered["node_traces"]], ["finish"])

    def test_react_style_task_finishes_after_first_model_answer(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            task_dir = project / "task_bench" / "tasks"
            task = _task("one_shot_react")
            task["evaluation"] = {
                "pass_score": 1,
                "checks": [{"type": "response_contains", "value": "finished"}],
            }
            _write_json(task_dir / "one_shot_react.json", task)
            _write_json(project / "identity" / "fixture" / "id.json", {
                "name": "fixture",
                "role": "offline fixture agent",
                "llm": {
                    "type": "dummy_llm", "mode": "scripted",
                    "script": [{"response": "finished"}],
                },
            })
            _write_json(project / "harness" / "react" / "config.json", {
                "name": "react", "slots": {"agent": {"required": True}}, "prompts": {},
                "pipeline": {
                    "start": "input", "max_steps": 5, "workspace_preview": False,
                    "nodes": {
                        "input": {"op": "输入", "edges": [{"condition": "input", "to": "infer"}]},
                        "infer": {"op": "推理", "agent": "agent", "edges": [{"condition": "has_text", "to": "input"}]},
                    },
                },
            })
            manager = TaskBenchManager(project, task_dir=task_dir, runs_dir=project / "runs")
            created = manager.start({"task_id": "one_shot_react", "harness": "react", "identity": "fixture"})
            state = self._wait(manager, created["id"], timeout=3)
            self.assertEqual(state["status"], "passed", state.get("error"))
            self.assertLess(state["completed_at"] - state["started_at"], 2)

    def test_tool_policy_survives_harness_workspace_reinitialization(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            task_dir = project / "task_bench" / "tasks"
            task = _task("policy_reload")
            task["evaluation"] = {
                "pass_score": 1,
                "checks": [{"type": "response_contains", "value": "finished"}],
            }
            _write_json(task_dir / "policy_reload.json", task)
            identity = project / "identity" / "fixture"
            _write_json(identity / "id.json", {
                "name": "fixture", "role": "offline fixture agent",
                "llm": {"type": "dummy_llm", "mode": "scripted", "script": [
                    {"response": "", "tool_calls": [{
                        "id": "1", "type": "function",
                        "function": {"name": "design_harness", "arguments": "{}"},
                    }]},
                    {"response": "finished", "tool_calls": []},
                ]},
            })
            _write_json(identity / "ego" / "skills" / "danger" / "meta.json", {
                "type": "tool", "name": "design_harness", "description": "must be hidden",
                "parameters": {"type": "object", "properties": {}},
            })
            script = identity / "ego" / "skills" / "danger" / "scripts" / "design_harness.py"
            script.parent.mkdir(parents=True, exist_ok=True)
            script.write_text(
                "from pathlib import Path\n"
                "def design_harness():\n"
                "    Path('policy_bypassed.txt').write_text('bad', encoding='utf-8')\n"
                "    return 'bad'\n",
                encoding="utf-8",
            )
            _write_json(project / "harness" / "react" / "config.json", {
                "name": "react", "slots": {"agent": {"required": True}}, "prompts": {},
                "pipeline": {"start": "input", "max_steps": 8, "workspace_preview": False, "nodes": {
                    "input": {"op": "输入", "edges": [{"condition": "input", "to": "infer"}]},
                    "infer": {"op": "推理", "agent": "agent", "edges": [
                        {"condition": "has_tool_calls", "to": "tools"},
                        {"condition": "has_text", "to": "input"},
                    ]},
                    "tools": {"op": "执行工具", "agent": "agent", "edges": [{"condition": "default", "to": "infer"}]},
                }},
            })
            manager = TaskBenchManager(project, task_dir=task_dir, runs_dir=project / "runs")
            created = manager.start({"task_id": "policy_reload", "harness": "react", "identity": "fixture"})
            state = self._wait(manager, created["id"], timeout=3)
            self.assertEqual(state["status"], "passed", state.get("error"))
            self.assertFalse((Path(state["workspace"]) / "policy_bypassed.txt").exists())
            self.assertIn("design_harness", state["policy"]["hidden_tools"])

    def _wait(self, manager: TaskBenchManager, run_id: str, timeout: float = 10):
        return self._wait_for(manager, run_id, lambda state: not state["running"], timeout)

    def _wait_for(self, manager: TaskBenchManager, run_id: str, predicate, timeout: float = 10):
        deadline = time.time() + timeout
        state = manager.get(run_id)
        while not predicate(state) and time.time() < deadline:
            time.sleep(0.02)
            state = manager.get(run_id)
        self.assertTrue(predicate(state), state)
        return state


if __name__ == "__main__":
    unittest.main()
