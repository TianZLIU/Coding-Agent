"""对话历史与上下文管理。

题目要求自行编写的核心逻辑之一：维护 system + 多轮 user/assistant/tool 消息，
并在超出 token 预算时裁剪最早的非关键轮次，同时始终保留 system 提示词与
第一条用户指令。

裁剪以「完整轮次」为单位进行，避免拆散 assistant 工具调用与其对应的 tool
结果，从而保证消息序列对 API 始终合法。
"""
from __future__ import annotations

import json


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

    def build(self) -> list[dict]:
        """返回发给模型的消息列表，并就地裁剪超预算的历史。"""
        self._trim_if_needed()
        return [{"role": "system", "content": self.system_prompt}] + self.messages

    # —— 内部 ——

    def _trim_if_needed(self) -> None:
        """超出预算时，从第二条 user 消息开始删除最早的完整轮次。"""
        while self._total_tokens() > self.budget_tokens:
            second_user_idx = self._find_next_user_idx(start=1)
            if second_user_idx is None:
                # 只有一个 user 任务且已超预算：无法安全裁剪（会拆散工具对），
                # 交由 max_iterations 兜底，防止无限增长。
                break
            third_user_idx = self._find_next_user_idx(start=second_user_idx + 1)
            end = third_user_idx if third_user_idx is not None else len(self.messages)
            del self.messages[second_user_idx:end]

    def _find_next_user_idx(self, start: int) -> int | None:
        for i in range(start, len(self.messages)):
            if self.messages[i]["role"] == "user":
                return i
        return None

    def _total_tokens(self) -> int:
        total = estimate_tokens(self.system_prompt)
        for msg in self.messages:
            total += estimate_tokens(json.dumps(msg, ensure_ascii=False))
        return total
