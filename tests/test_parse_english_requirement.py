from __future__ import annotations

import unittest

from src.transform.parse_english_requirement import parse_english_requirement


class ParseEnglishRequirementTests(unittest.TestCase):
    def test_regular_requirement(self) -> None:
        parsed = parse_english_requirement("6.5 (6.0)")
        self.assertEqual(parsed["ielts_overall"], 6.5)
        self.assertEqual(parsed["ielts_min_band"], 6.0)
        self.assertEqual(parsed["ielts_listening"], 6.0)
        self.assertEqual(parsed["ielts_reading"], 6.0)
        self.assertEqual(parsed["ielts_speaking"], 6.0)
        self.assertEqual(parsed["ielts_writing"], 6.0)
        self.assertEqual(parsed["english_req_details"], {})

    def test_irregular_requirement(self) -> None:
        parsed = parse_english_requirement("7.5 (7.0 R/W; 8.0 L/S)")
        self.assertEqual(parsed["ielts_overall"], 7.5)
        self.assertEqual(parsed["ielts_min_band"], 7.0)
        self.assertEqual(parsed["ielts_listening"], 8.0)
        self.assertEqual(parsed["ielts_reading"], 7.0)
        self.assertEqual(parsed["ielts_speaking"], 8.0)
        self.assertEqual(parsed["ielts_writing"], 7.0)
        self.assertEqual(parsed["english_req_details"]["ielts_subscores"]["reading"], 7.0)
        self.assertEqual(parsed["english_req_details"]["ielts_subscores"]["writing"], 7.0)
        self.assertEqual(parsed["english_req_details"]["ielts_subscores"]["listening"], 8.0)
        self.assertEqual(parsed["english_req_details"]["ielts_subscores"]["speaking"], 8.0)


if __name__ == "__main__":
    unittest.main()
