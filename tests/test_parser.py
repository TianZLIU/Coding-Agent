"""parser.py 的单元测试：工具参数 JSON 容错。"""
from __future__ import annotations

import unittest

from agent.parser import ParseError, parse_tool_arguments


class ParseToolArgumentsTest(unittest.TestCase):
    def test_none_or_empty_returns_empty_dict(self):
        self.assertEqual(parse_tool_arguments(None), {})
        self.assertEqual(parse_tool_arguments(""), {})
        self.assertEqual(parse_tool_arguments("   "), {})

    def test_valid_json_object(self):
        self.assertEqual(parse_tool_arguments('{"path": "a.py"}'), {"path": "a.py"})

    def test_json_with_surrounding_whitespace(self):
        self.assertEqual(parse_tool_arguments('  {"a": 1}  '), {"a": 1})

    def test_invalid_json_raises_parse_error(self):
        with self.assertRaises(ParseError):
            parse_tool_arguments("{not json")

    def test_non_object_raises_parse_error(self):
        with self.assertRaises(ParseError):
            parse_tool_arguments("[1, 2, 3]")
        with self.assertRaises(ParseError):
            parse_tool_arguments('"just a string"')


if __name__ == "__main__":
    unittest.main()
