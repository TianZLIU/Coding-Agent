"""执行追踪（--verbose）。

把 agent 内部每一步——每轮发送的 token 数、模型耗时、工具调用与结果、
上下文压缩——打印到 stderr。刻意走 stderr 而非 stdout，是为了不污染
stdout 上正在流式输出的模型回答。
"""
from __future__ import annotations

import sys


class Tracer:
    """轻量执行追踪器。enabled=False 时所有方法都是空操作，零开销。"""

    def __init__(self, enabled: bool = False):
        self.enabled = enabled

    def _emit(self, msg: str) -> None:
        if self.enabled:
            print(msg, file=sys.stderr, flush=True)

    def round_start(self, iteration: int, tokens: int) -> None:
        self._emit(f"[trace] 第 {iteration} 轮 · 发送约 {tokens} tokens")

    def model_elapsed(self, seconds: float) -> None:
        self._emit(f"[trace] 模型返回 · 耗时 {seconds:.2f}s")

    def tool_done(self, name: str, seconds: float, result: str) -> None:
        preview = result.replace("\n", " ")[:120]
        self._emit(f"[trace] 工具 {name} · {seconds:.2f}s · {preview}")

    def summarized(self, summary: str) -> None:
        self._emit(f"[trace] 上下文压缩 · {summary[:80]}…")

    def final(self, iterations: int, tool_calls: int) -> None:
        self._emit(f"[trace] 结束 · {iterations} 轮 / {tool_calls} 次工具调用")
