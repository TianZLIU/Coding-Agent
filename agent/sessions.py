"""会话管理：把 agent 的对话历史存成可命名的会话，支持列表 / 恢复 / 切换 / 删除。

CLI 与网页版共用这一个存储，因此网页里保存的会话能在终端 /load 恢复，反之亦然。
会话存放在 coding-agent 根目录的 .sessions/ 下（已 gitignore，不入库），每个会话
一个 JSON 文件，文件名是时间戳（唯一），标题取第一条用户消息。
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path

_TITLE_MAX = 24


def default_sessions_dir() -> Path:
    """默认会话目录：coding-agent 根目录下的 .sessions/。"""
    return Path(__file__).resolve().parent.parent / ".sessions"


class SessionStore:
    """一个目录下的会话集合，提供 list / save / load / delete。"""

    def __init__(self, directory: str | Path | None = None):
        self.directory = Path(directory) if directory else default_sessions_dir()
        self.directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _title(messages: list[dict]) -> str:
        for m in messages:
            if m.get("role") == "user" and m.get("content"):
                t = " ".join(str(m["content"]).split())
                return t[:_TITLE_MAX] + ("…" if len(t) > _TITLE_MAX else "")
        return "（空会话）"

    def new_name(self) -> str:
        """生成一个唯一的新会话文件名（不含扩展名）。"""
        return datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    def list(self) -> list[dict]:
        """按最后修改时间倒序列出所有会话（跳过损坏文件）。"""
        items: list[dict] = []
        for p in self.directory.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 —— 损坏文件跳过
                continue
            items.append(
                {
                    "name": p.stem,
                    "title": data.get("title") or self._title(data.get("messages", [])),
                    "updated_at": data.get("updated_at") or p.stat().st_mtime,
                    "message_count": len(data.get("messages", [])),
                }
            )
        items.sort(key=lambda it: (it["updated_at"], it["name"]), reverse=True)
        return items

    def save(self, name: str, messages: list[dict], history: dict) -> None:
        """把会话（显示消息 + 完整历史）原子写入名为 name 的文件。"""
        payload = {
            "title": self._title(messages),
            "updated_at": time.time(),
            "messages": messages,
            "history": history,
        }
        path = self.directory / f"{name}.json"
        fd, tmp = tempfile.mkstemp(dir=str(self.directory), prefix=name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def load(self, name: str) -> dict:
        """读取名为 name 的会话，返回 {'title', 'updated_at', 'messages', 'history'}。"""
        return json.loads((self.directory / f"{name}.json").read_text(encoding="utf-8"))

    def delete(self, name: str) -> None:
        (self.directory / f"{name}.json").unlink(missing_ok=True)
