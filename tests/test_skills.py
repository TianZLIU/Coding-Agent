"""声明式技能（Skills）测试：SkillManager 发现/解析、invoke_skill 工具、agent 注入清单。"""
import tempfile
import unittest
from pathlib import Path

from agent.agent import CodingAgent
from agent.config import Config
from agent.skills import SkillManager, make_skill_tool


def _write_skill(working_dir: str, rel: str, content: str) -> None:
    p = Path(working_dir) / ".agents" / "skills" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


class SkillManagerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_discover_dir_form_with_frontmatter(self):
        _write_skill(
            self._tmp.name, "write-tests/SKILL.md",
            "---\nname: write-tests\ndescription: 写测试\n---\n# 步骤\n写测试并跑通",
        )
        m = SkillManager(self._tmp.name)
        self.assertIn("write-tests", m.names())
        self.assertIn("write-tests: 写测试", m.manifest())
        self.assertIn("# 步骤", m.load("write-tests"))

    def test_discover_flat_form_no_frontmatter(self):
        _write_skill(self._tmp.name, "lint.md", "# 检查代码规范\n运行 lint")
        m = SkillManager(self._tmp.name)
        self.assertIn("lint", m.names())
        self.assertIn("检查代码规范", m.manifest())

    def test_no_skills_dir_returns_empty(self):
        m = SkillManager(self._tmp.name)
        self.assertEqual(m.names(), [])
        self.assertEqual(m.manifest(), "")
        self.assertIsNone(m.load("anything"))

    def test_load_missing_returns_none(self):
        _write_skill(self._tmp.name, "a/SKILL.md", "---\ndescription: A\n---\nbody")
        m = SkillManager(self._tmp.name)
        self.assertIsNone(m.load("nope"))


class SkillToolTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        _write_skill(
            self._tmp.name, "fix-bug/SKILL.md",
            "---\ndescription: 修复 bug\n---\n步骤：定位 → 修复 → 验证",
        )
        self.tool = make_skill_tool(SkillManager(self._tmp.name))

    def test_invoke_loads_body(self):
        out = self.tool.handler({"name": "fix-bug"})
        self.assertIn("定位", out)

    def test_invoke_missing(self):
        out = self.tool.handler({"name": "nope"})
        self.assertIn("未找到技能", out)

    def test_invoke_no_name_lists(self):
        out = self.tool.handler({})
        self.assertIn("fix-bug", out)


class SkillInjectionTest(unittest.TestCase):
    def test_manifest_injected_into_system_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_skill(tmp, "write-tests/SKILL.md", "---\ndescription: 写代码加测试\n---\nBODY_ONLY_MARKER")
            agent = CodingAgent(Config(api_key="test-key", working_dir=tmp))
            self.assertIn("可用技能", agent.history.system_prompt)
            self.assertIn("写代码加测试", agent.history.system_prompt)
            # 只注入清单（名称+描述），正文用唯一标记验证不注入（省 token）
            self.assertNotIn("BODY_ONLY_MARKER", agent.history.system_prompt)

    def test_no_manifest_when_no_skills(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = CodingAgent(Config(api_key="test-key", working_dir=tmp))
            self.assertNotIn("可用技能", agent.history.system_prompt)

    def test_skill_tool_registered(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = CodingAgent(Config(api_key="test-key", working_dir=tmp))
            names = [s["function"]["name"] for s in agent.tools.schemas()]
            self.assertIn("invoke_skill", names)


if __name__ == "__main__":
    unittest.main()
