"""声明式技能（Skills）：把常用工作流沉淀为可复用、按需加载的技能文件。

对应 Claude Code 的 Skills（「该重复的变 Skill」）思想：启动时只把「名称 + 描述」
清单注入 system prompt（省 token），模型真正需要时才 invoke_skill(name) 加载正文，
避免技能全文常驻主上下文。

技能文件约定（放在工作目录 .agents/skills/ 下）：
- 目录形式：.agents/skills/<技能名>/SKILL.md
- 平铺形式：.agents/skills/<技能名>.md

文件顶部可用 frontmatter 声明 name / description：
    ---
    name: write-code-with-tests
    description: 写代码 + 写测试 + 跑测试
    ---
    （正文……）

缺省时 name 取目录名/文件名，description 取正文第一个非空行。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .tools.base import Tool

SKILLS_DIR_NAME = ".agents/skills"


@dataclass
class Skill:
    name: str
    description: str
    body: str


class SkillManager:
    """扫描工作目录 .agents/skills/，提供清单注入与按需加载。"""

    def __init__(self, working_dir: str):
        self.skills_dir = Path(working_dir) / SKILLS_DIR_NAME
        self.skills: dict[str, Skill] = {}
        self.discover()

    def discover(self) -> None:
        self.skills = {}
        if not self.skills_dir.is_dir():
            return
        # 目录形式：<skills_dir>/<name>/SKILL.md
        for skill_md in sorted(self.skills_dir.rglob("SKILL.md")):
            if skill_md.parent == self.skills_dir:
                continue
            self._register(skill_md.parent.name, skill_md)
        # 平铺形式：<skills_dir>/<name>.md
        for md in sorted(self.skills_dir.glob("*.md")):
            if md.name == "SKILL.md":
                continue
            self._register(md.stem, md)

    def _register(self, fallback_name: str, path: Path) -> None:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        name, description, body = _parse_skill(text, fallback_name)
        self.skills[name] = Skill(name=name, description=description, body=body.strip())

    def names(self) -> list[str]:
        return sorted(self.skills)

    def manifest(self) -> str:
        """清单：仅名称 + 描述，注入 system prompt 用（省 token）。"""
        if not self.skills:
            return ""
        return "\n".join(
            f"- {s.name}: {s.description}"
            for s in sorted(self.skills.values(), key=lambda s: s.name)
        )

    def load(self, name: str) -> str | None:
        """按需加载技能正文；不存在返回 None。"""
        skill = self.skills.get(name)
        return skill.body if skill else None


def _parse_skill(text: str, fallback_name: str) -> tuple[str, str, str]:
    """解析技能文件：可选 frontmatter（name/description）+ 正文。"""
    name = fallback_name
    description = ""
    lines = text.splitlines()
    body = text
    if lines and lines[0].strip() == "---":
        end = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end = i
                break
        if end is not None:
            for ln in lines[1:end]:
                if ":" in ln:
                    key, val = ln.split(":", 1)
                    key = key.strip().lower()
                    val = val.strip()
                    if key == "name" and val:
                        name = val
                    elif key == "description" and val:
                        description = val
            body = "\n".join(lines[end + 1 :])
    if not description:
        for ln in lines:
            s = ln.strip()
            if s and s != "---":
                description = s.lstrip("#").strip()
                break
    return name, description, body


def make_skill_tool(manager: SkillManager) -> Tool:
    """构造 invoke_skill 工具，让模型按需加载技能正文。"""

    def handler(args: dict) -> str:
        name = args.get("name", "")
        if not name:
            avail = ", ".join(manager.names()) or "（无）"
            return f"用法：invoke_skill(name=<技能名>)。可用技能：{avail}"
        body = manager.load(name)
        if body is None:
            avail = ", ".join(manager.names()) or "（无）"
            return f"错误：未找到技能「{name}」。可用技能：{avail}"
        return body

    return Tool(
        name="invoke_skill",
        description="加载并查看某个技能的完整说明（仅按需调用，避免技能全文常驻上下文）。",
        parameters={"name": {"type": "string", "description": "技能名，见 system prompt 里的技能清单"}},
        required=["name"],
        handler=handler,
        read_only=True,
    )
