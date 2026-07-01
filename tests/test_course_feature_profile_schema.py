from __future__ import annotations

import unittest

from pydantic import ValidationError

from src.models.course_features import CourseFeatureProfile
from src.models.recommendation import CourseCandidate, KeywordSearchHit
from src.recommendation.query_builder import QueryBuilder
from src.recommendation.repository import CourseSearchRow, RecommendationRepository
from src.recommendation.retrieval import KeywordRetriever
from src.recommendation.retrieval import CandidateMerger


class CourseFeatureProfileSchemaTests(unittest.TestCase):
    def test_legacy_course_candidate_without_features_parses_safely(self) -> None:
        candidate = CourseCandidate(
            course_id="course-1",
            course_name="Master of Computer Science",
            cricos="123456A",
        )

        self.assertIsNone(candidate.course_features)

    def test_valid_feature_profile_round_trips_through_course_candidate(self) -> None:
        candidates = CandidateMerger().merge(
            keyword_hits=[
                KeywordSearchHit(
                    course_id="course-1",
                    course_name="Master of Data Science",
                    cricos="123456A",
                    course_features={
                        "discipline_tags": ["Data Science"],
                        "knowledge_tags": ["Machine Learning"],
                        "ai_relevance": 4,
                        "data_relevance": 5,
                    },
                    keyword_score=0.8,
                    retrieval_reason="keyword",
                )
            ],
            vector_hits=[],
            course_rows={},
            intakes_by_course_id={"course-1": ["FEB"]},
            final_candidate_limit=10,
            evidence_snippet_limit=3,
        )

        dumped = candidates[0].model_dump()
        reparsed = CourseCandidate.model_validate(dumped)

        self.assertEqual(reparsed.course_features.discipline_tags, ["data science"])
        self.assertEqual(reparsed.course_features.ai_relevance, 4)
        self.assertEqual(reparsed.course_features.data_relevance, 5)

    def test_feature_profile_rejects_scores_outside_zero_to_five(self) -> None:
        with self.assertRaises(ValidationError):
            CourseFeatureProfile(ai_relevance=6)

    def test_keyword_retrieval_preserves_stored_course_features(self) -> None:
        retriever = KeywordRetriever(_FeatureProfileRepository())

        hits = retriever.retrieve(
            object(),
            query_spec=QueryBuilder().build("data"),
            top_k=5,
            request_id="test-feature-storage",
        )

        self.assertEqual(hits[0].course_features.discipline_tags, ["data science"])
        self.assertEqual(hits[0].course_features.data_relevance, 5)

    def test_repository_fetches_course_features_from_storage(self) -> None:
        rows = RecommendationRepository().fetch_courses_by_ids(
            _FeatureProfileConnection(),
            course_ids=["course-1"],
        )

        self.assertEqual(rows["course-1"].course_features["ai_relevance"], 4)


class _FeatureProfileRepository:
    def search_courses_by_keywords(self, conn, *, keywords: list[str], limit: int) -> list[CourseSearchRow]:
        return [
            CourseSearchRow(
                course_id="course-1",
                course_name="Master of Data Science",
                course_name_raw="Master of Data Science",
                cricos="123456A",
                duration_min_years=1.5,
                duration_max_years=1.5,
                tuition_fee_aud=56000,
                academic_requirement_text="Data science admission requirements.",
                raw_english_requirement="6.5 (6.0)",
                ielts_overall_required=6.5,
                ielts_min_band_required=6.0,
                source_url="https://www.sydney.edu.au/courses/test.html",
                course_features={
                    "discipline_tags": ["Data Science"],
                    "data_relevance": 5,
                },
            )
        ][:limit]


class _FeatureProfileConnection:
    def cursor(self):
        return _FeatureProfileCursor()


class _FeatureProfileCursor:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params: list[object]) -> None:
        if "c.course_features" not in sql:
            raise AssertionError("courses query must select c.course_features")

    def fetchall(self):
        return [
            (
                "course-1",
                "Master of Data Science",
                "Master of Data Science",
                "123456A",
                1.5,
                1.5,
                56000,
                "Data science admission requirements.",
                "6.5 (6.0)",
                6.5,
                6.0,
                "https://www.sydney.edu.au/courses/test.html",
                None,
                None,
                None,
                None,
                {},
                {},
                {},
                {"ai_relevance": 4},
            )
        ]


if __name__ == "__main__":
    unittest.main()
