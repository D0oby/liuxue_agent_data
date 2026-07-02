from __future__ import annotations

from contextlib import contextmanager
import unittest
from unittest.mock import patch

import pandas as pd

from src.config import (
    BandConfig,
    OutputConfig,
    RecommendationConfig,
    RetrievalConfig,
    RulesConfig,
    ScoringConfig,
    Settings,
)
from src.models.recommendation import (
    CourseCandidate,
    EligibilityStatus,
    EvidenceSnippet,
    KeywordSearchHit,
    NormalizedRequirement,
    RangePreference,
    RawAdmissionRequirement,
    RecommendationRequest,
    ScoredCourseCandidate,
    UserProfile,
    VectorSearchHit,
)
from src.recommendation.agent import (
    CalculateMatchScoreTool,
    GeneratePlanTool,
    GetAdmissionRequirementTool,
    ParseUserProfileTool,
    PlanningAgent,
    RunEligibilityGateTool,
    SearchProgramTool,
)
from src.dashboard import (
    _build_courses_query,
    _build_keyword_mask,
    _feature_profile_storage_warning,
    _format_recommendation_error,
    _format_semantic_result_source_bits,
    _highlight_query_terms,
    _read_courses_dataframe,
    build_requirement_checks_dataframe,
)
from src.recommendation.eligibility import EligibilityGate
from src.recommendation.plan import PlanAssembler
from src.recommendation.profile import UserProfileParser
from src.recommendation.query_builder import QueryBuilder
from src.recommendation.repository import CourseSearchRow, RecommendationRepository
from src.recommendation.requirements import RequirementNormalizer, RequirementResult, RequirementService
from src.recommendation.retrieval import AdmissionsRAGService, CandidateMerger, KeywordRetriever, VectorRetriever
from src.recommendation.scoring import BandClassifier, ScoreCalculator, ScoringService
from src.recommendation.service import RecommendationService, RecommendationServiceError
from src.vector_store.storage import SearchResult


class QueryBuilderTests(unittest.TestCase):
    def test_computer_query_mapping(self) -> None:
        query = QueryBuilder().build("计算机")

        self.assertIn("computer science", query.keyword_query)
        self.assertIn("information technology", query.keyword_query)
        self.assertIn("software engineering", query.semantic_query)

    def test_direction_mappings_are_extensible(self) -> None:
        data_query = QueryBuilder().build("数据分析")
        business_query = QueryBuilder().build("商科")

        self.assertIn("data analytics", data_query.keyword_query)
        self.assertIn("business analytics", data_query.semantic_query)
        self.assertIn("commerce", business_query.keyword_query)
        self.assertIn("finance", business_query.semantic_query)


class RequirementNormalizerTests(unittest.TestCase):
    def test_gpa_rule_for_211_background(self) -> None:
        requirement = _raw_requirement()

        normalized = RequirementNormalizer().normalize(requirement, academic_background="211")

        self.assertEqual(normalized.gpa_min, 75.0)

    def test_gpa_rule_for_non_211_background(self) -> None:
        requirement = _raw_requirement()

        normalized = RequirementNormalizer().normalize(requirement, academic_background="双非")

        self.assertEqual(normalized.gpa_min, 80.0)

    def test_usyd_computing_rule_uses_arithmetic_average_thresholds(self) -> None:
        requirement = _raw_requirement()

        normalized_985 = RequirementNormalizer().normalize(
            requirement,
            academic_background="985",
            course_name="Master of Computer Science",
        )
        normalized_non_211 = RequirementNormalizer().normalize(
            requirement,
            academic_background="其他国内院校",
            course_name="Master of Computer Science",
        )

        self.assertEqual(normalized_985.gpa_min, 75.0)
        self.assertEqual(normalized_non_211.gpa_min, 80.0)
        self.assertIn("算术平均分", normalized_985.requirement_summary)
        self.assertEqual(normalized_985.gpa_calculation_method, "usyd_arithmetic_average_all_courses")

    def test_usyd_business_core_rule_uses_pdf_thresholds(self) -> None:
        requirement = _raw_requirement()

        normalized_c9 = RequirementNormalizer().normalize(
            requirement,
            academic_background="C9",
            course_name="Master of Commerce",
        )
        normalized_211 = RequirementNormalizer().normalize(
            requirement,
            academic_background="211",
            course_name="Master of Professional Accounting",
        )
        normalized_non_211 = RequirementNormalizer().normalize(
            requirement,
            academic_background="双非",
            course_name="Master of Commerce",
        )

        self.assertEqual(normalized_c9.gpa_min, 65.0)
        self.assertEqual(normalized_211.gpa_min, 75.0)
        self.assertEqual(normalized_non_211.gpa_min, 87.0)

    def test_ielts_takes_stricter_component_field(self) -> None:
        requirement = _raw_requirement(
            ielts_overall=6.5,
            ielts_min_band=6.0,
            ielts_writing=7.0,
            raw_english_requirement="6.5 (6.0)",
        )

        normalized = RequirementNormalizer().normalize(requirement, academic_background="211")

        self.assertEqual(normalized.ielts_overall_min, 6.5)
        self.assertEqual(normalized.ielts_min_band_min, 7.0)

    def test_ielts_falls_back_to_raw_text_parser(self) -> None:
        requirement = _raw_requirement(
            ielts_overall=None,
            ielts_min_band=None,
            raw_english_requirement="7.5 (7.0 R/W; 8.0 L/S)",
        )

        normalized = RequirementNormalizer().normalize(requirement, academic_background="211")

        self.assertEqual(normalized.ielts_overall_min, 7.5)
        self.assertEqual(normalized.ielts_min_band_min, 8.0)


