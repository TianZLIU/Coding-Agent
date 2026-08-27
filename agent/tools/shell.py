"""命令执行工具。

让 agent 能真正运行代码、跑测试、安装依赖等。带超时、输出截断，
并把 stdout/stderr 与退出码一并返回给模型。
"""
from __future__ import annotations

import subprocess

from .base import Tool


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
        combined = combined[:max_output_chars] + ("\n...(输出已截断)" if len(combined) >= max_output_chars else "")
        return f"退出码 {proc.returncode}\n{combined}"

    return Tool(
        name="run_command",
        description="在本地 shell 中执行一条命令，返回退出码、stdout 和 stderr。用于运行代码、测试、安装依赖等。",
        parameters={
            "command": {"type": "string", "description": "要执行的 shell 命令"},
            "timeout": {"type": "integer", "description": "超时秒数，默认 60"},
        },
        required=["command"],
        handler=run_command,
    )
