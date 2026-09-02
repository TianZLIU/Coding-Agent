coding-agent —— 自研 ReAct 编程智能体

【仓库地址】https://github.com/TianZLIU/Coding-Agent

【如何运行】
pip install -r requirements.txt
复制 .env.example 为 .env，填入 DEEPSEEK_API_KEY
python main.py                      # 交互式 REPL
python main.py "任务描述"           # 单任务
python main.py --verbose "任务"     # 打印每轮 token / 工具调用 / 耗时
python demo.py                      # 一键演示
python -m streamlit run web_app.py  # 网页版（或双击 启动网页.bat）
（也可 pip install -e . 后直接敲 coding-agent）

【特色功能】
1. 全自研工具循环：不依赖任何 agent 框架，仅用 DeepSeek 官方客户端做原始调用。
2. 9 个本地工具：列目录、读文件、写文件、精确改文件、通配符查找、grep 搜索、执行命令、长期记忆、按需技能。
3. 四层 cheap-first 上下文压缩：大结果落盘、旧结果占位、裁中间、摘要兜底，免费手段优先。
4. 并行工具执行：只读并行、含写串行，兼顾速度与因果。
5. 三重终止条件 + 自恢复错误处理：工具异常回传自纠、模型调用指数退避。
6. 双层安全沙箱：破坏性命令拦截 + 文件访问路径越界防护。
7. 长期记忆 + 声明式技能：项目约定与常用工作流沉淀复用。
8. 双入口：命令行 REPL 与 Streamlit 网页版共用同一核心与会话存储。

【其它说明】
- 120 个单元测试 + 7 个评测任务全部通过（成功率 100%）。
- 模型与语言不限；凭据走环境变量或 .env，不入库。