class EligibilityGateTests(unittest.TestCase):
    def test_gpa_meets_requirement_is_eligible(self) -> None:
        outcome = _eligibility_outcome(profile=_profile(gpa=82), requirement=_normalized_requirement(gpa_min=80))

        self.assertEqual(outcome.decisions[0].eligibility_status, EligibilityStatus.ELIGIBLE)
        self.assertTrue(outcome.decisions[0].can_enter_next_layer)

    def test_gpa_below_without_pathway_is_ineligible(self) -> None:
        outcome = _eligibility_outcome(profile=_profile(gpa=70), requirement=_normalized_requirement(gpa_min=80))

        self.assertEqual(outcome.decisions[0].eligibility_status, EligibilityStatus.INELIGIBLE)
        self.assertFalse(outcome.decisions[0].can_enter_next_layer)
        self.assertIn("GPA", outcome.decisions[0].blocking_reasons[0])

    def test_gpa_below_with_accepted_pathway_is_pathway_required(self) -> None:
        candidate = _candidate(
            academic_requirement_text=(
                "Admission requires a bachelor's degree. A graduate certificate pathway is available."
            )
        )
        raw = _raw_requirement(
            academic_requirement_text=(
                "Admission requires a bachelor's degree. A graduate certificate pathway is available."
            )
        )
        outcome = _eligibility_outcome(
            profile=_profile(gpa=70, accepts_pathway=True),
            candidate=candidate,
            requirement=_normalized_requirement(gpa_min=80),
            raw_requirement=raw,
        )

        self.assertEqual(outcome.decisions[0].eligibility_status, EligibilityStatus.PATHWAY_REQUIRED)
        self.assertFalse(outcome.decisions[0].can_enter_next_layer)

    def test_ielts_overall_below_requirement_is_ineligible(self) -> None:
        outcome = _eligibility_outcome(
            profile=_profile(ielts_overall=6.0),
            requirement=_normalized_requirement(ielts_overall_min=6.5),
        )

        self.assertEqual(outcome.decisions[0].eligibility_status, EligibilityStatus.INELIGIBLE)
        self.assertIn("IELTS", outcome.decisions[0].blocking_reasons[0])

    def test_ielts_component_below_requirement_is_ineligible(self) -> None:
        raw = _raw_requirement(ielts_min_band=6.0, ielts_writing=7.0)
        outcome = _eligibility_outcome(
            profile=_profile(ielts_band=6.5, ielts_writing=6.5),
            requirement=_normalized_requirement(ielts_min_band_min=7.0),
            raw_requirement=raw,
        )

        self.assertEqual(outcome.decisions[0].eligibility_status, EligibilityStatus.INELIGIBLE)
        self.assertTrue(any("writing" in reason for reason in outcome.decisions[0].blocking_reasons))

    def test_missing_user_ielts_is_unknown(self) -> None:
        outcome = _eligibility_outcome(profile=_profile(ielts_overall=None, ielts_band=None))

        self.assertEqual(outcome.decisions[0].eligibility_status, EligibilityStatus.UNKNOWN)
        self.assertIn("user_ielts", outcome.decisions[0].missing_fields)

    def test_preferred_intake_mismatch_is_ineligible(self) -> None:
        outcome = _eligibility_outcome(profile=_profile(preferred_intake=["JUL"]), candidate=_candidate(intakes=["FEB"]))

        self.assertEqual(outcome.decisions[0].eligibility_status, EligibilityStatus.INELIGIBLE)
        self.assertTrue(any("intake" in reason.casefold() for reason in outcome.decisions[0].blocking_reasons))

    def test_prerequisite_mismatch_is_high_risk(self) -> None:
        outcome = _eligibility_outcome(
            profile=_profile(prior_major="History", completed_courses=[]),
            candidate=_candidate(academic_requirement_text="Admission requires prerequisite mathematics."),
            raw_requirement=_raw_requirement(academic_requirement_text="Admission requires prerequisite mathematics."),
        )

        self.assertEqual(outcome.decisions[0].eligibility_status, EligibilityStatus.HIGH_RISK)
        self.assertTrue(any("prerequisite" in warning.casefold() for warning in outcome.decisions[0].warnings))


