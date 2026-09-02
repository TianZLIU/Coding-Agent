"""SessionStore 会话管理测试。

验证会话的 保存 / 列表 / 恢复 / 删除、标题提取与损坏文件容错。
"""
import json
import tempfile
import unittest
from pathlib import Path

from agent.sessions import SessionStore


class SessionStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = SessionStore(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    @staticmethod
    def _history() -> dict:
        return {"system_prompt": "s", "budget_tokens": 100, "summaries": [], "messages": []}

    def test_save_list_load_roundtrip(self):
        msgs = [
            {"role": "user", "content": "写个快速排序"},
            {"role": "assistant", "content": "完成"},
        ]
        name = self.store.new_name()
        self.store.save(name, msgs, self._history())

        items = self.store.list()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["name"], name)
        self.assertEqual(items[0]["title"], "写个快速排序")
        self.assertEqual(items[0]["message_count"], 2)

        data = self.store.load(name)
        self.assertEqual(data["messages"], msgs)
        self.assertEqual(data["history"]["budget_tokens"], 100)

    def test_title_truncated(self):
        long_title = "这是" + "很长" * 20 + "的标题"
        name = self.store.new_name()
        self.store.save(name, [{"role": "user", "content": long_title}], self._history())
        title = self.store.list()[0]["title"]
        self.assertLessEqual(len(title), 25)  # 24 字 + 省略号

    def test_delete(self):
        name = self.store.new_name()
        self.store.save(name, [{"role": "user", "content": "hi"}], self._history())
        self.store.delete(name)
        self.assertEqual(self.store.list(), [])

    def test_list_sorted_by_updated_desc(self):
        for content in ("first", "second"):
            self.store.save(
                self.store.new_name(),
                [{"role": "user", "content": content}],
                self._history(),
            )
        items = self.store.list()
        self.assertEqual(items[0]["title"], "second")
        self.assertEqual(items[1]["title"], "first")

    def test_corrupt_file_skipped(self):
        (Path(self._tmp.name) / "bad.json").write_text("{not json", encoding="utf-8")
        name = self.store.new_name()
        self.store.save(name, [{"role": "user", "content": "ok"}], self._history())
        items = self.store.list()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "ok")

    def test_saved_file_is_valid_json(self):
        name = self.store.new_name()
        self.store.save(name, [{"role": "user", "content": "x"}], self._history())
        raw = (Path(self._tmp.name) / f"{name}.json").read_text(encoding="utf-8")
        payload = json.loads(raw)
        self.assertIn("title", payload)
        self.assertIn("history", payload)
        self.assertIn("messages", payload)


if __name__ == "__main__":
    unittest.main()
