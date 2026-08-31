"""评测运行器：逐个任务在隔离临时目录里跑 agent，客观判定，输出成功率报告。

用法（在项目根目录）：
  python -m eval.run            # 跑全部任务
  python -m eval.run --only 斐波那契   # 只跑某个任务（按名称）
"""
from __future__ import annotations

import argparse
import tempfile
import time
from pathlib import Path

from agent.agent import CodingAgent
from agent.config import Config
from eval.tasks import TASKS


def run_task(task, max_seconds: int = 240) -> dict:
    """在隔离目录里跑一个任务，返回通过与否 + 耗时 + agent 最终输出。"""
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        task.setup(workdir)

        config = Config(working_dir=str(workdir))
        agent = CodingAgent(config)

        started = time.time()
        try:
            result = agent.run(task.description)
        except Exception as exc:  # noqa: BLE001 —— 单个任务失败不影响整体
            return {
                "passed": False,
                "elapsed": time.time() - started,
                "answer": f"运行异常：{exc}",
                "iterations": 0,
                "tool_calls": 0,
            }

        elapsed = time.time() - started
        return {
            "passed": task.check(workdir),
            "elapsed": elapsed,
            "answer": result.answer,
            "iterations": result.iterations,
            "tool_calls": result.tool_calls,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="评测 coding-agent 的成功率")
    parser.add_argument("--only", metavar="名称", help="只跑指定名称的任务")
    args = parser.parse_args()

    tasks = TASKS if not args.only else [t for t in TASKS if t.name == args.only]
    if not tasks:
        print(f"未找到任务「{args.only}」，可用：{', '.join(t.name for t in TASKS)}")
        return

    passed = 0
    total_time = 0.0
    print(f"评测开始，共 {len(tasks)} 个任务\n")
    for i, task in enumerate(tasks, 1):
        r = run_task(task)
        total_time += r["elapsed"]
        passed += int(r["passed"])
        mark = "✅" if r["passed"] else "❌"
        print(
            f"{mark} [{i}/{len(tasks)}] {task.name} · "
            f"{r['elapsed']:.0f}s · {r['iterations']} 轮 / {r['tool_calls']} 次工具调用"
        )
        if not r["passed"]:
            print(f"     判定失败，agent 最终输出：{r['answer'][:180]}")

    print(f"\n{'=' * 40}")
    print(f"通过 {passed}/{len(tasks)}（成功率 {passed / len(tasks) * 100:.0f}%）")
    print(f"总耗时 {total_time:.0f}s")


if __name__ == "__main__":
    main()
