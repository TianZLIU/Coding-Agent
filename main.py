"""命令行入口。

两种用法：
1. 交互式 REPL：  python main.py
2. 单任务模式：  python main.py "用 Python 写一个快速排序并测试"
"""
from __future__ import annotations

import sys

from agent.agent import CodingAgent
from agent.config import Config

# Windows 控制台默认 GBK，打印含 emoji 的模型回答会崩溃；
# 这里把标准输出重配为 UTF-8（无法编码的字符用 ? 代替，绝不抛异常）。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


class _StreamPrinter:
    """流式打印：逐字输出模型文本，结束时补一个换行。"""

    def __init__(self) -> None:
        self.printed_any = False

    def emit(self, delta: str) -> None:
        sys.stdout.write(delta)
        sys.stdout.flush()
        self.printed_any = True

    def finish(self) -> None:
        if self.printed_any:
            sys.stdout.write("\n")
            sys.stdout.flush()


def _build_agent() -> CodingAgent:
    config = Config()
    try:
        config.validate()
    except RuntimeError as exc:
        print(f"[配置错误] {exc}", file=sys.stderr)
        sys.exit(1)
    return CodingAgent(config)


def run_one_shot(task: str) -> None:
    agent = _build_agent()
    print(f"任务：{task}\n")
    print("agent 工作中……\n")
    printer = _StreamPrinter()
    result = agent.run(task, on_text=printer.emit)
    if printer.printed_any:
        printer.finish()
    else:
        print(result.answer)  # 兜底：无流式内容（如空回答）时整段打印
    print(f"\n[完成：{result.iterations} 轮，{result.tool_calls} 次工具调用]")


def run_repl() -> None:
    agent = _build_agent()
    print(f"coding-agent 已就绪（模型 {agent.config.model}）")
    print(f"工作目录：{agent.config.working_dir}")
    print("输入你的编程任务后回车开始；输入 /exit 退出。\n")

    while True:
        try:
            task = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not task:
            continue
        if task.lower() in {"/exit", "/quit"}:
            break

        print("agent 工作中……\n")
        printer = _StreamPrinter()
        try:
            result = agent.run(task, on_text=printer.emit)
        except Exception as exc:  # noqa: BLE001 —— 显示错误但保持 REPL 存活
            print(f"[运行出错] {exc}\n")
            continue
        if printer.printed_any:
            printer.finish()
        else:
            print(result.answer)  # 兜底：无流式内容时整段打印
        print(f"\n[完成：{result.iterations} 轮，{result.tool_calls} 次工具调用]\n")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        run_one_shot(" ".join(sys.argv[1:]))
    else:
        run_repl()
