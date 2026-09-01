"""长期记忆测试：MemoryStore 读写、memory 工具、agent 注入 system prompt。"""
import tempfile
import unittest

from agent.agent import CodingAgent
from agent.config import Config
from agent.memory import MemoryStore, make_memory_tool


class MemoryStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = MemoryStore(self._tmp.name)

    def test_add_and_load(self):
        self.store.add("项目使用 DeepSeek API")
        self.assertEqual(self.store.load(), "项目使用 DeepSeek API")

    def test_add_appends(self):
        self.store.add("第一条约")
        self.store.add("第二条约")
        out = self.store.load()
        self.assertIn("第一条约", out)
        self.assertIn("第二条约", out)

    def test_replace(self):
        self.store.add("版本是 1.0")
        self.store.replace("1.0", "2.0")
        self.assertEqual(self.store.load(), "版本是 2.0")

    def test_replace_missing(self):
        self.store.add("hello")
        out = self.store.replace("zzz", "x")
        self.assertIn("未在记忆中找到", out)

    def test_clear_removes_file(self):
        self.store.add("hello")
        self.store.clear()
        self.assertEqual(self.store.load(), "")
        self.assertFalse(self.store.path.exists())

    def test_load_missing_returns_empty(self):
        self.assertEqual(self.store.load(), "")


class MemoryToolTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tool = make_memory_tool(MemoryStore(self._tmp.name))

    def test_add(self):
        out = self.tool.handler({"action": "add", "content": "约定 A"})
        self.assertIn("已追加", out)

    def test_clear(self):
        out = self.tool.handler({"action": "clear"})
        self.assertIn("已清空", out)

    def test_unknown_action(self):
        out = self.tool.handler({"action": "nope"})
        self.assertIn("未知 action", out)

    def test_add_requires_content(self):
        out = self.tool.handler({"action": "add"})
        self.assertIn("需要 content", out)


class MemoryInjectionTest(unittest.TestCase):
    def test_memory_injected_into_system_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            MemoryStore(tmp).add("用户偏好：用 pytest 写测试")
            # 传假 key：绕过 openai 2.x 空 api_key 构造报错
            agent = CodingAgent(Config(api_key="test-key", working_dir=tmp))
            self.assertIn("长期记忆", agent.history.system_prompt)
            self.assertIn("用 pytest 写测试", agent.history.system_prompt)

    def test_no_memory_section_when_file_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = CodingAgent(Config(api_key="test-key", working_dir=tmp))
            self.assertNotIn("长期记忆", agent.history.system_prompt)

    def test_memory_tool_registered(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = CodingAgent(Config(api_key="test-key", working_dir=tmp))
            schemas = agent.tools.schemas()
            names = [s["function"]["name"] for s in schemas]
            self.assertIn("memory", names)


if __name__ == "__main__":
    unittest.main()
