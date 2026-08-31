"""编程智能体的网页界面（Streamlit）。

复用核心 CodingAgent，把原本在终端黑框框里的 agent 搬进浏览器：
- 聊天区：st.chat_input 提问，st.write_stream 流式展示模型回答
- 过程区：每条回答下方用 st.expander 展示本次的工具调用
- 连续对话：agent 与消息历史存于 session_state，跨提交保留
- 持久化：对话历史写入 .web_session.json，刷新/重开浏览器后自动恢复

核心逻辑零改动，本文件只是「壳」。
"""
from __future__ import annotations

import json
import queue
import threading
from pathlib import Path

import streamlit as st

from agent.agent import CodingAgent
from agent.config import Config
from agent.history import ConversationHistory
from agent.usage import format_cost_report

st.set_page_config(page_title="编程智能体", page_icon="🤖", layout="wide")

SESSION_FILE = Path(__file__).resolve().parent / ".web_session.json"

config = Config()

with st.sidebar:
    st.markdown("**运行环境**")
    st.write(f"模型：`{config.model}`")
    st.write(f"工作目录：`{config.working_dir}`")
    if st.button("🗑️ 新开对话", use_container_width=True):
        st.session_state.pop("agent", None)
        st.session_state.pop("messages", None)
        SESSION_FILE.unlink(missing_ok=True)
        st.rerun()

# 初始化 agent 与历史（优先从磁盘恢复，实现刷新后对话不丢）
if "agent" not in st.session_state:
    try:
        config.validate()
    except RuntimeError as exc:
        st.error(f"配置错误：{exc}")
        st.stop()
    agent = CodingAgent(config)
    messages: list[dict] = []
    if SESSION_FILE.exists():
        try:
            data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
            messages = data.get("messages", [])
            hist = data.get("history")
            if hist:
                agent.history = ConversationHistory.from_dict(hist)
        except Exception:  # noqa: BLE001 —— 损坏则当作全新会话
            messages = []
    st.session_state.agent = agent
    st.session_state.messages = messages

agent: CodingAgent = st.session_state.agent


def _save_session() -> None:
    """把消息历史与 agent 上下文写入本地文件，供刷新后恢复。"""
    SESSION_FILE.write_text(
        json.dumps(
            {
                "messages": st.session_state.messages,
                "history": agent.history.to_dict(),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _run_task(prompt: str) -> None:
    """渲染一次提问、运行 agent、流式展示，最后持久化。"""
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        tool_log: list[str] = []
        q: queue.Queue = queue.Queue()
        outcome: list = []

        def _on_event(event: dict) -> None:
            if event["type"] == "tool_call":
                tool_log.append(f"→ `{event['name']}` · {event['elapsed']:.2f}s")

        agent.tracer.sink = _on_event

        def _worker() -> None:
            try:
                result = agent.run(prompt, on_text=lambda d: q.put(("text", d)))
                q.put(("done", result))
            except Exception as exc:  # noqa: BLE001 —— 错误经队列回主线程展示
                q.put(("error", exc))

        threading.Thread(target=_worker, daemon=True).start()

        def _stream():
            while True:
                kind, payload = q.get()
                if kind == "text":
                    yield payload
                else:
                    outcome.append((kind, payload))
                    break

        st.write_stream(_stream())
        agent.tracer.sink = None

        if not outcome:
            st.error("运行未返回结果")
        else:
            kind, payload = outcome[0]
            if kind == "done":
                st.session_state.messages.append(
                    {"role": "assistant", "content": payload.answer}
                )
                if tool_log or payload.cost:
                    with st.expander("执行过程与成本", expanded=False):
                        if tool_log:
                            st.markdown("\n".join(tool_log))
                        if payload.cost:
                            st.text(
                                format_cost_report(
                                    payload.cost,
                                    config.price_input_per_million,
                                    config.price_output_per_million,
                                )
                            )
                cost_yuan = (
                    payload.cost.cost(
                        config.price_input_per_million,
                        config.price_output_per_million,
                    )
                    if payload.cost
                    else 0.0
                )
                st.caption(
                    f"完成 · {payload.iterations} 轮 · {payload.tool_calls} 次工具调用"
                    f" · ¥{cost_yuan:.4f}"
                )
            else:
                st.error(f"运行出错：{payload}")
                if tool_log:
                    st.markdown("\n".join(tool_log))

    _save_session()


st.title("🤖 编程智能体")
st.caption("自研 ReAct 编程智能体 · 通过读写文件、执行命令自主完成编程任务")

# 渲染历史对话
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# 处理新输入（输入框固定在页面底部；示例按钮通过 pending_prompt 触发）
prompt = st.chat_input("输入编程任务，例如：写一个快速排序并测试它")
pending = st.session_state.pop("pending_prompt", None)
if prompt:
    _run_task(prompt)
elif pending is not None:
    _run_task(pending)

# 欢迎语 + 示例任务（处理完输入后仍无历史时才显示，避免首次输入后残留）
if not st.session_state.messages:
    st.markdown("##### 试试这些任务，或直接在下方输入：")
    examples = [
        "列出当前目录下的文件",
        "写一个快速排序，并写测试验证",
        "写一个 hello.py 打印 Hello World",
    ]
    cols = st.columns(len(examples))
    for col, ex in zip(cols, examples):
        if col.button(ex, use_container_width=True, key=f"example_{ex}"):
            st.session_state.pending_prompt = ex
            st.rerun()
