"""模型输出解析。

负责把模型返回的工具调用参数（JSON 字符串）解析为字典，并处理各种边界情况：
空参数、多余空白、非法 JSON 等。这是题目要求自行编写的核心逻辑之一。
"""
from __future__ import annotations

import json


class ParseError(Exception):
    """工具参数解析失败。"""


def parse_tool_arguments(arguments: str) -> dict:
    """把模型返回的 JSON 字符串解析成参数字典。

    模型偶尔会对无参工具返回空字符串，或返回带前后空白的 JSON，这里做容错。
    """
    if arguments is None or arguments.strip() == "":
        return {}

    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError as exc:
        raise ParseError(f"工具参数不是合法 JSON：{arguments!r}") from exc

    if not isinstance(parsed, dict):
        raise ParseError(f"工具参数应为 JSON 对象，实际为 {type(parsed).__name__}")

    return parsed
