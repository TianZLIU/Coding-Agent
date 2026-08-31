"""成本统计单元测试。"""
import unittest

from agent.usage import CostStats, format_cost_report


class CostStatsTest(unittest.TestCase):
    def test_add_usage_accumulates_tokens(self):
        stats = CostStats()
        stats.add_usage({"prompt_tokens": 100, "completion_tokens": 50})
        stats.add_usage({"prompt_tokens": 200, "completion_tokens": 80})
        self.assertEqual(stats.prompt_tokens, 300)
        self.assertEqual(stats.completion_tokens, 130)
        self.assertEqual(stats.total_tokens, 430)
        self.assertEqual(stats.calls, 2)

    def test_add_usage_ignores_none(self):
        stats = CostStats()
        stats.add_usage(None)
        self.assertEqual(stats.calls, 0)
        self.assertEqual(stats.total_tokens, 0)

    def test_cost_uses_per_million_pricing(self):
        stats = CostStats(prompt_tokens=1_000_000, completion_tokens=1_000_000)
        # 1M * 1元 + 1M * 2元 = 3 元
        self.assertAlmostEqual(stats.cost(1.0, 2.0), 3.0)

    def test_total_seconds_sums_model_and_tool(self):
        stats = CostStats(model_seconds=1.5, tool_seconds=0.5)
        self.assertEqual(stats.total_seconds, 2.0)

    def test_format_report_contains_metrics(self):
        stats = CostStats(
            prompt_tokens=1000,
            completion_tokens=500,
            calls=3,
            model_seconds=2.0,
            tool_seconds=1.0,
        )
        report = format_cost_report(stats, 1.0, 2.0)
        self.assertIn("3 次", report)
        self.assertIn("1,500", report)  # 合计 token 的千分位格式
        self.assertIn("¥0.0020", report)  # 1000/1e6*1 + 500/1e6*2 = 0.002


if __name__ == "__main__":
    unittest.main()
