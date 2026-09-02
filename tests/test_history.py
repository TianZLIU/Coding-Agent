"""history.py 的单元测试：对话历史、token 裁剪、摘要压缩、持久化。"""
from __future__ import annotations

import os
import tempfile
import unittest

from agent.history import RECENT_RESULTS, ConversationHistory, estimate_tokens


def make_round(n: int) -> list[dict]:
    """构造一轮完整的 user -> assistant(tool_call) -> tool 消息。"""
    return [
        {"role": "user", "content": f"user task {n}: read the file"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": f"c{n}",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": f"c{n}",
            "name": "read_file",
            "content": "line1 line2 line3",
        },
    ]


class EstimateTokensTest(unittest.TestCase):
    def test_ascii_roughly_4_chars_per_token(self):
        self.assertEqual(estimate_tokens("abcd"), 1)
        self.assertEqual(estimate_tokens("abcdefgh"), 2)

    def test_cjk_roughly_1_char_per_token(self):
        self.assertEqual(estimate_tokens("中文"), 2)


class ConversationHistoryBuildTest(unittest.TestCase):
    def test_build_prepends_system(self):
        h = ConversationHistory("SYS", 10000)
        h.add_user("hello")
        out = h.build()
        self.assertEqual(out[0], {"role": "system", "content": "SYS"})

    def test_add_helpers_produce_correct_roles(self):
        h = ConversationHistory("SYS", 10000)
        h.add_user("u")
        h.add_assistant_text("a")
        h.add_assistant_tool_call([{"id": "1", "name": "list_dir", "arguments": "{}"}])
        h.add_tool_result("1", "list_dir", "res")
        self.assertEqual([m["role"] for m in h.messages], ["user", "assistant", "assistant", "tool"])
        self.assertEqual(h.messages[2]["tool_calls"][0]["function"]["name"], "list_dir")


class TrimTest(unittest.TestCase):
    def test_keeps_system_and_first_user_when_over_budget(self):
        h = ConversationHistory("SYS", 10)
        h.messages = make_round(1) + make_round(2) + make_round(3)
        out = h.build()
        self.assertEqual(out[0]["role"], "system")
        # 第一条 user 任务必须保留
        self.assertTrue(any(m.get("role") == "user" and "task 1" in m["content"] for m in out))

    def test_trim_preserves_tool_call_pairing(self):
        """裁剪以整轮为单位，不能把 assistant tool_call 与 tool 结果拆散。"""
        h = ConversationHistory("SYS", 10)
        h.messages = make_round(1) + make_round(2) + make_round(3)
        h.build()
        for i, msg in enumerate(h.messages):
            if msg["role"] == "assistant" and msg.get("tool_calls"):
                self.assertEqual(h.messages[i + 1]["role"], "tool")

    def test_tiny_budget_terminates(self):
        """极小预算下（首轮就超预算）必须终止，不无限循环。"""
        h = ConversationHistory("SYS", 1)
        h.messages = make_round(1) + make_round(2) + make_round(3)
        out = h.build()  # 若死循环，测试会超时
        self.assertEqual(out[0]["role"], "system")


class SummarizeTest(unittest.TestCase):
    def test_summarizer_called_and_summary_inserted(self):
        calls = []

        def fake_summarizer(messages):
            calls.append(list(messages))
            return "compressed summary"

        h = ConversationHistory("SYS", 10)
        h.messages = make_round(1) + make_round(2) + make_round(3)
        out = h.build(summarizer=fake_summarizer)
        self.assertGreaterEqual(len(calls), 1)
        self.assertEqual(out[1]["role"], "user")
        self.assertIn("[前面对话摘要]", out[1]["content"])
        self.assertIn("compressed summary", out[1]["content"])

    def test_summarizer_failure_degrades_to_pure_trim(self):
        def boom(messages):
            raise RuntimeError("boom")

        h = ConversationHistory("SYS", 10)
        h.messages = make_round(1) + make_round(2) + make_round(3)
        out = h.build(summarizer=boom)
        self.assertEqual(out[0]["role"], "system")
        self.assertEqual(h.summaries, [])


