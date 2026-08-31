"""编程智能体的网页界面（Streamlit）。

复用核心 CodingAgent，把原本在终端黑框框里的 agent 搬进浏览器：
- 回答区：st.write_stream 流式展示模型文字
- 过程区：st.status 实时列出每个工具调用（来自 Tracer 的 sink 事件）
- 连续对话：agent 存于 session_state，跨运行保留上下文

核心逻辑零改动，本文件只是「壳」。
"""
from __future__ import annotations

import queue
import threading

import streamlit as st

from agent.agent import CodingAgent
from agent.config import Config

st.set_page_config(page_title="编程智能体", page_icon="🤖", layout="wide")

st.title("🤖 编程智能体")
st.caption("自研 ReAct 编程智能体 · 不依赖任何 agent 框架")

config = Config()

with st.sidebar:
    st.markdown("**运行环境**")
    st.write(f"模型：`{config.model}`")
    st.write(f"工作目录：`{config.working_dir}`")
    if st.button("清空会话", use_container_width=True):
        st.session_state.pop("agent", None)
        st.rerun()

# 会话级 agent：跨 rerun 保留，实现连续对话
if "agent" not in st.session_state:
    try:
        config.validate()
    except RuntimeError as exc:
        st.error(f"配置错误：{exc}")
        st.stop()
    st.session_state.agent = CodingAgent(config)

agent: CodingAgent = st.session_state.agent

task = st.text_area(
    "输入编程任务",
    placeholder="例如：用 Python 写一个快速排序，并写测试验证它",
    height=90,
    key="task_input",
)

if st.button("运行", type="primary", disabled=not task.strip()):
    q: queue.Queue = queue.Queue()
    result_box: list = []

    def _on_text(delta: str) -> None:
        q.put(("text", delta))

    def _on_event(event: dict) -> None:
        q.put(("event", event))

    # 把 agent 的事件流临时接到队列，运行结束后恢复
    agent.tracer.sink = _on_event

    def _worker() -> None:
        try:
            result = agent.run(task, on_text=_on_text)
            q.put(("done", result))
        except Exception as exc:  # noqa: BLE001 —— 显示错误，保持页面存活
            q.put(("error", exc))

    threading.Thread(target=_worker, daemon=True).start()

    status = st.status("agent 工作中…", expanded=True)

    def _stream():
        while True:
            kind, payload = q.get()
            if kind == "text":
                yield payload
            elif kind == "event":
                if payload["type"] == "tool_call":
                    status.write(f"→ `{payload['name']}` · {payload['elapsed']:.2f}s")
            elif kind == "done":
                result_box.append(payload)
                status.update(label="完成", state="complete", expanded=False)
                break
            elif kind == "error":
                status.update(label="出错", state="error", expanded=True)
                st.error(f"运行出错：{payload}")
                break

    st.write_stream(_stream())

    agent.tracer.sink = None

    if result_box:
        r = result_box[0]
        st.success(f"完成 · {r.iterations} 轮 · {r.tool_calls} 次工具调用")
