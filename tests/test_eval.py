"""评测任务判定函数测试：用「黄金解法」手工搭建工作目录，验证客观判定正确。

这些测试不跑模型，只为保证新增任务（跨文件重构 / 数据处理）的判定逻辑本身正确，
避免「判定函数写错 → 评测静默失效」。
"""
import tempfile
import unittest
from pathlib import Path

from eval.tasks import TASKS


def _task(name: str):
    return next(t for t in TASKS if t.name == name)


class EvalTaskCheckTest(unittest.TestCase):
    def test_refactor_check_passes_on_golden_solution(self):
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            task = _task("跨文件重构")
            task.setup(workdir)
            (workdir / "common.py").write_text("def double(x):\n    return x * 2\n", encoding="utf-8")
            (workdir / "a.py").write_text("from common import double\n", encoding="utf-8")
            (workdir / "b.py").write_text("from common import double\n", encoding="utf-8")
            self.assertTrue(task.check(workdir))

    def test_refactor_check_fails_without_refactor(self):
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            task = _task("跨文件重构")
            task.setup(workdir)  # 只有 a.py/b.py 各自定义 double，未提取到 common
            self.assertFalse(task.check(workdir))

    def test_sum_evens_check_passes_on_golden_solution(self):
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            task = _task("数据处理")
            task.setup(workdir)
            (workdir / "sum_evens.py").write_text(
                "nums = [int(l) for l in open('numbers.txt')]\n"
                "open('result.txt', 'w').write(str(sum(n for n in nums if n % 2 == 0)))\n",
                encoding="utf-8",
            )
            self.assertTrue(task.check(workdir))


if __name__ == "__main__":
    unittest.main()
