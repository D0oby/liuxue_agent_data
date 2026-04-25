from __future__ import annotations

import unittest

from src.load.upsert_courses import build_source_row_hash


class ImportIdempotencyTests(unittest.TestCase):
    def test_same_row_generates_same_hash(self) -> None:
        row = {
            "Course Name": "Master of Computer Science",
            "CRICOS": "111671D",
            "IELTS Academic": "6.5 (6.0)",
            "Commencing Semester": "Feb/Aug",
            "Duration (Years)": "1.5",
            "Tuition Fee ($AUD)": "61700",
        }
        hash_one = build_source_row_hash(row, "week1.xlsx", "Sheet1", 12)
        hash_two = build_source_row_hash(row, "week1.xlsx", "Sheet1", 12)
        self.assertEqual(hash_one, hash_two)

    def test_changed_row_number_changes_hash(self) -> None:
        row = {
            "Course Name": "Master of Computer Science",
            "CRICOS": "111671D",
            "IELTS Academic": "6.5 (6.0)",
            "Commencing Semester": "Feb/Aug",
            "Duration (Years)": "1.5",
            "Tuition Fee ($AUD)": "61700",
        }
        hash_one = build_source_row_hash(row, "week1.xlsx", "Sheet1", 12)
        hash_two = build_source_row_hash(row, "week1.xlsx", "Sheet1", 13)
        self.assertNotEqual(hash_one, hash_two)


if __name__ == "__main__":
    unittest.main()
