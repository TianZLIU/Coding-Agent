"""命令执行工具。

让 agent 能真正运行代码、跑测试、安装依赖等。带超时、输出截断，
并把 stdout/stderr 与退出码一并返回给模型。

安全拦截（危险命令 / 路径越界）已抽到 agent/hooks.py 的可插拔 hook 层，
本工具只负责「执行」，不再内联安全判断——拦截由 Toolbox.execute 前的
pre-tool hook 统一处理，`allow_dangerous` 参数由 hook 消费而非本处理器。
"""
from __future__ import annotations

import subprocess

from .base import Tool
from .files import _truncate


def make_shell_tool(working_dir: str, max_output_chars: int) -> Tool:
    def run_command(args: dict) -> str:
        command = args["command"]
        timeout = int(args.get("timeout", 60))
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=working_dir,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return f"错误：命令超时（>{timeout} 秒）。"

        parts = []
        if proc.stdout:
            parts.append(proc.stdout.strip())
        if proc.stderr:
            parts.append(f"[stderr]\n{proc.stderr.strip()}")
        combined = "\n".join(parts).strip() or "(无输出)"
        combined = _truncate(combined, max_output_chars)
        return f"退出码 {proc.returncode}\n{combined}"

    return Tool(
        name="run_command",
        description="在本地 shell 中执行一条命令，返回退出码、stdout 和 stderr。用于运行代码、测试、安装依赖等。",
        parameters={
            "command": {"type": "string", "description": "要执行的 shell 命令"},
            "timeout": {"type": "integer", "description": "超时秒数，默认 60"},
            "allow_dangerous": {"type": "boolean", "description": "是否允许执行被判定为破坏性或越界的命令（默认 false，需二次确认才放开）"},
        },
        required=["command"],
        handler=run_command,
    )
