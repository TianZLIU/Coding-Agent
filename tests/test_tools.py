"""tools 的单元测试：文件工具与命令执行工具。"""
from __future__ import annotations

import os
import tempfile
import unittest

from agent.tools.files import make_file_tools
from agent.tools.shell import make_shell_tool


class FileToolsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.wd = self._tmp.name
        self.tools = {t.name: t for t in make_file_tools(self.wd, 12000)}

    def _call(self, name, args):
        return self.tools[name].handler(args)

    def test_write_and_read_file(self):
        self._call("write_file", {"path": "a.txt", "content": "hello\nworld\n"})
        out = self._call("read_file", {"path": "a.txt"})
        self.assertIn("hello", out)
        self.assertIn("world", out)
        self.assertIn("1|", out)  # 带行号

    def test_read_file_line_range(self):
        self._call("write_file", {"path": "a.txt", "content": "l1\nl2\nl3\nl4\n"})
        out = self._call("read_file", {"path": "a.txt", "start_line": 2, "end_line": 3})
        self.assertIn("l2", out)
        self.assertIn("l3", out)
        self.assertNotIn("l1", out)
        self.assertNotIn("l4", out)

    def test_write_file_creates_parent_dirs(self):
        self._call("write_file", {"path": "sub/dir/deep.txt", "content": "x"})
        self.assertTrue(os.path.exists(os.path.join(self.wd, "sub", "dir", "deep.txt")))

    def test_list_dir(self):
        self._call("write_file", {"path": "a.txt", "content": "x"})
        os.mkdir(os.path.join(self.wd, "sub"))
        out = self._call("list_dir", {"path": "."})
        self.assertIn("a.txt", out)
        self.assertIn("sub", out)

    def test_edit_file_replaces_unique_old(self):
        self._call("write_file", {"path": "a.txt", "content": "AAA BBB"})
        out = self._call("edit_file", {"path": "a.txt", "old_string": "AAA", "new_string": "CCC"})
        self.assertIn("已成功修改", out)
        with open(os.path.join(self.wd, "a.txt"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "CCC BBB")

    def test_edit_file_errors_on_duplicate(self):
        self._call("write_file", {"path": "a.txt", "content": "AAA AAA"})
        out = self._call("edit_file", {"path": "a.txt", "old_string": "AAA", "new_string": "X"})
        self.assertIn("出现 2 次", out)

    def test_edit_file_errors_on_missing(self):
        self._call("write_file", {"path": "a.txt", "content": "hello"})
        out = self._call("edit_file", {"path": "a.txt", "old_string": "zzz", "new_string": "X"})
        self.assertIn("未在文件中找到", out)

    def test_glob_files(self):
        self._call("write_file", {"path": "x.py", "content": "1"})
        self._call("write_file", {"path": "y.txt", "content": "2"})
        out = self._call("glob_files", {"pattern": "*.py"})
        self.assertIn("x.py", out)
        self.assertNotIn("y.txt", out)


class ShellToolTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tool = make_shell_tool(self._tmp.name, 12000)

    def _call(self, args):
        return self.tool.handler(args)

    def test_runs_simple_command(self):
        out = self._call({"command": "echo hello123"})
        self.assertIn("hello123", out)
        self.assertIn("退出码 0", out)

    def test_intercepts_dangerous_command(self):
        for cmd in ["rm -rf /tmp/foo", "git push --force origin main", "shutdown -h now"]:
            out = self._call({"command": cmd})
            self.assertIn("已拦截", out)

    def test_allow_dangerous_bypasses_interception(self):
        out = self._call({"command": "rm -rf __nonexistent_dir_123__", "allow_dangerous": True})
        self.assertNotIn("已拦截", out)


if __name__ == "__main__":
    unittest.main()
