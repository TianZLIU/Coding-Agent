"""上下文管理免费层（L1/L2/L3）测试：cheap-first 四层管线。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.history import RECENT_RESULTS, ConversationHistory


def big_result(n: int = 5000) -> str:
    return "x" * n


class L3OffloadTest(unittest.TestCase):
    def test_large_result_offloaded_to_disk(self):
        with tempfile.TemporaryDirectory() as d:
            results_dir = Path(d) / ".agent_results"
            h = ConversationHistory("SYS", 100000, results_dir=results_dir)
            h.add_user("task")
            h.add_assistant_tool_call([{"id": "c1", "name": "read_file", "arguments": "{}"}])
            h.add_tool_result("c1", "read_file", big_result())
            out = h.build()
            tool_msg = next(m for m in out if m["role"] == "tool")
            # 视图里只留句柄 + 预览，不塞全文
            self.assertIn("[persisted-output]", tool_msg["content"])
            self.assertNotIn("x" * 5000, tool_msg["content"])
            # 非破坏：self.messages 仍保留全文
            self.assertEqual(h.messages[-1]["content"], "x" * 5000)
            # 落盘文件确实写了
            persisted = results_dir / "c1.txt"
            self.assertTrue(persisted.exists())
            self.assertEqual(persisted.read_text(encoding="utf-8"), "x" * 5000)

    def test_small_result_not_offloaded(self):
        with tempfile.TemporaryDirectory() as d:
            h = ConversationHistory("SYS", 100000, results_dir=Path(d) / ".agent_results")
            h.add_user("task")
            h.add_assistant_tool_call([{"id": "c1", "name": "read_file", "arguments": "{}"}])
            h.add_tool_result("c1", "read_file", "short")
            out = h.build()
            tool_msg = next(m for m in out if m["role"] == "tool")
            self.assertEqual(tool_msg["content"], "short")

    def test_no_results_dir_skips_l3(self):
        h = ConversationHistory("SYS", 100000)  # results_dir=None → 禁用 L3
        h.add_user("task")
        h.add_assistant_tool_call([{"id": "c1", "name": "read_file", "arguments": "{}"}])
        h.add_tool_result("c1", "read_file", big_result())
        out = h.build()
        tool_msg = next(m for m in out if m["role"] == "tool")
        self.assertEqual(tool_msg["content"], "x" * 5000)


class L2PlaceholderTest(unittest.TestCase):
    def test_old_results_compacted_recent_kept(self):
        h = ConversationHistory("SYS", 100000)
        h.add_user("task")
        for i in range(RECENT_RESULTS + 3):
            cid = f"c{i}"
            h.add_assistant_tool_call([{"id": cid, "name": "list_dir", "arguments": "{}"}])
            h.add_tool_result(cid, "list_dir", f"result {i}")
        out = h.build()
        tool_msgs = [m for m in out if m["role"] == "tool"]
        # 最老的前 3 条被占位，最近 RECENT_RESULTS 条保留
        self.assertEqual(tool_msgs[0]["content"], "[Earlier tool result compacted]")
        self.assertEqual(tool_msgs[-1]["content"], f"result {RECENT_RESULTS + 2}")
        # tool_call_id 保留（配对不变式）
        self.assertEqual(tool_msgs[0]["tool_call_id"], "c0")
        # 非破坏：self.messages 原文未动
        self.assertEqual(h.messages[2]["content"], "result 0")
        self.assertEqual(h.messages[-1]["content"], f"result {RECENT_RESULTS + 2}")

    def test_large_old_result_keeps_handle_not_placeholder(self):
        # 大结果即使变旧，L3 的落盘句柄也应保留，不被 L2 占位覆盖（可恢复 > 不可恢复）
        with tempfile.TemporaryDirectory() as d:
            h = ConversationHistory("SYS", 100000, results_dir=Path(d) / ".agent_results")
            h.add_user("task")
            for i in range(RECENT_RESULTS + 1):
                cid = f"c{i}"
                h.add_assistant_tool_call([{"id": cid, "name": "read_file", "arguments": "{}"}])
                content = big_result() if i == 0 else f"r{i}"
                h.add_tool_result(cid, "read_file", content)
            out = h.build()
            first_tool = next(m for m in out if m["role"] == "tool")
            self.assertIn("[persisted-output]", first_tool["content"])


class L1CutMiddleTest(unittest.TestCase):
    def test_middle_snipped_head_tail_kept(self):
        h = ConversationHistory("SYS", 100000)
        h.add_user("task 0")
        for i in range(24):
            cid = f"c{i}"
            h.add_assistant_tool_call([{"id": cid, "name": "list_dir", "arguments": "{}"}])
            h.add_tool_result(cid, "list_dir", f"r{i}")
        h.add_assistant_text("done")
        self.assertGreater(len(h.messages), 40)
        out = h.build()
        # 中间被裁，出现 snipped 占位
        self.assertTrue(
            any("[snipped" in m.get("content", "") for m in out if m["role"] == "user")
        )
        # 头尾保留
        self.assertEqual(out[1]["content"], "task 0")
        self.assertEqual(out[-1]["content"], "done")

    def test_l1_preserves_pairing(self):
        h = ConversationHistory("SYS", 100000)
        h.add_user("task 0")
        for i in range(24):
            cid = f"c{i}"
            h.add_assistant_tool_call([{"id": cid, "name": "list_dir", "arguments": "{}"}])
            h.add_tool_result(cid, "list_dir", f"r{i}")
        h.add_assistant_text("done")
        out = h.build()
        for i, m in enumerate(out):
            if m["role"] == "assistant" and m.get("tool_calls"):
                self.assertEqual(out[i + 1]["role"], "tool")


if __name__ == "__main__":
    unittest.main()