class UsageAnchorTest(unittest.TestCase):
    def test_record_usage_sets_ratio(self):
        h = ConversationHistory("SYS", 100000)
        h.add_user("hello world")
        h.build()
        self.assertIsNone(h._token_ratio)  # 初始无校准
        h.record_usage(20)
        self.assertIsNotNone(h._token_ratio)
        self.assertGreater(h._token_ratio, 0)

    def test_record_usage_ignores_zero(self):
        h = ConversationHistory("SYS", 100000)
        h.add_user("hello")
        h.build()
        h.record_usage(0)
        self.assertIsNone(h._token_ratio)

    def test_record_usage_calibrates_token_count(self):
        h = ConversationHistory("SYS", 100000)
        h.add_user("hello world")
        h.build()
        chars = h._last_view_chars
        h.record_usage(chars * 2)  # 校准为每字符 2 token
        self.assertEqual(h.token_count(), round(h._current_chars() * 2))


class PersistenceTest(unittest.TestCase):
    def test_save_load_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "session.json")
            h = ConversationHistory("SYS", 56000)
            h.add_user("task 1")
            h.add_assistant_tool_call([{"id": "1", "name": "list_dir", "arguments": "{}"}])
            h.add_tool_result("1", "list_dir", "ok")
            h.summaries.append("summary")
            h.save(path)

            h2 = ConversationHistory.load(path)
            self.assertEqual(h2.system_prompt, "SYS")
            self.assertEqual(h2.budget_tokens, 56000)
            self.assertEqual(h2.summaries, ["summary"])
            self.assertEqual(h2.messages, h.messages)

            # 原子写：目录内不应残留 .tmp 临时文件
            leftovers = [n for n in os.listdir(d) if n.endswith(".tmp")]
            self.assertEqual(leftovers, [])


class ContextStatsTest(unittest.TestCase):
    """context_stats：/context 命令所依赖的只读上下文状态摘要。"""

    def test_baseline_stats(self):
        h = ConversationHistory("SYS", 10000)
        h.add_user("task")
        h.add_assistant_tool_call([{"id": "1", "name": "list_dir", "arguments": "{}"}])
        h.add_tool_result("1", "list_dir", "ok")
        s = h.context_stats()
        self.assertEqual(s["budget_tokens"], 10000)
        self.assertEqual(s["message_count"], 3)
        self.assertEqual(s["roles"], {"user": 1, "assistant": 1, "tool": 1})
        self.assertGreater(s["tokens"], 0)
        self.assertEqual(s["summary_count"], 0)
        self.assertFalse(s["ratio_anchored"])

    def test_detects_large_result_for_l3(self):
        h = ConversationHistory("SYS", 100000)
        h.add_user("task")
        h.add_assistant_tool_call([{"id": "c1", "name": "read_file", "arguments": "{}"}])
        h.add_tool_result("c1", "read_file", "x" * 5000)
        self.assertEqual(h.context_stats()["l3_large_results"], 1)

    def test_detects_l2_compaction_after_many_results(self):
        h = ConversationHistory("SYS", 100000)
        h.add_user("task")
        for i in range(RECENT_RESULTS + 2):
            cid = f"c{i}"
            h.add_assistant_tool_call([{"id": cid, "name": "list_dir", "arguments": "{}"}])
            h.add_tool_result(cid, "list_dir", f"r{i}")
        self.assertEqual(h.context_stats()["l2_compacted"], 2)

    def test_summary_count_reflects_l4(self):
        h = ConversationHistory("SYS", 10)
        h.messages = make_round(1) + make_round(2) + make_round(3)
        h.build(summarizer=lambda msgs: "sum")
        self.assertEqual(h.context_stats()["summary_count"], len(h.summaries))
        self.assertGreater(len(h.summaries), 0)


if __name__ == "__main__":
    unittest.main()
