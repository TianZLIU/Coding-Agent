"""可插拔的工具拦截层（PreToolUse hooks）。

对应 Claude Code 的 PreToolUse hook——「唯一能硬约束工具调用的扩展层」（返回拦截即
阻断工具调用），以及 my-pi-agent 的 ToolExecutionStart 拦截点（支持 block / updated_args）。

把原先硬编码在 shell.py 里的沙箱检查（危险命令 / 路径越界）抽成独立 hook 函数，
在 Toolbox.execute 前统一跑一遍，从而：
- 可插拔：新增 / 移除安全策略不碰工具本体，只增删 hook；
- 可组合：多个 hook 依次执行，任一返回 allowed=False 即阻断；
- 可测试：每个 hook 是 (tool_name, args) -> HookResult 的纯函数，可单独测。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass
class HookResult:
    """hook 的返回：是否放行、拦截原因、可选的参数改写。

    - allowed=False 时，Toolbox 不再执行工具，直接把 reason 回传模型；
    - updated_args 非 None 时，用改写后的参数继续执行（如自动修正、注入默认值）。
    """

    allowed: bool = True
    reason: str = ""
    updated_args: dict | None = None


# hook 签名：(工具名, 参数字典) -> HookResult
Hook = Callable[[str, dict], HookResult]

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


def make_dangerous_command_hook() -> Hook:
    """危险命令拦截：run_command 命中破坏性模式即阻断（allow_dangerous=true 放行）。"""

    def hook(name: str, args: dict) -> HookResult:
        if name != "run_command":
            return HookResult()
        command = args.get("command", "")
        allow = bool(args.get("allow_dangerous", False))
        for pattern, label in DANGEROUS_PATTERNS:
            if re.search(pattern, command, flags=re.IGNORECASE):
                if not allow:
                    return HookResult(
                        allowed=False,
                        reason=(
                            f"已拦截：该命令疑似破坏性操作（{label}）。"
                            "为避免不可逆后果，默认拒绝执行；若确需执行，请把 allow_dangerous 设为 true 后重新调用。"
                        ),
                    )
                break
        return HookResult()

    return hook


def make_outside_path_hook(working_dir: str) -> Hook:
    """路径越界拦截：run_command 的命令引用了工作目录之外的路径即阻断。"""

    def hook(name: str, args: dict) -> HookResult:
        if name != "run_command":
            return HookResult()
        if bool(args.get("allow_dangerous", False)):
            return HookResult()
        outside = _outside_path(working_dir, args.get("command", ""))
        if outside is not None:
            return HookResult(
                allowed=False,
                reason=(
                    f"已拦截：命令引用了工作目录之外的路径「{outside}」。"
                    "为避免越界读写，默认拒绝执行；若确需访问，请把 allow_dangerous 设为 true 后重新调用。"
                ),
            )
        return HookResult()

    return hook


def build_default_hooks(working_dir: str) -> list[Hook]:
    """默认安全策略：危险命令 + 路径越界，两条 hook 依次执行（可组合）。"""
    return [make_dangerous_command_hook(), make_outside_path_hook(working_dir)]