class ScoreAndBandTests(unittest.TestCase):
    def test_score_calculator_uses_configured_weights(self) -> None:
        config = RecommendationConfig(scoring=ScoringConfig(gpa_weight=0.6, ielts_weight=0.4))
        profile = _profile(gpa=80, ielts_overall=7.0)
        requirement = NormalizedRequirement(
            course_id="course-1",
            gpa_min=75,
            ielts_overall_min=6.5,
            ielts_min_band_min=6.0,
            requirement_summary="summary",
        )

        _, _, score = ScoreCalculator(config).calculate(user_profile=profile, requirement=requirement)

        expected = 0.6 * (80 / 75) + 0.4 * (7.0 / 6.5)
        self.assertAlmostEqual(score, expected)

    def test_band_classifier_boundaries(self) -> None:
        classifier = BandClassifier(RecommendationConfig(band=BandConfig(reach_upper=0.95, match_upper=1.1)))

        self.assertEqual(classifier.classify(0.949), "REACH")
        self.assertEqual(classifier.classify(0.95), "MATCH")
        self.assertEqual(classifier.classify(1.1), "MATCH")
        self.assertEqual(classifier.classify(1.101), "SAFETY")


class CandidateMergerTests(unittest.TestCase):
    def test_merges_by_course_id_and_boosts_dual_hits(self) -> None:
        keyword_hit = KeywordSearchHit(
            course_id="course-1",
            course_name="Master of Computer Science",
            cricos="123456A",
            keyword_score=0.6,
            retrieval_reason="keyword",
            evidence_snippets=[EvidenceSnippet(text="keyword evidence", source="academic")],
        )
        vector_hit = VectorSearchHit(
            course_id="course-1",
            course_name="Master of Computer Science",
            cricos="123456A",
            chunk_text="vector evidence",
            vector_score=0.7,
            retrieval_reason="vector",
            evidence_snippets=[EvidenceSnippet(text="vector evidence", source="academic")],
        )

        candidates = CandidateMerger().merge(
            keyword_hits=[keyword_hit],
            vector_hits=[vector_hit],
            course_rows={"course-1": _course_row()},
            intakes_by_course_id={"course-1": ["FEB", "JUL"]},
            final_candidate_limit=50,
            evidence_snippet_limit=3,
        )

        self.assertEqual(len(candidates), 1)
        self.assertGreater(candidates[0].combined_retrieval_score, 0.7)
        self.assertEqual(len(candidates[0].evidence_snippets), 2)
        self.assertEqual(candidates[0].course_id, "course-1")


class VectorRetrieverTests(unittest.TestCase):
    def test_reads_semantic_hits_from_chroma_vector_store(self) -> None:
        retriever = VectorRetriever(
            FakeRecommendationRepository(),
            embedding_client=DummyEmbeddingClient(),
            embedding_model="test-embedding-model",
            vector_store=FakeVectorStore(),
        )

        hits = retriever.retrieve(
            object(),
            query_spec=QueryBuilder().build("计算机"),
            top_k=5,
            request_id="req-vector",
        )

        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].course_id, "course-1")
        self.assertEqual(hits[0].vector_score, 0.82)
        self.assertIn("vector evidence", hits[0].evidence_snippets[0].text)


