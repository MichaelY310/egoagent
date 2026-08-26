from __future__ import annotations

import json
import re
import sys
import tempfile
import threading
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness import Harness
from agent_bus import AgentBus
from pipeline_engine import PipelineRunner
from pipeline_schema import validate_pipeline
from test_pipeline_runtime import FakeAgent


class ContinueToolLoopAgent(FakeAgent):
    def __init__(self, replies, first_tool_calls):
        super().__init__("coder", replies)
        self.first_tool_calls = first_tool_calls
        self.executed = []
        self.seen_tool_names = []
        self.tool_descriptions = [
            {"type": "function", "function": {"name": name, "description": name, "parameters": {"type": "object"}}}
            for name in ["read_file", "search_code", "run_command", "write_file", "submit_result", "finish"]
        ]

    def step(self, messages, tools_desc=None, on_token=None):
        self.last_messages = messages
        self.last_tools_desc = tools_desc
        self.seen_tool_names.append([item["function"]["name"] for item in (tools_desc or [])])
        index = self.calls
        self.calls += 1
        text = self.replies[min(index, len(self.replies) - 1)]
        tool_calls = self.first_tool_calls if index == 0 else None
        if on_token and text:
            on_token(text)
        from harness import get_current_harness

        harness = get_current_harness()
        message = {"role": "assistant", "name": self.name, "content": text}
        harness.session.record(message)
        harness.session.record_full({**message, **({"tool_calls": tool_calls} if tool_calls else {})})
        return text, tool_calls

    def execute_tool_call(self, call):
        from harness import get_current_harness

        name = call["function"]["name"]
        self.executed.append(name)
        result = (
            "Tool read_file error: simulated read failure"
            if name == "read_file"
            else f"observed:{name}"
        )
        message = {
            "role": "user",
            "content": f'<tool_response>{json.dumps({"tool": name, "content": result})}</tool_response>',
        }
        harness = get_current_harness()
        harness.session.record(message)
        harness.session.record_full(message.copy())
        return result


class AutoGPTPortWorker(FakeAgent):
    """Deterministic worker for named/repeated port-event contract tests."""

    def __init__(self):
        super().__init__("worker")
        self._lock = threading.Lock()

    def step(self, messages, tools_desc=None, on_token=None):
        content = messages[-1]["content"]
        if '"id": "settings"' in content:
            text = '{"outputs":[{"name":"config","value":{"prefix":"v"}}]}'
        elif '"id": "items"' in content:
            text = '{"outputs":[{"name":"item","value":1},{"name":"item","value":2},{"name":"item","value":3}]}'
        else:
            match = re.search(r'"item"\s*:\s*(\d+)', content)
            text = f"v{match.group(1)}" if match else "missing item"
        with self._lock:
            self.calls += 1
        if on_token:
            on_token(text)
        from harness import get_current_harness

        harness = get_current_harness()
        message = {"role": "assistant", "name": self.name, "content": text}
        harness.session.record(message)
        harness.session.record_full(message.copy())
        return text, None


class HarnessReplicaTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "tmp").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "tmp")
        self.workspace = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def load(self, name: str, agents: dict[str, FakeAgent]) -> Harness:
        harness = Harness(ROOT / "harness" / name, agents=agents, workspace=self.workspace)
        harness._non_interactive = True
        return harness

    @staticmethod
    def ask(harness: Harness, text: str):
        message = {"role": "user", "content": text}
        harness.session.record(message)
        harness.session.record_full(message.copy())
        return PipelineRunner(harness).run()

    def test_replica_configs_are_valid(self):
        names = [
            "open_deep_research_worker",
            "open_deep_research_replica",
            "gpt_researcher_query_worker",
            "gpt_researcher_deep_query_worker",
            "gpt_researcher_deep_worker",
            "gpt_researcher_deep_replica",
            "bounded_coder_worker",
            "aider_review_worker",
            "aider_replica",
            "swe_agent_replica",
            "bounded_action_worker",
            "voyager_action_worker",
            "voyager_replica",
            "generative_reflection_worker",
            "generative_agent_replica",
            "gpt_researcher_replica",
            "metagpt_rolezero_worker",
            "metagpt_mgx_replica",
            "metagpt_software_company_replica",
            "openmanus_replica",
            "openmanus_planning_replica",
            "devika_replica",
            "continue_agent_replica",
            "continue_plan_replica",
            "browser_use_replica",
            "stagehand_replica",
            "autogpt_platform_replica",
            "openhands_replica",
            "ai_scientist_novelty_worker",
            "ai_scientist_experiment_run_worker",
            "ai_scientist_idea_worker",
            "ai_scientist_replica",
        ]
        for name in names:
            config = json.loads((ROOT / "harness" / name / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(validate_pipeline(config["pipeline"]), [], name)

    def test_open_deep_research_contract_runs_through_parallel_subflows(self):
        planner = FakeAgent("planner")
        planner.llm.responses = [
            '{"need_clarification": false, "question": "", "verification": "starting"}',
            '{"research_brief": "brief"}',
            '{"complete": false, "reflection": "need two independent areas", "tasks": [{"research_topic": "q1 with detailed scope"}, {"research_topic": "q2 with detailed scope"}]}',
            '{"complete": true, "reflection": "evidence is sufficient", "tasks": []}',
        ]
        researcher = FakeAgent("researcher", ["evidence with https://example.test/source"])
        writer = FakeAgent("writer")
        writer.llm.responses = ["final cited report"]
        harness = self.load(
            "open_deep_research_replica",
            {"planner": planner, "researcher": researcher, "writer": writer},
        )

        result = self.ask(harness, "research topic")

        self.assertEqual(result.result, "final cited report")
        self.assertEqual(len(result.data["research_runs"]), 2)
        self.assertIn("evidence with", result.data["evidence"])
        self.assertEqual(len(result.data["supervisor_history"]), 2)
        self.assertEqual(planner.llm.calls, 4)
        self.assertEqual(result.stats.model_calls, 9)
        self.assertEqual(researcher.llm.calls, 2)
        self.assertEqual(researcher.name, "researcher")

    def test_gpt_researcher_contract_curates_parallel_sources_before_writing(self):
        strategist = FakeAgent("strategist")
        strategist.llm.responses = [
            '{"server":"Domain Researcher","agent_role_prompt":"You are a domain expert."}',
            '{"queries":["query one","query two"]}',
            "curated official evidence https://example.test/source",
        ]
        researcher = FakeAgent("researcher", ["raw evidence https://example.test/source"])
        writer = FakeAgent("writer")
        writer.llm.responses = ["# Report\nGrounded answer [source](https://example.test/source)"]
        harness = self.load(
            "gpt_researcher_replica",
            {"strategist": strategist, "researcher": researcher, "writer": writer},
        )

        result = self.ask(harness, "research a topic")

        self.assertTrue(result.result.startswith("# Report"))
        self.assertEqual(len(result.data["research_runs"]), 3)
        self.assertEqual(result.data["queries"], ["query one", "query two", "research a topic"])
        self.assertIn("raw evidence", result.data["seed_context"])
        self.assertIn("curated official evidence", result.data["curated_context"])
        self.assertEqual(strategist.llm.calls, 3)
        self.assertEqual(result.stats.model_calls, 8)

    def test_gpt_researcher_deep_contract_runs_breadth_and_preserves_typed_citations(self):
        strategist = FakeAgent("strategist")
        extracted = '{"learnings":["measured finding"],"follow_up_questions":["what changed later?"],"citations":{"measured finding":"https://example.test/source"}}'
        strategist.llm.responses = [
            '{"questions":["historical baseline?","current evidence?","remaining uncertainty?"]}',
            '{"queries":[{"query":"query one","research_goal":"goal one"},{"query":"query two","research_goal":"goal two"}]}',
            extracted,
            extracted,
        ]
        researcher = FakeAgent("researcher", ["source evidence https://example.test/source"])
        writer = FakeAgent("writer")
        writer.llm.responses = ["# Deep report\nGrounded finding [source](https://example.test/source)"]
        harness = self.load(
            "gpt_researcher_deep_replica",
            {"strategist": strategist, "researcher": researcher, "writer": writer},
        )
        harness.config["pipeline"]["context"]["deep_depth"] = 1
        harness.config["pipeline"]["context"]["deep_breadth"] = 2

        result = self.ask(harness, "deeply research a topic")

        self.assertTrue(result.result.startswith("# Deep report"))
        self.assertEqual(len(result.data["deep_results"]["level_results"]), 2)
        self.assertEqual(result.data["deep_results"]["deeper_results"], [])
        self.assertEqual(
            result.data["deep_results"]["level_results"][0]["citations"]["measured finding"],
            "https://example.test/source",
        )
        self.assertEqual(strategist.llm.calls, 4)
        self.assertEqual(result.stats.model_calls, 8)

    def test_aider_contract_accepts_plan_runs_editor_and_reviews(self):
        (self.workspace / "demo.txt").write_text("before\n", encoding="utf-8")
        architect = FakeAgent("architect")
        architect.llm.responses = ['{"action":"edit","summary":"plan","files":["demo.txt"],"steps":["edit"],"tests":["test"]}']
        editor = FakeAgent("editor", ["demo.txt\n```text\n<<<<<<< SEARCH\nbefore\n=======\nafter\n>>>>>>> REPLACE\n```"])
        reviewer = FakeAgent("reviewer", ["checks pass"])
        reviewer.llm.responses = ['{"accepted":true,"feedback":"","summary":"verified"}']
        harness = self.load(
            "aider_replica",
            {"architect": architect, "editor": editor, "reviewer": reviewer},
        )

        result = self.ask(harness, "make a small safe change")

        self.assertIn("verified", result.result)
        self.assertIn("SEARCH", result.result)
        self.assertTrue(result.data["review_accepted"])
        self.assertEqual(result.data["edit_apply"]["applied"], 1)
        self.assertEqual(editor.name, "editor")
        self.assertEqual(reviewer.name, "reviewer")

    def test_aider_contract_answers_read_only_requests_without_starting_an_edit(self):
        architect = FakeAgent("architect", ["EgoAgent is a DAG-based agent development and evaluation platform."])
        architect.llm.responses = [
            '{"action":"answer","summary":"read-only repository question","files":[],"steps":[],"tests":[]}'
        ]
        editor = FakeAgent("editor", ["must not be called"])
        reviewer = FakeAgent("reviewer", ["must not be called"])
        harness = self.load("aider_replica", {"architect": architect, "editor": editor, "reviewer": reviewer})

        result = self.ask(harness, "What is this project about?")

        self.assertIn("DAG-based", result.result)
        self.assertEqual(editor.calls, 0)
        self.assertEqual(reviewer.calls, 0)
        self.assertEqual(result.data["edit_plan"]["action"], "answer")
        self.assertNotIn("edit_transaction", result.data)

    def test_aider_contract_reflects_after_format_error_then_applies_fixed_block(self):
        (self.workspace / "demo.txt").write_text("before\n", encoding="utf-8")
        architect = FakeAgent("architect")
        architect.llm.responses = ['{"action":"edit","summary":"plan","files":["demo.txt"],"steps":["edit"],"tests":["test"]}']
        editor = FakeAgent(
            "editor",
            [
                "ordinary prose without an edit",
                "demo.txt\n<<<<<<< SEARCH\nbefore\n=======\nafter\n>>>>>>> REPLACE",
            ],
        )
        reviewer = FakeAgent("reviewer", ["checks pass"])
        reviewer.llm.responses = ['{"accepted":true,"feedback":"","summary":"verified after format repair"}']
        harness = self.load("aider_replica", {"architect": architect, "editor": editor, "reviewer": reviewer})

        result = self.ask(harness, "make the change")

        self.assertIn("verified after format repair", result.result)
        self.assertEqual(editor.calls, 2)
        corrections = [message for message in harness.session.messages if message.get("name") == "runtime_aider_format_error"]
        self.assertEqual(len(corrections), 1)

    def test_aider_contract_feeds_match_failure_back_without_resending_successful_blocks(self):
        (self.workspace / "demo.txt").write_text("before\n", encoding="utf-8")
        architect = FakeAgent("architect")
        architect.llm.responses = ['{"action":"edit","summary":"plan","files":["demo.txt"],"steps":["edit"],"tests":["test"]}']
        editor = FakeAgent(
            "editor",
            [
                "demo.txt\n<<<<<<< SEARCH\nmissing\n=======\nafter\n>>>>>>> REPLACE",
                "demo.txt\n<<<<<<< SEARCH\nbefore\n=======\nafter\n>>>>>>> REPLACE",
            ],
        )
        reviewer = FakeAgent("reviewer", ["checks pass"])
        reviewer.llm.responses = ['{"accepted":true,"feedback":"","summary":"verified after match repair"}']
        harness = self.load("aider_replica", {"architect": architect, "editor": editor, "reviewer": reviewer})

        result = self.ask(harness, "make the change")

        self.assertIn("verified after match repair", result.result)
        self.assertEqual(editor.calls, 2)
        instructions = "\n".join(str(message.get("content", "")) for message in editor.last_messages)
        self.assertIn("failed to match", instructions)

    def test_aider_contract_reflects_lint_feedback_into_a_second_edit(self):
        (self.workspace / "demo.txt").write_text("before\n", encoding="utf-8")
        architect = FakeAgent("architect")
        architect.llm.responses = ['{"action":"edit","summary":"plan","files":["demo.txt"],"steps":["edit"],"tests":["test"]}']
        editor = FakeAgent(
            "editor",
            [
                "demo.txt\n<<<<<<< SEARCH\nbefore\n=======\nbad\n>>>>>>> REPLACE",
                "demo.txt\n<<<<<<< SEARCH\nbad\n=======\ngood\n>>>>>>> REPLACE",
            ],
        )
        reviewer = FakeAgent("reviewer", ["lint command failed", "lint and tests pass"])
        reviewer.llm.responses = [
            '{"accepted":false,"feedback":"fix lint failure in demo.txt","summary":"lint failed"}',
            '{"accepted":true,"feedback":"","summary":"verified after lint repair"}',
        ]
        harness = self.load("aider_replica", {"architect": architect, "editor": editor, "reviewer": reviewer})

        result = self.ask(harness, "make the change")

        self.assertIn("verified after lint repair", result.result)
        self.assertEqual(editor.calls, 2)
        instructions = "\n".join(str(message.get("content", "")) for message in editor.last_messages)
        self.assertIn("fix lint failure", instructions)

    def test_aider_contract_stops_after_three_malformed_reflections(self):
        (self.workspace / "demo.txt").write_text("before\n", encoding="utf-8")
        architect = FakeAgent("architect")
        architect.llm.responses = ['{"action":"edit","summary":"plan","files":["demo.txt"],"steps":["edit"],"tests":["test"]}']
        editor = FakeAgent("editor", ["malformed one", "malformed two", "malformed three"])
        reviewer = FakeAgent("reviewer")
        harness = self.load("aider_replica", {"architect": architect, "editor": editor, "reviewer": reviewer})

        result = self.ask(harness, "make the change")

        self.assertIn("three unsuccessful", result.result)
        self.assertEqual(editor.calls, 3)
        self.assertEqual(result.data["aider_status"]["status"], "reflection_limit")

    def test_aider_contract_budget_limit_uses_safe_transaction_finalizer(self):
        (self.workspace / "demo.txt").write_text("before\n", encoding="utf-8")
        architect = FakeAgent("architect")
        architect.llm.responses = ['{"action":"edit","summary":"plan","files":["demo.txt"],"steps":["edit"],"tests":["test"]}']
        editor = FakeAgent("editor")
        reviewer = FakeAgent("reviewer")
        harness = self.load("aider_replica", {"architect": architect, "editor": editor, "reviewer": reviewer})
        harness.config["pipeline"]["budget"]["max_model_calls"] = 1

        result = self.ask(harness, "make the change")

        self.assertEqual(result.result["status"], "limit_exceeded")
        self.assertIn("max model calls", result.result["reason"])
        self.assertEqual(editor.calls, 0)

    def test_aider_contract_does_not_run_suggested_shell_commands_without_explicit_approval(self):
        (self.workspace / "demo.txt").write_text("before\n", encoding="utf-8")
        architect = FakeAgent("architect")
        architect.llm.responses = ['{"action":"edit","summary":"plan","files":["demo.txt"],"steps":["edit"],"tests":["test"]}']
        editor = FakeAgent(
            "editor",
            [
                "demo.txt\n<<<<<<< SEARCH\nbefore\n=======\nafter\n>>>>>>> REPLACE\n"
                "```bash\npython dangerous_suggestion.py\n```"
            ],
        )
        reviewer = FakeAgent("reviewer", ["lint passes; suggested command was not run"])
        reviewer.llm.responses = ['{"accepted":true,"feedback":"","summary":"verified safely"}']
        harness = self.load("aider_replica", {"architect": architect, "editor": editor, "reviewer": reviewer})

        result = self.ask(harness, "make the change")

        self.assertIn("verified safely", result.result)
        self.assertFalse(result.data["shell_commands_approved"])
        self.assertIn("dangerous_suggestion.py", result.data["suggested_shell_commands"][0])
        self.assertIn("not run", result.data["review_result"])

    def test_swe_agent_contract_executes_one_action_observes_and_explicitly_submits(self):
        coder = FakeAgent(
            "coder",
            [
                "I will inspect the repository.\n```\necho inspected\n```",
                "The requested change is verified.\n```\nsubmit patch complete and tests pass\n```",
            ],
        )
        harness = self.load("swe_agent_replica", {"coder": coder})

        result = self.ask(harness, "fix issue #1")

        self.assertEqual(result.result["status"], "submitted")
        self.assertEqual(result.result["submission"], "patch complete and tests pass")
        self.assertEqual(result.stats.model_calls, 2)
        self.assertEqual(result.stats.tool_calls, 1)
        self.assertEqual(len(result.result["trajectory"]), 1)
        self.assertEqual(result.result["trajectory"][0]["action"], "run_command")
        self.assertEqual(result.result["trajectory"][0]["environment_action"], "echo inspected")
        self.assertEqual(result.result["trajectory"][0]["observation"], "ran:run_command")
        checkpoints = list((self.workspace / ".egoagent/checkpoints").glob("*-swe-step.json"))
        self.assertEqual(len(checkpoints), 1)

    def test_swe_agent_contract_requeries_format_errors_then_exits_with_autosubmit_status(self):
        coder = FakeAgent("coder", ["ordinary final answer", "still no action", "third malformed response"])
        harness = self.load("swe_agent_replica", {"coder": coder})

        result = self.ask(harness, "fix issue #2")

        self.assertEqual(result.result["status"], "exit_format")
        self.assertEqual(result.stats.model_calls, 3)
        self.assertEqual(result.stats.tool_calls, 0)
        self.assertEqual(len(result.result["trajectory"]), 3)
        self.assertTrue(all(item["phase"] == "action_parse" for item in result.result["trajectory"]))
        corrections = [
            message for message in harness.session.messages
            if message.get("name") == "runtime_action_format_error"
        ]
        self.assertEqual(len(corrections), 2)

    def test_swe_agent_contract_feeds_environment_error_back_before_submission(self):
        class EnvironmentErrorAgent(FakeAgent):
            def execute_tool_call(self, _call):
                return "Tool run_command error: simulated environment failure"

        coder = EnvironmentErrorAgent(
            "coder",
            [
                "Try the environment action.\n```\necho attempt\n```",
                "The environment failed, so submit the evidence.\n```\nsubmit environment failure documented\n```",
            ],
        )
        harness = self.load("swe_agent_replica", {"coder": coder})

        result = self.ask(harness, "diagnose environment")

        self.assertEqual(result.result["status"], "submitted")
        self.assertFalse(result.result["trajectory"][0]["ok"])
        self.assertIn("environment failure", result.result["trajectory"][0]["observation"])
        self.assertEqual(result.stats.model_calls, 2)

    def test_swe_agent_contract_budget_exhaustion_runs_safe_autosubmit_finalizer(self):
        coder = FakeAgent("coder", ["Inspect once.\n```\necho inspected\n```", "should never be called"])
        harness = self.load("swe_agent_replica", {"coder": coder})
        harness.config["pipeline"]["budget"]["max_model_calls"] = 1

        result = self.ask(harness, "bounded issue")

        self.assertEqual(result.result["status"], "exit_budget")
        self.assertIn("max model calls", result.result["termination_reason"])
        self.assertEqual(result.stats.model_calls, 1)
        self.assertEqual(result.stats.tool_calls, 1)
        self.assertEqual(coder.calls, 1)

    def test_voyager_contract_learns_curriculum_tasks_and_persists_skills(self):
        curriculum = FakeAgent("curriculum")
        curriculum.llm.responses = [
            f'{{"task":"task {index}","context":"context {index}"}}' for index in range(2, 4)
        ]
        action = FakeAgent("action", ["environment action completed"])
        critic = FakeAgent("critic")
        critic.llm.responses = [
            '{"success":true,"critique":"environment observation confirms success"}'
            for index in range(1, 4)
        ]
        skill_manager = FakeAgent("skill_manager")
        skill_manager.llm.responses = [
            f'{{"name":"skill_{index}","description":"skill {index}","importance":5}}'
            for index in range(1, 4)
        ]
        harness = self.load(
            "voyager_replica",
            {"curriculum": curriculum, "action": action, "critic": critic, "skill_manager": skill_manager},
        )
        harness.config["pipeline"]["context"]["max_iterations"] = 3

        result = self.ask(harness, "learn useful environment skills")

        self.assertEqual(len(result.result["skills"]), 3)
        self.assertEqual(result.data["completed_tasks"], ["Mine 1 wood log", "task 2", "task 3"])
        self.assertEqual(result.data["failed_tasks"], [])
        self.assertTrue((self.workspace / ".egoagent/memory/voyager_skills.json").is_file())
        progress = json.loads((self.workspace / ".egoagent/voyager-progress.json").read_text(encoding="utf-8"))
        self.assertEqual(progress["completed_tasks"], result.data["completed_tasks"])
        self.assertTrue(all("trajectory" in item["metadata"] for item in result.result["skills"]))

    def test_generative_agent_contract_accumulates_memory_and_reflects(self):
        first = FakeAgent("persona")
        first.llm.responses = [
            '{"events":[{"description":"noticed rain","event_key":"rain|starts|outside","importance":80,"keywords":["rain"],"distance":1}]}',
            '{"daily_plan":["stay safe"],"action":{"description":"seek shelter","duration_minutes":10,"address":"world:block:home:door","emoji":"🏠","event_key":"persona|seeks|shelter","should_talk":false,"utterance":""}}',
        ]
        first_harness = self.load("generative_agent_replica", {"persona": first})
        first_result = self.ask(first_harness, "heavy rain starts")
        self.assertEqual(first_result.result["description"], "seek shelter")

        second = FakeAgent("persona")
        reflection_replies = [
            json.dumps({"insights": [
                {"thought": f"insight {focus}-{index}", "evidence": ["grounded-memory"], "importance": 5}
                for index in range(1, 6)
            ]})
            for focus in range(1, 4)
        ]
        second.llm.responses = [
            '{"events":[{"description":"friend arrives","event_key":"friend|arrives|home","importance":80,"keywords":["friend"],"distance":1}]}',
            '{"daily_plan":["stay safe","help friend"],"action":{"description":"invite friend inside","duration_minutes":5,"address":"world:block:home:door","emoji":"👋","event_key":"persona|invites|friend inside","should_talk":true,"utterance":"come inside"}}',
            '{"focal_points":["How do weather and friendship interact?","What safety pattern is emerging?","How should the persona help others?"]}',
            *reflection_replies,
        ]
        second_harness = self.load("generative_agent_replica", {"persona": second})
        second_result = self.ask(second_harness, "a friend arrives in the rain")
        self.assertEqual(second_result.result["description"], "invite friend inside")
        memory = json.loads((self.workspace / ".egoagent/memory/generative_persona.json").read_text(encoding="utf-8"))
        thoughts = [item for item in memory["items"] if item["type"] == "thought"]
        self.assertEqual(len(thoughts), 15, second_result.data["insights"])
        self.assertTrue(any(item["text"] == "insight 1-1" for item in thoughts))
        self.assertEqual(memory["reflection_cursor"], len(memory["items"]))
        scratch = json.loads((self.workspace / ".egoagent/generative-scratch.json").read_text(encoding="utf-8"))
        self.assertEqual(scratch["current_action"]["event_key"], "persona|invites|friend inside")

    def test_metagpt_contract_routes_typed_artifacts_and_repairs_until_qa_passes(self):
        product = FakeAgent("product")
        product.llm.responses = [
            '{"name":"demo","goals":["ship"],"user_stories":["use it"],'
            '"functional_requirements":["feature"],"non_functional_requirements":["safe"],'
            '"constraints":[],"acceptance_criteria":["tests pass"]}'
        ]
        architect = FakeAgent("architect")
        architect.llm.responses = [
            '{"summary":"small design","modules":[{"name":"core","responsibility":"feature"}],'
            '"interfaces":["run"],"data_model":[],"runtime_flow":["input to output"],'
            '"technology":["python"],"verification":["unit tests"]}'
        ]
        manager = FakeAgent("manager")
        manager.llm.responses = [
            '{"tasks":[{"id":"T1","title":"build core","deliverable":"core.py",'
            '"description":"implement feature","dependencies":[],"acceptance":["unit test"]},'
            '{"id":"T2","title":"add tests","deliverable":"test_core.py",'
            '"description":"verify feature","dependencies":["T1"],"acceptance":["passes"]}]}'
        ]
        engineer = FakeAgent("engineer", ["implemented T1", "implemented T2", "repaired tests"])
        qa = FakeAgent("qa")
        qa.llm.responses = [
            '{"accepted":false,"summary":"test missing","feedback":"add boundary test",'
            '"tests":[{"name":"unit","status":"fail","evidence":"missing case"}]}',
            '{"accepted":true,"summary":"verified","feedback":"",'
            '"tests":[{"name":"unit","status":"pass","evidence":"all pass"}]}',
        ]
        harness = self.load(
            "metagpt_software_company_replica",
            {"product": product, "architect": architect, "manager": manager, "engineer": engineer, "qa": qa},
        )

        result = self.ask(harness, "build a tiny demo")

        self.assertTrue(result.result["accepted"])
        self.assertEqual(result.result["summary"], "verified")
        self.assertEqual(len(result.result["implementation_reports"]), 2)
        self.assertEqual(len(result.result["repair_reports"]), 1)
        self.assertEqual(result.result["tasks"][1]["dependencies"], ["T1"])
        self.assertEqual(engineer.name, "engineer")
        bus = AgentBus(self.workspace / ".egoagent" / "agent-bus.sqlite3")
        registered_roles = {item["metadata"]["role"] for item in bus.list_agents()}
        self.assertEqual(
            registered_roles,
            {"Product Manager", "Architect", "Project Manager", "Engineer", "QA Engineer"},
        )
        acknowledged = bus.list_messages(state="acked")
        self.assertEqual(len(acknowledged), 9)
        self.assertEqual(bus.list_messages(state="pending"), [])
        self.assertEqual(bus.list_messages(state="leased"), [])
        self.assertTrue(any(item["topic"].endswith(".repair.1") for item in acknowledged))

    def test_metagpt_mgx_contract_routes_rolezero_reports_across_company_rounds(self):
        team_leader = FakeAgent("team_leader")
        team_leader.llm.responses = [
            '{"intent":"TASK"}',
            '{"complete":false,"reply":"","delegations":[{"role":"product","task":"write a precise PRD for the demo"}]}',
            '{"complete":false,"reply":"","delegations":[{"role":"architect","task":"design the demo using the completed PRD report"}]}',
            '{"complete":true,"reply":"The team completed the requested design.","delegations":[]}',
        ]
        product = FakeAgent("product", ["PRD report complete"])
        architect = FakeAgent("architect", ["architecture report complete"])
        engineer = FakeAgent("engineer", ["engineering report complete"])
        analyst = FakeAgent("data_analyst", ["analysis report complete"])
        harness = self.load(
            "metagpt_mgx_replica",
            {
                "team_leader": team_leader,
                "product": product,
                "architect": architect,
                "engineer": engineer,
                "data_analyst": analyst,
            },
        )

        result = self.ask(harness, "build a tiny demo")

        self.assertTrue(result.result["complete"])
        self.assertEqual(result.result["reply"], "The team completed the requested design.")
        self.assertEqual([report["role"] for report in result.result["reports"]], ["product", "architect"])
        self.assertEqual([report["status"] for report in result.result["reports"]], ["completed", "completed"])
        bus = AgentBus(self.workspace / ".egoagent" / "agent-bus.sqlite3")
        self.assertEqual({item["metadata"]["role"] for item in bus.list_agents()}, {"Team Leader", "Product Manager", "Architect", "Engineer2", "DataAnalyst"})
        self.assertEqual(len(bus.list_messages(state="acked")), 2)
        self.assertEqual(bus.list_messages(state="pending"), [])
        self.assertEqual(bus.list_messages(state="leased"), [])

    def test_openmanus_planning_contract_executes_each_step_then_summarizes(self):
        planner = FakeAgent("planner")
        planner.llm.responses = [
            '{"title":"demo plan","steps":[{"id":"S1","text":"inspect",'
            '"type":"executor","dependencies":[],"verification":"files read"},'
            '{"id":"S2","text":"implement","type":"executor",'
            '"dependencies":["S1"],"verification":"tests pass"}]}',
            "Plan completed with verification evidence.",
        ]
        executor = FakeAgent("executor", ["step completed"])
        harness = self.load("openmanus_planning_replica", {"planner": planner, "executor": executor})

        result = self.ask(harness, "build demo")

        self.assertEqual(result.result, "Plan completed with verification evidence.")
        self.assertEqual(len(result.data["step_reports"]), 2)
        self.assertEqual(result.data["steps"][1]["dependencies"], ["S1"])
        self.assertEqual(result.data["step_statuses"], ["blocked", "blocked"])

    def test_openmanus_contract_requires_explicit_terminate(self):
        class TerminatingManus(FakeAgent):
            def __init__(self):
                super().__init__("manus", ["done"])
                self.tool_descriptions = [
                    {"type": "function", "function": {"name": "terminate", "description": "terminate", "parameters": {"type": "object"}}}
                ]

            def step(self, messages, tools_desc=None, on_token=None):
                self.calls += 1
                return "verified the task", [
                    {
                        "id": "terminate-1",
                        "type": "function",
                        "function": {
                            "name": "terminate",
                            "arguments": '{"status":"success","summary":"task verified and complete"}',
                        },
                    }
                ]

            def execute_tool_call(self, call):
                return {"terminated": True, "status": "success", "summary": "task verified and complete"}

        manus = TerminatingManus()
        harness = self.load("openmanus_replica", {"manus": manus})

        result = self.ask(harness, "complete a small task")

        self.assertEqual(result.result["status"], "success")
        self.assertEqual(result.result["answer"], "task verified and complete")
        self.assertEqual(result.result["steps"], 1)
        self.assertEqual(result.stats.model_calls, 1)
        self.assertEqual(result.stats.tool_calls, 1)

    def test_devika_contract_routes_new_project_through_plan_research_and_code(self):
        coordinator = FakeAgent("coordinator")
        coordinator.llm.responses = [
            '{"response":"I will build it.","action":"coding_project"}',
            '{"project_name":"demo","reply":"planning","focus":"tiny app",'
            '"steps":[{"id":1,"text":"build","dependencies":[],"verification":"test"}],'
            '"summary":"small project"}',
            '{"internal_monologue":"I am turning the plan into a small verified project."}',
        ]
        researcher = FakeAgent("researcher")
        researcher.llm.responses = ['{"queries":[],"ask_user":""}']
        coder = FakeAgent("coder", ["project built and tested"])
        reporter = FakeAgent("reporter")
        harness = self.load(
            "devika_replica",
            {"coordinator": coordinator, "researcher": researcher, "coder": coder, "reporter": reporter},
        )

        result = self.ask(harness, "build a tiny app")

        self.assertEqual(result.result, "project built and tested")
        self.assertEqual(result.data["plan"]["project_name"], "demo")
        self.assertEqual(result.data["queries"], [])
        self.assertEqual(result.data["research_context"], "")
        self.assertIn("verified project", result.data["internal_status"])

    def test_devika_contract_keeps_distinct_run_feature_and_bug_paths(self):
        config = json.loads((ROOT / "harness" / "devika_replica" / "config.json").read_text(encoding="utf-8"))
        nodes = config["pipeline"]["nodes"]
        route_targets = {edge["to"] for edge in nodes["route"]["edges"]}

        self.assertTrue({"run_project", "feature_project", "bug_project"} <= route_targets)
        self.assertIn("stdout and stderr", nodes["run_project"]["inputs"]["message"])
        self.assertIn("per-hunk review", nodes["feature_project"]["inputs"]["message"])
        self.assertIn("root cause", nodes["bug_project"]["inputs"]["message"])
        self.assertEqual(nodes["browser_task"]["harness"], "browser_use_replica")
        self.assertEqual(nodes["browser_task"]["inputs"]["data"]["max_browser_steps"], 5)

    def test_continue_agent_contract_runs_parallel_tools_and_feeds_errors_back(self):
        calls = [
            {"id": "read-1", "type": "function", "function": {"name": "read_file", "arguments": "{\"path\":\"README.md\"}"}},
            {"id": "search-1", "type": "function", "function": {"name": "search_code", "arguments": "{\"query\":\"TODO\"}"}},
        ]
        coder = ContinueToolLoopAgent(["I will inspect in parallel.", "resolved after observations"], calls)
        harness = self.load("continue_agent_replica", {"coder": coder})

        result = self.ask(harness, "inspect the project")

        self.assertEqual(result.result, "resolved after observations")
        self.assertEqual(result.stats.model_calls, 2)
        self.assertEqual(result.stats.tool_calls, 2)
        self.assertEqual(coder.calls, 2)
        self.assertCountEqual(coder.executed, ["read_file", "search_code"])
        self.assertEqual([item["action"] for item in result.data["_trajectory"]], ["read_file", "search_code"])
        self.assertFalse(result.data["_trajectory"][0]["ok"])
        self.assertTrue(result.data["_trajectory"][1]["ok"])
        self.assertNotIn("submit_result", coder.seen_tool_names[0])
        self.assertTrue(any("simulated read failure" in str(message.get("content")) for message in coder.last_messages))

    def test_continue_plan_contract_hides_and_blocks_write_tools_but_keeps_bash(self):
        injected_write = [
            {"id": "write-1", "type": "function", "function": {"name": "write_file", "arguments": "{\"path\":\"x.py\",\"content\":\"bad\"}"}},
        ]
        planner = ContinueToolLoopAgent(["Attempt an injected write.", "read-only plan complete"], injected_write)
        harness = self.load("continue_plan_replica", {"planner": planner})

        result = self.ask(harness, "plan a change")

        self.assertEqual(result.result, "read-only plan complete")
        self.assertEqual(result.stats.model_calls, 2)
        self.assertEqual(result.stats.tool_calls, 0)
        self.assertEqual(planner.executed, [])
        self.assertNotIn("write_file", planner.seen_tool_names[0])
        self.assertIn("run_command", planner.seen_tool_names[0])
        blocked = [message for message in harness.session.messages if "status\": \"blocked" in str(message.get("content", ""))]
        self.assertEqual(len(blocked), 1)

    def test_continue_contract_auto_compacts_persists_and_continues_once(self):
        coder = FakeAgent("coder", ["would have stopped", "continued final"])
        coder.llm.responses = ["compact summary with unfinished work"]
        harness = self.load("continue_agent_replica", {"coder": coder})
        context = harness.config["pipeline"]["nodes"]["context"]
        context.update(
            {
                "context_limit_tokens": 120,
                "max_output_tokens": 20,
                "reserved_tokens": 0,
                "compaction_buffer_cap": 10,
            }
        )

        result = self.ask(harness, "large context " * 300)

        self.assertEqual(result.result, "continued final")
        self.assertEqual(result.stats.model_calls, 3)
        self.assertEqual(coder.llm.calls, 1)
        self.assertEqual(coder.calls, 2)
        self.assertEqual(harness.session.messages[0]["name"], "context_summary")
        self.assertTrue(any(message.get("name") == "runtime_auto_continue" for message in harness.session.messages))

    def test_continue_contract_budget_finalizer_does_not_make_an_extra_model_call(self):
        calls = [
            {"id": "read-1", "type": "function", "function": {"name": "read_file", "arguments": "{\"path\":\"README.md\"}"}},
        ]
        coder = ContinueToolLoopAgent(["inspect once", "must not run"], calls)
        harness = self.load("continue_agent_replica", {"coder": coder})
        harness.config["pipeline"]["budget"]["max_model_calls"] = 1

        result = self.ask(harness, "bounded inspection")

        self.assertEqual(result.result["status"], "limit_exceeded")
        self.assertIn("max model calls", result.result["reason"])
        self.assertEqual(result.stats.model_calls, 1)
        self.assertEqual(result.stats.tool_calls, 1)
        self.assertEqual(coder.calls, 1)

    def test_browser_use_contract_runs_final_evidence_judge(self):
        browser_agent = FakeAgent("browser_agent", ["task completed on the page"])
        judge = FakeAgent("judge")
        judge.llm.responses = ['{"success":true,"summary":"verified","evidence":["page confirmed"],"gaps":[]}']
        harness = self.load("browser_use_replica", {"browser_agent": browser_agent, "judge": judge})

        result = self.ask(harness, "inspect a page")

        self.assertTrue(result.result["success"])
        self.assertEqual(result.result["answer"], "task completed on the page")
        self.assertEqual(result.result["evidence"], ["page confirmed"])

    def test_browser_use_contract_stops_after_five_consecutive_failures(self):
        class FailingBrowserAgent(FakeAgent):
            def __init__(self):
                super().__init__("browser_agent", ["ignored"])
                self.tool_descriptions = [
                    {"type": "function", "function": {"name": "browser", "description": "browser", "parameters": {"type": "object"}}}
                ]
                self.llm.responses = ["factual blocker after repeated browser failures"]

            def step(self, messages, tools_desc=None, on_token=None):
                self.calls += 1
                calls = [{"id": f"fail-{self.calls}", "type": "function", "function": {"name": "browser", "arguments": '{"action":"observe"}'}}]
                return "observe", calls

            def execute_tool_call(self, call):
                return "Tool browser error: simulated connection failure"

        browser_agent = FailingBrowserAgent()
        judge = FakeAgent("judge")
        judge.llm.responses = ['{"success":false,"summary":"blocked","evidence":[],"gaps":["browser unavailable"]}']
        harness = self.load("browser_use_replica", {"browser_agent": browser_agent, "judge": judge})

        result = self.ask(harness, "inspect a page")

        self.assertFalse(result.result["success"])
        self.assertEqual(result.result["consecutive_failures"], 5)
        self.assertEqual(result.stats.tool_calls, 5)
        self.assertGreaterEqual(browser_agent.calls, 5)
        self.assertEqual(result.result["answer"], "factual blocker after repeated browser failures")

    def test_stagehand_contract_returns_fused_verifier_outcome(self):
        browser_agent = FakeAgent("browser_agent", ["finished"])
        verifier = FakeAgent("verifier")
        verifier.llm.responses = [
            '{"success":true,"fused_outcome":"all criteria met","first_failure":"",'
            '"criteria":[{"criterion":"page inspected","passed":true,"evidence":"terminal observation"}]}'
        ]
        harness = self.load("stagehand_replica", {"browser_agent": browser_agent, "verifier": verifier})

        result = self.ask(harness, "inspect a page")

        self.assertTrue(result.result["success"])
        self.assertEqual(result.result["outcome"], "all criteria met")
        self.assertEqual(result.result["criteria"][0]["passed"], True)

    def test_stagehand_contract_forces_done_and_replays_deterministic_cache(self):
        class StagehandBrowserAgent(FakeAgent):
            def __init__(self, *, fail_if_planned=False):
                super().__init__("browser_agent", ["navigate", "work complete"])
                self.fail_if_planned = fail_if_planned
                self.executed = []
                self.tool_descriptions = [
                    {"type": "function", "function": {"name": "browser", "description": "browser", "parameters": {"type": "object"}}}
                ]
                self.llm.responses = [
                    '{"reasoning":"confirmed by terminal page state","taskComplete":true,"output":{"value":"ok"}}'
                ]

            def step(self, messages, tools_desc=None, on_token=None):
                if self.fail_if_planned:
                    raise AssertionError("cache hit should replay actions without planning again")
                if self.calls == 0:
                    self.calls += 1
                    call = {
                        "id": "navigate-1",
                        "type": "function",
                        "function": {"name": "browser", "arguments": '{"action":"navigate","url":"https://example.test"}'},
                    }
                    return "navigate", [call]
                return super().step(messages, tools_desc=tools_desc, on_token=on_token)

            def execute_tool_call(self, call):
                self.executed.append(call)
                return {
                    "action": "navigate",
                    "result": {"ok": True},
                    "observation": {"url": "https://example.test", "title": "Example", "page_changed": True},
                }

        first_browser = StagehandBrowserAgent()
        first_verifier = FakeAgent("verifier")
        first_verifier.llm.responses = [
            '{"success":true,"fused_outcome":"verified first run","first_failure":"","criteria":[]}'
        ]
        first = self.load(
            "stagehand_replica",
            {"browser_agent": first_browser, "verifier": first_verifier},
        )

        first_result = self.ask(first, "open the example page")

        self.assertFalse(first_result.result["cache_hit"])
        self.assertTrue(first_result.result["completed"])
        self.assertEqual(first_result.result["output"], {"value": "ok"})
        self.assertEqual(len(first_browser.executed), 1)

        replay_browser = StagehandBrowserAgent(fail_if_planned=True)
        replay_verifier = FakeAgent("verifier")
        replay_verifier.llm.responses = [
            '{"success":true,"fused_outcome":"verified replay","first_failure":"","criteria":[]}'
        ]
        replay = self.load(
            "stagehand_replica",
            {"browser_agent": replay_browser, "verifier": replay_verifier},
        )

        replay_result = self.ask(replay, "open the example page")

        self.assertTrue(replay_result.result["cache_hit"])
        self.assertTrue(replay_result.result["completed"])
        self.assertEqual(replay_result.result["answer"], "confirmed by terminal page state")
        self.assertEqual(len(replay_browser.executed), 1)
        replay_args = replay_browser.executed[0]["function"]["arguments"]
        self.assertEqual(replay_args["action"], "navigate")

    def test_stagehand_contract_uses_source_default_step_caps(self):
        config = json.loads((ROOT / "harness" / "stagehand_replica" / "config.json").read_text(encoding="utf-8"))
        nodes = config["pipeline"]["nodes"]

        self.assertEqual(config["pipeline"]["context"]["mode"], "dom")
        self.assertEqual(nodes["configure_dom"]["value"], 20)
        self.assertEqual(nodes["configure_hybrid"]["value"], 20)
        self.assertEqual(nodes["configure_cua"]["value"], 10)
        self.assertEqual(nodes["agent_loop"]["max_count"], "$ctx.max_agent_steps")

    def test_autogpt_platform_contract_compiles_maps_joins_and_verifies(self):
        planner = FakeAgent("planner")
        planner.llm.responses = [
            '{"goal":"prepare two artifacts","blocks":['
            '{"id":"T1","instruction":"prepare first","required_inputs":[],"defaults":{},"output_port":"output","sensitive":false,"output_schema":{"type":"string","minLength":1},"output_schemas":{}},'
            '{"id":"T2","instruction":"prepare second","required_inputs":[],"defaults":{},"output_port":"output","sensitive":false,"output_schema":{"type":"string","minLength":1},"output_schemas":{}}],"links":[]}'
        ]
        worker = FakeAgent("worker", ["first block complete", "second block complete"])
        verifier = FakeAgent("verifier")
        verifier.llm.responses = [
            '{"success":true,"summary":"both complete","completed_tasks":["T1","T2"],'
            '"failed_tasks":[],"evidence":["first block complete","second block complete"]}'
        ]
        harness = self.load(
            "autogpt_platform_replica",
            {"planner": planner, "worker": worker, "verifier": verifier},
        )

        result = self.ask(harness, "prepare two artifacts")

        self.assertTrue(result.result["success"])
        self.assertEqual(result.result["completed_tasks"], ["T1", "T2"])
        self.assertEqual(len(result.data["block_results"]), 2)
        self.assertEqual([item["status"] for item in result.data["block_results"]], ["completed", "completed"])
        self.assertEqual(result.data["port_graph_result"]["counts"]["completed"], 2)
        self.assertEqual(result.data["plan"]["blocks"][1]["id"], "T2")
        self.assertEqual(
            {item["block_id"] for item in result.data["port_graph_result"]["terminal_outputs"]},
            {"T1", "T2"},
        )

    def test_autogpt_platform_routes_dependency_events_and_exposes_upstream_results(self):
        planner = FakeAgent("planner")
        planner.llm.responses = [
            '{"goal":"sequential work","blocks":['
            '{"id":"T1","instruction":"first","required_inputs":[],"defaults":{},"output_port":"output","sensitive":false,"output_schema":{"type":"string"},"output_schemas":{}},'
            '{"id":"T2","instruction":"second","required_inputs":["source"],"defaults":{},"output_port":"output","sensitive":false,"output_schema":{"type":"string"},"output_schemas":{}}],'
            '"links":[{"source_id":"T1","source_name":"output","sink_id":"T2","sink_name":"source","is_static":false}]}'
        ]
        worker = FakeAgent("worker", ["upstream evidence", "dependent evidence"])
        verifier = FakeAgent("verifier")
        verifier.llm.responses = [
            '{"success":true,"summary":"ordered","completed_tasks":["T1","T2"],"failed_tasks":[],"evidence":["upstream evidence","dependent evidence"]}'
        ]
        harness = self.load(
            "autogpt_platform_replica",
            {"planner": planner, "worker": worker, "verifier": verifier},
        )

        result = self.ask(harness, "do sequential work")

        self.assertEqual([item["task_id"] for item in result.data["block_results"]], ["T1", "T2"])
        self.assertEqual([item["status"] for item in result.data["block_results"]], ["completed", "completed"])
        self.assertEqual(result.data["block_results"][1]["inputs"], {"source": "upstream evidence"})
        config = json.loads((ROOT / "harness" / "autogpt_platform_replica" / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(config["pipeline"]["nodes"]["execute_graph"]["mode"], "port_graph")
        self.assertNotIn("dependency_levels", config["pipeline"]["nodes"])

    def test_autogpt_platform_reuses_static_ports_for_repeated_dynamic_events(self):
        planner = FakeAgent("planner")
        planner.llm.responses = [json.dumps({
            "goal": "process three items with shared settings",
            "blocks": [
                {
                    "id": "settings", "instruction": "emit shared settings", "required_inputs": [],
                    "defaults": {}, "output_port": "config", "sensitive": False,
                    "output_schema": {"type": "object", "required": ["prefix"]}, "output_schemas": {},
                },
                {
                    "id": "items", "instruction": "emit three item events", "required_inputs": [],
                    "defaults": {}, "output_port": "item", "sensitive": False,
                    "output_schema": {"type": "integer"}, "output_schemas": {},
                },
                {
                    "id": "process", "instruction": "combine config and item", "required_inputs": ["config", "item"],
                    "defaults": {}, "output_port": "output", "sensitive": False,
                    "output_schema": {"type": "string", "minLength": 1}, "output_schemas": {},
                },
            ],
            "links": [
                {"source_id": "settings", "source_name": "config", "sink_id": "process", "sink_name": "config", "is_static": True},
                {"source_id": "items", "source_name": "item", "sink_id": "process", "sink_name": "item", "is_static": False},
            ],
        })]
        worker = AutoGPTPortWorker()
        verifier = FakeAgent("verifier")
        verifier.llm.responses = [
            '{"success":true,"summary":"three processed","completed_tasks":["settings","items","process"],'
            '"failed_tasks":[],"evidence":["v1","v2","v3"]}'
        ]
        harness = self.load(
            "autogpt_platform_replica",
            {"planner": planner, "worker": worker, "verifier": verifier},
        )

        result = self.ask(harness, "process items")

        process_runs = [item for item in result.data["block_results"] if item["task_id"] == "process"]
        self.assertEqual(len(process_runs), 3)
        self.assertEqual(sorted(item["output"] for item in process_runs), ["v1", "v2", "v3"])
        self.assertTrue(all(item["inputs"]["config"] == {"prefix": "v"} for item in process_runs))
        self.assertEqual(result.data["port_graph_result"]["counts"]["executions"], 5)
        self.assertEqual(result.data["port_graph_result"]["static_values"], [
            {"block_id": "process", "port": "config", "value": {"prefix": "v"}},
        ])
        self.assertEqual(worker.calls, 5)
        state_path = self.workspace / result.data["_port_graph_state_path"]
        persisted = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(len(persisted["records"]), 5)
        self.assertTrue(
            all(item["status"] == "completed" for item in persisted["records"]),
            [item["status"] for item in persisted["records"]],
        )
        self.assertEqual(len(persisted["events"]), len(result.data["port_events"]))

    def test_autogpt_platform_reviews_only_the_sensitive_block(self):
        planner = FakeAgent("planner")
        planner.llm.responses = [
            '{"goal":"send safely","blocks":['
            '{"id":"T1","instruction":"send message","required_inputs":[],"defaults":{},"output_port":"output","sensitive":true,"output_schema":{"type":"string"},"output_schemas":{}}],"links":[]}'
        ]
        worker = FakeAgent("worker", ["should not run"])
        verifier = FakeAgent("verifier")
        verifier.llm.responses = [
            '{"success":false,"summary":"review rejected","completed_tasks":[],"failed_tasks":["T1"],"evidence":[]}'
        ]
        harness = self.load(
            "autogpt_platform_replica",
            {"planner": planner, "worker": worker, "verifier": verifier},
        )

        result = self.ask(harness, "send a message")

        self.assertFalse(result.result["success"])
        self.assertEqual(worker.calls, 0)
        self.assertEqual(result.data["block_results"][0]["status"], "rejected")

    def test_openhands_contract_retries_until_independent_goal_judge_accepts(self):
        agent = FakeAgent("agent", ["implemented change", "ran tests and verified"])
        judge = FakeAgent("judge")
        judge.llm.responses = [
            '{"complete":false,"score":0.5,"missing":"Run the tests and show output."}',
            '{"complete":true,"score":1.0,"missing":""}',
        ]
        harness = self.load("openhands_replica", {"agent": agent, "judge": judge})

        result = self.ask(harness, "make the verified change")

        self.assertEqual(result.result["status"], "complete")
        self.assertTrue(result.result["audit"]["complete"])
        self.assertEqual(result.result["audit_reports"][0]["missing"], "Run the tests and show output.")
        self.assertEqual(agent.calls, 2)
        self.assertIn("Run the tests", agent.last_messages[-1]["content"])

    def test_openhands_contract_uses_conservative_invalid_judge_fallback(self):
        agent = FakeAgent("agent", ["claimed completion", "verified completion"])
        judge = FakeAgent("judge")
        judge.llm.responses = [
            "this is not valid json",
            '{"complete":true,"score":1.0,"missing":""}',
        ]
        harness = self.load("openhands_replica", {"agent": agent, "judge": judge})

        result = self.ask(harness, "make a verified change")

        self.assertEqual(result.result["status"], "complete")
        self.assertEqual(result.result["audit_reports"][0], {
            "complete": False,
            "score": 0.0,
            "missing": "Judge verdict could not be parsed.",
        })
        self.assertEqual(agent.calls, 2)
        self.assertEqual(judge.llm.calls, 2)

    def test_openhands_contract_finish_ends_inner_loop_and_discards_later_tools(self):
        calls = [
            {"id": name, "type": "function", "function": {"name": name, "arguments": "{}"}}
            for name in ["read_file", "finish", "write_file"]
        ]
        agent = ContinueToolLoopAgent([""], calls)
        judge = FakeAgent("judge")
        judge.llm.responses = ['{"complete":true,"score":1.0,"missing":""}']
        harness = self.load("openhands_replica", {"agent": agent, "judge": judge})
        harness.config["pipeline"]["nodes"]["security"]["default_permission"] = "allow"
        harness.config["pipeline"]["nodes"]["security"]["policies"] = []

        result = self.ask(harness, "inspect and finish")

        self.assertEqual(result.result["status"], "complete")
        self.assertEqual(agent.calls, 1)
        self.assertEqual(agent.executed, ["read_file", "finish"])
        self.assertEqual(
            [item["action"] for item in result.result["trajectory"]],
            ["read_file", "finish"],
        )
        self.assertEqual(result.data["_terminal_tool"]["tool"], "finish")

    def test_openhands_contract_caps_goal_controller_at_ten_iterations(self):
        agent = FakeAgent("agent", [f"attempt {index}" for index in range(1, 11)])
        judge = FakeAgent("judge")
        judge.llm.responses = [
            '{"complete":false,"score":0.2,"missing":"authoritative test evidence"}'
            for _ in range(10)
        ]
        harness = self.load("openhands_replica", {"agent": agent, "judge": judge})

        result = self.ask(harness, "complete a difficult goal")

        self.assertEqual(result.result["status"], "capped")
        self.assertEqual(result.result["iterations"], 10)
        self.assertEqual(agent.calls, 10)
        self.assertEqual(judge.llm.calls, 10)
        self.assertEqual(len(result.result["audit_reports"]), 10)

    def test_openhands_contract_budget_limit_runs_safe_finalizer_without_extra_model_call(self):
        agent = FakeAgent("agent", ["claimed completion"])
        judge = FakeAgent("judge")
        judge.llm.responses = ['{"complete":true,"score":1.0,"missing":""}']
        harness = self.load("openhands_replica", {"agent": agent, "judge": judge})
        harness.config["pipeline"]["budget"]["max_model_calls"] = 1

        result = self.ask(harness, "make a change")

        self.assertEqual(result.result["status"], "limit_exceeded")
        self.assertEqual(agent.calls, 1)
        self.assertEqual(judge.llm.calls, 0)
        self.assertIn("model call", result.result["termination_reason"].lower())

    def test_ai_scientist_contract_filters_novel_ideas_and_ensemble_reviews_study(self):
        ideator = FakeAgent("ideator")
        idea = '{"Name":"tiny","Title":"Tiny Study","Experiment":"compare A and B","Interestingness":7,"Feasibility":9,"Novelty":7}'
        ideator.llm.responses = [idea, f"THOUGHT: I am done.\nNEW IDEA JSON:\n```json\n{idea}\n```"]
        novelty = FakeAgent("novelty")
        novelty.llm.responses = [
            'THOUGHT: Search the closest method.\nRESPONSE:\n```json\n{"Query":"closest method paper"}\n```',
            'THOUGHT: The evidence is distinct. Decision made: novel.\nRESPONSE:\n```json\n{}\n```',
        ]
        researcher = FakeAgent("researcher", ["paper evidence https://example.test/paper"])
        scientist = FakeAgent("scientist")
        scientist.llm.responses = [json.dumps({
            "name": "tiny",
            "hypothesis": "A beats B",
            "artifact_dir": ".egoagent/ai-scientist/tiny",
            "runs": [{
                "id": "run_1",
                "purpose": "compare",
                "command": sys.executable,
                "args": ["-c", "print('metric=0.8')"],
                "cwd": ".",
                "resources": {"cpu": 1},
                "success_criteria": ["metric recorded"],
            }],
            "required_artifacts": ["notes.txt", "results.json"],
        })]
        experimenter = FakeAgent("experimenter", ["experiment ran; metric=0.8; artifacts saved"])
        writer = FakeAgent("writer")
        writer.llm.responses = ["# Tiny Study\nMeasured result: 0.8", "No more citations needed\n{}"]
        review_json = (
            '{"Summary":"measured study","Strengths":["measured"],"Weaknesses":[],'
            '"Originality":3,"Quality":4,"Clarity":3,"Significance":3,"Questions":[],'
            '"Limitations":[],"Ethical Concerns":false,"Soundness":4,"Presentation":3,'
            '"Contribution":3,"Overall":8,"Confidence":4,"Decision":"Accept"}'
        )
        reviewer_a = FakeAgent("reviewer_a"); reviewer_a.llm.responses = [review_json]
        reviewer_b = FakeAgent("reviewer_b"); reviewer_b.llm.responses = [review_json]
        reviewer_c = FakeAgent("reviewer_c"); reviewer_c.llm.responses = [review_json]
        reviewer_d = FakeAgent("reviewer_d"); reviewer_d.llm.responses = [review_json]
        reviewer_e = FakeAgent("reviewer_e"); reviewer_e.llm.responses = [review_json]
        meta = FakeAgent("meta_reviewer")
        meta.llm.responses = [
            review_json,
            f"THOUGHT: I am done.\nREVIEW JSON:\n```json\n{review_json}\n```",
        ]
        synthesizer = FakeAgent("synthesizer")
        synthesizer.llm.responses = ["One novel study completed and accepted."]
        template = self.workspace / "templates" / "tiny"
        (template / "run_0").mkdir(parents=True)
        (template / "experiment.py").write_text("# template experiment\n", encoding="utf-8")
        (template / "run_0" / "final_info.json").write_text(
            '{"baseline_metric":{"means":0.5}}', encoding="utf-8"
        )
        harness = self.load(
            "ai_scientist_replica",
            {
                "ideator": ideator, "novelty": novelty, "researcher": researcher,
                "scientist": scientist, "experimenter": experimenter, "writer": writer,
                "citation_researcher": researcher,
                "reviewer_a": reviewer_a, "reviewer_b": reviewer_b, "reviewer_c": reviewer_c,
                "reviewer_d": reviewer_d, "reviewer_e": reviewer_e,
                "meta_reviewer": meta, "synthesizer": synthesizer,
            },
        )
        harness.config["pipeline"]["context"]["generation_slots"] = [1]
        harness.config["pipeline"]["context"]["template_dir"] = "templates/tiny"

        result = self.ask(harness, "run a tiny scientific study")

        self.assertEqual(result.result["status"], "completed")
        self.assertEqual(len(result.result["selected_ideas"]), 1)
        self.assertEqual(len(result.result["studies"]), 1)
        self.assertEqual(result.result["novelty_results"][0]["rounds"], 2)
        self.assertEqual(len(result.result["novelty_results"][0]["searches"]), 1)
        self.assertEqual(novelty.llm.calls, 2)
        self.assertTrue(result.result["studies"][0]["accepted"])
        self.assertEqual(
            result.result["studies"][0]["experiment_report"]["baseline"]["baseline_metric"]["means"],
            0.5,
        )
        self.assertTrue((self.workspace / ".egoagent" / "ai-scientist" / "tiny" / "experiment.py").is_file())
        self.assertEqual(result.result["studies"][0]["paper_path"], ".egoagent/ai-scientist/tiny/paper.md")
        self.assertTrue((self.workspace / result.result["studies"][0]["paper_path"]).is_file())
        self.assertEqual(len(result.result["studies"][0]["reviews"]), 5)
        self.assertEqual(result.result["studies"][0]["score_averages"]["Overall"], 8)
        self.assertEqual(result.result["studies"][0]["meta_review"]["Decision"], "Accept")
        self.assertEqual(meta.llm.calls, 2)
        self.assertTrue(result.result["studies"][0]["experiment_report"]["runs"][0]["success"])
        self.assertEqual(result.result["studies"][0]["experiment_report"]["runs"][0]["process"]["exit_code"], 0)
        self.assertEqual(result.result["studies"][0]["experiment_report"]["runs"][0]["attempts"], 1)
        self.assertTrue((self.workspace / result.result["studies"][0]["artifact_snapshot"]["path"]).is_file())
        self.assertEqual(result.stats.process_calls, 1)
        self.assertIn("accepted", result.result["summary"])

    def test_ai_scientist_generation_contract_reflects_each_idea_for_three_total_rounds(self):
        idea = '{"Name":"three_rounds","Title":"Three Rounds","Experiment":"compare A and B","Interestingness":7,"Feasibility":8,"Novelty":6}'
        ideator = FakeAgent("ideator")
        ideator.llm.responses = [idea, idea, idea]
        novelty = FakeAgent("novelty")
        novelty.llm.responses = [
            'THOUGHT: Existing work overlaps. Decision made: not novel.\nRESPONSE:\n```json\n{}\n```'
        ]
        agents = {
            name: FakeAgent(name)
            for name in [
                "researcher", "scientist", "experimenter", "writer", "citation_researcher",
                "reviewer_a", "reviewer_b", "reviewer_c", "reviewer_d", "reviewer_e",
                "meta_reviewer", "synthesizer",
            ]
        }
        agents.update({"ideator": ideator, "novelty": novelty})
        harness = self.load(
            "ai_scientist_replica",
            agents,
        )
        harness.config["pipeline"]["context"]["generation_slots"] = [1]

        result = self.ask(harness, "generate one bounded idea")

        self.assertEqual(result.result["status"], "no_novel_idea")
        self.assertEqual(ideator.llm.calls, 3)
        self.assertEqual(novelty.llm.calls, 1)
        self.assertEqual(result.result["novelty_results"][0]["rounds"], 1)

    def test_ai_scientist_novelty_contract_is_sequential_and_defaults_not_novel_after_ten_rounds(self):
        critic = FakeAgent("critic")
        critic.llm.responses = [
            f'THOUGHT: More evidence is required.\nRESPONSE:\n```json\n{{"Query":"query {index}"}}\n```'
            for index in range(1, 11)
        ]
        researcher = FakeAgent("researcher", ["No authoritative overlap found."])
        harness = self.load(
            "ai_scientist_novelty_worker",
            {"critic": critic, "researcher": researcher},
        )

        result = self.ask(harness, '{"Name":"bounded_novelty","Experiment":"test"}')

        self.assertFalse(result.result["novel"])
        self.assertFalse(result.result["decision_made"])
        self.assertEqual(result.result["rounds"], 10)
        self.assertEqual(len(result.result["searches"]), 10)
        self.assertEqual(critic.llm.calls, 10)
        self.assertEqual([item["query"] for item in result.result["searches"]], [f"query {index}" for index in range(1, 11)])

    def test_ai_scientist_experiment_contract_retries_one_failed_run_at_most_four_times(self):
        coder = FakeAgent("coder", ["repair attempted"])
        harness = self.load("ai_scientist_experiment_run_worker", {"coder": coder})
        harness.config["pipeline"]["context"]["experiment_run"] = {
            "id": "run_1",
            "purpose": "failing experiment",
            "command": sys.executable,
            "args": ["-c", "raise SystemExit(2)"],
            "cwd": ".",
            "resources": {"cpu": 1},
        }

        result = self.ask(harness, "run and repair the experiment")

        self.assertFalse(result.result["success"])
        self.assertEqual(result.result["attempts"], 4)
        self.assertEqual(len(result.result["history"]), 4)
        self.assertEqual(result.stats.process_calls, 4)
        self.assertEqual(result.result["process"]["exit_code"], 2)


if __name__ == "__main__":
    unittest.main()
