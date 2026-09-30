import json
import unittest

from llm.custom_llm import CustomLLM


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "parameters": {"type": "object", "properties": {}},
        },
    }
]


class TextToolFallbackTests(unittest.TestCase):
    def test_recovers_one_known_fenced_call(self):
        call = CustomLLM._recover_text_tool_call(
            {
                "content": "I will run it.\n```json\n"
                '{"name":"run_command","arguments":{"command":"pytest"}}'
                "\n```"
            },
            TOOLS,
        )
        self.assertEqual(call["function"]["name"], "run_command")
        self.assertEqual(json.loads(call["function"]["arguments"]), {"command": "pytest"})

    def test_rejects_unknown_tool(self):
        call = CustomLLM._recover_text_tool_call(
            {"content": '```json\n{"name":"delete_everything","arguments":{}}\n```'},
            TOOLS,
        )
        self.assertIsNone(call)

    def test_rejects_ambiguous_multiple_blocks(self):
        block = '```json\n{"name":"run_command","arguments":{"command":"pytest"}}\n```'
        self.assertIsNone(CustomLLM._recover_text_tool_call({"content": block + block}, TOOLS))

    def test_rejects_extra_fields(self):
        call = CustomLLM._recover_text_tool_call(
            {
                "content": "```json\n"
                '{"name":"run_command","arguments":{},"approved":true}'
                "\n```"
            },
            TOOLS,
        )
        self.assertIsNone(call)


if __name__ == "__main__":
    unittest.main()