class PlanAssemblerTests(unittest.TestCase):
    def test_limits_each_band_and_builds_required_fields(self) -> None:
        config = RecommendationConfig(output=OutputConfig(max_programs_per_band=1))
        plan = PlanAssembler(config).assemble(
            user_profile=_profile(),
            scored_candidates=[
                _scored_candidate("reach-1", score=0.94, band="REACH"),
                _scored_candidate("match-1", score=1.0, band="MATCH"),
                _scored_candidate("match-2", score=1.02, band="MATCH"),
                _scored_candidate("safety-1", score=1.2, band="SAFETY"),
            ],
            excluded_programs=[],
            request_id="test-request",
        )

        self.assertEqual(len(plan.match_programs), 1)
        program = plan.match_programs[0]
        self.assertEqual(program.band, "MATCH")
        self.assertGreater(program.score, 0)
        self.assertTrue(program.recommendation_reason)
        self.assertTrue(program.source_url)
        self.assertTrue(program.evidence_snippets)

    def test_excludes_programs_with_reasons(self) -> None:
        plan = PlanAssembler(RecommendationConfig()).assemble(
            user_profile=_profile(ielts_band=6.0),
            scored_candidates=[_scored_candidate("strict-ielts", score=1.0, band="MATCH", ielts_min_band=7.0)],
            excluded_programs=[],
            request_id="test-request",
        )

        self.assertEqual(plan.excluded_programs[0].reason, "ielts_band_below_requirement")


class RecommendationServiceTests(unittest.TestCase):
    def test_end_to_end_response_tolerates_missing_course_fields(self) -> None:
        service = _build_service(FakeRecommendationRepository())
        request = _request()

        response = service.recommend(request, request_id="req-1")

        self.assertIsNotNone(response.reach_programs)
        self.assertIsNotNone(response.match_programs)
        self.assertIsNotNone(response.safety_programs)
        self.assertEqual(response.eligibility_summary.total_candidates, 2)
        self.assertEqual(response.eligibility_summary.eligible_count, 1)
        self.assertTrue(response.next_layer_candidates)
        self.assertTrue(response.high_risk_programs)
        self.assertEqual(response.high_risk_programs[0].eligibility_status, EligibilityStatus.UNKNOWN)
        self.assertFalse(response.excluded_programs)
        self.assertEqual(response.metadata.candidate_count, 2)
        self.assertEqual(response.metadata.scored_candidate_count, 1)
        self.assertTrue(response.metadata.degraded_retrieval)

    def test_vector_failure_degrades_to_keyword_retrieval(self) -> None:
        service = _build_service(FakeRecommendationRepository(), embedding_client=None)

        response = service.recommend(_request(), request_id="req-degraded")

        self.assertTrue(response.metadata.degraded_retrieval)
        self.assertGreaterEqual(response.metadata.candidate_count, 1)

    def test_ineligible_programs_do_not_enter_reach_match_safety(self) -> None:
        service = _build_service(FakeRecommendationRepository())
        request = _request(gpa=70)

        response = service.recommend(request, request_id="req-ineligible")

        recommended_ids = {
            program.course_id
            for band in [response.reach_programs, response.match_programs, response.safety_programs]
            for program in band
        }
        excluded_ids = {program.course_id for program in response.excluded_programs}
        self.assertFalse(recommended_ids & excluded_ids)
        self.assertIn("course-1", excluded_ids)

    def test_recommendation_runs_when_feature_profile_columns_are_missing(self) -> None:
        conn = MissingFeatureProfileStorageConnection()
        service = _build_service(
            RecommendationRepository(),
            embedding_client=None,
            connection_factory=_connection_factory_for(conn),
        )

        response = service.recommend(_request(), request_id="req-missing-feature-columns")

        self.assertEqual(response.metadata.candidate_count, 1)
        self.assertEqual(response.metadata.scored_candidate_count, 1)
        self.assertTrue(response.metadata.degraded_retrieval)
        self.assertEqual(response.eligibility_summary.eligible_count, 1)
        self.assertGreaterEqual(conn.rollback_count, 1)
        self.assertTrue(response.match_programs)
        self.assertIsNotNone(response.match_programs[0].feature_match)


