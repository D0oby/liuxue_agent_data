from __future__ import annotations

import unittest

from src.config import FeatureMatchingConfig
from src.models.course_features import CourseFeatureProfile, UserFeatureProfile
from src.models.recommendation import RangePreference, RecommendationRequest
from src.recommendation.course_features import (
    audit_course_feature_profiles,
    filter_courses_by_features,
    generate_course_features,
    match_course_to_user,
    merge_course_feature_override,
)


class CourseFeatureGenerationWorkflowTests(unittest.TestCase):
    def test_rule_based_generation_handles_sparse_data_and_detects_data_ai_features(self) -> None:
        profile = generate_course_features(
            {
                "course_name": "Master of Data Science",
                "academic_requirement_text": (
                    "Study machine learning, artificial intelligence, statistics, "
                    "Python programming and data visualisation."
                ),
                "duration_max_years": 1.5,
                "tuition_fee_aud": 56000,
                "intakes": ["FEB", "JUL"],
            }
        )

        self.assertIn("data science", profile.discipline_tags)
        self.assertIn("machine learning", profile.knowledge_tags)
        self.assertGreaterEqual(profile.ai_relevance, 4)
        self.assertGreaterEqual(profile.data_relevance, 4)
        self.assertGreaterEqual(profile.coding_intensity, 3)

    def test_manual_override_wins_and_survives_regeneration(self) -> None:
        generated = generate_course_features({"course_name": "Master of Information Technology"})

        merged = merge_course_feature_override(
            generated,
            {"discipline_tags": ["business"], "coding_intensity": 1},
        )
        regenerated = merge_course_feature_override(
            generate_course_features({"course_name": "Master of Information Technology"}),
            {"discipline_tags": ["business"], "coding_intensity": 1},
        )

        self.assertEqual(merged.discipline_tags, ["business"])
        self.assertEqual(regenerated.coding_intensity, 1)


class CourseFeatureMatchingWorkflowTests(unittest.TestCase):
    def test_configured_matching_weights_change_match_score(self) -> None:
        course = CourseFeatureProfile(
            discipline_tags=["data science"],
            ai_relevance=5,
            data_relevance=5,
            coding_intensity=4,
        )
        user = UserFeatureProfile(
            discipline_interests=["data science"],
            ai_interest=5,
            data_interest=1,
            coding_strength=0,
        )

        tag_heavy = match_course_to_user(
            course,
            user,
            config=FeatureMatchingConfig(tag_weight=1.0, numeric_weight=0.0),
        )
        numeric_heavy = match_course_to_user(
            course,
            user,
            config=FeatureMatchingConfig(tag_weight=0.0, numeric_weight=1.0),
        )

        self.assertNotEqual(tag_heavy.score, numeric_heavy.score)
        self.assertGreater(tag_heavy.score, 0)
        self.assertGreater(numeric_heavy.score, 0)

    def test_recommendation_request_accepts_explicit_user_features(self) -> None:
        request = RecommendationRequest(
            target_major_keyword="data",
            academic_background="双非",
            budget_range=RangePreference(max=70000),
            duration_preference=RangePreference(max=2),
            user_features={
                "discipline_interests": ["data science"],
                "ai_interest": 5,
                "data_interest": 5,
            },
        )

        self.assertEqual(request.user_features.discipline_interests, ["data science"])
        self.assertEqual(request.user_features.ai_interest, 5)


class CourseFeatureFilteringAndAuditTests(unittest.TestCase):
    def test_filter_courses_by_tags_and_thresholds(self) -> None:
        rows = [
            {
                "course_id": "data",
                "course_name": "Master of Data Science",
                "course_features": CourseFeatureProfile(
                    discipline_tags=["data science"],
                    ai_relevance=5,
                    risk_level=3,
                ),
            },
            {
                "course_id": "arts",
                "course_name": "Master of Arts",
                "course_features": CourseFeatureProfile(discipline_tags=["arts"], ai_relevance=0),
            },
        ]

        filtered = filter_courses_by_features(rows, discipline_tags=["data science"], min_ai_relevance=4)

        self.assertEqual([row["course_id"] for row in filtered], ["data"])

    def test_audit_flags_missing_and_suspicious_profiles(self) -> None:
        findings = audit_course_feature_profiles(
            [
                {"course_id": "missing", "course_name": "Missing Profile", "course_features": None},
                {
                    "course_id": "empty",
                    "course_name": "Empty Profile",
                    "course_features": CourseFeatureProfile(),
                },
                {
                    "course_id": "outlier",
                    "course_name": "Risk Outlier",
                    "course_features": CourseFeatureProfile(risk_level=5),
                },
            ]
        )

        codes = {finding.code for finding in findings}
        self.assertIn("missing_profile", codes)
        self.assertIn("empty_profile", codes)
        self.assertIn("high_risk_profile", codes)


if __name__ == "__main__":
    unittest.main()
