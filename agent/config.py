"""配置与凭据加载。

凭据一律通过环境变量或未入库的 .env 文件读取，绝不硬编码、绝不进仓库。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# 读取项目根目录下的 .env（该文件已加入 .gitignore，不会被提交）
load_dotenv()


@dataclass
class Config:
    """agent 运行所需的全部配置项。"""

    # —— 模型与凭据 ——
    api_key: str = field(default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", ""))
    base_url: str = field(default_factory=lambda: os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    model: str = field(default_factory=lambda: os.getenv("DEEPSEEK_MODEL", "deepseek-chat"))
    temperature: float = 0.2

    # —— agent 行为 ——
    max_iterations: int = 30          # 最大工具循环轮数（终止条件之一）
    context_budget_tokens: int = 56000  # 上下文 token 预算，超出后裁剪历史
    max_output_chars: int = 12000     # 单次工具输出最大字符数，超出截断

    # —— 运行环境 ——
    working_dir: str = field(default_factory=lambda: str(Path.cwd()))

    def validate(self) -> None:
        """启动前校验：必须能拿到 API key。"""
        if not self.api_key:
            raise RuntimeError(
                "未找到 DEEPSEEK_API_KEY。请在环境变量中设置，"
                "或复制 .env.example 为 .env 并填入真实 key。"
            )
