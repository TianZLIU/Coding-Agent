"""文件工具：列目录、读文件、写文件、精确改文件、按模式查找。

所有文件操作都限制在 working_dir 内（相对路径也基于它解析），
并对读取/命令输出做截断，避免单次结果撑爆上下文。
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from .base import Tool


def _resolve(working_dir: str, raw_path: str) -> Path:
    """把用户/模型给的路径解析为绝对路径（相对路径基于 working_dir）。"""
    p = Path(raw_path)
    if not p.is_absolute():
        p = Path(working_dir) / p
    return p.resolve()


def _truncate(text: str, limit: int) -> str:
    if len(text) > limit:
        return text[:limit] + "\n...(输出已截断)"
    return text


def make_file_tools(working_dir: str, max_output_chars: int) -> list[Tool]:
    """构造文件相关工具，闭包捕获 working_dir 与输出上限。"""

    def list_dir(args: dict) -> str:
        raw = args.get("path", ".")
        path = _resolve(working_dir, raw)
        if not path.exists():
            return f"错误：路径不存在：{path}"
        if not path.is_dir():
            return f"错误：{path} 不是目录。"
        entries = sorted(path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        lines = []
        for e in entries:
            kind = "[目录]" if e.is_dir() else "[文件]"
            try:
                size = "" if e.is_dir() else f" ({e.stat().st_size} 字节)"
            except OSError:
                size = ""
            lines.append(f"{kind} {e.name}{size}")
        return _truncate("\n".join(lines) or "(空目录)", max_output_chars)

    def read_file(args: dict) -> str:
        path = _resolve(working_dir, args["path"])
        if not path.exists():
            return f"错误：文件不存在：{path}"
        if path.is_dir():
            return f"错误：{path} 是目录，请用 list_dir。"
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        start = max(1, int(args.get("start_line", 1)))
        end_raw = args.get("end_line")
        end = int(end_raw) if end_raw else len(lines)
        selected = lines[start - 1 : end]
        numbered = "\n".join(f"{i + start:>5}| {line}" for i, line in enumerate(selected))
        return _truncate(numbered or "(空文件)", max_output_chars)

    def write_file(args: dict) -> str:
        path = _resolve(working_dir, args["path"])
        content = args.get("content", "")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"已写入 {path}（{len(content)} 字符）。"

    def edit_file(args: dict) -> str:
        path = _resolve(working_dir, args["path"])
        if not path.exists():
            return f"错误：文件不存在：{path}"
        content = path.read_text(encoding="utf-8", errors="replace")
        old = args["old_string"]
        new = args.get("new_string", "")
        count = content.count(old)
        if count == 0:
            return "错误：未在文件中找到待替换内容，请先用 read_file 确认原文。"
        if count > 1:
            return f"错误：待替换内容出现 {count} 次，请提供更长的唯一上下文。"
        path.write_text(content.replace(old, new), encoding="utf-8")
        return f"已成功修改 {path}。"

    def glob_files(args: dict) -> str:
        pattern = args.get("pattern", "*")
        base = _resolve(working_dir, args.get("path", "."))
        matches = sorted(base.glob(pattern))
        rel = [str(m.relative_to(base)) if m != base else m.name for m in matches]
        return _truncate("\n".join(rel[:200]) or "无匹配。", max_output_chars)

    return [
        Tool(
            name="list_dir",
            description="列出指定目录下的文件和子目录。",
            parameters={"path": {"type": "string", "description": "目录路径，默认当前目录"}},
            handler=list_dir,
        ),
        Tool(
            name="read_file",
            description="读取文本文件内容，返回带行号的内容，可指定行范围。",
            parameters={
                "path": {"type": "string", "description": "文件路径"},
                "start_line": {"type": "integer", "description": "起始行（从 1 开始，可选）"},
                "end_line": {"type": "integer", "description": "结束行（含，可选）"},
            },
            required=["path"],
            handler=read_file,
        ),
        Tool(
            name="write_file",
            description="创建或覆盖写入一个文本文件（会自动创建父目录）。",
            parameters={
                "path": {"type": "string", "description": "文件路径"},
                "content": {"type": "string", "description": "要写入的完整内容"},
            },
            required=["path", "content"],
            handler=write_file,
        ),
        Tool(
            name="edit_file",
            description="在文件中把一段唯一的旧文本精确替换为新文本（替换第一次出现）。",
            parameters={
                "path": {"type": "string", "description": "文件路径"},
                "old_string": {"type": "string", "description": "要替换的原文（必须唯一）"},
                "new_string": {"type": "string", "description": "替换后的新文本"},
            },
            required=["path", "old_string", "new_string"],
            handler=edit_file,
        ),
        Tool(
            name="glob_files",
            description="按通配符模式查找文件，例如 pattern='*.py'。",
            parameters={
                "pattern": {"type": "string", "description": "通配符模式，如 *.py"},
                "path": {"type": "string", "description": "查找起点目录，默认当前目录"},
            },
            required=["pattern"],
            handler=glob_files,
        ),
    ]
