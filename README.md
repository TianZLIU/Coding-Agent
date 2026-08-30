# coding-agent

[![CI](https://github.com/TianZLIU/Coding-Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/TianZLIU/Coding-Agent/actions/workflows/ci.yml)

一个自研的编程智能体（coding agent）：通过与大语言模型交互，自主读写文件、执行命令，完成编程任务——类似一个简化的 Claude Code / Codex / OpenCode。

> 软件工程专业项目。独立设计实现，不依赖任何 agent 框架 / SDK。

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置凭据（任选其一）
#    a) 复制 .env.example 为 .env 并填入真实 key
#    b) 或设置环境变量 DEEPSEEK_API_KEY=sk-...

# 3. 运行
python main.py              # 交互式 REPL
python main.py "用 Python 写一个冒泡排序并测试"   # 单任务模式
```

## 架构

```
main.py             CLI 入口（REPL / 单任务）
agent/
├── config.py       配置与凭据加载（.env，不入库）
├── llm.py          DeepSeek 客户端（仅原始调用 + 反序列化）
├── parser.py       模型输出解析（tool_call 参数 JSON 容错）
├── history.py      对话历史 + 上下文管理（token 预算裁剪）
├── agent.py        核心循环（工具循环 + 终止条件 + 错误处理）
└── tools/
    ├── base.py     Tool 抽象 + Toolbox 分发
    ├── files.py    list_dir / read_file / write_file / edit_file / glob_files
    └── shell.py    run_command（本地命令执行）
```

## 核心循环（ReAct 风格）

```
用户任务 → 加入历史
   └─→ 组装消息（system + 裁剪后历史）→ 调用模型（携带工具 schema）
        ├─ 返回 tool_calls → 解析参数 → 本地执行 → 结果回填 → 回到「组装消息」
        └─ 返回文本      → 视为最终回答 → 终止
```

## 关键设计决策

| 问题 | 决策 | 理由 |
|---|---|---|
| 为何自写循环而非用框架 | 题目禁止框架，且自写能精确控制每个环节 | 逻辑透明、易调试、可解释 |
| 模型输出如何解析 | 模型返回 tool_call 的 JSON 参数字符串，用 `parser.py` 容错解析（空串→空参、非法 JSON→报错回传） | 模型偶尔返回空参或格式瑕疵，需容错 |
| 上下文如何管理 | `history.py` 维护消息列表，超出 token 预算时按「完整轮次」裁剪，始终保留 system 与首条用户指令 | 按轮次裁剪避免拆散工具调用对，保证消息序列合法 |
| 循环何时终止 | ① 模型不再请求工具（最终回答）② 达 `max_iterations` 上限 ③ 模型调用重试仍失败 | 三重兜底，防止失控死循环 |
| 错误如何处理 | 工具异常→转成可读错误回传模型自纠；模型调用→指数退避重试 | 让 agent 具备自恢复能力 |
| 命令执行安全 | 限制在 working_dir、带超时、输出截断、返回退出码 | 平衡能力与可控性 |
| 为何用 openai SDK | 它是 DeepSeek 官方推荐的 API 客户端（非框架），只承担 HTTP + 反序列化 | 题目允许厂商客户端库 |

## 工具一览

- `list_dir` — 列目录
- `read_file` — 读文件（带行号，可指定范围）
- `write_file` — 创建/覆盖写文件
- `edit_file` — 精确字符串替换（要求 old_string 唯一）
- `glob_files` — 通配符查找文件
- `run_command` — 本地执行命令（超时 + 输出截断）
