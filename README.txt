coding-agent —— 自研编程智能体

【仓库地址】https://github.com/TianZLIU/Coding-Agent

【如何运行】
pip install -r requirements.txt
复制 .env.example 为 .env 并填入 DEEPSEEK_API_KEY
python main.py               # 交互式
python main.py "任务描述"     # 单任务

【特色功能】
1. 全自研工具循环：不依赖任何 agent 框架，仅用 DeepSeek 官方客户端完成原始调用。
2. 6 个本地工具：列目录、读文件、写文件、精确改文件、通配符查找、执行命令。
3. 上下文管理：按 token 预算裁剪历史，按完整轮次裁剪，不破坏工具调用配对。
4. 三重终止条件：模型给出最终回答 / 达到最大轮数 / 调用重试失败，防止失控。
5. 自恢复错误处理：工具异常回传模型自纠，模型调用指数退避重试。

【说明】
模型不限、语言不限；凭据走环境变量或 .env，不入库。
