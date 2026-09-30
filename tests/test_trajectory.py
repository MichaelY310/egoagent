import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from harness import Session
from message_protocol import compose_model_messages
from pipeline_engine import RunContext
from trajectory import (
    TrajectoryReader,
    TrajectoryRecorder,
    export_training_data,
    save_collection_settings,
)
from runtime_contracts import capability_descriptor, missing_model_provider_members
from subagent_lifecycle import finish_subagent, link_subagent


class TrajectoryRecorderTests(unittest.TestCase):
    def test_nested_subflow_event_is_persisted_once_and_forwarded_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = Session(workspace=root, save_dir=root / "session")
            public_events = []

            def harness(name):
                return SimpleNamespace(
                    name=name, workspace=root, dir=root, session=session, agents={},
                    config={"pipeline": {"nodes": {"apply": {"op": "上下文"}}}},
                )

            root_ctx = RunContext(
                harness=harness("root"), graph={"nodes": {"apply": {"op": "上下文"}}},
                on_output=lambda event, payload: public_events.append((event, payload)),
                get_input=lambda: None, is_running=lambda: True,
            )
            child_ctx = RunContext(
                harness=harness("child"), graph={"nodes": {"apply": {"op": "上下文"}}},
                on_output=lambda event, payload: root_ctx.emit(event, {**payload, "subflow": "child"}),
                get_input=lambda: None, is_running=lambda: True, parent=root_ctx,
            )
            grandchild_ctx = RunContext(
                harness=harness("grandchild"), graph={"nodes": {"apply": {"op": "上下文"}}},
                on_output=lambda event, payload: child_ctx.emit(event, {**payload, "subflow": "grandchild"}),
                get_input=lambda: None, is_running=lambda: True, parent=child_ctx,
            )
            grandchild_ctx.current_node = "apply"
            grandchild_ctx.emit("conversation_applied", {"mode": "tool_prune", "saved_tokens_estimated": 100})

            events = TrajectoryReader(root / "session" / "trajectory.jsonl").read_all()
            matching = [
                item for item in events
                if item["type"] == "runtime.event"
                and (item.get("data") or {}).get("event") == "conversation_applied"
            ]
            self.assertEqual(len(matching), 1)
            self.assertEqual(matching[0]["harness"], "grandchild")
            self.assertEqual(len(public_events), 1)
            self.assertNotIn("_egoagent_trajectory_recorded", public_events[0][1])

    def test_provider_request_has_one_system_prefix_after_compaction(self):
        messages = compose_model_messages(
            "identity and workspace instructions",
            [
                {"role": "system", "name": "context_summary", "content": "compressed facts"},
                {"role": "user", "content": "continue"},
            ],
        )
        self.assertEqual([message["role"] for message in messages], ["system", "user"])
        self.assertIn("identity and workspace instructions", messages[0]["content"])
        self.assertIn("[context_summary]", messages[0]["content"])
        self.assertIn("compressed facts", messages[0]["content"])

    def test_exact_model_surface_survives_context_replacement_and_export(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = Session(workspace=root, save_dir=root / "session")
            old_user = {"role": "user", "content": "a very long original request"}
            old_answer = {"role": "assistant", "name": "coder", "content": "old analysis"}
            session.record(old_user)
            session.record_full(dict(old_user))
            session.record(old_answer)
            session.record_full(dict(old_answer))
            summary = {
                "role": "assistant",
                "name": "context_summary",
                "content": "summary of the original request and current state",
            }
            session.apply_context_result({
                "messages": [summary],
                "full_messages": [old_user, old_answer],
                "ledger": [{"action": "summarize", "summary": summary["content"]}],
                "stats": {"before_tokens_estimated": 100, "after_tokens_estimated": 20},
            })
            exact_view = [
                {"role": "system", "content": "You are the coder."},
                summary,
                {"role": "user", "content": "continue"},
            ]
            call_id = session.begin_model_call(
                messages=exact_view,
                tools=[{"type": "function", "function": {"name": "read_file"}}],
                agent="coder",
                model="tiny-model",
                provider="dummy",
                parameters={"stream": True},
                purpose="agent_step",
            )
            session.finish_model_call(
                call_id,
                agent="coder",
                content="continued answer",
                finish_reason="stop",
                usage={"prompt_tokens": 12, "completion_tokens": 3},
            )
            session.save()

            path = root / "session" / "trajectory.jsonl"
            reader = TrajectoryReader(path)
            validation = reader.validate()
            self.assertTrue(validation["valid"], validation)
            calls = reader.model_calls()
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]["messages"], exact_view)
            self.assertIn("summary of the original", json.dumps(calls[0]["messages"]))
            self.assertNotIn("old analysis", json.dumps(calls[0]["messages"]))
            replacement = next(
                event for event in reader.read_all()
                if event["type"] == "conversation.surface.replace"
            )
            self.assertEqual(replacement["data"]["after_messages"], [summary])

            manifest = export_training_data(path, root / "export")
            self.assertEqual(manifest["exported_model_calls"], 1)
            sharegpt = json.loads((root / "export" / "llamafactory_sharegpt.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(sharegpt["metadata"]["agent"], "coder")
            self.assertEqual(sharegpt["conversations"][-1]["value"], "continued answer")
            verl = json.loads((root / "export" / "verl_rollouts.jsonl").read_text(encoding="utf-8"))
            self.assertIsNone(verl["reward"])
            self.assertEqual(verl["prompt"], exact_view)
            otel = json.loads((root / "export" / "otel_genai_trace.json").read_text(encoding="utf-8"))
            spans = otel["resourceSpans"][0]["scopeSpans"][0]["spans"]
            model_span = next(span for span in spans if span["name"].startswith("chat "))
            attributes = {item["key"]: item["value"] for item in model_span["attributes"]}
            self.assertEqual(attributes["gen_ai.request.model"]["stringValue"], "tiny-model")
            self.assertEqual(
                attributes["gen_ai.response.finish_reasons"]["arrayValue"]["values"][0]["stringValue"],
                "stop",
            )
            input_messages = attributes["gen_ai.input.messages"]["arrayValue"]["values"]
            self.assertIn("kvlistValue", input_messages[0])
            self.assertIn("opentelemetry_otlp_json", manifest["files"])

    def test_child_sessions_share_one_ordered_root_trace_without_mixing_agents(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = Session(workspace=root, save_dir=root / "parent")
            child = Session(workspace=root, save_dir=None)
            child.attach_trajectory(parent.trajectory)
            first = parent.begin_model_call(
                messages=[{"role": "user", "content": "parent"}], tools=[], agent="planner",
                model="m", provider="dummy", purpose="agent_step",
            )
            second = child.begin_model_call(
                messages=[{"role": "user", "content": "child"}], tools=[], agent="researcher",
                model="m", provider="dummy", purpose="subagent",
            )
            child.finish_model_call(second, agent="researcher", content="child result")
            parent.finish_model_call(first, agent="planner", content="parent result")

            reader = TrajectoryReader(root / "parent" / "trajectory.jsonl")
            events = reader.read_all()
            self.assertEqual([event["sequence"] for event in events], list(range(1, len(events) + 1)))
            calls = reader.model_calls()
            self.assertEqual({call["metadata"]["agent"] for call in calls}, {"planner", "researcher"})
            by_agent = {call["metadata"]["agent"]: call for call in calls}
            self.assertEqual(by_agent["planner"]["response"]["content"], "parent result")
            self.assertEqual(by_agent["researcher"]["response"]["content"], "child result")

    def test_optional_mirror_tracks_same_event_ids(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings_path = root / "settings.json"
            destination = root / "training-collection"
            with patch("trajectory.SETTINGS_PATH", settings_path):
                save_collection_settings(enabled=True, destination=str(destination), path=settings_path)
                recorder = TrajectoryRecorder(root / "native" / "trajectory.jsonl", project_name="demo")
                event = recorder.append("test.event", {"value": 1})
                mirror = recorder.location.mirror_path
                self.assertIsNotNone(mirror)
                native_event = TrajectoryReader(root / "native" / "trajectory.jsonl").read_all()[0]
                mirror_event = TrajectoryReader(mirror).read_all()[0]
                self.assertEqual(native_event["event_id"], event["event_id"])
                self.assertEqual(mirror_event["event_id"], event["event_id"])

    def test_invalid_integrity_is_reported(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "trajectory.jsonl"
            recorder = TrajectoryRecorder(path)
            recorder.append("test.event", {"value": 1})
            event = json.loads(path.read_text(encoding="utf-8"))
            event["data"]["value"] = 2
            path.write_text(json.dumps(event) + "\n", encoding="utf-8")
            validation = TrajectoryReader(path).validate()
            self.assertFalse(validation["valid"])
            self.assertTrue(any("integrity" in error for error in validation["errors"]))

    def test_typed_event_contract_and_session_health_are_persisted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            location = root / "session"
            session = Session(workspace=root, save_dir=location)
            session.record({"role": "user", "content": "solve this"})
            call_id = session.begin_model_call(
                messages=[{"role": "user", "content": "solve this"}],
                tools=[],
                agent="coder",
                model="fake",
                provider="test",
            )
            session.finish_model_call(call_id, agent="coder", content="done")
            session.save()

            events = TrajectoryReader(location / "trajectory.jsonl").read_all()
            request = next(event for event in events if event["type"] == "model.request")
            self.assertEqual(request["event_version"], 1)
            self.assertEqual(request["category"], "model")
            health = TrajectoryReader(location / "trajectory.jsonl").health()
            self.assertTrue(health.replayable)
            self.assertTrue(health.training_ready)
            persisted = json.loads((location / "session.json").read_text(encoding="utf-8"))
            self.assertTrue(persisted["health"]["training_ready"])

    def test_incomplete_model_call_is_replayable_but_not_training_ready(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = Session(workspace=root, save_dir=root / "session")
            session.begin_model_call(
                messages=[{"role": "user", "content": "interrupted"}],
                tools=[],
                agent="coder",
                model="fake",
                provider="test",
            )
            health = TrajectoryReader(root / "session" / "trajectory.jsonl").health()
            self.assertEqual(health.status, "incomplete")
            self.assertTrue(health.replayable)
            self.assertFalse(health.training_ready)
            self.assertTrue(any("terminal event" in item for item in health.blockers))

    def test_valid_event_projection_wins_over_corrupt_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            location = root / "session"
            session = Session(workspace=root, save_dir=location)
            session.record({"role": "user", "content": "truth from events"})
            session.record_full({"role": "user", "content": "truth from events"})
            session.save()
            (location / "messages.json").write_text(
                json.dumps([{"role": "user", "content": "corrupt cache"}]), encoding="utf-8"
            )

            restored = Session(workspace=root, save_dir=None)
            restored.load(location)
            self.assertEqual(restored.messages[0]["content"], "truth from events")
            self.assertEqual(restored.trajectory.trace_id, session.trajectory.trace_id)

    def test_event_only_session_is_portable_and_continues_same_trace(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            location = root / "session"
            session = Session(workspace=root, save_dir=location)
            session.record({"role": "user", "content": "recover without snapshots"})
            session.record_full({"role": "user", "content": "recover without snapshots"})
            original_session_id = session.session_id
            original_trace_id = session.trajectory.trace_id
            original_count = session.trajectory.event_count

            restored = Session(workspace=root, save_dir=None)
            restored.load(location)
            self.assertEqual(restored.session_id, original_session_id)
            self.assertEqual(restored.trajectory.trace_id, original_trace_id)
            self.assertEqual(len(restored.messages), 1)
            self.assertEqual(restored.messages[0]["role"], "user")
            self.assertEqual(restored.messages[0]["content"], "recover without snapshots")
            restored.record({"role": "assistant", "content": "continued"})

            events = TrajectoryReader(location / "trajectory.jsonl").read_all()
            self.assertEqual(events[-1]["sequence"], original_count + 1)
            self.assertEqual(events[-1]["session_id"], original_session_id)

    def test_subagent_lifecycle_is_one_trace_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = SimpleNamespace(
                name="parent", workspace=root, children=[], agents={},
                session=Session(workspace=root, save_dir=root / "parent"),
            )
            identity = SimpleNamespace(identity_path=root / "identity" / "researcher")
            child = SimpleNamespace(
                name="child", workspace=root, children=[],
                agents={"researcher": SimpleNamespace(name="researcher", identity=identity)},
                session=Session(workspace=root, save_dir=root / "child"), parent=None,
            )
            invocation = link_subagent(parent, child, purpose="test")
            child.session.record({"role": "user", "content": "child input"})
            first = finish_subagent(child, status="completed", result={"answer": 1})
            second = finish_subagent(child, status="failed", error="must not overwrite completion")
            self.assertEqual(first, second)
            self.assertEqual(first.invocation_id, invocation.invocation_id)

            events = TrajectoryReader(root / "parent" / "trajectory.jsonl").read_all()
            self.assertEqual(sum(event["type"] == "subagent.spawned" for event in events), 1)
            self.assertEqual(sum(event["type"] == "subagent.completed" for event in events), 1)
            child_append = next(event for event in events if event["type"] == "conversation.working.append")
            self.assertEqual(child_append["session_id"], child.session.session_id)

    def test_model_provider_contract_is_structural(self):
        class Provider:
            model = "tiny"
            last_response_metadata = {}
            def chat(self, messages, tools=None, **parameters):
                return {"choices": [{"message": {"content": "ok"}}]}
            def chat_stream(self, messages, tools=None, **parameters):
                yield {"content": "ok"}

        self.assertEqual(missing_model_provider_members(Provider()), [])
        self.assertTrue(capability_descriptor(Provider())["conforms"])

    def test_secret_like_values_are_redacted_before_native_and_mirror_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "trajectory.jsonl"
            recorder = TrajectoryRecorder(path)
            recorder.append("model.request", {
                "messages": [{"role": "user", "content": "use sk-abcdefghijklmnopqrstuv"}],
                "tools": [],
                "api_key": "top-secret-value",
            }, model_call_id="call_secret")
            raw = path.read_text(encoding="utf-8")
            self.assertNotIn("sk-abcdefghijklmnopqrstuv", raw)
            self.assertNotIn("top-secret-value", raw)
            event = TrajectoryReader(path).read_all()[0]
            self.assertGreaterEqual(event["redaction"]["count"], 2)
            self.assertTrue(TrajectoryReader(path).validate()["valid"])


if __name__ == "__main__":
    unittest.main()
