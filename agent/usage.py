"""成本统计：累计真实 token 与耗时，并按单价折算花费。

区别于 history.estimate_tokens 的启发式估算（英文 4 字符 / token、中文 1 字符
/token，仅用于上下文裁剪决策），这里的 token 数来自 DeepSeek API 返回的真实
usage（prompt_tokens / completion_tokens），是准确的计量值；配合单价即可得到
每次任务的实际花费。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CostStats:
    """一次会话累计的模型调用成本。

    - prompt_tokens / completion_tokens：来自 API 返回的 usage 真实值
    - calls：模型调用次数
    - model_seconds：模型调用的累计墙钟时间
    - tool_seconds：工具执行的累计墙钟时间
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0
    model_seconds: float = 0.0
    tool_seconds: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def total_seconds(self) -> float:
        return self.model_seconds + self.tool_seconds

    def add_usage(self, usage: dict | None) -> None:
        """累加一次 API 调用的真实 usage；usage 为 None（流式未返回）则跳过。"""
        if not usage:
            return
        self.prompt_tokens += usage.get("prompt_tokens", 0) or 0
        self.completion_tokens += usage.get("completion_tokens", 0) or 0
        self.calls += 1

    def cost(self, price_input_per_m: float, price_output_per_m: float) -> float:
        """按「元 / 百万 token」单价折算花费。"""
        return (
            self.prompt_tokens / 1_000_000 * price_input_per_m
            + self.completion_tokens / 1_000_000 * price_output_per_m
        )


def format_cost_report(
    stats: CostStats, price_input_per_m: float, price_output_per_m: float
) -> str:
    """把成本统计格式化为多行报告（CLI 与网页共用）。"""
    return (
        f"📊 成本统计\n"
        f"  模型调用：{stats.calls} 次\n"
        f"  输入 {stats.prompt_tokens:,} / 输出 {stats.completion_tokens:,} tokens"
        f"（合计 {stats.total_tokens:,}）\n"
        f"  模型耗时 {stats.model_seconds:.1f}s / 工具耗时 {stats.tool_seconds:.1f}s"
        f" / 总耗时 {stats.total_seconds:.1f}s\n"
        f"  估算花费：¥{stats.cost(price_input_per_m, price_output_per_m):.4f}"
    )
