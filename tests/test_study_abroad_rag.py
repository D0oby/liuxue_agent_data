from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from src.study_abroad_rag import RankingConfig, SourceConfig, StudyAbroadRAGConfig, StudyAbroadRAGIndex, format_search_results


class KeywordEmbedder:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            lowered = text.casefold()
            vectors.append(
                [
                    1.0 if any(term in lowered for term in ["financial capacity", "proof of funds", "money proof"]) else 0.0,
                    1.0 if "cas deadline" in lowered else 0.0,
                ]
            )
        return vectors


class StudyAbroadRAGIndexTests(unittest.TestCase):
    def test_official_markdown_source_returns_traceable_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            source_path = Path(tmp_dir) / "melbourne-data-science.md"
            source_path.write_text(
                "\n".join(
                    [
                        "# Master of Data Science",
                        "",
                        "## Entry requirements",
                        "",
                        "Applicants need a recognised bachelor degree in a quantitative discipline.",
                        "English requirement: IELTS overall 7.0 with no band below 6.5.",
                        "",
                        "## Application deadlines",
                        "",
                        "Semester 1 applications close on 31 October 2026.",
                    ]
                ),
                encoding="utf-8",
            )

            index = StudyAbroadRAGIndex.from_sources(
                [
                    SourceConfig(
                        source_id="unimelb_mds_2026",
                        source_type="official_university",
                        title="Master of Data Science - Entry requirements",
                        locator="melbourne-data-science.md",
                        content_path=source_path,
                        trust_tier="official_university",
                        language="en",
                        updated_at="2026-01-15",
                        privacy_level="public",
                    )
                ]
            )

            results = index.search("IELTS 7.0 data science entry requirements", top_k=3)

        self.assertGreaterEqual(len(results), 1)
        top = results[0]
        self.assertEqual(top.source_id, "unimelb_mds_2026")
        self.assertEqual(top.source_type, "official_university")
        self.assertIn("IELTS overall 7.0", top.content)
        self.assertIn("#entry-requirements", top.locator)
        self.assertGreater(top.rrf_score, 0)
        self.assertGreater(top.final_score, 0)
        self.assertTrue(top.ranking_reasons)

        payload = format_search_results("IELTS 7.0 data science entry requirements", results)

        self.assertEqual(payload["query"], "IELTS 7.0 data science entry requirements")
        self.assertEqual(payload["results"][0]["source_id"], "unimelb_mds_2026")
        self.assertIn("content", payload["results"][0])
        self.assertNotIn("chunk", payload["results"][0])

    def test_source_manifest_requires_traceable_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            source_path = Path(tmp_dir) / "missing-source-id.md"
            source_path.write_text("# Entry requirements\nIELTS overall 7.0.", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "source_id"):
                StudyAbroadRAGIndex.from_sources(
                    [
                        SourceConfig(
                            source_id="",
                            source_type="official_university",
                            title="Entry requirements",
                            locator="missing-source-id.md",
                            content_path=source_path,
                            trust_tier="official_university",
                            language="en",
                            updated_at="2026-01-15",
                            privacy_level="public",
                        )
                    ]
                )

    def test_html_source_and_dense_only_match_survive_hybrid_rrf_search(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            html_path = Path(tmp_dir) / "uk-cas.html"
            html_path.write_text(
                "<html><body><h1>CAS deadlines</h1><p>CAS deadline is 30 June 2026.</p></body></html>",
                encoding="utf-8",
            )
            markdown_path = Path(tmp_dir) / "australia-visa.md"
            markdown_path.write_text(
                "# Student visa evidence\nApplicants should prepare financial capacity documents before lodgement.",
                encoding="utf-8",
            )

            index = StudyAbroadRAGIndex.from_sources(
                [
                    SourceConfig(
                        source_id="uk_cas_2026",
                        source_type="official_university",
                        title="UK CAS deadlines",
                        locator="uk-cas.html",
                        content_path=html_path,
                        trust_tier="official_university",
                        language="en",
                        updated_at="2026-02-01",
                        privacy_level="public",
                    ),
                    SourceConfig(
                        source_id="au_visa_financial_capacity",
                        source_type="official_government",
                        title="Australia student visa evidence",
                        locator="australia-visa.md",
                        content_path=markdown_path,
                        trust_tier="official_government",
                        language="en",
                        updated_at="2026-02-01",
                        privacy_level="public",
                    ),
                ],
                embedder=KeywordEmbedder(),
            )

            results = index.search("CAS deadline money proof", top_k=5)

        source_ids = [result.source_id for result in results]
        self.assertIn("uk_cas_2026", source_ids)
        self.assertIn("au_visa_financial_capacity", source_ids)
        cas_result = next(result for result in results if result.source_id == "uk_cas_2026")
        dense_result = next(result for result in results if result.source_id == "au_visa_financial_capacity")
        self.assertIn("uk-cas.html#cas-deadlines", cas_result.locator)
        self.assertTrue(any("sparse_rrf" in reason for reason in cas_result.ranking_reasons))
        self.assertTrue(any("dense_rrf" in reason for reason in dense_result.ranking_reasons))

    def test_sparse_search_supports_chinese_study_abroad_terms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            source_path = Path(tmp_dir) / "visa-policy.md"
            source_path.write_text(
                "# 学生签证\n申请学生签证需要准备资金证明和录取通知书。",
                encoding="utf-8",
            )

            index = StudyAbroadRAGIndex.from_sources(
                [
                    SourceConfig(
                        source_id="cn_visa_policy",
                        source_type="official_government",
                        title="学生签证政策",
                        locator="visa-policy.md",
                        content_path=source_path,
                        trust_tier="official_government",
                        language="zh",
                        updated_at="2026-06-01",
                        privacy_level="public",
                    )
                ]
            )

            results = index.search("学生签证 资金证明", top_k=3)

        self.assertEqual(results[0].source_id, "cn_visa_policy")
        self.assertIn("资金证明", results[0].content)

    def test_record_sources_return_privacy_safe_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            csv_path = Path(tmp_dir) / "student-experience.csv"
            csv_path.write_text(
                "record_id,title,content\n"
                "post-1,Student workload,Students describe the data science course as project heavy.\n",
                encoding="utf-8",
            )
            jsonl_path = Path(tmp_dir) / "anonymous-cases.jsonl"
            jsonl_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "record_id": "summary-1",
                                "title": "Similar applicant summary",
                                "content": "Anonymous summary: 82 WAM applicant received an offer.",
                                "privacy_level": "anonymous_summary",
                            }
                        ),
                        json.dumps(
                            {
                                "record_id": "raw-1",
                                "title": "Raw internal record",
                                "content": "Raw applicant Jane Citizen jane@example.com received an offer.",
                                "privacy_level": "raw_anonymous_internal_record",
                            }
                        ),
                    ]
                ),
                encoding="utf-8",
            )

            index = StudyAbroadRAGIndex.from_sources(
                [
                    SourceConfig(
                        source_id="student_posts",
                        source_type="public_forum_post",
                        title="Student experience posts",
                        locator="student-experience.csv",
                        content_path=csv_path,
                        trust_tier="public_forum_post",
                        language="en",
                        updated_at="2026-03-01",
                        privacy_level="public",
                    ),
                    SourceConfig(
                        source_id="internal_cases",
                        source_type="anonymous_internal_source",
                        title="Anonymous internal case summaries",
                        locator="anonymous-cases.jsonl",
                        content_path=jsonl_path,
                        trust_tier="anonymous_internal_summary",
                        language="en",
                        updated_at="2026-03-01",
                        privacy_level="anonymous_summary",
                    ),
                ]
            )

            results = index.search("applicant offer project heavy Jane", top_k=10)
            payload = format_search_results("applicant offer project heavy Jane", results)

        joined_content = "\n".join(str(row.get("content", "")) for row in payload["results"])
        self.assertIn("project heavy", joined_content)
        self.assertIn("Anonymous summary", joined_content)
        self.assertNotIn("Jane Citizen", joined_content)
        self.assertNotIn("jane@example.com", joined_content)
        raw_result = next(result for result in results if "raw-1" in result.locator)
        self.assertTrue(any("privacy_blocked_reason" in reason for reason in raw_result.ranking_reasons))
        summary_result = next(result for result in results if "summary-1" in result.locator)
        self.assertTrue(any("privacy_summary_only_penalty" in reason for reason in summary_result.ranking_reasons))

    def test_query_intent_changes_ranking_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            official_path = Path(tmp_dir) / "official-requirements.md"
            official_path.write_text(
                "# English requirements\nIELTS overall 7.0 is required for admission.",
                encoding="utf-8",
            )
            forum_path = Path(tmp_dir) / "experience.csv"
            forum_path.write_text(
                "record_id,title,content\n"
                "forum-1,Student experience,IELTS felt less important than group workload in this course experience.\n",
                encoding="utf-8",
            )
            sources = [
                SourceConfig(
                    source_id="official_requirements",
                    source_type="official_university",
                    title="Official English requirements",
                    locator="official-requirements.md",
                    content_path=official_path,
                    trust_tier="official_university",
                    language="en",
                    updated_at="2026-04-01",
                    privacy_level="public",
                ),
                SourceConfig(
                    source_id="forum_experience",
                    source_type="student_experience_post",
                    title="Student experience",
                    locator="experience.csv",
                    content_path=forum_path,
                    trust_tier="public_forum_post",
                    language="en",
                    updated_at="2026-04-01",
                    privacy_level="public",
                ),
            ]

            index = StudyAbroadRAGIndex.from_sources(sources)

            requirement_results = index.search("IELTS admission requirement", top_k=2, query_intent="requirement")
            experience_results = index.search("IELTS course experience workload", top_k=2, query_intent="student_experience")

        self.assertEqual(requirement_results[0].source_id, "official_requirements")
        self.assertTrue(any("requirement_intent_official_boost" in reason for reason in requirement_results[0].ranking_reasons))
        self.assertEqual(experience_results[0].source_id, "forum_experience")
        self.assertTrue(any("student_experience_intent_boost" in reason for reason in experience_results[0].ranking_reasons))

    def test_ranking_config_controls_trust_and_staleness_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            source_path = Path(tmp_dir) / "stale-official.md"
            source_path.write_text(
                "# Entry requirements\nIELTS overall 7.0 is required.",
                encoding="utf-8",
            )

            index = StudyAbroadRAGIndex.from_sources(
                [
                    SourceConfig(
                        source_id="stale_official",
                        source_type="official_university",
                        title="Stale official requirements",
                        locator="stale-official.md",
                        content_path=source_path,
                        trust_tier="official_university",
                        language="en",
                        updated_at="2024-01-01",
                        privacy_level="public",
                    )
                ],
                config=StudyAbroadRAGConfig(
                    ranking=RankingConfig(
                        trust_tier_boosts={"official_university": 0.42},
                        staleness_penalty=0.17,
                        freshness_year=2026,
                    )
                ),
            )

            result = index.search("IELTS entry requirements", query_intent="requirement")[0]

        self.assertTrue(any("official_university_boost:+0.42" in reason for reason in result.ranking_reasons))
        self.assertTrue(any("stale_source_penalty:-0.17" in reason for reason in result.ranking_reasons))

    def test_internal_case_supports_fit_but_not_official_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            official_path = Path(tmp_dir) / "official-data-science.md"
            official_path.write_text(
                "# Admission requirements\nData Science applicants require IELTS 7.0 and a quantitative degree.",
                encoding="utf-8",
            )
            cases_path = Path(tmp_dir) / "cases.jsonl"
            cases_path.write_text(
                json.dumps(
                    {
                        "record_id": "case-1",
                        "title": "Similar background case",
                        "content": "Anonymous summary: 82 WAM economics applicant got a data science offer.",
                        "privacy_level": "anonymous_summary",
                        "tags": "similar_background_case data_science economics",
                    }
                ),
                encoding="utf-8",
            )

            index = StudyAbroadRAGIndex.from_sources(
                [
                    SourceConfig(
                        source_id="official_data_science",
                        source_type="official_university",
                        title="Official Data Science requirements",
                        locator="official-data-science.md",
                        content_path=official_path,
                        trust_tier="official_university",
                        language="en",
                        updated_at="2026-04-01",
                        privacy_level="public",
                    ),
                    SourceConfig(
                        source_id="anonymous_cases",
                        source_type="anonymous_internal_source",
                        title="Anonymous internal cases",
                        locator="cases.jsonl",
                        content_path=cases_path,
                        trust_tier="anonymous_internal_summary",
                        language="en",
                        updated_at="2026-04-01",
                        privacy_level="anonymous_summary",
                    ),
                ]
            )

            fit_results = index.search("82 WAM economics data science offer", top_k=2, query_intent="applicant_fit")
            requirement_results = index.search("data science IELTS requirement", top_k=2, query_intent="requirement")

        self.assertEqual(fit_results[0].source_id, "anonymous_cases")
        self.assertTrue(any("similar_background_case_boost" in reason for reason in fit_results[0].ranking_reasons))
        self.assertEqual(requirement_results[0].source_id, "official_data_science")
        self.assertTrue(any("requirement_intent_official_boost" in reason for reason in requirement_results[0].ranking_reasons))
        self.assertTrue(any("not_official_requirement_source" in reason for reason in requirement_results[1].ranking_reasons))

    def test_filters_mismatch_penalties_and_same_source_saturation_shape_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            handbook_path = Path(tmp_dir) / "ucl-handbook.md"
            handbook_path.write_text(
                "\n".join(
                    [
                        "# MSc Data Science",
                        "Data science admission details for UCL.",
                        "## Careers",
                        "Data science career outcomes include AI and analytics roles.",
                        "## Curriculum",
                        "Data science curriculum includes machine learning.",
                    ]
                ),
                encoding="utf-8",
            )
            scholarship_path = Path(tmp_dir) / "ucl-scholarship.md"
            scholarship_path.write_text(
                "# Data Science scholarship\nUCL data science applicants can review scholarship options.",
                encoding="utf-8",
            )
            monash_path = Path(tmp_dir) / "monash-handbook.md"
            monash_path.write_text(
                "# Master of Data Science\nData science admission details for Monash in Australia.",
                encoding="utf-8",
            )

            index = StudyAbroadRAGIndex.from_sources(
                [
                    SourceConfig(
                        source_id="ucl_handbook",
                        source_type="course_handbook",
                        title="UCL MSc Data Science handbook",
                        locator="ucl-handbook.md",
                        content_path=handbook_path,
                        trust_tier="official_university",
                        language="en",
                        updated_at="2026-05-01",
                        privacy_level="public",
                        country="UK",
                        institution="UCL",
                        program="MSc Data Science",
                    ),
                    SourceConfig(
                        source_id="ucl_scholarship",
                        source_type="official_university",
                        title="UCL Data Science scholarship",
                        locator="ucl-scholarship.md",
                        content_path=scholarship_path,
                        trust_tier="official_university",
                        language="en",
                        updated_at="2026-05-01",
                        privacy_level="public",
                        country="UK",
                        institution="UCL",
                        program="MSc Data Science",
                    ),
                    SourceConfig(
                        source_id="monash_handbook",
                        source_type="course_handbook",
                        title="Monash Master of Data Science handbook",
                        locator="monash-handbook.md",
                        content_path=monash_path,
                        trust_tier="official_university",
                        language="en",
                        updated_at="2026-05-01",
                        privacy_level="public",
                        country="Australia",
                        institution="Monash",
                        program="Master of Data Science",
                    ),
                ]
            )

            results = index.search(
                "data science admission curriculum scholarship",
                top_k=5,
                filters={"country": "UK", "institution": "UCL", "program": "MSc Data Science"},
                query_intent="program_recommendation",
            )

        self.assertNotEqual(results[0].source_id, "monash_handbook")
        self.assertGreater(len({result.source_id for result in results[:2]}), 1)
        self.assertTrue(any("filter_match_boost" in reason for reason in results[0].ranking_reasons))
        mismatch = next(result for result in results if result.source_id == "monash_handbook")
        self.assertTrue(any("mismatch_penalty" in reason for reason in mismatch.ranking_reasons))
        repeated_ucl = [result for result in results if result.source_id == "ucl_handbook"]
        self.assertTrue(any("same_source_saturation_penalty" in reason for result in repeated_ucl for reason in result.ranking_reasons))

    def test_saturation_penalizes_repeated_source_type_and_domain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            ucl_one_path = Path(tmp_dir) / "ucl-one.md"
            ucl_two_path = Path(tmp_dir) / "ucl-two.md"
            ucl_three_path = Path(tmp_dir) / "ucl-three.md"
            gov_path = Path(tmp_dir) / "gov.md"
            for path in [ucl_one_path, ucl_two_path, ucl_three_path, gov_path]:
                path.write_text("# Data science admission\nData science admission visa evidence.", encoding="utf-8")

            index = StudyAbroadRAGIndex.from_sources(
                [
                    SourceConfig(
                        source_id="ucl_one",
                        source_type="official_university",
                        title="UCL data science one",
                        locator="https://www.ucl.ac.uk/data-science/one",
                        content_path=ucl_one_path,
                        trust_tier="official_university",
                        language="en",
                        updated_at="2026-05-01",
                        privacy_level="public",
                    ),
                    SourceConfig(
                        source_id="ucl_two",
                        source_type="official_university",
                        title="UCL data science two",
                        locator="https://www.ucl.ac.uk/data-science/two",
                        content_path=ucl_two_path,
                        trust_tier="official_university",
                        language="en",
                        updated_at="2026-05-01",
                        privacy_level="public",
                    ),
                    SourceConfig(
                        source_id="ucl_three",
                        source_type="official_university",
                        title="UCL data science three",
                        locator="https://www.ucl.ac.uk/data-science/three",
                        content_path=ucl_three_path,
                        trust_tier="official_university",
                        language="en",
                        updated_at="2026-05-01",
                        privacy_level="public",
                    ),
                    SourceConfig(
                        source_id="gov_visa",
                        source_type="official_government",
                        title="Government visa evidence",
                        locator="https://www.gov.uk/student-visa",
                        content_path=gov_path,
                        trust_tier="official_government",
                        language="en",
                        updated_at="2026-05-01",
                        privacy_level="public",
                    ),
                ],
                config=StudyAbroadRAGConfig(
                    ranking=RankingConfig(
                        same_source_saturation={"source_id": 1, "source_type": 1, "domain": 1},
                        same_source_saturation_penalty=2.0,
                    )
                ),
            )

            results = index.search("data science admission visa", top_k=4)

        self.assertIn("gov_visa", {result.source_id for result in results[:2]})
        self.assertLess(sum(1 for result in results[:3] if result.source_type == "official_university"), 3)
        self.assertTrue(
            any(
                "same_source_saturation_penalty:source_type=official_university" in reason
                for result in results
                for reason in result.ranking_reasons
            )
        )
        self.assertTrue(
            any(
                "same_source_saturation_penalty:domain=www.ucl.ac.uk" in reason
                for result in results
                for reason in result.ranking_reasons
            )
        )

    def test_cache_metadata_detects_version_manifest_model_and_content_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            source_path = Path(tmp_dir) / "official-requirements.md"
            source_path.write_text("# Entry requirements\nIELTS overall 7.0.", encoding="utf-8")
            sources = [
                SourceConfig(
                    source_id="official_requirements",
                    source_type="official_university",
                    title="Official requirements",
                    locator="official-requirements.md",
                    content_path=source_path,
                    trust_tier="official_university",
                    language="en",
                    updated_at="2026-06-01",
                    privacy_level="public",
                )
            ]

            index = StudyAbroadRAGIndex.from_sources(
                sources,
                schema_version="study-rag-v1",
                chunker_version="markdown-v1",
                tokenizer_version="simple-v1",
                model_name="deterministic-test-model",
            )
            metadata = index.cache_metadata

            self.assertTrue(
                metadata.is_valid_for(
                    sources,
                    schema_version="study-rag-v1",
                    chunker_version="markdown-v1",
                    tokenizer_version="simple-v1",
                    model_name="deterministic-test-model",
                )
            )
            self.assertFalse(
                metadata.is_valid_for(
                    sources,
                    schema_version="study-rag-v2",
                    chunker_version="markdown-v1",
                    tokenizer_version="simple-v1",
                    model_name="deterministic-test-model",
                )
            )
            self.assertFalse(
                metadata.is_valid_for(
                    sources,
                    schema_version="study-rag-v1",
                    chunker_version="markdown-v2",
                    tokenizer_version="simple-v1",
                    model_name="deterministic-test-model",
                )
            )
            self.assertFalse(
                metadata.is_valid_for(
                    sources,
                    schema_version="study-rag-v1",
                    chunker_version="markdown-v1",
                    tokenizer_version="simple-v2",
                    model_name="deterministic-test-model",
                )
            )
            self.assertFalse(
                metadata.is_valid_for(
                    sources,
                    schema_version="study-rag-v1",
                    chunker_version="markdown-v1",
                    tokenizer_version="simple-v1",
                    model_name="other-model",
                )
            )

            source_path.write_text("# Entry requirements\nIELTS overall 7.5.", encoding="utf-8")
            self.assertFalse(
                metadata.is_valid_for(
                    sources,
                    schema_version="study-rag-v1",
                    chunker_version="markdown-v1",
                    tokenizer_version="simple-v1",
                    model_name="deterministic-test-model",
                )
            )
            self.assertIn("official_requirements", metadata.source_content_hashes)

    def test_find_related_uses_public_results_and_preserves_privacy_formatting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            official_path = Path(tmp_dir) / "official-english.md"
            official_path.write_text(
                "# English requirements\nIELTS overall 7.0 with no band below 6.5.",
                encoding="utf-8",
            )
            raw_path = Path(tmp_dir) / "raw-cases.jsonl"
            raw_path.write_text(
                json.dumps(
                    {
                        "record_id": "raw-ielts",
                        "title": "Raw IELTS case",
                        "content": "IELTS case for Jane Citizen jane@example.com showed a 7.0 result.",
                        "privacy_level": "raw_anonymous_internal_record",
                    }
                ),
                encoding="utf-8",
            )

            index = StudyAbroadRAGIndex.from_sources(
                [
                    SourceConfig(
                        source_id="official_english",
                        source_type="official_university",
                        title="Official English requirements",
                        locator="official-english.md",
                        content_path=official_path,
                        trust_tier="official_university",
                        language="en",
                        updated_at="2026-06-01",
                        privacy_level="public",
                    ),
                    SourceConfig(
                        source_id="raw_cases",
                        source_type="anonymous_internal_source",
                        title="Raw internal cases",
                        locator="raw-cases.jsonl",
                        content_path=raw_path,
                        trust_tier="anonymous_internal_summary",
                        language="en",
                        updated_at="2026-06-01",
                        privacy_level="raw_anonymous_internal_record",
                    ),
                ]
            )

            seed = index.search("official IELTS requirement", top_k=1)[0]
            related = index.find_related(seed, top_k=5)
            payload = format_search_results("related to official IELTS requirement", related)

        self.assertTrue(related)
        self.assertIn("results", payload)
        self.assertNotIn("chunk", payload["results"][0])
        raw_related = next(result for result in related if result.source_id == "raw_cases")
        self.assertEqual(raw_related.content, "Evidence suppressed by privacy policy.")
        self.assertTrue(any("privacy_blocked_reason" in reason for reason in raw_related.ranking_reasons))

    def test_from_path_fixture_corpus_stays_retrieval_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            content_path = root / "official-policy.md"
            content_path.write_text(
                "# Visa policy\nOfficial visa policy requires proof of funds for student applicants.",
                encoding="utf-8",
            )
            (root / "source_manifest.json").write_text(
                json.dumps(
                    [
                        {
                            "source_id": "official_policy",
                            "source_type": "official_government",
                            "title": "Official visa policy",
                            "locator": "official-policy.md",
                            "content_path": "official-policy.md",
                            "trust_tier": "official_government",
                            "language": "en",
                            "updated_at": "2026-07-01",
                            "privacy_level": "public",
                            "country": "Australia",
                            "tags": ["visa", "proof_of_funds"],
                        }
                    ]
                ),
                encoding="utf-8",
            )

            index = StudyAbroadRAGIndex.from_path(root)
            payload = format_search_results("student visa proof of funds", index.search("student visa proof of funds"))

        self.assertEqual(payload["results"][0]["source_id"], "official_policy")
        self.assertNotIn("answer", payload)
        self.assertNotIn("recommendation_plan", payload)
        self.assertFalse(hasattr(index, "create_mcp_server"))
        self.assertFalse(hasattr(index, "recommend"))


if __name__ == "__main__":
    unittest.main()