class DashboardHelperTests(unittest.TestCase):
    def test_requirement_checks_render_to_dataframe(self) -> None:
        outcome = _eligibility_outcome()

        dataframe = build_requirement_checks_dataframe(outcome.decisions[0].requirement_checks)

        self.assertEqual(list(dataframe.columns), ["条件", "用户情况", "学校要求", "判断", "原因"])
        self.assertIn("GPA / WAM", set(dataframe["条件"]))

    def test_keyword_search_matches_course_feature_tags(self) -> None:
        dataframe = pd.DataFrame(
            [
                {
                    "course_name": "Master of Analytics",
                    "cricos": "000001A",
                    "academic_requirement_text": "",
                    "raw_english_requirement": "",
                    "academic_summary": "",
                    "application_flags_display": "",
                    "required_documents_display": "",
                    "language_tests_display": "",
                    "course_features": {
                        "discipline_tags": ["data science"],
                        "knowledge_tags": ["machine learning"],
                        "career_tags": ["data scientist"],
                        "background_fit_tags": ["math background"],
                    },
                },
                {
                    "course_name": "Master of Arts",
                    "cricos": "000002A",
                    "academic_requirement_text": "",
                    "raw_english_requirement": "",
                    "academic_summary": "",
                    "application_flags_display": "",
                    "required_documents_display": "",
                    "language_tests_display": "",
                    "course_features": {
                        "discipline_tags": ["arts"],
                        "knowledge_tags": ["communication"],
                    },
                },
            ]
        )

        mask = _build_keyword_mask(dataframe, "machine learning")

        self.assertEqual(mask.tolist(), [True, False])

    def test_keyword_search_still_matches_old_courses_without_feature_profiles(self) -> None:
        dataframe = pd.DataFrame(
            [
                {
                    "course_name": "Master of Computer Science",
                    "cricos": "000001A",
                    "academic_requirement_text": "",
                    "raw_english_requirement": "",
                    "academic_summary": "",
                    "application_flags_display": "",
                    "required_documents_display": "",
                    "language_tests_display": "",
                }
            ]
        )

        mask = _build_keyword_mask(dataframe, "computer")

        self.assertEqual(mask.tolist(), [True])

    def test_highlight_query_terms_escapes_text_and_marks_matches(self) -> None:
        highlighted = _highlight_query_terms("Portfolio <required> for design portfolio.", "portfolio")

        self.assertIn("<mark>Portfolio</mark>", highlighted)
        self.assertIn("&lt;required&gt;", highlighted)

    def test_semantic_result_source_bits_include_field_and_url(self) -> None:
        result = SearchResult(
            course_id="course-1",
            course_name="Master of Design",
            cricos="123456A",
            chunk_kind="application",
            content="Portfolio required.",
            source_url="https://www.sydney.edu.au/courses/test.html",
            similarity=0.88,
            metadata={"field": "application_details_json"},
        )

        source_bits = _format_semantic_result_source_bits(result)

        self.assertEqual(
            source_bits,
            ["application_details_json", "[官网来源](https://www.sydney.edu.au/courses/test.html)"],
        )

    def test_courses_query_can_fallback_when_feature_columns_are_missing(self) -> None:
        query = _build_courses_query(include_feature_columns=False)

        self.assertNotIn("c.course_features", query)
        self.assertIn("null::jsonb as course_features", query)
        self.assertIn("null::jsonb as course_feature_overrides", query)

    def test_courses_dataframe_fallback_marks_feature_storage_unavailable(self) -> None:
        calls: list[str] = []

        def fake_read_sql(sql: str, conn):
            calls.append(sql)
            if len(calls) == 1:
                raise RuntimeError("column c.course_features does not exist")
            return pd.DataFrame([{"course_features": None, "course_feature_overrides": None}])

        with patch("src.dashboard.pd.read_sql", side_effect=fake_read_sql):
            dataframe = _read_courses_dataframe(object())

        self.assertEqual(len(calls), 2)
        self.assertFalse(dataframe.attrs["feature_profile_storage_available"])

    def test_courses_dataframe_normal_path_marks_feature_storage_available(self) -> None:
        with patch(
            "src.dashboard.pd.read_sql",
            return_value=pd.DataFrame([{"course_features": {"ai_relevance": 4}}]),
        ):
            dataframe = _read_courses_dataframe(object())

        self.assertTrue(dataframe.attrs["feature_profile_storage_available"])

    def test_feature_profile_storage_warning_explains_degraded_mode(self) -> None:
        message = _feature_profile_storage_warning()

        self.assertIn("课程画像", message)
        self.assertIn("migration", message)

    def test_recommendation_error_message_identifies_missing_feature_profile_migration(self) -> None:
        message = _format_recommendation_error(
            _recommendation_error_from(RuntimeError("column c.course_features does not exist"))
        )

        self.assertIn("课程画像", message)
        self.assertIn("migration", message)
        self.assertNotEqual(message, "推荐失败：Recommendation request failed.")

    def test_recommendation_error_message_identifies_database_connection_failure(self) -> None:
        message = _format_recommendation_error(
            _recommendation_error_from(RuntimeError("connection to server at 127.0.0.1 failed"))
        )

        self.assertIn("数据库连接失败", message)

    def test_recommendation_error_message_identifies_vector_configuration_failure(self) -> None:
        message = _format_recommendation_error(
            _recommendation_error_from(RuntimeError("Vector retrieval requires an embedding client."))
        )

        self.assertIn("向量检索", message)

    def test_recommendation_error_message_keeps_unexpected_errors_safe(self) -> None:
        message = _format_recommendation_error(_recommendation_error_from(ValueError("unexpected bad input")))

        self.assertIn("推荐失败", message)
        self.assertIn("unexpected bad input", message)


