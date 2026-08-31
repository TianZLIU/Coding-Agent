"""执行追踪（--verbose）。

把 agent 内部每一步——每轮发送的 token 数、模型耗时、工具调用与结果、
上下文压缩——打印到 stderr。刻意走 stderr 而非 stdout，是为了不污染
stdout 上正在流式输出的模型回答。

此外支持 sink 回调：传入 sink 后，每个事件会以结构化 dict 的形式同步
分发给 sink，供网页界面等「非终端」前端实时渲染。CLI 用 enabled 打印，
Web 用 sink 订阅，二者互不干扰。
"""
from __future__ import annotations

import sys
from typing import Callable


class Tracer:
    """轻量执行追踪器。enabled=False 且 sink=None 时所有方法都是空操作。"""

    def __init__(self, enabled: bool = False, sink: Callable[[dict], None] | None = None):
        self.enabled = enabled
        self.sink = sink

    def _emit(self, event: dict, text: str) -> None:
        if self.enabled:
            print(text, file=sys.stderr, flush=True)
        if self.sink is not None:
            self.sink(event)

    def round_start(self, iteration: int, tokens: int) -> None:
        self._emit(
            {"type": "round", "iteration": iteration, "tokens": tokens},
            f"[trace] 第 {iteration} 轮 · 发送约 {tokens} tokens",
        )

    def model_elapsed(self, seconds: float) -> None:
        self._emit(
            {"type": "model", "elapsed": seconds},
            f"[trace] 模型返回 · 耗时 {seconds:.2f}s",
        )

    def tool_done(self, name: str, seconds: float, result: str) -> None:
        preview = result.replace("\n", " ")[:120]
        self._emit(
            {"type": "tool_call", "name": name, "elapsed": seconds, "result": result},
            f"[trace] 工具 {name} · {seconds:.2f}s · {preview}",
        )

    def summarized(self, summary: str) -> None:
        self._emit(
            {"type": "summary", "summary": summary},
            f"[trace] 上下文压缩 · {summary[:80]}…",
        )

    def final(self, iterations: int, tool_calls: int) -> None:
        self._emit(
            {"type": "final", "iterations": iterations, "tool_calls": tool_calls},
            f"[trace] 结束 · {iterations} 轮 / {tool_calls} 次工具调用",
        )
