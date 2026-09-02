"""工具抽象与分发。

每个工具由三部分组成：名字、JSON Schema 参数定义、本地执行函数。
Toolbox 负责把工具描述发给模型，并在模型请求时、执行前先跑一遍可插拔的
pre-tool hook 拦截层，再调度到对应的本地函数。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ..hooks import Hook


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]       # JSON Schema 的 properties
    handler: Callable[[dict], str]   # 本地执行函数，入参为解析后的参数字典
    required: list[str] = field(default_factory=list)
    read_only: bool = False          # True 表示无副作用，可与其它只读工具并行

    def to_openai_schema(self) -> dict:
        """转换为 OpenAI function-calling 格式的工具描述。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.parameters,
                    "required": self.required,
                },
            },
        }


class Toolbox:
    """持有全部工具，负责生成 schema、跑 hook 拦截层，并分发执行。"""

    def __init__(self, tools: list[Tool], hooks: list[Hook] | None = None):
        self._map: dict[str, Tool] = {t.name: t for t in tools}
        self._hooks: list[Hook] = list(hooks) if hooks else []

    def schemas(self) -> list[dict]:
        return [t.to_openai_schema() for t in self._map.values()]

    def add(self, tool: Tool) -> None:
        """追加一个工具（供 agent 构造时动态补充，如 memory / skill 工具）。"""
        self._map[tool.name] = tool

    def add_hook(self, hook: Hook) -> None:
        """追加一个 pre-tool hook（可插拔安全策略），在工具执行前生效。"""
        self._hooks.append(hook)

    def is_read_only(self, name: str) -> bool:
        """工具是否为只读（无副作用），用于决定可否并行执行。"""
        tool = self._map.get(name)
        return tool is not None and tool.read_only

    def execute(self, name: str, args: dict) -> str:
        """执行工具：先跑 hook 拦截层，再分发；任何异常转成给模型的错误描述。

        可插拔拦截层：依次执行每个 hook；任一返回 allowed=False 即阻断并把原因
        回传模型；hook 也可通过 updated_args 改写参数后再继续。这样模型能读到
        失败原因并自行修正，而不是让整个循环崩溃。
        """
        tool = self._map.get(name)
        if tool is None:
            return f"错误：未知工具「{name}」。可用工具：{', '.join(self._map)}。"
        for hook in self._hooks:
            result = hook(name, args)
            if not result.allowed:
                return result.reason or f"已拦截：工具「{name}」被 hook 阻断。"
            if result.updated_args is not None:
                args = result.updated_args
        try:
            return tool.handler(args)
        except Exception as exc:  # noqa: BLE001 —— 统一转为可读错误回传模型
            return f"工具「{name}」执行出错：{type(exc).__name__}: {exc}"
