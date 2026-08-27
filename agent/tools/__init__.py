"""工具层：定义工具、本地执行、统一分发。"""
from __future__ import annotations

from ..config import Config
from .base import Toolbox
from .files import make_file_tools
from .shell import make_shell_tool


def build_toolbox(config: Config) -> Toolbox:
    """根据配置组装全部工具。"""
    tools = [
        *make_file_tools(config.working_dir, config.max_output_chars),
        make_shell_tool(config.working_dir, config.max_output_chars),
    ]
    return Toolbox(tools)
