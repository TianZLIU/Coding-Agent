"""长期记忆：跨会话项目约定持久化。

对应 Claude Code 的 CLAUDE.md（always-on 持久上下文）思想：把「项目约定、
用户偏好」这类跨任务稳定的信息存到工作目录的 .agent_memory.md，下次会话
自动加载并注入 system prompt，解决 agent 跨任务失忆。
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .tools.base import Tool

MEMORY_FILE_NAME = ".agent_memory.md"


class MemoryStore:
    """跨会话记忆的持久化读写（原子写，崩溃不损坏）。"""

    def __init__(self, working_dir: str):
        self.path = Path(working_dir) / MEMORY_FILE_NAME

    def load(self) -> str:
        """读取当前记忆内容；文件不存在返回空串。"""
        if not self.path.exists():
            return ""
        return self.path.read_text(encoding="utf-8").strip()

    def add(self, content: str) -> str:
        """追加一条记忆。"""
        existing = self.load()
        new = f"{existing}\n\n{content}".strip() if existing else content.strip()
        self._write(new)
        return f"已追加记忆（当前 {len(new)} 字符）。"

    def replace(self, old_text: str, new_text: str) -> str:
        """替换记忆里的一段旧文本；找不到则报错。"""
        existing = self.load()
        if old_text not in existing:
            return "错误：未在记忆中找到待替换内容。"
        new = existing.replace(old_text, new_text)
        self._write(new)
        return "已替换记忆。"

    def clear(self) -> str:
        """清空全部记忆（直接删除文件）。"""
        self._write("")
        return "已清空记忆。"

    def _write(self, text: str) -> None:
        """原子写：临时文件 + fsync + replace；空文本则删除文件。"""
        if not text:
            self.path.unlink(missing_ok=True)
            return
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=self.path.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text + "\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def make_memory_tool(memory: MemoryStore) -> Tool:
    """构造 memory 工具，让模型自主维护跨会话记忆。"""

    def handler(args: dict) -> str:
        action = args.get("action", "")
        if action == "add":
            content = args.get("content", "")
            if not content:
                return "错误：add 需要 content。"
            return memory.add(content)
        if action == "replace":
            old_text = args.get("old_text", "")
            new_text = args.get("new_text", "")
            if not old_text:
                return "错误：replace 需要 old_text。"
            return memory.replace(old_text, new_text)
        if action == "clear":
            return memory.clear()
        return "错误：未知 action，可用 add / replace / clear。"

    return Tool(
        name="memory",
        description="读写跨会话长期记忆（存于工作目录 .agent_memory.md，下次会话自动加载）。action：add=追加一条 / replace=替换一段 / clear=清空。",
        parameters={
            "action": {"type": "string", "description": "add / replace / clear"},
            "content": {"type": "string", "description": "要追加的记忆内容（add 用）"},
            "old_text": {"type": "string", "description": "要替换的旧文本（replace 用）"},
            "new_text": {"type": "string", "description": "替换后的新文本（replace 用）"},
        },
        required=["action"],
        handler=handler,
    )
