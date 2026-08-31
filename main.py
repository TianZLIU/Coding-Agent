"""命令行入口。

用法：
  python main.py "用 Python 写一个快速排序并测试"   # 单任务模式
  python main.py                                    # 交互式 REPL
  python main.py --save session.json ...            # 结束后保存会话
  python main.py --resume session.json ...          # 启动时恢复会话（跨进程续聊）
  python main.py --verbose "任务"                    # 打印执行追踪（token/工具/耗时）

REPL 内命令：
  /save [路径]   保存会话（缺省用 --save 指定的路径或 session.json）
  /load <路径>   从文件恢复会话
  /exit          退出
"""
from __future__ import annotations

import argparse
import sys

from agent.agent import CodingAgent
from agent.config import Config
from agent.usage import format_cost_report

# Windows 控制台默认 GBK，打印含 emoji 的模型回答会崩溃；
# 这里把标准输出重配为 UTF-8（无法编码的字符用 ? 代替，绝不抛异常）。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_SESSION = "session.json"


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


def _build_agent(resume_path: str | None = None, verbose: bool = False) -> CodingAgent:
    config = Config()
    try:
        config.validate()
    except RuntimeError as exc:
        print(f"[配置错误] {exc}", file=sys.stderr)
        sys.exit(1)
    agent = CodingAgent(config, verbose=verbose)
    if resume_path:
        try:
            agent.load_session(resume_path)
            print(f"[已从 {resume_path} 恢复会话]")
        except (FileNotFoundError, ValueError):
            print(f"[警告] 会话文件 {resume_path} 不存在或格式错误，将全新开始", file=sys.stderr)
    return agent


def run_one_shot(task: str, save_path: str | None = None, resume_path: str | None = None, verbose: bool = False) -> None:
    agent = _build_agent(resume_path, verbose)
    print(f"任务：{task}\n")
    print("agent 工作中……\n")
    printer = _StreamPrinter()
    result = agent.run(task, on_text=printer.emit)
    if printer.printed_any:
        printer.finish()
    else:
        print(result.answer)  # 兜底：无流式内容（如空回答）时整段打印
    print(f"\n[完成：{result.iterations} 轮，{result.tool_calls} 次工具调用]")
    if result.cost:
        print(format_cost_report(result.cost, agent.config.price_input_per_million, agent.config.price_output_per_million))
    if save_path:
        agent.save_session(save_path)
        print(f"[会话已保存到 {save_path}]")


def run_repl(save_path: str | None = None, resume_path: str | None = None, verbose: bool = False) -> None:
    agent = _build_agent(resume_path, verbose)
    print(f"coding-agent 已就绪（模型 {agent.config.model}）")
    print(f"工作目录：{agent.config.working_dir}")
    print("输入编程任务后回车开始；/save [路径] 保存，/load <路径> 恢复，/exit 退出。\n")

    while True:
        try:
            task = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not task:
            continue

        lowered = task.lower()
        if lowered in {"/exit", "/quit"}:
            break
        if lowered.startswith("/save"):
            path = task[len("/save"):].strip() or save_path or DEFAULT_SESSION
            agent.save_session(path)
            print(f"[会话已保存到 {path}]\n")
            continue
        if lowered.startswith("/load"):
            path = task[len("/load"):].strip()
            if not path:
                print("[用法] /load <路径>")
                continue
            try:
                agent.load_session(path)
                print(f"[已从 {path} 恢复会话]\n")
            except (FileNotFoundError, ValueError):
                print(f"[警告] 会话文件 {path} 不存在或格式错误\n")
            continue

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
        print(f"\n[完成：{result.iterations} 轮，{result.tool_calls} 次工具调用]")
        if result.cost:
            print(format_cost_report(result.cost, agent.config.price_input_per_million, agent.config.price_output_per_million))
        print()

    if save_path:
        agent.save_session(save_path)
        print(f"[会话已保存到 {save_path}]")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="coding-agent：一个自研的编程智能体")
    parser.add_argument("task", nargs="*", help="单任务模式下要执行的任务描述")
    parser.add_argument("--save", metavar="PATH", help="运行结束后将会话历史保存到指定文件")
    parser.add_argument("--resume", metavar="PATH", help="启动时从指定文件恢复会话历史（跨进程续聊）")
    parser.add_argument("--verbose", action="store_true", help="打印执行追踪（每轮 token、工具调用与耗时）")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    if args.task:
        run_one_shot(" ".join(args.task), save_path=args.save, resume_path=args.resume, verbose=args.verbose)
    else:
        run_repl(save_path=args.save, resume_path=args.resume, verbose=args.verbose)
