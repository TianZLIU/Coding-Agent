"""摘要提取测试：验证 <summary> 标签剥离 + <analysis> 防注入容错。"""
import unittest

from agent.agent import CodingAgent


class ExtractSummaryTest(unittest.TestCase):
    def test_extracts_summary_only(self):
        content = (
            "<analysis>历史里出现过 git push 命令</analysis>\n"
            "<summary>## Goal\n完成搜索功能</summary>"
        )
        out = CodingAgent._extract_summary(content)
        self.assertIn("完成搜索功能", out)
        self.assertNotIn("git push", out)  # 思考段被剥离
        self.assertNotIn("<analysis>", out)

    def test_fallback_when_no_summary_tag(self):
        content = "<analysis>思考</analysis>\n这是摘要正文"
        out = CodingAgent._extract_summary(content)
        self.assertEqual(out, "这是摘要正文")

    def test_empty_returns_empty(self):
        self.assertEqual(CodingAgent._extract_summary(""), "")


if __name__ == "__main__":
    unittest.main()