class FakeRecommendationRepository:
    def __init__(self) -> None:
        self.rows = {
            "course-1": _course_row(course_id="course-1", course_name="Master of Computer Science"),
            "course-2": _course_row(course_id="course-2", course_name="Master of Computing"),
        }

    def search_courses_by_keywords(self, conn, *, keywords: list[str], limit: int) -> list[CourseSearchRow]:
        return list(self.rows.values())[:limit]

    def fetch_courses_by_ids(self, conn, *, course_ids: list[str]) -> dict[str, CourseSearchRow]:
        return {course_id: self.rows[course_id] for course_id in course_ids if course_id in self.rows}

    def fetch_intakes_by_course_ids(self, conn, *, course_ids: list[str]) -> dict[str, list[str]]:
        return {course_id: ["FEB", "JUL"] for course_id in course_ids}

    def fetch_current_requirements_by_course_ids(
        self,
        conn,
        *,
        course_ids: list[str],
    ) -> dict[str, RawAdmissionRequirement]:
        return {
            "course-1": _raw_requirement(course_id="course-1"),
        }

class DummyEmbeddingClient:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _ in texts]


class FakeVectorStore:
    def search_admission_chunks(
        self,
        *,
        query_embedding: list[float],
        embedding_model: str,
        top_k: int,
    ) -> list[SearchResult]:
        return [
            SearchResult(
                course_id="course-1",
                course_name="Master of Computer Science",
                cricos="123456A",
                chunk_kind="academic",
                content="vector evidence",
                source_url="https://www.sydney.edu.au/courses/test.html",
                similarity=0.82,
                metadata={"embedding_model": embedding_model},
            )
        ][:top_k]


class MissingFeatureProfileStorageConnection:
    def __init__(self) -> None:
        self.rollback_count = 0

    def cursor(self):
        return MissingFeatureProfileStorageCursor()

    def rollback(self) -> None:
        self.rollback_count += 1


class MissingFeatureProfileStorageCursor:
    def __init__(self) -> None:
        self.sql = ""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params: list[object]) -> None:
        self.sql = sql
        if "from courses c" in sql and "c.course_features" in sql:
            raise RuntimeError("column c.course_features does not exist")

    def fetchall(self):
        if "from courses c" in self.sql:
            return [
                (
                    "course-1",
                    "Master of Computer Science",
                    "Master of Computer Science",
                    "123456A",
                    1.5,
                    1.5,
                    56000,
                    "Computer science admission requirements include a bachelor's degree.",
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
                    None,
                )
            ]
        if "from course_intakes" in self.sql:
            return [("course-1", "FEB"), ("course-1", "JUL")]
        if "from course_admission_requirements" in self.sql:
            return [
                (
                    "course-1",
                    "Admission requires a bachelor's degree in a related discipline.",
                    "6.5 (6.0)",
                    6.5,
                    6.0,
                    None,
                    None,
                    None,
                    None,
                    {},
                    {},
                    {},
                    {},
                    "https://www.sydney.edu.au/courses/test.html",
                )
            ]
        return []


@contextmanager
def _fake_connection_factory(settings: Settings):
    yield object()


