"""核心 agent 循环。

这是整个项目的核心：把「对话历史管理 → 调用模型 → 解析输出 → 本地执行工具
→ 结果回填 → 判断终止」串起来。全部逻辑自行实现，不依赖任何 agent 框架。

循环终止条件（题目要求的核心逻辑之一）：
1. 模型返回文本而非工具调用 —— 视为任务完成，正常终止；
2. 迭代次数达到 max_iterations —— 强制终止，防止失控；
3. 模型调用在重试后仍失败 —— 抛异常，由调用方处理。
"""
from __future__ import annotations

import json

from .config import Config
from .history import ConversationHistory
from .llm import LLMClient
from .parser import ParseError, parse_tool_arguments
from .tools import build_toolbox

SYSTEM_PROMPT = """你是一个编程智能体（coding agent），运行在用户的本地机器上。
你的任务是通过读写文件、执行命令，自主完成用户交给你的编程任务。

工作方式：
1. 你可以调用工具（list_dir / read_file / write_file / edit_file / glob_files / run_command）。
2. 每次调用工具后，你会收到执行结果，然后基于结果决定下一步。
3. 当你认为任务已完成时，停止调用工具，直接用文字总结你做了什么、结果如何。

行为准则：
- 先了解现状（列目录、读文件），再动手修改。
- 执行命令前想清楚影响；避免破坏性或不可逆命令。
- 优先在当前工作目录内操作文件。
- 若某操作失败，先读错误信息再修正，不要反复重试相同操作。
- 修改文件前先用 read_file 确认原文，保证 edit_file 的 old_string 精确。
"""

SUMMARY_PROMPT = """你是对话压缩助手。请把下面这段「agent 与工具的交互历史」压缩成一段简洁的中文摘要，用于替换原文以节省上下文。

要求：
- 保留：用户任务目标、已执行的关键操作与命令、重要结论/错误、尚未完成的待办。
- 省略：重复尝试、工具返回的冗长原文、过程性细节。
- 直接输出一段连贯的摘要文字，不要加标题或序号。
"""


class AgentResult:
    def __init__(self, answer: str, iterations: int, tool_calls: int):
        self.answer = answer
        self.iterations = iterations
        self.tool_calls = tool_calls


class CodingAgent:
    def __init__(self, config: Config):
        self.config = config
        self.llm = LLMClient(config)
        self.tools = build_toolbox(config)
        self.history = ConversationHistory(SYSTEM_PROMPT, config.context_budget_tokens)

    def _summarize(self, messages: list[dict]) -> str:
        """把一段历史轮次压缩成摘要（调用模型，不带工具）。"""
        prompt = [
            {"role": "system", "content": SUMMARY_PROMPT},
            {"role": "user", "content": json.dumps(messages, ensure_ascii=False)},
        ]
        resp = self.llm.chat(prompt, tools=[])
        return resp.content or "（无内容）"

    def run(self, task: str, on_text=None) -> AgentResult:
        """执行一个编程任务，返回最终结果。

        on_text（可选）：流式输出回调，模型文本增量会实时传入。传入即启用流式，
        否则退化为整段返回（chat）。
        """
        self.history.add_user(task)
        total_tool_calls = 0

        for iteration in range(1, self.config.max_iterations + 1):
            messages = self.history.build(summarizer=self._summarize)
            if on_text is not None:
                response = self.llm.chat_stream(messages, self.tools.schemas(), on_text=on_text)
            else:
                response = self.llm.chat(messages, self.tools.schemas())

            if response.wants_tool_call:
                # 记录 assistant 的工具调用请求
                self.history.add_assistant_tool_call(response.tool_calls)
                # 逐个本地执行工具，并把结果回填
                for tc in response.tool_calls:
                    try:
                        args = parse_tool_arguments(tc["arguments"])
                    except ParseError as exc:
                        result = f"参数解析失败：{exc}"
                    else:
                        result = self.tools.execute(tc["name"], args)
                    total_tool_calls += 1
                    self.history.add_tool_result(tc["id"], tc["name"], result)
                continue

            # 无工具调用 → 模型给出最终回答，终止
            answer = response.content or "(模型返回了空回答)"
            self.history.add_assistant_text(answer)
            return AgentResult(answer, iteration, total_tool_calls)

        # 达到最大轮数仍无最终回答：强制终止
        fallback = (
            f"已达到最大迭代次数（{self.config.max_iterations}），agent 停止。"
            f"本次共执行 {total_tool_calls} 次工具调用。"
        )
        self.history.add_assistant_text(fallback)
        return AgentResult(fallback, self.config.max_iterations, total_tool_calls)

    def save_session(self, path: str) -> None:
        """把当前会话历史保存到本地 JSON 文件，便于跨进程续聊。"""
        self.history.save(path)

    def load_session(self, path: str) -> None:
        """从本地 JSON 文件恢复会话历史（覆盖当前内存中的历史）。"""
        self.history = ConversationHistory.load(path)
