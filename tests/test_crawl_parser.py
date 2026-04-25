from __future__ import annotations

import unittest

try:
    from src.crawl.models import AdmissionsPayload, ApplicationDetails, AcademicPathway, LanguageTestScore
except ModuleNotFoundError:  # pragma: no cover - optional dependency for crawler feature
    AdmissionsPayload = None
    ApplicationDetails = None
    AcademicPathway = None
    LanguageTestScore = None

from src.crawl.parser import (
    build_source_fingerprint,
    canonicalize_url,
    parse_academic_pathways,
    parse_application_details,
    parse_language_tests,
)


@unittest.skipIf(AdmissionsPayload is None, "Crawler dependencies are not installed in this environment.")
class CrawlParserTests(unittest.TestCase):
    def test_parse_academic_pathways_extracts_multiple_routes(self) -> None:
        text = (
            "Admission requirements: You must have a bachelor's degree in business with a credit average "
            "or a bachelor's degree in another discipline with a credit average and 1 year relevant work experience."
        )
        pathways = parse_academic_pathways(text)
        self.assertGreaterEqual(len(pathways), 2)

    def test_parse_language_tests_extracts_ielts(self) -> None:
        text = "IELTS Academic overall 6.5 with no band below 6.0. PTE Academic 61."
        tests = parse_language_tests(text, "https://www.sydney.edu.au/x", "explicit_course_page", 1)
        ielts = next(test for test in tests if test["test_name"] == "IELTS Academic")
        self.assertEqual("6.5", ielts["overall"])
        self.assertEqual("6.0", ielts["component_scores"]["reading"])

    def test_parse_application_details_flags_documents(self) -> None:
        details = parse_application_details(
            "Applications are made directly to the University. Limited places apply. "
            "Please submit a portfolio, CV and supplementary form."
        )
        self.assertTrue(details["limited_places"])
        self.assertTrue(details["requires_portfolio"])
        self.assertIn("CV", details["required_documents"])
        self.assertTrue(details["selection_notes"][0].startswith("Limited places"))

    def test_parse_academic_pathways_handles_research_style_requirements(self) -> None:
        text = (
            "Admission to this course requires an Australian honours degree or a master's degree with outstanding "
            "results of at least 80%, and prior completion of a 20,000 word thesis."
        )
        pathways = parse_academic_pathways(text)
        self.assertGreaterEqual(len(pathways), 1)
        self.assertTrue(any(pathway["qualification"] == "honours degree" for pathway in pathways))
        self.assertTrue(any(pathway["grade_requirement"] == "outstanding results" for pathway in pathways))

    def test_parse_application_details_maps_statement_of_intent(self) -> None:
        details = parse_application_details(
            "Please provide a statement of intent with your application. This is a mandatory document for admission."
        )
        self.assertTrue(details["requires_personal_statement"])
        self.assertIn("Personal statement", details["required_documents"])

    def test_payload_validation_accepts_standard_english_reference(self) -> None:
        payload = AdmissionsPayload(
            course_id="course-1",
            course_name="Master of Architecture",
            cricos="012345A",
            source_url="https://www.sydney.edu.au/courses/courses/pc/master-of-architecture.html?cid=1",
            canonical_url=canonicalize_url("https://www.sydney.edu.au/courses/courses/pc/master-of-architecture.html?cid=1"),
            academic_requirement_text="Admission requirement You must hold a bachelor's degree in architecture.",
            academic_pathways=[
                AcademicPathway(
                    summary="You must hold a bachelor's degree in architecture.",
                    qualification="bachelor's degree",
                    discipline="architecture",
                )
            ],
            raw_english_requirement="Standard English language requirement applies to this course.",
            language_tests=[],
            application_details=ApplicationDetails(raw_text="Applications are made directly to the University."),
            source_map={},
            notes=[],
        )
        self.assertEqual("012345A", payload.cricos)

    def test_language_test_model_accepts_supported_names(self) -> None:
        test = LanguageTestScore(
            test_name="IELTS Academic",
            overall="6.5",
            component_scores={"reading": "6.0"},
            raw_text="IELTS Academic overall 6.5 with no band below 6.0",
            source_url="https://www.sydney.edu.au/english",
            source_type="explicit_course_page",
            source_priority=1,
        )
        self.assertEqual("IELTS Academic", test.test_name)

    def test_payload_fingerprint_changes_with_application_details(self) -> None:
        payload = AdmissionsPayload(
            course_id="course-1",
            course_name="Master of Architecture",
            cricos="012345A",
            source_url="https://www.sydney.edu.au/courses/courses/pc/master-of-architecture.html",
            canonical_url="https://www.sydney.edu.au/courses/courses/pc/master-of-architecture.html",
            academic_requirement_text="Admission requirements include a bachelor's degree in architecture.",
            academic_pathways=[
                AcademicPathway(
                    summary="A bachelor's degree in architecture.",
                    qualification="bachelor's degree",
                    discipline="architecture",
                )
            ],
            raw_english_requirement="Standard English language requirement applies.",
            application_details=ApplicationDetails(
                raw_text="Applicants must provide a portfolio.",
                required_documents=["Portfolio"],
                requires_portfolio=True,
            ),
        )
        left = build_source_fingerprint(payload)
        updated = payload.model_copy(
            update={
                "application_details": ApplicationDetails(
                    raw_text="Applicants must provide a portfolio and CV.",
                    required_documents=["Portfolio", "CV"],
                    requires_portfolio=True,
                    requires_cv_or_resume=True,
                )
            }
        )
        right = build_source_fingerprint(updated)
        self.assertNotEqual(left, right)


if __name__ == "__main__":
    unittest.main()
