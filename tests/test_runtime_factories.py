import tempfile
import unittest
from pathlib import Path

from agent_factory import AgentFactory, AgentFactoryError
from model_gateway import ModelGateway, ModelGatewayError
from runtime_contracts import ToolExecutionRequest
from tool_pipeline import AgentToolExecutor
from pipeline_engine import _clone_agent_for_slot


ROOT = Path(__file__).resolve().parent.parent


class FakeProvider:
    model = "fake-model"
    last_response_metadata = {}

    def chat(self, messages, tools=None, **parameters):
        return {"choices": [{"message": {"content": "ok"}}]}

    def chat_stream(self, messages, tools=None, **parameters):
        yield {"choices": [{"delta": {"content": "ok"}}]}


class FakeAgent:
    name = "coder"

    def __init__(self):
        self.calls = []

    def execute_tool_call(self, call, **options):
        self.calls.append((call, options))
        return {"ok": True, "path": "result.txt"}


class RuntimeFactoryTests(unittest.TestCase):
    def test_subflow_slot_clone_rebinds_tool_executor_and_runtime_context(self):
        class CloneableAgent:
            name = "governor"
            llm = FakeProvider()

            def __init__(self):
                self._runtime_context = {"agent_name": self.name, "agent": self}
                self.tool_executor = AgentToolExecutor(self)

            def execute_tool_call(self, call, **_options):
                return {"ok": True, "name": call["function"]["name"]}

        parent = CloneableAgent()
        child = _clone_agent_for_slot(parent, "searcher")
        result = child.tool_executor.execute(ToolExecutionRequest(
            name="read_file", arguments={}, call_id="call-1", agent="searcher"
        ))

        self.assertEqual(result.status, "ok")
        self.assertEqual(child.name, "searcher")
        self.assertIs(child.tool_executor.agent, child)
        self.assertEqual(child._runtime_context["agent_name"], "searcher")
        self.assertIs(child._runtime_context["agent"], child)
        self.assertEqual(parent.name, "governor")

    def test_model_gateway_is_the_provider_conformance_boundary(self):
        gateway = ModelGateway(provider_factory=lambda config: FakeProvider())
        provider = gateway.create({"provider": "fake", "model": "fake-model"})
        self.assertEqual(provider.model, "fake-model")
        self.assertTrue(gateway.describe(provider)["conforms"])
        with self.assertRaises(ModelGatewayError):
            gateway.validate(object())

    def test_agent_factory_confines_identity_and_wires_runtime_services(self):
        factory = AgentFactory(identity_roots=(ROOT / "identity",))
        provider = FakeProvider()
        agent = factory.create("dante", name="coder", workspace=ROOT, model_provider=provider)
        self.assertIs(agent.llm, provider)
        self.assertIs(agent.runtime_services.model, provider)
        self.assertIs(agent.runtime_services.tools, agent.tool_executor)
        with tempfile.TemporaryDirectory() as outside:
            with self.assertRaises(AgentFactoryError):
                factory.resolve_identity(Path(outside))

    def test_tool_executor_preserves_raw_call_and_returns_typed_result(self):
        agent = FakeAgent()
        executor = AgentToolExecutor(agent)
        raw_call = {
            "id": "call-1",
            "type": "function",
            "function": {"name": "write_file", "arguments": '{"file_path":"result.txt"}'},
        }
        result = executor.execute(ToolExecutionRequest(
            name="write_file",
            arguments={"file_path": "result.txt"},
            call_id="call-1",
            agent="coder",
            workspace=ROOT,
            metadata={"raw_tool_call": raw_call, "execution_options": {"max_result_chars": 100}},
        ))
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.model_observation["path"], "result.txt")
        self.assertEqual(agent.calls[0][0], raw_call)
        self.assertEqual(agent.calls[0][1]["max_result_chars"], 100)


if __name__ == "__main__":
    unittest.main()
