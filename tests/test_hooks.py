"""可插拔 hook 拦截层（B2）测试。

验证：HookResult 结构、危险命令 hook、路径越界 hook、hook 组合、参数改写
（updated_args）、动态增删 hook（add_hook），以及默认沙箱经 Toolbox.execute 生效。
"""
from __future__ import annotations

import tempfile
import unittest

from agent.hooks import (
    HookResult,
    build_default_hooks,
    make_dangerous_command_hook,
    make_outside_path_hook,
)
from agent.tools.base import Tool, Toolbox
from agent.tools.shell import make_shell_tool


class HookResultTest(unittest.TestCase):
    def test_default_is_allowed(self):
        self.assertTrue(HookResult().allowed)
        self.assertEqual(HookResult().reason, "")

    def test_blocked_carries_reason(self):
        r = HookResult(allowed=False, reason="stop")
        self.assertFalse(r.allowed)
        self.assertEqual(r.reason, "stop")


class DangerousCommandHookTest(unittest.TestCase):
    def setUp(self):
        self.hook = make_dangerous_command_hook()

    def test_blocks_rm_rf(self):
        r = self.hook("run_command", {"command": "rm -rf /tmp/x"})
        self.assertFalse(r.allowed)
        self.assertIn("已拦截", r.reason)

    def test_allow_dangerous_bypasses(self):
        r = self.hook("run_command", {"command": "rm -rf /tmp/x", "allow_dangerous": True})
        self.assertTrue(r.allowed)

    def test_ignores_other_tools(self):
        r = self.hook("read_file", {"path": "x"})
        self.assertTrue(r.allowed)

    def test_benign_command_passes(self):
        r = self.hook("run_command", {"command": "python test.py"})
        self.assertTrue(r.allowed)


class OutsidePathHookTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.hook = make_outside_path_hook(self._tmp.name)

    def test_blocks_parent_path(self):
        r = self.hook("run_command", {"command": "cat ../secret.txt"})
        self.assertFalse(r.allowed)
        self.assertIn("已拦截", r.reason)

    def test_blocks_absolute_path(self):
        r = self.hook("run_command", {"command": "cat /etc/passwd"})
        self.assertFalse(r.allowed)

    def test_allows_inside_relative(self):
        r = self.hook("run_command", {"command": "python script.py"})
        self.assertTrue(r.allowed)


class HookCompositionTest(unittest.TestCase):
    """多个 hook 依次执行：任一拦截即阻断；updated_args 改写参数后继续。"""

    def test_default_hooks_compose_on_toolbox(self):
        with tempfile.TemporaryDirectory() as wd:
            box = Toolbox([make_shell_tool(wd, 12000)], hooks=build_default_hooks(wd))
            self.assertIn("已拦截", box.execute("run_command", {"command": "rm -rf /tmp/x"}))
            self.assertIn("ok", box.execute("run_command", {"command": "echo ok"}))

    def test_updated_args_rewrites_before_execution(self):
        seen_name = {}

        def rewrite_hook(name, args):
            seen_name["name"] = name
            if args.get("flag") == "rewrite":
                new = dict(args)
                new["flag"] = "rewritten"
                return HookResult(updated_args=new)
            return HookResult()

        box = Toolbox(
            [Tool(name="t", description="d", parameters={}, handler=lambda a: f"flag={a['flag']}")],
            hooks=[rewrite_hook],
        )
        self.assertEqual(box.execute("t", {"flag": "rewrite"}), "flag=rewritten")
        self.assertEqual(seen_name["name"], "t")

    def test_add_hook_extends_policy(self):
        def block_everything(name, args):
            return HookResult(allowed=False, reason="全量阻断")

        box = Toolbox([Tool(name="t", description="d", parameters={}, handler=lambda a: "ran")])
        box.add_hook(block_everything)
        self.assertIn("全量阻断", box.execute("t", {}))


if __name__ == "__main__":
    unittest.main()
