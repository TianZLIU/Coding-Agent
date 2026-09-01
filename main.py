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
  /help          显示帮助
  /exit          退出
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory, InMemoryHistory
from prompt_toolkit.styles import Style
from rich import box
from rich.console import Console
from rich.markup import escape as rich_escape
from rich.panel import Panel
from rich.table import Table

from agent.agent import CodingAgent
from agent.config import Config
from agent.usage import CostStats

# Windows 控制台默认 GBK，打印含 emoji 的模型回答会崩溃；
# 这里把标准输出重配为 UTF-8（无法编码的字符用 ? 代替，绝不抛异常）。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

console = Console()
err_console = Console(stderr=True)

DEFAULT_SESSION = "session.json"

_REPL_COMMANDS = WordCompleter(
    ["/save", "/load", "/help", "/exit", "/quit"], ignore_case=True
)
_PROMPT_STYLE = Style.from_dict({"prompt": "bold #00c853"})


def _make_history():
    """命令历史：持久化到用户目录，写入失败则退化为仅本次会话内有效。"""
    try:
        return FileHistory(str(Path.home() / ".coding_agent_history"))
    except Exception:  # noqa: BLE001 —— 历史文件不可写不影响使用
        return InMemoryHistory()


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
        err_console.print(f"[bold red]配置错误：[/bold red]{rich_escape(str(exc))}")
        sys.exit(1)
    agent = CodingAgent(config, verbose=verbose)
    if resume_path:
        try:
            agent.load_session(resume_path)
            console.print(f"[dim]已从 {rich_escape(resume_path)} 恢复会话[/dim]")
        except (FileNotFoundError, ValueError):
            console.print(
                f"[yellow]警告：会话文件 {rich_escape(resume_path)} 不存在或格式错误，将全新开始[/yellow]"
            )
    return agent


def _print_banner(agent: CodingAgent) -> None:
    console.print(
        Panel(
            f"[bold cyan]coding-agent[/bold cyan]  模型 [green]{agent.config.model}[/green]\n"
            f"工作目录 [dim]{agent.config.working_dir}[/dim]",
            title="编程智能体",
            border_style="cyan",
            box=box.ROUNDED,
        )
    )
    console.print(
        "[dim]输入任务后回车开始；[/dim]"
        "[cyan]/save[/cyan][dim] 保存 · [/dim]"
        "[cyan]/load[/cyan][dim] 恢复 · [/dim]"
        "[cyan]/help[/cyan][dim] 帮助 · [/dim]"
        "[cyan]/exit[/cyan][dim] 退出[/dim]\n"
    )


def _print_cost(cost: CostStats, price_in: float, price_out: float) -> None:
    table = Table(show_header=False, box=box.SIMPLE_HEAVY, title="成本统计", border_style="dim")
    table.add_column(style="dim")
    table.add_column(justify="right")
    table.add_row("模型调用", f"{cost.calls} 次")
    table.add_row(
        "输入 / 输出 tokens",
        f"{cost.prompt_tokens:,} / {cost.completion_tokens:,}（合计 {cost.total_tokens:,}）",
    )
    table.add_row(
        "模型 / 工具 / 总耗时",
        f"{cost.model_seconds:.1f}s / {cost.tool_seconds:.1f}s / {cost.total_seconds:.1f}s",
    )
    table.add_row("估算花费", f"¥{cost.cost(price_in, price_out):.4f}")
    console.print(table)


def _print_done(iterations: int, tool_calls: int) -> None:
    console.print(f"[bold green]完成[/bold green]：{iterations} 轮，[cyan]{tool_calls}[/cyan] 次工具调用")


