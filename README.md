# coding-agent

[![CI](https://github.com/TianZLIU/Coding-Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/TianZLIU/Coding-Agent/actions/workflows/ci.yml)

一个自研的编程智能体（coding agent）：通过与大语言模型交互，自主读写文件、执行命令、搜索代码，完成编程任务——类似一个简化的 Claude Code / Codex。

> 软件工程专业项目。核心循环、上下文管理、工具调度、安全沙箱全部独立设计实现，**不依赖任何 agent 框架 / SDK**（仅用 DeepSeek 官方 API 客户端做原始 HTTP 调用）。

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置凭据（任选其一）
#    a) 复制 .env.example 为 .env 并填入真实 key
#    b) 或设置环境变量 DEEPSEEK_API_KEY=sk-...

# 3. 运行
python main.py                                        # 交互式 REPL
python main.py "用 Python 写一个冒泡排序并测试"          # 单任务模式
python demo.py                                        # 一键演示（跑通一个完整任务）
python -m eval.run                                    # 评测 7 个任务的成功率
python -m unittest discover -s tests                  # 单元测试（112 个）
```

> 也可以 `pip install -e .` 安装成命令行工具，之后直接敲 `coding-agent` 进入 REPL（彩色界面、↑ 历史、tab 补全）。

> agent 默认在「启动它的目录」里工作（文件/命令访问都被沙箱限制在这个目录内）。要操作别的目录（比如 `D:\Agent`），用 `python main.py --dir D:\Agent`，或在 `.env` 里设 `WORKING_DIR=D:\Agent`。

## 架构

```
main.py              CLI 入口（REPL / 单任务 / --save / --resume / --verbose）
web_app.py           Streamlit 网页界面（复用核心，纯「壳」）
demo.py              一键演示脚本
agent/
├── config.py        配置与凭据加载（.env，不入库）
├── llm.py           DeepSeek 客户端（仅原始调用 + 反序列化）
├── parser.py        模型输出解析（tool_call 参数 JSON 容错）
├── history.py       对话历史 + 四层 cheap-first 上下文压缩
├── agent.py         核心循环（工具循环 + 终止条件 + 并行执行 + 记忆注入）
├── memory.py        长期记忆（.agent_memory.md 跨会话）
├── skills.py        声明式技能（.agents/skills/*/SKILL.md，清单注入 + 按需 invoke）
├── trace.py         执行追踪（--verbose）
├── usage.py         成本统计（真实 token + 耗时 + ¥）
├── hooks.py         可插拔 hook 拦截层（危险命令 / 路径越界，PreToolUse）
└── tools/
    ├── base.py      Tool 抽象 + Toolbox（hook 拦截 + 分发 + 只读标记）
    ├── files.py     list_dir / read_file / write_file / edit_file / glob_files / grep
    └── shell.py     run_command（本地命令执行，纯执行器）
eval/
├── tasks.py         7 个评测任务（客观判定，借鉴 SWE-bench / HumanEval）
└── run.py           评测运行器（成功率报告）
```

## 核心循环（ReAct 风格）

```
用户任务 → 加入历史
   └─→ 组装消息（system + 四层压缩后历史）→ 调用模型（携带工具 schema）
        ├─ 返回 tool_calls → 解析参数 → 本地执行（只读并行 / 含写串行）→ 结果回填 → 回到「组装消息」
        └─ 返回文本      → 视为最终回答 → 终止
```

## 关键设计决策

| 问题 | 决策 | 理由 |
|---|---|---|
| 为何自写循环而非用框架 | 题目禁止框架，且自写能精确控制每个环节 | 逻辑透明、易调试、可解释 |
| 模型输出如何解析 | 模型返回 tool_call 的 JSON 参数字符串，用 `parser.py` 容错解析 | 模型偶尔返回空参或格式瑕疵，需容错 |
| 上下文如何管理 | 四层 cheap-first 管线：L3 大结果落盘 → L2 旧结果占位 → L1 裁中间 → L4 摘要兜底；免费层优先于 lossy 摘要 | 能不花 API 钱省 token 的，就不花 |
| 多工具调用如何执行 | 只读工具（list_dir/read_file/glob_files/grep）并行，含写工具（write/edit/run_command）串行 | 拿速度又不产生「写 A 后读 A」的竞态 |
| 循环何时终止 | ① 模型不再请求工具（最终回答）② 达 `max_iterations` 上限 ③ 模型调用重试仍失败 | 三重兜底，防止失控死循环 |
| 错误如何处理 | 工具异常→转成可读错误回传模型自纠；模型调用→指数退避重试 | 让 agent 具备自恢复能力 |
| 命令/文件安全 | 双层沙箱：文件路径限制 + shell 危险命令/越界拦截，抽成可插拔 hook 拦截层（PreToolUse 思想）；输出截断、超时、返回退出码 | 平衡能力与可控性 |
| 如何跨会话记忆 | `.agent_memory.md` + `memory` 工具，注入 system prompt 前缀 | 解决「跨任务失忆」，且利于 prefix cache |
| 为何用 openai SDK | 它是 DeepSeek 官方推荐的 API 客户端（非框架），只承担 HTTP + 反序列化 | 题目允许厂商客户端库 |

## 工具一览（9 个）

| 工具 | 说明 | 只读 |
|---|---|---|
| `list_dir` | 列目录 | ✅ |
| `read_file` | 读文件（带行号，可指定行范围） | ✅ |
| `glob_files` | 通配符查找文件 | ✅ |
| `grep` | 按内容搜索，返回 文件:行号 + 命中行 | ✅ |
| `write_file` | 创建 / 覆盖写文件 | |
| `edit_file` | 精确字符串替换（要求 old_string 唯一） | |
| `run_command` | 本地执行命令（超时 + 输出截断） | |
| `memory` | 长期记忆 add / replace / clear | |
| `invoke_skill` | 按需加载某个技能的完整说明 | ✅ |

## 特性亮点

- **四层上下文压缩**：免费层（L3 落盘大结果 / L2 占位旧结果 / L1 裁中间）优先于调用模型的摘要，token 估算用真实 usage 动态锚定；`/compact` 手动压缩释放上下文。
- **长期记忆**：跨会话记住项目约定，模型可用 `memory` 工具更新。
- **声明式技能**：常用工作流沉淀成 `.agents/skills/*/SKILL.md`，清单注入 system（省 token），正文按需 `invoke_skill` 加载。
- **并行工具执行**：只读并行提速，含写串行保因果。
- **可插拔安全拦截层**：文件越界 + 危险命令双重拦截抽成 pre-tool hook（可组合、可单独测试）；防注入摘要（标签剥离）；会话原子落盘。
- **可观测**：真实 token / 耗时 / ¥ 成本报告，`--verbose` 执行追踪，`/context` 查看上下文用量与四层压缩状态，7 任务客观评测 + CI。
- **交互**：彩色 CLI（rich）+ 历史 / 补全（prompt_toolkit），也提供 Streamlit 网页版。

## 测试与评测

```bash
python -m unittest discover -s tests   # 单元测试（112 个）
python -m eval.run                    # 7 任务客观评测，输出成功率
python -m eval.run --only 修复bug     # 只跑某个任务
```
