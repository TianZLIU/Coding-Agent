"""CodingAgent 的 REPL 命令测试：/compact（手动压缩）与 /clear（清空对话）。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

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


class CompactTest(unittest.TestCase):
    def test_compact_keeps_first_user_and_summarizes(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = CodingAgent(Config(api_key="test-key", working_dir=tmp))
            agent.llm = _FakeLLM([ChatResponse(content="<summary>压缩后的摘要</summary>", tool_calls=[])])
            agent.history.add_user("原始任务")
            agent.history.add_assistant_text("中间过程")
            agent.history.add_user("继续")
            agent.history.add_assistant_text("完成")

            r = agent.compact()

            self.assertFalse(r["skipped"])
            self.assertEqual(r["message_count_before"], 4)
            self.assertEqual(r["summary"], "压缩后的摘要")
            # 只保留首条 user 指令 + 摘要累积
            self.assertEqual(agent.history.messages, [{"role": "user", "content": "原始任务"}])
            self.assertEqual(agent.history.summaries[-1], "压缩后的摘要")
            # 压缩后 token 应下降
            self.assertLess(r["after_tokens"], r["before_tokens"])

    def test_compact_skips_when_only_one_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = CodingAgent(Config(api_key="test-key", working_dir=tmp))
            agent.history.add_user("唯一任务")
            r = agent.compact()
            self.assertTrue(r["skipped"])
            self.assertEqual(agent.history.messages, [{"role": "user", "content": "唯一任务"}])
            self.assertEqual(agent.history.summaries, [])


class ClearTest(unittest.TestCase):
    def test_clear_resets_conversation(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = CodingAgent(Config(api_key="test-key", working_dir=tmp))
            agent.history.add_user("任务")
            agent.history.add_assistant_text("回答")
            agent.history.summaries.append("旧摘要")
            agent.clear()
            self.assertEqual(agent.history.messages, [])
            self.assertEqual(agent.history.summaries, [])

    def test_clear_removes_offloaded_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            results_dir = Path(tmp) / ".agent_results"
            results_dir.mkdir()
            (results_dir / "c1.txt").write_text("x", encoding="utf-8")
            agent = CodingAgent(Config(api_key="test-key", working_dir=tmp))
            agent.clear()
            self.assertFalse(any(results_dir.iterdir()))


if __name__ == "__main__":
    unittest.main()
