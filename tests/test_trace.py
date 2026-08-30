"""trace.py 的单元测试：--verbose 执行追踪的输出开关。"""
from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr

from agent.trace import Tracer


class TracerTest(unittest.TestCase):
    def test_disabled_emits_nothing(self):
        buf = io.StringIO()
        with redirect_stderr(buf):
            Tracer(enabled=False).round_start(1, 100)
        self.assertEqual(buf.getvalue(), "")

    def test_enabled_emits_to_stderr(self):
        buf = io.StringIO()
        with redirect_stderr(buf):
            Tracer(enabled=True).round_start(1, 100)
        out = buf.getvalue()
        self.assertIn("[trace]", out)
        self.assertIn("100", out)


if __name__ == "__main__":
    unittest.main()
