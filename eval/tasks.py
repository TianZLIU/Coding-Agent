"""评测任务集。

每个任务 = 一句自然语言描述 + 一个可机器校验的判定函数。
判定不依赖「输出像不像」，而是用文件系统断言或子进程跑测试，保证客观、
可复现（借鉴 SWE-bench 的客观判定 + HumanEval 的可测断言思想）。
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass
class EvalTask:
    name: str
    description: str
    check: Callable[[Path], bool]              # 入参：agent 跑完后的工作目录
    setup: Callable[[Path], None] = lambda d: None  # 预置初始文件（如带 bug 的代码）


def _run_py(workdir: Path, code: str) -> bool:
    """在子进程里跑一段 Python，退出码 0 视为通过（客观 + 隔离，不污染评测进程）。"""
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=workdir,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return False
    return proc.returncode == 0


def _run_file(workdir: Path, filename: str) -> bool:
    """在子进程里直接运行一个 .py 脚本，退出码 0 视为通过。"""
    script = workdir / filename
    if not script.exists():
        return False
    try:
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=workdir,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return False
    return proc.returncode == 0


def _read_stripped(workdir: Path, name: str) -> str | None:
    f = workdir / name
    if not f.exists() or not f.is_file():
        return None
    return f.read_text(encoding="utf-8", errors="replace").strip()


# —— 各任务的判定 ——

def _check_answer_txt(workdir: Path) -> bool:
    return _read_stripped(workdir, "answer.txt") == "42"


def _check_fib(workdir: Path) -> bool:
    code = "from fib import fib; assert fib(0) == 0; assert fib(1) == 1; assert fib(10) == 55; assert fib(20) == 6765"
    return _run_py(workdir, code)


def _check_math_utils(workdir: Path) -> bool:
    code = "from math_utils import add, subtract; assert add(3, 4) == 7; assert subtract(10, 4) == 6; assert add(-1, 1) == 0"
    return _run_py(workdir, code)


def _check_sum(workdir: Path) -> bool:
    return _read_stripped(workdir, "sum.txt") == "5050"


def _setup_buggy(workdir: Path) -> None:
    (workdir / "buggy.py").write_text(
        "def classify(n):\n"
        "    # 这个函数有 bug：奇偶判断写反了\n"
        "    return 'even' if n % 2 == 1 else 'odd'\n",
        encoding="utf-8",
    )


def _check_bugfix(workdir: Path) -> bool:
    code = "from buggy import classify; assert classify(5) == 'odd'; assert classify(4) == 'even'; assert classify(0) == 'even'"
    return _run_py(workdir, code)


def _setup_dup(workdir: Path) -> None:
    # a.py 与 b.py 里各有一份完全相同的 double，供 agent 提取到 common.py
    (workdir / "a.py").write_text("def double(x):\n    return x * 2\n", encoding="utf-8")
    (workdir / "b.py").write_text("def double(x):\n    return x * 2\n", encoding="utf-8")


def _check_refactor(workdir: Path) -> bool:
    # 用 inspect 校验 double 确实来自 common（而非 a/b 各自定义），真·验证重构发生
    code = (
        "import inspect, common, a, b\n"
        "assert common.double(3) == 6\n"
        "assert inspect.getmodule(a.double) is common, 'a.double 应来自 common'\n"
        "assert inspect.getmodule(b.double) is common, 'b.double 应来自 common'\n"
    )
    return _run_py(workdir, code)


def _setup_numbers(workdir: Path) -> None:
    (workdir / "numbers.txt").write_text("3\n10\n7\n20\n15\n30\n5\n", encoding="utf-8")


def _check_sum_evens(workdir: Path) -> bool:
    # 偶数和 = 10 + 20 + 30 = 60；先跑脚本，再核对它写的 result.txt
    if not _run_file(workdir, "sum_evens.py"):
        return False
    return _read_stripped(workdir, "result.txt") == "60"


TASKS: list[EvalTask] = [
    EvalTask(
        "文件创建",
        "在当前目录创建一个文件 answer.txt，内容正好是数字 42（不要有多余字符或换行）。",
        _check_answer_txt,
    ),
    EvalTask(
        "斐波那契",
        "写一个 Python 文件 fib.py，实现函数 fib(n) 返回第 n 个斐波那契数（约定 fib(0)=0，fib(1)=1）。",
        _check_fib,
    ),
    EvalTask(
        "多函数实现",
        "写一个 Python 文件 math_utils.py，实现 add(a, b) 返回两数之和、subtract(a, b) 返回 a 减 b。",
        _check_math_utils,
    ),
    EvalTask(
        "计算求和",
        "用 Python 计算 1 到 100 的整数之和（结果应为 5050），把结果写入文件 sum.txt，只写数字。",
        _check_sum,
    ),
    EvalTask(
        "修复 bug",
        "当前目录下有个 buggy.py，它的 classify(n) 函数应该对奇数返回 'odd'、偶数返回 'even'，但实现有错误。请修复它。",
        _check_bugfix,
        setup=_setup_buggy,
    ),
    EvalTask(
        "跨文件重构",
        "当前目录有 a.py 和 b.py，里面各有一个完全相同的 double(x) 函数（重复代码）。"
        "请把 double 提取到一个新的公共模块 common.py，并让 a.py、b.py 都改为从 common 导入 double，消除重复。",
        _check_refactor,
        setup=_setup_dup,
    ),
    EvalTask(
        "数据处理",
        "当前目录有 numbers.txt，每行一个整数。写一个 Python 脚本 sum_evens.py："
        "读取 numbers.txt，计算其中所有偶数的和（应为 60），并把结果写入 result.txt（只写数字）。",
        _check_sum_evens,
        setup=_setup_numbers,
    ),
]