def _build_service(repository, embedding_client=None, connection_factory=_fake_connection_factory) -> RecommendationService:
    config = RecommendationConfig(
        retrieval=RetrievalConfig(keyword_top_k=30, vector_top_k=30, final_candidate_limit=50),
        rules=RulesConfig(enable_ielts_band_gate=True),
    )
    keyword_retriever = KeywordRetriever(repository)
    vector_retriever = VectorRetriever(
        repository,
        embedding_client=embedding_client,
        embedding_model="test-embedding-model",
    )
    rag_service = AdmissionsRAGService(
        repository=repository,
        query_builder=QueryBuilder(),
        keyword_retriever=keyword_retriever,
        vector_retriever=vector_retriever,
        candidate_merger=CandidateMerger(),
        config=config,
    )
    requirement_service = RequirementService(
        repository=repository,
        normalizer=RequirementNormalizer(),
    )
    scoring_service = ScoringService(
        score_calculator=ScoreCalculator(config),
        band_classifier=BandClassifier(config),
    )
    agent = PlanningAgent(
        parse_user_profile_tool=ParseUserProfileTool(UserProfileParser()),
        search_program_tool=SearchProgramTool(rag_service),
        get_admission_requirement_tool=GetAdmissionRequirementTool(requirement_service),
        run_eligibility_gate_tool=RunEligibilityGateTool(EligibilityGate()),
        calculate_match_score_tool=CalculateMatchScoreTool(scoring_service),
        generate_plan_tool=GeneratePlanTool(PlanAssembler(config)),
    )
    settings = Settings(database_url="postgresql://test", recommendation=config)
    return RecommendationService(
        settings=settings,
        planning_agent=agent,
        connection_factory=connection_factory,
    )


def _connection_factory_for(conn):
    @contextmanager
    def factory(settings: Settings):
        yield conn

    return factory


def _recommendation_error_from(cause: Exception) -> RecommendationServiceError:
    try:
        raise RecommendationServiceError("Recommendation request failed.") from cause
    except RecommendationServiceError as exc:
        return exc


def _request(gpa: float = 82) -> RecommendationRequest:
    return RecommendationRequest(
        target_major_keyword="计算机",
        gpa_user=gpa,
        gpa_scale=100,
        ielts_overall_user=7.0,
        ielts_min_band_user=6.5,
        ielts_listening_user=6.5,
        ielts_reading_user=6.5,
        ielts_speaking_user=6.5,
        ielts_writing_user=6.5,
        academic_background="双非",
        prior_major="Computer Science",
        completed_courses=["Programming", "Statistics"],
        preferred_intake=["FEB", "JUL"],
        budget_range=RangePreference(min=0, max=70000),
        duration_preference=RangePreference(min=1, max=2),
    )


def _profile(
    gpa: float | None = 82,
    ielts_overall: float | None = 7.0,
    ielts_band: float | None = 6.5,
    *,
    ielts_writing: float | None = 6.5,
    preferred_intake: list[str] | None = None,
    prior_major: str | None = "Computer Science",
    completed_courses: list[str] | None = None,
    accepts_pathway: bool = False,
) -> UserProfile:
    return UserProfile(
        target_major_keyword="计算机",
        gpa_user=gpa,
        gpa_scale=100,
        ielts_overall_user=ielts_overall,
        ielts_min_band_user=ielts_band,
        ielts_listening_user=ielts_band,
        ielts_reading_user=ielts_band,
        ielts_speaking_user=ielts_band,
        ielts_writing_user=ielts_writing,
        academic_background="双非",
        prior_major=prior_major,
        completed_courses=completed_courses if completed_courses is not None else ["Programming", "Statistics"],
        preferred_intake=preferred_intake if preferred_intake is not None else ["FEB"],
        budget_range=RangePreference(min=0, max=70000),
        duration_preference=RangePreference(min=1, max=2),
        accepts_pathway=accepts_pathway,
    )


def _raw_requirement(
    course_id: str = "course-1",
    academic_requirement_text: str = "Admission requires a bachelor's degree in a related discipline.",
    ielts_overall: float | None = 6.5,
    ielts_min_band: float | None = 6.0,
    ielts_writing: float | None = None,
    raw_english_requirement: str = "6.5 (6.0)",
) -> RawAdmissionRequirement:
    return RawAdmissionRequirement(
        course_id=course_id,
        academic_requirement_text=academic_requirement_text,
        raw_english_requirement=raw_english_requirement,
        ielts_overall=ielts_overall,
        ielts_min_band=ielts_min_band,
        ielts_listening=None,
        ielts_reading=None,
        ielts_speaking=None,
        ielts_writing=ielts_writing,
        source_url="https://www.sydney.edu.au/courses/test.html",
    )


def _normalized_requirement(
    course_id: str = "course-1",
    *,
    gpa_min: float = 80,
    ielts_overall_min: float = 6.5,
    ielts_min_band_min: float = 6.0,
) -> NormalizedRequirement:
    return NormalizedRequirement(
        course_id=course_id,
        gpa_min=gpa_min,
        ielts_overall_min=ielts_overall_min,
        ielts_min_band_min=ielts_min_band_min,
        requirement_summary="Admission requires a bachelor's degree. IELTS 6.5 overall.",
        requirement_source_url="https://www.sydney.edu.au/courses/test.html",
    )


