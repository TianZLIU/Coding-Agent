"""命令执行工具。

让 agent 能真正运行代码、跑测试、安装依赖等。带超时、输出截断，
并把 stdout/stderr 与退出码一并返回给模型。
"""
from __future__ import annotations

import re
import subprocess

from .base import Tool

# 命中即视为「破坏性 / 危险」的命令模式。默认拒绝执行，要求模型显式二次确认。
DANGEROUS_PATTERNS: list[tuple[str, str]] = [
    (r"\brm\s+-[a-z]*r[a-z]*f[a-z]*\b|\brm\s+-[a-z]*f[a-z]*r[a-z]*\b", "递归强制删除"),
    (r"\b(mkfs|fdisk|parted|dd)\b", "磁盘格式化 / 底层写入"),
    (r"\b(shutdown|reboot|halt|poweroff)\b", "关机 / 重启"),
    (r"\bgit\s+(push\s+--force|reset\s+--hard)\b", "git 强制改写历史"),
    (r">\s*/dev/(sd[a-z]*|hd[a-z]*|nvme\w*)", "覆盖磁盘设备"),
]


def make_shell_tool(working_dir: str, max_output_chars: int) -> Tool:
    def run_command(args: dict) -> str:
        command = args["command"]
        timeout = int(args.get("timeout", 60))
        allow_dangerous = bool(args.get("allow_dangerous", False))
        for pattern, label in DANGEROUS_PATTERNS:
            if re.search(pattern, command, flags=re.IGNORECASE):
                if not allow_dangerous:
                    return (
                        f"已拦截：该命令疑似破坏性操作（{label}）。"
                        "为避免不可逆后果，默认拒绝执行；若确需执行，请把 allow_dangerous 设为 true 后重新调用。"
                    )
                break
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
            "allow_dangerous": {"type": "boolean", "description": "是否允许执行被判定为破坏性的命令（默认 false，需二次确认才放开）"},
        },
        required=["command"],
        handler=run_command,
    )