def run_one_shot(task: str, save_path: str | None = None, resume_path: str | None = None, verbose: bool = False) -> None:
    agent = _build_agent(resume_path, verbose)
    console.print(f"任务：[bold]{rich_escape(task)}[/bold]\n")
    console.print("[dim]agent 工作中……[/dim]\n")
    printer = _StreamPrinter()
    result = agent.run(task, on_text=printer.emit)
    if printer.printed_any:
        printer.finish()
    else:
        console.print(result.answer, markup=False, highlight=False)
    _print_done(result.iterations, result.tool_calls)
    if result.cost:
        _print_cost(result.cost, agent.config.price_input_per_million, agent.config.price_output_per_million)
    if save_path:
        agent.save_session(save_path)
        console.print(f"[dim]会话已保存到 {rich_escape(save_path)}[/dim]")


def run_repl(save_path: str | None = None, resume_path: str | None = None, verbose: bool = False) -> None:
    agent = _build_agent(resume_path, verbose)
    _print_banner(agent)
    # prompt_toolkit 需要真正的 Windows 控制台；在 Git Bash/mintty 等伪终端里拿不到
    # 屏幕缓冲区，这里退化为标准 input()（无历史/补全，但功能完整）。
    try:
        session = PromptSession(history=_make_history(), completer=_REPL_COMMANDS)
    except Exception:  # noqa: BLE001 —— 伪终端环境下无屏幕缓冲区，降级即可
        session = None

    while True:
        try:
            if session is not None:
                task = session.prompt([("class:prompt", "> ")], style=_PROMPT_STYLE).strip()
            else:
                task = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            break
        if not task:
            continue

        lowered = task.lower()
        if lowered in {"/exit", "/quit"}:
            break
        if lowered.startswith("/save"):
            path = task[len("/save"):].strip() or save_path or DEFAULT_SESSION
            agent.save_session(path)
            console.print(f"[dim]会话已保存到 {rich_escape(path)}[/dim]\n")
            continue
        if lowered.startswith("/load"):
            path = task[len("/load"):].strip()
            if not path:
                console.print("[yellow]用法：/load <路径>[/yellow]")
                continue
            try:
                agent.load_session(path)
                console.print(f"[dim]已从 {rich_escape(path)} 恢复会话[/dim]\n")
            except (FileNotFoundError, ValueError):
                console.print(f"[yellow]警告：会话文件 {rich_escape(path)} 不存在或格式错误[/yellow]\n")
            continue
        if lowered == "/help":
            console.print("[cyan]/save [路径][/cyan]  保存会话到文件")
            console.print("[cyan]/load <路径>[/cyan]  从文件恢复会话")
            console.print("[cyan]/exit[/cyan]         退出")
            console.print()
            continue

        console.print("[dim]agent 工作中……[/dim]\n")
        printer = _StreamPrinter()
        try:
            result = agent.run(task, on_text=printer.emit)
        except Exception as exc:  # noqa: BLE001 —— 显示错误但保持 REPL 存活
            console.print(f"[bold red]运行出错：[/bold red]{rich_escape(str(exc))}\n")
            continue
        if printer.printed_any:
            printer.finish()
        else:
            console.print(result.answer, markup=False, highlight=False)
        _print_done(result.iterations, result.tool_calls)
        if result.cost:
            _print_cost(result.cost, agent.config.price_input_per_million, agent.config.price_output_per_million)
        console.print()

    if save_path:
        agent.save_session(save_path)
        console.print(f"[dim]会话已保存到 {rich_escape(save_path)}[/dim]")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="coding-agent：一个自研的编程智能体")
    parser.add_argument("task", nargs="*", help="单任务模式下要执行的任务描述")
    parser.add_argument("--save", metavar="PATH", help="运行结束后将会话历史保存到指定文件")
    parser.add_argument("--resume", metavar="PATH", help="启动时从指定文件恢复会话历史（跨进程续聊）")
    parser.add_argument("--verbose", action="store_true", help="打印执行追踪（每轮 token、工具调用与耗时）")
    return parser.parse_args()


def main() -> None:
    """CLI 入口（供 console_scripts 调用）。"""
    args = _parse_args()
    if args.task:
        run_one_shot(" ".join(args.task), save_path=args.save, resume_path=args.resume, verbose=args.verbose)
    else:
        run_repl(save_path=args.save, resume_path=args.resume, verbose=args.verbose)


if __name__ == "__main__":
    main()
