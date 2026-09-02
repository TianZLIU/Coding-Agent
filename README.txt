coding-agent —— 自研编程智能体

【仓库地址】https://github.com/TianZLIU/Coding-Agent

【如何运行】
pip install -r requirements.txt
复制 .env.example 为 .env 并填入 DEEPSEEK_API_KEY
python main.py               # 交互式 REPL
python main.py "任务描述"     # 单任务
python demo.py               # 一键演示
（或 pip install -e . 后直接敲 coding-agent）

【特色功能】
1. 全自研工具循环：不依赖任何 agent 框架，仅用 DeepSeek 官方客户端完成原始调用。
2. 9 个本地工具：列目录、读文件、写文件、精确改文件、通配符查找、内容搜索(grep)、执行命令、长期记忆、按需技能加载。
3. 四层 cheap-first 上下文压缩：大结果落盘、旧结果占位、裁中间、摘要兜底，免费手段优先。
4. 并行工具执行：只读并行、含写串行，兼顾速度与因果。
5. 三重终止条件 + 自恢复错误处理：工具异常回传自纠、模型调用指数退避。
6. 双层安全沙箱 + 长期记忆 + 成本统计 + 客观评测 + CI。
7. 声明式技能：常用工作流沉淀为 .agents/skills/*/SKILL.md，清单注入 system、正文按需 invoke_skill 加载。

【说明】
模型不限、语言不限；凭据走环境变量或 .env，不入库。
