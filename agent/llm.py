"""DeepSeek 模型客户端。

仅使用厂商官方推荐的 OpenAI 兼容 SDK 完成「原始 HTTP 调用 + JSON 反序列化」，
不做任何 agent 逻辑——工具循环、历史管理、输出解析、终止条件均由本项目自行实现。
"""
from __future__ import annotations

import time
from typing import Any

from openai import OpenAI

from .config import Config


class ChatResponse:
    """归一化后的模型返回结果：要么是文本回答，要么是工具调用。"""

    def __init__(self, content: str | None, tool_calls: list[dict] | None):
        self.content = content or ""
        self.tool_calls = tool_calls or []

    @property
    def wants_tool_call(self) -> bool:
        """模型是否请求调用工具。"""
        return bool(self.tool_calls)


class LLMClient:
    def __init__(self, config: Config):
        self.config = config
        self.client = OpenAI(api_key=config.api_key, base_url=config.base_url)

    def chat(self, messages: list[dict], tools: list[dict]) -> ChatResponse:
        """调用模型，带指数退避重试（应对限流/瞬时网络错误）。"""
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
        }
        if tools:
            kwargs["tools"] = tools

        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                resp = self.client.chat.completions.create(**kwargs)
                return self._parse(resp)
            except Exception as exc:  # noqa: BLE001 —— 统一做重试处理
                last_exc = exc
                time.sleep(2 ** attempt)

        raise RuntimeError(f"模型调用失败（已重试 3 次）：{last_exc}")

    def chat_stream(self, messages: list[dict], tools: list[dict], on_text=None) -> ChatResponse:
        """流式调用模型：文本增量实时回传 on_text，工具调用增量聚合成完整参数。

        与 chat() 相同的指数退避重试。流式过程中若中途出错，重试会重新发起请求，
        极端情况下已输出的文本可能重复——这是「实时性」与「重试」之间的取舍。
        """
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools

        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                stream = self.client.chat.completions.create(**kwargs)
                return self._collect_stream(stream, on_text)
            except Exception as exc:  # noqa: BLE001 —— 统一做重试处理
                last_exc = exc
                time.sleep(2 ** attempt)

        raise RuntimeError(f"模型调用失败（已重试 3 次）：{last_exc}")

    @staticmethod
    def _collect_stream(stream, on_text=None) -> ChatResponse:
        """聚合流式增量：文本按序拼接并实时回调，工具调用按 index 累积参数。"""
        content_parts: list[str] = []
        tool_calls: dict[int, dict[str, Any]] = {}

        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta is None:
                continue
            if delta.content:
                content_parts.append(delta.content)
                if on_text:
                    on_text(delta.content)
            for tc in delta.tool_calls or []:
                entry = tool_calls.setdefault(
                    tc.index, {"id": "", "name": "", "arguments": []}
                )
                if tc.id:
                    entry["id"] = tc.id
                if tc.function and tc.function.name:
                    entry["name"] = tc.function.name
                if tc.function and tc.function.arguments:
                    entry["arguments"].append(tc.function.arguments)

        assembled = [
            {
                "id": tool_calls[i]["id"],
                "name": tool_calls[i]["name"],
                "arguments": "".join(tool_calls[i]["arguments"]),
            }
            for i in sorted(tool_calls)
        ]
        return ChatResponse("".join(content_parts), assembled)

    @staticmethod
    def _parse(resp) -> ChatResponse:
        """把 SDK 返回对象归一化，保留工具调用的原始 JSON 参数串。

        注意：这里只做「结构上的搬运」，参数的 JSON 解析交由 agent/parser.py 完成。
        """
        choice = resp.choices[0].message
        tool_calls = None
        if getattr(choice, "tool_calls", None):
            tool_calls = [
                {
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,  # JSON 字符串，稍后解析
                }
                for tc in choice.tool_calls
            ]
        return ChatResponse(choice.content, tool_calls)
