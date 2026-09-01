"""多工具调用并行执行测试。

验证 agent 在一次模型响应里请求多个工具时，会并行执行、并按请求顺序
回填结果（借助 _FakeLLM 避免真实调用 DeepSeek API）。
"""
import os
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


class ParallelToolsTest(unittest.TestCase):
    def test_multiple_tool_calls_execute_and_backfill_in_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(working_dir=tmp)
            agent = CodingAgent(config)
            agent.llm = _FakeLLM([
                ChatResponse(
                    content="",
                    tool_calls=[
                        {"id": "c1", "name": "write_file", "arguments": '{"path": "a.txt", "content": "AAA"}'},
                        {"id": "c2", "name": "write_file", "arguments": '{"path": "b.txt", "content": "BBB"}'},
                    ],
                ),
                ChatResponse(content="完成", tool_calls=[]),
            ])

            result = agent.run("写两个文件 a.txt 和 b.txt")

            # 两个工具都执行了
            self.assertEqual(result.tool_calls, 2)
            self.assertEqual(result.iterations, 2)
            with open(os.path.join(tmp, "a.txt"), encoding="utf-8") as f:
                self.assertEqual(f.read(), "AAA")
            with open(os.path.join(tmp, "b.txt"), encoding="utf-8") as f:
                self.assertEqual(f.read(), "BBB")

            # 结果按请求顺序回填（先 c1 后 c2），且 tool_call_id 一一对应
            tool_msgs = [m for m in agent.history.messages if m["role"] == "tool"]
            self.assertEqual([m["tool_call_id"] for m in tool_msgs], ["c1", "c2"])
            self.assertEqual([m["name"] for m in tool_msgs], ["write_file", "write_file"])

            self.assertEqual(result.answer, "完成")


if __name__ == "__main__":
    unittest.main()
