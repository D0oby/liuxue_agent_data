from __future__ import annotations

import unittest

from src.vector_store.chunking import TextSection, build_chunks, split_text
from src.vector_store.runner import _format_application_details


class VectorChunkingTests(unittest.TestCase):
    def test_split_text_keeps_chunks_within_limit(self) -> None:
        text = " ".join([f"Sentence {index} has useful admission detail." for index in range(80)])

        chunks = split_text(text, max_chars=180, overlap_chars=30)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 180 for chunk in chunks))

    def test_build_chunks_includes_course_context(self) -> None:
        chunks = build_chunks(
            course_name="Master of Data Science",
            cricos="123456A",
            sections=[
                TextSection(
                    kind="academic",
                    title="Academic admission requirements",
                    body="Applicants need a bachelor's degree with a credit average.",
                )
            ],
            max_chars=500,
        )

        self.assertEqual(len(chunks), 1)
        self.assertIn("Master of Data Science", chunks[0].content)
        self.assertEqual(chunks[0].metadata["cricos"], "123456A")
        self.assertEqual(chunks[0].kind, "academic")

    def test_format_application_details_preserves_flags(self) -> None:
        text = _format_application_details(
            {
                "raw_text": "Submit supporting documents through the online portal.",
                "required_documents": ["CV", "portfolio"],
                "requires_portfolio": True,
                "requires_cv_or_resume": True,
                "limited_places": True,
                "selection_notes": ["Selection is competitive."],
            }
        )

        self.assertIn("Required documents: CV; portfolio", text)
        self.assertIn("Portfolio required", text)
        self.assertIn("Limited places", text)
        self.assertIn("Selection is competitive.", text)


if __name__ == "__main__":
    unittest.main()
