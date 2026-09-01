"""tools 的单元测试：文件工具与命令执行工具。"""
from __future__ import annotations

import os
import tempfile
import unittest

from agent.tools.base import Toolbox
from agent.tools.files import _truncate, make_file_tools
from agent.tools.shell import _outside_path, make_shell_tool


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

    def test_grep_substring(self):
        self._call("write_file", {"path": "a.py", "content": "def foo():\n    return 1\nfoo()\n"})
        out = self._call("grep", {"pattern": "foo"})
        self.assertIn("a.py:1:", out)
        self.assertIn("a.py:3:", out)
        self.assertNotIn("return 1", out)

    def test_grep_regex(self):
        self._call("write_file", {"path": "a.py", "content": "x = 1\ny = 2\nz = 3\n"})
        out = self._call("grep", {"pattern": r"^[xy] =", "regex": True})
        self.assertIn("x = 1", out)
        self.assertIn("y = 2", out)
        self.assertNotIn("z = 3", out)

    def test_grep_glob_filter(self):
        self._call("write_file", {"path": "a.py", "content": "needle"})
        self._call("write_file", {"path": "b.txt", "content": "needle"})
        out = self._call("grep", {"pattern": "needle", "glob": "*.py"})
        self.assertIn("a.py", out)
        self.assertNotIn("b.txt", out)

    def test_grep_no_match(self):
        self._call("write_file", {"path": "a.py", "content": "hello"})
        out = self._call("grep", {"pattern": "zzz"})
        self.assertIn("无匹配", out)

    def test_grep_empty_pattern(self):
        out = self._call("grep", {"pattern": ""})
        self.assertIn("不能为空", out)

    def test_path_escape_is_rejected(self):
        """越出 working_dir 的绝对路径应被拒绝（sandbox 化）。"""
        outside = os.path.join(os.path.dirname(self.wd), "outside.txt")
        with self.assertRaises(ValueError):
            self._call("read_file", {"path": outside})

    def test_read_only_flags(self):
        for name in ("list_dir", "read_file", "glob_files", "grep"):
            self.assertTrue(self.tools[name].read_only, name)
        for name in ("write_file", "edit_file"):
            self.assertFalse(self.tools[name].read_only, name)

    def test_toolbox_is_read_only(self):
        box = Toolbox(list(self.tools.values()))
        self.assertTrue(box.is_read_only("read_file"))
        self.assertFalse(box.is_read_only("write_file"))
        self.assertFalse(box.is_read_only("unknown"))

    def test_truncate_keeps_head_and_tail(self):
        text = "HEAD\n" + "\n".join(f"line{i}" for i in range(1000)) + "\nTAIL"
        out = _truncate(text, 200)
        self.assertIn("HEAD", out)
        self.assertIn("TAIL", out)  # 尾部（如 traceback 末行）被保留
        self.assertIn("中间省略", out)
        self.assertLessEqual(len(out), 200)

    def test_truncate_passthrough_when_short(self):
        self.assertEqual(_truncate("short", 100), "short")


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

    def test_command_with_outside_path_is_intercepted(self):
        out = self._call({"command": "cat ../outside.txt"})
        self.assertIn("已拦截", out)

    def test_run_command_is_not_read_only(self):
        self.assertFalse(self.tool.read_only)


class PathGuardTest(unittest.TestCase):
    """shell 层路径越界防护：_outside_path 纯函数。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.wd = self._tmp.name

    def test_absolute_path_outside_detected(self):
        self.assertIsNotNone(_outside_path(self.wd, "cat /etc/passwd"))

    def test_parent_dir_detected(self):
        self.assertIsNotNone(_outside_path(self.wd, "cat ../secret.txt"))

    def test_home_dir_detected(self):
        self.assertIsNotNone(_outside_path(self.wd, "cat ~/.ssh/id_rsa"))

    def test_url_not_detected(self):
        self.assertIsNone(_outside_path(self.wd, "git clone https://github.com/x/y.git"))

    def test_relative_path_not_detected(self):
        self.assertIsNone(_outside_path(self.wd, "python script.py"))

    def test_inside_absolute_path_ok(self):
        inside = os.path.join(self.wd, "ok.txt")
        self.assertIsNone(_outside_path(self.wd, f"cat {inside}"))


if __name__ == "__main__":
    unittest.main()
