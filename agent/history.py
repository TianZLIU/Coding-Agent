"""对话历史与上下文管理。

题目要求自行编写的核心逻辑之一：维护 system + 多轮 user/assistant/tool 消息，
并在超出 token 预算时裁剪最早的非关键轮次，同时始终保留 system 提示词与
第一条用户指令。

上下文压缩采用「cheap-first」四层管线：
- L3 大结果落盘：单条工具结果超阈值 → 写盘 .agent_results/<id>.txt，视图只留句柄+预览；
- L2 旧结果占位：非最近 N 条工具结果 → 视图内容换占位符，保留 tool_call_id 保配对；
- L1 裁中间：消息条数超限 → 留头尾、中间插 [snipped] 占位（对齐安全切点）；
- L4 摘要（兜底）：前三层免费压缩后仍超预算，才调用模型把最早轮次总结后删除。

L3/L2/L1 都是「视图级」压缩，不改动 self.messages 原文、不调 API（零耗损）；
只有 L4 是 lossy 且要花 API 钱，所以被放到最后。
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

# —— 免费层阈值（可按需调整）——
LARGE_RESULT_CHARS = 2000   # L3：单条工具结果超过该字符数即落盘
LARGE_RESULT_PREVIEW = 200  # L3：落盘后视图保留的预览字符数
RECENT_RESULTS = 8          # L2：保留最近 N 条工具结果的完整内容
MAX_VIEW_MESSAGES = 40      # L1：视图消息条数上限
KEEP_HEAD = 3               # L1：保留头部条数
KEEP_TAIL = 20              # L1：保留尾部条数


def estimate_tokens(text: str) -> int:
    """粗略估算 token 数：英文约 4 字符/token，中文约 1 字符/token。

    不引入额外分词器，用启发式估算已足以支撑上下文裁剪的决策。
    """
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    cjk_chars = len(text) - ascii_chars
    return ascii_chars // 4 + cjk_chars


def _is_safe_cut(view: list[dict], i: int) -> bool:
    """切点 i（切在 view[i-1] 与 view[i] 之间）是否安全。

    左边不能是待配对的 assistant(tool_calls)、右边不能是孤立的 tool 结果，
    否则会拆散 tool_call 与 tool_result 的配对，导致消息序列对 API 非法。
    """
    left = view[i - 1]
    right = view[i]
    left_is_tool_call = left["role"] == "assistant" and left.get("tool_calls")
    right_is_tool = right["role"] == "tool"
    return not left_is_tool_call and not right_is_tool


class ConversationHistory:
    def __init__(self, system_prompt: str, budget_tokens: int, results_dir: Path | None = None):
        self.system_prompt = system_prompt
        self.budget_tokens = budget_tokens
        self.results_dir = results_dir  # L3 落盘目录（None 则禁用 L3）
        self.messages: list[dict] = []
        self.summaries: list[str] = []
        # usage 锚定估算状态：_token_ratio 由真实 prompt_tokens 动态校准，
        # 为 None 时退回 estimate_tokens 的固定启发式（英文 4 字符/token）。
        self._token_ratio: float | None = None
        self._last_view_chars: int = 0

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
        """返回发给模型的消息列表，并就地压缩超预算的历史。

        cheap-first：先施加免费的视图级压缩（L3/L2/L1），若压缩后的视图仍超
        预算，才退到 L4（调用 summarizer 总结最早轮次并删除）。summarizer 为
        None 时 L4 退化为「直接丢弃最早轮次」。
        """
        while True:
            view = self._free_view()
            if self._tokens_of_view(view) <= self.budget_tokens:
                break
            if not self._summarize_oldest_round(summarizer):
                # 无可裁剪轮次（如单任务只有一条 user），交由 max_iterations 兜底
                break
        result = self._assemble(view)
        self._last_view_chars = len(json.dumps(result, ensure_ascii=False))
        return result

    def token_count(self) -> int:
        """当前视图（免费压缩后）的估算 token 数，供 --verbose 追踪显示。"""
        return self._tokens_of_view(self._free_view(write_disk=False))

    def record_usage(self, prompt_tokens: int) -> None:
        """用 API 返回的真实 prompt_tokens 校准估算比例（usage 锚定）。

        ratio = 实测 prompt_tokens / 上一次发送视图的字符数；此后 _tokens_of_view
        据此把「字符数」换算成 token，比固定「4 字符/token」更贴近模型真实分词。
        """
        if prompt_tokens > 0 and self._last_view_chars > 0:
            self._token_ratio = prompt_tokens / self._last_view_chars

    def context_stats(self) -> dict:
        """当前上下文状态摘要（只读，供 /context 命令展示）。

        不调用 API、不改动 self.messages；L3/L2/L1 的计数是与 _free_view
        同源的静态分析——「若此刻组装会触发多少」。L4 摘要数是已实际发生过的次数。
        """
        roles: dict[str, int] = {}
        tool_count = 0
        large_results = 0
        for m in self.messages:
            roles[m["role"]] = roles.get(m["role"], 0) + 1
            if m["role"] == "tool":
                tool_count += 1
                if len(m.get("content", "")) > LARGE_RESULT_CHARS:
                    large_results += 1
        offloaded_files = 0
        if self.results_dir is not None and self.results_dir.exists():
            offloaded_files = sum(1 for p in self.results_dir.iterdir() if p.is_file())
        return {
            "budget_tokens": self.budget_tokens,
            "tokens": self.token_count(),
            "ratio_anchored": self._token_ratio is not None,
            "message_count": len(self.messages),
            "roles": roles,
            "summary_count": len(self.summaries),
            "l3_large_results": large_results,
            "l3_files_on_disk": offloaded_files,
            "l2_compacted": max(0, tool_count - RECENT_RESULTS),
            "l1_over_limit": max(0, len(self.messages) - MAX_VIEW_MESSAGES),
        }

    # —— 免费层压缩（视图级，非破坏）——

    def _free_view(self, write_disk: bool = True) -> list[dict]:
        """对当前消息施加 L3→L2→L1 免费压缩，返回压缩后的视图副本。

        不修改 self.messages；L3 会把大结果写盘（write_disk=True 时）。
        """
        view = [dict(m) for m in self.messages]
        view = self._l3_offload(view, write_disk)
        view = self._l2_placeholder(view)
        view = self._l1_cut_middle(view)
        return view

    def _l3_offload(self, view: list[dict], write_disk: bool) -> list[dict]:
        """L3：超长工具结果写盘，视图只留句柄 + 预览，避免塞满全文。"""
        if self.results_dir is None:
            return view
        for i, msg in enumerate(view):
            if msg["role"] != "tool":
                continue
            content = msg.get("content", "")
            if len(content) <= LARGE_RESULT_CHARS:
                continue
            file_name = f"{msg.get('tool_call_id', i)}.txt"
            if write_disk:
                self.results_dir.mkdir(parents=True, exist_ok=True)
                (self.results_dir / file_name).write_text(content, encoding="utf-8")
            preview = content[:LARGE_RESULT_PREVIEW]
            msg["content"] = (
                f"[persisted-output] 该工具结果共 {len(content)} 字符，"
                f"已落盘到 .agent_results/{file_name}。前 {LARGE_RESULT_PREVIEW} 字符预览：\n"
                f"{preview}\n"
                f"需要完整内容时用 read_file 读取 .agent_results/{file_name}。"
            )
        return view

    def _l2_placeholder(self, view: list[dict]) -> list[dict]:
        """L2：非最近 RECENT_RESULTS 条工具结果 → 内容换占位符，保留 tool_call_id。"""
        tool_indices = [i for i, m in enumerate(view) if m["role"] == "tool"]
        if len(tool_indices) <= RECENT_RESULTS:
            return view
        keep = set(tool_indices[-RECENT_RESULTS:])
        for i in tool_indices:
            # 已被 L3 落盘的大结果保留句柄（可恢复），不被 L2 的不可恢复占位覆盖
            if i not in keep and not view[i]["content"].startswith("[persisted-output]"):
                view[i]["content"] = "[Earlier tool result compacted]"
        return view

    def _l1_cut_middle(self, view: list[dict]) -> list[dict]:
        """L1：消息条数超限时，留头 KEEP_HEAD + 尾 KEEP_TAIL，中间插占位。

        切点对齐到安全边界（不拆散 tool_call 与其 tool 结果）。
        """
        if len(view) <= MAX_VIEW_MESSAGES:
            return view
        head_end = min(KEEP_HEAD, len(view))
        while head_end < len(view) and not _is_safe_cut(view, head_end):
            head_end += 1
        tail_start = max(head_end, len(view) - KEEP_TAIL)
        while tail_start > head_end and not _is_safe_cut(view, tail_start):
            tail_start -= 1
        if tail_start <= head_end:
            return view  # 头尾已相接，无需裁
        snipped = tail_start - head_end
        placeholder = {"role": "user", "content": f"[snipped {snipped} messages]"}
        return view[:head_end] + [placeholder] + view[tail_start:]

    # —— L4：摘要兜底（破坏性，删 self.messages）——

    def _summarize_oldest_round(self, summarizer) -> bool:
        """总结并删除最早的完整轮次（从第二条 user 开始）。返回是否真删了一轮。

        提供 summarizer 时先「总结再裁剪」以保留关键信息；总结失败则退回
        「直接丢弃」。摘要累积到独立列表，messages 只删不插，保证循环必然终止。
        """
        second_user_idx = self._find_next_user_idx(start=1)
        if second_user_idx is None:
            return False
        third_user_idx = self._find_next_user_idx(start=second_user_idx + 1)
        end = third_user_idx if third_user_idx is not None else len(self.messages)
        old_round = self.messages[second_user_idx:end]
        del self.messages[second_user_idx:end]
        if summarizer is not None:
            try:
                self.summaries.append(summarizer(old_round))
            except Exception:  # noqa: BLE001 —— 总结失败退回直接丢弃
                pass
        return True

    def _find_next_user_idx(self, start: int) -> int | None:
        for i in range(start, len(self.messages)):
            if self.messages[i]["role"] == "user":
                return i
        return None

    # —— token 估算 ——

    def _assemble(self, view: list[dict]) -> list[dict]:
        result = [{"role": "system", "content": self.system_prompt}]
        if self.summaries:
            result.append(
                {"role": "user", "content": "[前面对话摘要]\n" + "\n\n".join(self.summaries)}
            )
        return result + view

    def _chars_for(self, view: list[dict]) -> int:
        """视图（system + 摘要 + messages）序列化后的字符数，与 ratio 口径一致。"""
        total = len(json.dumps({"role": "system", "content": self.system_prompt}, ensure_ascii=False))
        for summary in self.summaries:
            total += len(json.dumps({"role": "user", "content": "[前面对话摘要]\n" + summary}, ensure_ascii=False))
        for msg in view:
            total += len(json.dumps(msg, ensure_ascii=False))
        return total

    def _tokens_of_view(self, view: list[dict]) -> int:
        if self._token_ratio is not None:
            return max(1, round(self._chars_for(view) * self._token_ratio))
        total = estimate_tokens(self.system_prompt)
        for summary in self.summaries:
            total += estimate_tokens("[前面对话摘要]\n" + summary)
        for msg in view:
            total += estimate_tokens(json.dumps(msg, ensure_ascii=False))
        return total

    def _current_chars(self) -> int:
        """当前未压缩历史的字符数（兼容旧接口，测试与 record_usage 使用）。"""
        return self._chars_for(self.messages)

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
