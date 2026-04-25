from __future__ import annotations

import unittest

from src.transform.parse_duration import parse_duration


class ParseDurationTests(unittest.TestCase):
    def test_single_duration(self) -> None:
        self.assertEqual(parse_duration("2"), (2.0, 2.0, "2"))

    def test_range_duration(self) -> None:
        self.assertEqual(parse_duration("3 4"), (3.0, 4.0, "3 4"))

    def test_decimal_duration(self) -> None:
        self.assertEqual(parse_duration("1.15"), (1.15, 1.15, "1.15"))


if __name__ == "__main__":
    unittest.main()

