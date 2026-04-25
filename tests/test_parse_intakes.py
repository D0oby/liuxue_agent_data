from __future__ import annotations

import unittest

from src.transform.parse_intakes import parse_intakes


class ParseIntakesTests(unittest.TestCase):
    def test_mar_july_normalization(self) -> None:
        self.assertEqual(parse_intakes("Mar/July"), ["MAR", "JUL"])

    def test_four_intakes(self) -> None:
        self.assertEqual(parse_intakes("Jan/Mar/Jul/Oct"), ["JAN", "MAR", "JUL", "OCT"])


if __name__ == "__main__":
    unittest.main()

