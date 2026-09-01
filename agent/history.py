"""对话历史与上下文管理。

题目要求自行编写的核心逻辑之一：维护 system + 多轮 user/assistant/tool 消息，
并在超出 token 预算时裁剪最早的非关键轮次，同时始终保留 system 提示词与
第一条用户指令。

裁剪以「完整轮次」为单位进行，避免拆散 assistant 工具调用与其对应的 tool
结果，从而保证消息序列对 API 始终合法。
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def estimate_tokens(text: str) -> int:
    """粗略估算 token 数：英文约 4 字符/token，中文约 1 字符/token。

    不引入额外分词器，用启发式估算已足以支撑上下文裁剪的决策。
    """
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    cjk_chars = len(text) - ascii_chars
    return ascii_chars // 4 + cjk_chars


class ConversationHistory:
    def __init__(self, system_prompt: str, budget_tokens: int):
        self.system_prompt = system_prompt
        self.budget_tokens = budget_tokens
        self.messages: list[dict] = []
        self.summaries: list[str] = []

    # —— 增 ——

    def add_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def add_assistant_text(self, text: str) -> None:
        self.messages.append({"role": "assistant", "content": text})

    def add_assistant_tool_call(self, tool_calls: list[dict]) -> None:
        """记录 assistant 发起的工具调用（OpenAI 消息格式）。"""
        self.messages.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": tc["arguments"]},
                    }
                    for tc in tool_calls
                ],
            }
        )

    def add_tool_result(self, tool_call_id: str, name: str, result: str) -> None:
        self.messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": name,
                "content": result,
            }
        )

    # —— 组装 ——

    def build(self, summarizer=None) -> list[dict]:
        """返回发给模型的消息列表，并就地压缩/裁剪超预算的历史。

        summarizer：可选，签名 (list[dict]) -> str，用于把将被裁剪的最早轮次
        先总结成摘要再丢弃；为 None 时退化为「直接丢弃」。压缩得到的摘要统一
        插在 system 之后，独立保存、不会被再次裁剪。
        """
        self._trim_if_needed(summarizer)
        result = [{"role": "system", "content": self.system_prompt}]
        if self.summaries:
            result.append(
                {"role": "user", "content": "[前面对话摘要]\n" + "\n\n".join(self.summaries)}
            )
        return result + self.messages

    def token_count(self) -> int:
        """当前历史（含 system、摘要、消息）的估算 token 数，供 --verbose 追踪显示。"""
        return self._total_tokens()

    # —— 内部 ——

    def _trim_if_needed(self, summarizer=None) -> None:
        """超出预算时，从第二条 user 消息开始压缩最早的完整轮次。

        提供 summarizer 时先「总结再裁剪」以保留关键信息；总结失败则退回
        「直接丢弃」。摘要累积到独立列表，messages 只删不插，保证循环必然终止。
        """
        while self._total_tokens() > self.budget_tokens:
            second_user_idx = self._find_next_user_idx(start=1)
            if second_user_idx is None:
                # 只剩首条 user 任务且已超预算：无法安全裁剪（会拆散工具对），
                # 交由 max_iterations 兜底，防止无限增长。
                break
            third_user_idx = self._find_next_user_idx(start=second_user_idx + 1)
            end = third_user_idx if third_user_idx is not None else len(self.messages)
            old_round = self.messages[second_user_idx:end]
            del self.messages[second_user_idx:end]
            if summarizer is not None:
                try:
                    self.summaries.append(summarizer(old_round))
                except Exception:  # noqa: BLE001 —— 总结失败退回直接丢弃
                    pass

    def _find_next_user_idx(self, start: int) -> int | None:
        for i in range(start, len(self.messages)):
            if self.messages[i]["role"] == "user":
                return i
        return None

    def _total_tokens(self) -> int:
        total = estimate_tokens(self.system_prompt)
        for summary in self.summaries:
            total += estimate_tokens(summary)
        for msg in self.messages:
            total += estimate_tokens(json.dumps(msg, ensure_ascii=False))
        return total

    # —— 持久化 ——

    def to_dict(self) -> dict:
        """把完整会话状态导出为可 JSON 序列化的字典。"""
        return {
            "version": 1,
            "system_prompt": self.system_prompt,
            "budget_tokens": self.budget_tokens,
            "summaries": self.summaries,
            "messages": self.messages,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ConversationHistory":
        """从 to_dict 的结果重建会话。"""
        obj = cls(data["system_prompt"], data["budget_tokens"])
        obj.summaries = list(data.get("summaries", []))
        obj.messages = list(data.get("messages", []))
        return obj

    def save(self, path: str) -> None:
        """将会话保存为 UTF-8 JSON 文件（原子写：先写临时文件再替换，中途崩溃不损坏旧文件）。"""
        target = Path(path)
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=target.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    @classmethod
    def load(cls, path: str) -> "ConversationHistory":
        """从 save 生成的 JSON 文件恢复会话。"""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)
