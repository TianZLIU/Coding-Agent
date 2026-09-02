---
name: write-code-with-tests
description: 实现函数/类并配套单元测试，跑通后交付
---

# 写代码 + 写测试 + 跑测试

## 步骤
1. 先 list_dir / read_file 了解现有结构与命名约定。
2. 用 write_file 写实现（模块名、函数名按用户要求）。
3. 用 write_file 写测试（unittest 风格，覆盖正常与边界用例）。
4. 用 run_command 跑 `python -m unittest <测试文件>` 验证。
5. 若有失败，读错误信息（重点看 traceback 最底行）→ edit_file 修正 → 重跑，直到全绿。
6. 最后用一句话总结：实现位置 + 测试结果。

## 要点
- 修改前先 read_file 确认原文，保证 edit_file 的 old_string 精确唯一。
- 测试失败时，先读 traceback 最底部那一行报错，再决定改哪里。
