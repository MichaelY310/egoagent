import json
import tempfile
import unittest
from pathlib import Path

from context_policy import (
    apply_context_decisions,
    apply_pressure_compaction,
    compress_tool_observation,
    context_blocks,
    conversation_turns,
    pressure_budget,
    restore_full_context,
    review_batch,
)
from harness import Session
from pipeline_engine import _prune_oldest_conversation_message


def user(text):
    return {"role": "user", "content": text}


def assistant(text):
    return {"role": "assistant", "content": text}


class ContextPolicyTests(unittest.TestCase):
    def test_review_runs_in_five_turn_batches_and_protects_recent_turns(self):
        messages = []
        for index in range(8):
            messages.extend([user(f"question {index}"), assistant(f"answer {index}")])
        batch = review_batch(messages, interval=5, protect_recent=2)
        self.assertEqual(len(batch), 5)
        protected_text = " ".join(message["content"] for turn in batch for message in turn.messages)
        self.assertNotIn("question 7", protected_text)
        self.assertNotIn("question 6", protected_text)

    def test_elision_is_a_working_view_only_and_is_reversible(self):
        messages = [
            {"role": "system", "content": "project rules"},
            user("unrelated weather question"),
            assistant("sunny"),
            user("edit src/app.py"),
            assistant("working"),
            user("continue"),
        ]
        turns = conversation_turns(messages)
        unrelated = next(turn for turn in turns if any("weather" in message.get("content", "") for message in turn.messages))
        result = apply_context_decisions(
            messages,
            [{"turn_id": unrelated.id, "action": "elide", "reason": "project_irrelevant"}],
            protect_recent=1,
        )
        working_text = json.dumps(result["messages"], ensure_ascii=False)
        audit_text = json.dumps(result["full_messages"], ensure_ascii=False)
        self.assertNotIn("weather", working_text)
        self.assertIn("weather", audit_text)
        self.assertIn('"status": "elided"', audit_text)
        restored = restore_full_context(result["full_messages"])
        self.assertIn("weather", json.dumps(restored, ensure_ascii=False))
        self.assertNotIn("_context", json.dumps(restored, ensure_ascii=False))

    def test_summary_carries_exact_paths_and_errors(self):
        messages = [
            user("fix C:\\repo\\src\\app.py"),
            assistant("Tool failed with Error: syntax failure in C:\\repo\\src\\app.py"),
            user("continue current task"),
        ]
        target = conversation_turns(messages)[0]
        result = apply_context_decisions(
            messages,
            [{"turn_id": target.id, "action": "summarize", "reason": "verbose", "summary": "A fix was attempted."}],
            protect_recent=1,
        )
        summary = result["messages"][0]["content"]
        self.assertIn("C:\\repo\\src\\app.py", summary)
        self.assertIn("Error: syntax failure", summary)

    def test_large_tool_output_keeps_protocol_and_audit_original(self):
        observation = "header\n" + ("ordinary output\n" * 300) + "Error: failed at src/main.py\nlast"
        message = {
            "role": "user",
            "content": f'<tool_response>{json.dumps({"tool": "run", "tool_call_id": "1", "content": observation})}</tool_response>',
        }
        compressed, annotation = compress_tool_observation(message, max_chars=500)
        self.assertIsNotNone(annotation)
        self.assertIn("<tool_response>", compressed["content"])
        self.assertIn("src/main.py", compressed["content"])
        result = apply_context_decisions([message, user("next")], protect_recent=1, max_tool_chars=500)
        audit_payload = json.loads(result["full_messages"][0]["content"].split("<tool_response>", 1)[1].split("</tool_response>", 1)[0])
        self.assertEqual(audit_payload["content"], observation)

    def test_auto_compaction_prunes_oldest_not_latest(self):
        messages = [
            {"role": "system", "content": "rules"},
            user("old requirement"), assistant("old answer"),
            user("LATEST REQUIREMENT"), assistant("latest answer"),
        ]
        pruned = _prune_oldest_conversation_message(messages)
        serialized = json.dumps(pruned)
        self.assertNotIn("old requirement", serialized)
        self.assertIn("LATEST REQUIREMENT", serialized)
        self.assertEqual(pruned[0]["role"], "system")

    def test_session_round_trip_restores_full_messages_and_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            session = Session(save_dir=Path(directory))
            message = user("hello")
            session.record(message)
            session.record_full(message.copy())
            result = apply_context_decisions(session.full_messages)
            session.apply_context_result(result)
            session.save()
            loaded = Session()
            loaded.load(directory)
            self.assertEqual(len(loaded.full_messages), 1)
            self.assertIn("context_governance", loaded.state)

    def test_long_project_reduction_preserves_decisions_and_restores_everything(self):
        long_log = "ordinary compiler output\n" * 500 + "Error: failed in src/ir/compiler.py\n"
        messages = [{"role": "system", "content": "Never edit outside C:\\project."}]
        messages.extend([
            user("The architecture decision is to keep port 7319 and edit src/ir/compiler.py."),
            assistant("Recorded the port and target file."),
            user("What is the weather today?"),
            assistant("Sunny; this is unrelated to the project."),
            user("Tell me a joke."),
            assistant("A short unrelated joke."),
            user("Run the compiler and inspect the failure."),
            {"role": "user", "content": f'<tool_response>{json.dumps({"tool": "run", "tool_call_id": "long-1", "content": long_log})}</tool_response>'},
            user("We resolved the formatting discussion; the durable decision remains port 7319."),
            assistant("Acknowledged."),
            user("Continue the current compiler task without changing its port."),
        ])
        turns = conversation_turns(messages)
        decisions = []
        for turn in turns:
            text = " ".join(str(message.get("content", "")) for message in turn.messages)
            if "weather" in text or "joke" in text:
                decisions.append({"turn_id": turn.id, "action": "elide", "reason": "project_irrelevant"})
            elif "architecture decision" in text:
                decisions.append({
                    "turn_id": turn.id,
                    "action": "summarize",
                    "reason": "retain_decision",
                    "summary": "Compiler work uses port 7319 and targets src/ir/compiler.py.",
                })
        result = apply_context_decisions(messages, decisions, protect_recent=1, max_tool_chars=600)
        working = json.dumps(result["messages"], ensure_ascii=False)
        self.assertIn("7319", working)
        self.assertIn("src/ir/compiler.py", working)
        self.assertIn("Error: failed", working)
        self.assertNotIn("weather", working)
        self.assertGreater(result["stats"]["reduction_ratio"], 0.7)
        restored_messages = restore_full_context(result["full_messages"])
        restored = json.dumps(restored_messages, ensure_ascii=False)
        self.assertIn("What is the weather today?", restored)
        restored_tool = next(message for message in restored_messages if "<tool_response>" in message["content"])
        restored_payload = json.loads(
            restored_tool["content"].split("<tool_response>", 1)[1].split("</tool_response>", 1)[0]
        )
        self.assertEqual(restored_payload["content"], long_log)

    def test_pressure_trigger_is_runtime_owned_and_reserves_output_space(self):
        short = [user("small request"), assistant("small answer")]
        self.assertFalse(pressure_budget(short, context_limit_tokens=4096)["triggered"])
        long = [user("important project context " * 500)]
        budget = pressure_budget(
            long,
            context_limit_tokens=2048,
            high_watermark=0.7,
            target_ratio=0.45,
            reserved_output_tokens=256,
        )
        self.assertTrue(budget["triggered"])
        self.assertLess(budget["target_tokens"], budget["threshold_tokens"])
        self.assertEqual(budget["threshold_tokens"], int(2048 * 0.7))

    def test_pressure_blocks_keep_tool_call_and_result_together(self):
        messages = [
            user("inspect the project"),
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "call-1", "function": {"name": "search_files", "arguments": "{}"}}],
            },
            {"role": "user", "content": '<tool_response>{"tool":"search_files","tool_call_id":"call-1","content":"result"}</tool_response>'},
            user("continue"),
        ]
        blocks = context_blocks(messages, protect_recent_turns=1)
        exchange = next(block for block in blocks if block.kind == "tool_exchange")
        self.assertEqual(len(exchange.messages), 2)
        self.assertEqual([message["role"] for message in exchange.messages], ["assistant", "user"])

    def test_model_authored_pressure_plan_simplifies_pre_aha_reasoning_and_restores_original(self):
        raw_tool = "search miss\n" * 250 + "Error: old failure in src/index.py\nresolved by src/search.py"
        messages = [
            {"role": "system", "content": "Keep project rules."},
            user("Use port 7319 and implement semantic search in src/search.py."),
            {
                "role": "assistant",
                "content": "The decisive result was to use RRF.",
                "reasoning_content": "boilerplate exploration " * 500 + "Aha: lexical and vector ranks must be fused with RRF.",
            },
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "call-2", "function": {"name": "search_files", "arguments": '{"query":"retrieval"}'}}],
            },
            {"role": "user", "content": f'<tool_response>{json.dumps({"tool": "search_files", "tool_call_id": "call-2", "content": raw_tool})}</tool_response>'},
            user("Continue and do not change port 7319."),
        ]
        blocks = context_blocks(messages, protect_recent_turns=1)
        requirement = next(block for block in blocks if block.kind == "user_requirement" and not block.protected)
        reasoning = next(block for block in blocks if block.kind == "assistant_reasoning")
        exchange = next(block for block in blocks if block.kind == "tool_exchange")
        plan = {
            "blocks": [
                {"block_id": requirement.id, "action": "summarize", "reason": "durable requirement", "summary": "User requires port 7319 and semantic search in src/search.py."},
                {"block_id": reasoning.id, "action": "simplify_reasoning", "reason": "pre-aha exploration", "summary": "The decisive ranking insight was retained."},
                {"block_id": exchange.id, "action": "summarize", "reason": "resolved repeated searches", "summary": "search_files found the implementation direction in src/search.py after an old resolved failure in src/index.py."},
            ],
            "continuation_summary": "Use port 7319; implement semantic search in src/search.py with RRF; the src/index.py failure is resolved.",
        }
        result = apply_pressure_compaction(messages, plan, target_tokens=1000, protect_recent_turns=1)
        working = json.dumps(result["messages"], ensure_ascii=False)
        audit = json.dumps(result["full_messages"], ensure_ascii=False)
        self.assertIn("port 7319", working)
        self.assertIn("src/search.py", working)
        self.assertIn("RRF", working)
        self.assertNotIn("boilerplate exploration boilerplate exploration", working)
        self.assertNotIn("search miss\\nsearch miss\\nsearch miss", working)
        self.assertIn("boilerplate exploration", audit)
        self.assertIn("search miss", audit)
        self.assertGreater(result["stats"]["reduction_ratio"], 0.8)
        restored_messages = restore_full_context(result["full_messages"])
        restored = json.dumps(restored_messages, ensure_ascii=False)
        self.assertIn("Aha: lexical and vector ranks", restored)
        restored_tool = next(message for message in restored_messages if "<tool_response>" in message.get("content", ""))
        restored_payload = json.loads(restored_tool["content"].split("<tool_response>", 1)[1].split("</tool_response>", 1)[0])
        self.assertEqual(restored_payload["content"], raw_tool)


if __name__ == "__main__":
    unittest.main()
