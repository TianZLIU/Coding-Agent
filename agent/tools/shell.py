"""命令执行工具。

让 agent 能真正运行代码、跑测试、安装依赖等。带超时、输出截断，
并把 stdout/stderr 与退出码一并返回给模型。
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .base import Tool

# 命中即视为「破坏性 / 危险」的命令模式。默认拒绝执行，要求模型显式二次确认。
DANGEROUS_PATTERNS: list[tuple[str, str]] = [
    (r"\brm\s+-[a-z]*r[a-z]*f[a-z]*\b|\brm\s+-[a-z]*f[a-z]*r[a-z]*\b", "递归强制删除"),
    (r"\b(mkfs|fdisk|parted|dd)\b", "磁盘格式化 / 底层写入"),
    (r"\b(shutdown|reboot|halt|poweroff)\b", "关机 / 重启"),
    (r"\bgit\s+(push\s+--force|reset\s+--hard)\b", "git 强制改写历史"),
    (r">\s*/dev/(sd[a-z]*|hd[a-z]*|nvme\w*)", "覆盖磁盘设备"),
]

# 命令里「越界路径引用」的检测模式：绝对路径、家目录、显式父目录引用。
# 这些会突破 working_dir 边界，与文件工具层的 sandbox 语义保持一致。
_PATH_PATTERNS = [
    re.compile(r'(?<![\w])[A-Za-z]:[\\/][^\s"\']*'),           # Windows 盘符 C:\...（排除 URL 里的 s://）
    re.compile(r'(?<![:/\w])/(?:[^\s"\']*/)*[^\s"\']*'),        # Unix 绝对路径 /etc/...（排除 URL 里的 /）
    re.compile(r'~(/[^\s"\']*)?'),                              # 家目录 ~ 或 ~/...
    re.compile(r'(?<![\w.])\.\.(?![\w.])(?:[\\/][^\s"\']+)?'),  # 父目录 .. 或 ../...
]


def _outside_path(working_dir: str, command: str) -> str | None:
    """返回命令里第一个越出 working_dir 的路径引用；没有则返回 None。

    与 files._resolve 用同一套「绝对化后再判断是否在工作目录内」的语义，
    使命令执行层与文件读写层对「越界」的判定保持一致。
    """
    base = Path(working_dir).resolve()
    for pattern in _PATH_PATTERNS:
        for raw in pattern.findall(command):
            p = Path(raw).expanduser()
            if not p.is_absolute():
                p = base / p
            p = p.resolve()
            if p != base and base not in p.parents:
                return raw
    return None


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
        if not allow_dangerous:
            outside = _outside_path(working_dir, command)
            if outside is not None:
                return (
                    f"已拦截：命令引用了工作目录之外的路径「{outside}」。"
                    "为避免越界读写，默认拒绝执行；若确需访问，请把 allow_dangerous 设为 true 后重新调用。"
                )
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
