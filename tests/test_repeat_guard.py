"""重复调用护栏测试。

验证 agent 连续多次用同一工具同一参数时，会在工具结果前注入提示，
打断模型的「重试死循环」（配合 max_iterations 硬上限，双保险）。
"""
import tempfile
import unittest

from agent.agent import CodingAgent
from agent.config import Config
from agent.llm import ChatResponse
from agent.usage import CostStats


class _FakeLLM:
    """按脚本依次返回响应，避免真实调用 DeepSeek API。"""

    def __init__(self, responses):
        self._responses = list(responses)
        self.cost = CostStats()

    def chat(self, messages, tools):
        return self._responses.pop(0)


def _tool_call(call_id: str, name: str, arguments: str) -> dict:
    return {"id": call_id, "name": name, "arguments": arguments}


class RepeatGuardTest(unittest.TestCase):
    def test_repeated_identical_call_injects_hint_on_third(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = CodingAgent(Config(api_key="test-key", working_dir=tmp))
            write = '{"path": "a.txt", "content": "AAA"}'
            agent.llm = _FakeLLM([
                ChatResponse(content="", tool_calls=[_tool_call("c1", "write_file", write)]),
                ChatResponse(content="", tool_calls=[_tool_call("c2", "write_file", write)]),
                ChatResponse(content="", tool_calls=[_tool_call("c3", "write_file", write)]),
                ChatResponse(content="完成", tool_calls=[]),
            ])

            result = agent.run("写文件")

            tool_msgs = [m for m in agent.history.messages if m["role"] == "tool"]
            self.assertEqual(len(tool_msgs), 3)
            self.assertNotIn("重复调用护栏", tool_msgs[0]["content"])
            self.assertNotIn("重复调用护栏", tool_msgs[1]["content"])
            self.assertIn("重复调用护栏", tool_msgs[2]["content"])
            self.assertEqual(result.answer, "完成")

    def test_different_arguments_reset_repeat_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = CodingAgent(Config(api_key="test-key", working_dir=tmp))
            agent.llm = _FakeLLM([
                ChatResponse(content="", tool_calls=[_tool_call("c1", "write_file", '{"path": "a.txt", "content": "A"}')]),
                ChatResponse(content="", tool_calls=[_tool_call("c2", "write_file", '{"path": "a.txt", "content": "B"}')]),
                ChatResponse(content="", tool_calls=[_tool_call("c3", "write_file", '{"path": "a.txt", "content": "C"}')]),
                ChatResponse(content="完成", tool_calls=[]),
            ])

            agent.run("写文件")

            tool_msgs = [m for m in agent.history.messages if m["role"] == "tool"]
            self.assertEqual(len(tool_msgs), 3)
            for m in tool_msgs:
                self.assertNotIn("重复调用护栏", m["content"])


if __name__ == "__main__":
    unittest.main()