def _candidate(
    course_id: str = "course-1",
    *,
    course_name: str = "Master of Computer Science",
    academic_requirement_text: str = "Admission requires a bachelor's degree in a related discipline.",
    intakes: list[str] | None = None,
    tuition_fee_aud: float | None = 56000,
    duration_min_years: float | None = 1.5,
    duration_max_years: float | None = 1.5,
) -> CourseCandidate:
    return CourseCandidate(
        course_id=course_id,
        course_name=course_name,
        cricos="123456A",
        duration_min_years=duration_min_years,
        duration_max_years=duration_max_years,
        tuition_fee_aud=tuition_fee_aud,
        intakes=intakes if intakes is not None else ["FEB"],
        academic_requirement_text=academic_requirement_text,
        raw_english_requirement="6.5 (6.0)",
        ielts_overall_required=6.5,
        ielts_min_band_required=6.0,
        retrieval_score=0.6,
        retrieval_reason="Keyword matched computer science.",
        keyword_score=0.6,
        combined_retrieval_score=0.6,
        degree_type="Master",
        evidence_snippets=[
            EvidenceSnippet(
                text=academic_requirement_text,
                source_url="https://www.sydney.edu.au/courses/test.html",
                source="academic",
            )
        ],
        source_url="https://www.sydney.edu.au/courses/test.html",
    )


def _eligibility_outcome(
    *,
    profile: UserProfile | None = None,
    candidate: CourseCandidate | None = None,
    requirement: NormalizedRequirement | None = None,
    raw_requirement: RawAdmissionRequirement | None = None,
):
    resolved_candidate = candidate or _candidate()
    resolved_requirement = requirement or _normalized_requirement(course_id=resolved_candidate.course_id)
    resolved_raw_requirement = raw_requirement or _raw_requirement(course_id=resolved_candidate.course_id)
    return EligibilityGate().evaluate(
        user_profile=profile or _profile(),
        candidates=[resolved_candidate],
        requirement_result=RequirementResult(
            requirements={resolved_candidate.course_id: resolved_requirement},
            errors={},
            raw_requirements={resolved_candidate.course_id: resolved_raw_requirement},
        ),
        request_id="test-eligibility",
    )


def _course_row(course_id: str = "course-1", course_name: str = "Master of Computer Science") -> CourseSearchRow:
    return CourseSearchRow(
        course_id=course_id,
        course_name=course_name,
        course_name_raw=course_name,
        cricos="123456A",
        duration_min_years=1.5,
        duration_max_years=1.5,
        tuition_fee_aud=56000,
        academic_requirement_text="Computer science admission requirements include a bachelor's degree.",
        raw_english_requirement="6.5 (6.0)",
        ielts_overall_required=6.5,
        ielts_min_band_required=6.0,
        source_url="https://www.sydney.edu.au/courses/test.html",
    )


def _scored_candidate(
    course_id: str,
    *,
    score: float,
    band: str,
    ielts_min_band: float = 6.0,
) -> ScoredCourseCandidate:
    return ScoredCourseCandidate(
        course_id=course_id,
        course_name=f"Course {course_id}",
        cricos="123456A",
        duration_min_years=1.5,
        duration_max_years=1.5,
        tuition_fee_aud=56000,
        intakes=["FEB"],
        academic_requirement_text="Admission requires a bachelor's degree.",
        retrieval_score=0.6,
        retrieval_reason="Keyword matched course_name.",
        keyword_score=0.6,
        vector_score=0.0,
        combined_retrieval_score=0.6,
        evidence_snippets=[EvidenceSnippet(text="Admission evidence.", source_url="https://www.sydney.edu.au")],
        source_url="https://www.sydney.edu.au/courses/test.html",
        gpa_min=80,
        ielts_overall_min=6.5,
        ielts_min_band_min=ielts_min_band,
        requirement_summary="Admission requires a bachelor's degree. IELTS 6.5 overall.",
        requirement_source_url="https://www.sydney.edu.au/courses/test.html",
        gpa_score_component=1.0,
        ielts_score_component=1.0,
        final_score=score,
        match_band=band,  # type: ignore[arg-type]
        reason_tags=["gpa_meets_requirement"],
        recommendation_reason="reason",
    )


if __name__ == "__main__":
    unittest.main()
