"""一键演示脚本：跑通一个完整任务，实时展示 agent 的工具调用过程，并客观判定结果。

用法（项目根目录）：
  python demo.py                    # 默认演示「修复 bug」（展示 读文件→改文件→跑测试 闭环）
  python demo.py --task 斐波那契     # 演示指定任务（名称见 eval/tasks.py）

前置：已完成 `pip install -r requirements.txt` 并配置好 DEEPSEEK_API_KEY。
"""
from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from agent.agent import CodingAgent
from agent.config import Config
from agent.usage import format_cost_report
from eval.tasks import TASKS

console = Console()
err = Console(stderr=True)


class _StreamPrinter:
    """把模型的最终回答流式打到 stdout。"""

    def __init__(self) -> None:
        self.printed = False

    def emit(self, delta: str) -> None:
        sys.stdout.write(delta)
        sys.stdout.flush()
        self.printed = True

    def finish(self) -> None:
        if self.printed:
            sys.stdout.write("\n")
            sys.stdout.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description="coding-agent 一键演示")
    parser.add_argument("--task", default="修复 bug", help="要演示的任务名称")
    args = parser.parse_args()

    task = next((t for t in TASKS if t.name == args.task), None)
    if task is None:
        err.print(f"[bold red]未找到任务「{args.task}」[/bold red]，可用：{', '.join(t.name for t in TASKS)}")
        sys.exit(1)

    console.print(
        Panel(f"[bold cyan]coding-agent 演示[/bold cyan]  任务：[green]{task.name}[/green]",
              border_style="cyan")
    )
    console.print(f"[dim]任务描述：{task.description}[/dim]")

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        task.setup(workdir)

        initial = [p.name for p in sorted(workdir.iterdir()) if p.is_file()]
        if initial:
            console.print(f"[dim]初始文件：{', '.join(initial)}[/dim]")

        config = Config(working_dir=str(workdir))
        try:
            config.validate()
        except RuntimeError as exc:
            err.print(f"[bold red]配置错误：[/bold red]{exc}")
            sys.exit(1)

        agent = CodingAgent(config, verbose=True)  # verbose：stderr 实时打印工具调用
        console.print("\n[dim]agent 工作中……[/dim]\n")
        printer = _StreamPrinter()
        started = time.time()
        result = agent.run(task.description, on_text=printer.emit)
        elapsed = time.time() - started
        printer.finish()
        if not printer.printed:
            console.print(result.answer)

        passed = task.check(workdir)
        mark = "[bold green]✅ 判定通过[/bold green]" if passed else "[bold red]❌ 判定失败[/bold red]"
        console.print(
            f"\n{mark}  ·  耗时 {elapsed:.0f}s · {result.iterations} 轮 / {result.tool_calls} 次工具调用"
        )

        if result.cost:
            console.print(Panel(
                format_cost_report(
                    result.cost,
                    config.price_input_per_million,
                    config.price_output_per_million,
                ),
                border_style="dim",
            ))


if __name__ == "__main__":
    main()
