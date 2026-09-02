coding-agent —— 自研 ReAct 编程智能体

【仓库地址】https://github.com/TianZLIU/Coding-Agent

【项目简介】
一个不依赖任何 agent 框架、从零实现的编程智能体：给一句自然语言任务，它会自主读文件、写代码、运行命令，直到完成。模型层只用 DeepSeek 官方客户端做原始调用，循环、解析、执行、上下文管理全部自研。

【技术栈】
Python 3.11+ · DeepSeek API（OpenAI 兼容客户端）· Streamlit（网页壳）· rich / prompt_toolkit（CLI 交互）

【如何运行】
pip install -e ".[web]"             # 一次装好：项目 + coding-agent 命令 + 全部依赖
复制 .env.example 为 .env，填入 DEEPSEEK_API_KEY
coding-agent                        # 交互式 REPL
coding-agent "任务描述"             # 单任务模式
coding-agent --verbose "任务"       # 打印每轮 token / 工具调用 / 耗时
python -m streamlit run web_app.py  # 网页版（或双击 启动网页.bat）
# 不装 CLI 也行：pip install -r requirements.txt 后 python main.py "任务" 直接跑

【工作流程】
每轮循环：① 模型给出「文本答案或工具调用」→ ② 若是工具调用，本地解析参数并真正执行 → ③ 把结果回传模型 → ④ 重复，直到模型输出纯文本、判定任务完成。三重终止条件 + 重复调用护栏保证必然停下、不死循环。

【目录结构】
main.py        命令行入口（REPL / 单任务 / 会话持久化）
web_app.py     Streamlit 网页版（同一核心的展示外壳）
agent/         核心模块：config / llm / parser / history / agent / tools
tests/         单元测试（120 个）
eval/          评测脚本（7 个固定任务量化成功率）

【特色功能】
1. 全自研 ReAct 工具循环：三重终止条件 + 重复调用护栏，防死循环。
2. 9 个本地工具：列目录、读文件、写文件、精确改文件、通配符查找、grep 搜索、执行命令、长期记忆、按需技能。
3. 四层 cheap-first 上下文压缩：大结果落盘、旧结果占位、裁中间、摘要兜底，免费手段优先。
4. 并行工具执行：只读并行、含写串行，兼顾速度与因果。
5. 模型输出 JSON 容错解析：参数带瑕疵时回传模型自纠，不崩溃。
6. 自恢复错误处理：工具异常回传 traceback、模型调用指数退避。
7. 双层安全沙箱：破坏性命令拦截 + 文件访问路径越界防护。
8. 长期记忆 + 声明式技能：项目约定与常用工作流沉淀复用。
9. 双入口 + 会话管理：命令行与网页版共用同一核心与 .sessions 会话存储。

【测试与评测】
python -m unittest discover -s tests -t .   # 120 个单元测试，全绿
python -m eval.run                          # 7 个评测任务，成功率 100%

【其它说明】
模型与语言不限；凭据走环境变量或 .env，不入库。
