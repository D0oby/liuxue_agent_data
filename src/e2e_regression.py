from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from contextlib import contextmanager
import html
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from typing import Protocol
import urllib.request
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from src.config import RecommendationConfig, Settings
from src.db import apply_migrations, connect
from src.models.recommendation import RangePreference, RecommendationRequest, UserProfile
from src.recommendation.agent import (
    CalculateMatchScoreTool,
    GeneratePlanTool,
    GetAdmissionRequirementTool,
    ParseUserProfileTool,
    PlanningAgent,
    RunEligibilityGateTool,
    SearchProgramTool,
)
from src.recommendation.eligibility import EligibilityGate
from src.recommendation.feature_repository import CourseFeatureRepository
from src.recommendation.plan import PlanAssembler
from src.recommendation.profile import UserProfileParser
from src.recommendation.query_builder import QueryBuilder
from src.recommendation.repository import RecommendationRepository
from src.recommendation.requirements import RequirementNormalizer, RequirementService
from src.recommendation.retrieval import AdmissionsRAGService, CandidateMerger, KeywordRetriever, VectorRetriever
from src.recommendation.course_features import generate_course_features
from src.recommendation.scoring import BandClassifier, ScoreCalculator, ScoringService
from src.recommendation.service import RecommendationService
from src.vector_store.runner import search_admissions, vectorize_admissions
from src.vector_store.storage import ChromaVectorStore


E2E_STAGE_SEQUENCE = [
    "database_guard",
    "migrations",
    "fixture_excel_import",
    "admissions_fixture_enrichment",
    "deterministic_vector_retrieval",
    "course_feature_profiles",
    "recommendation_service",
    "api_schema_smoke",
    "dashboard_playwright",
]


@dataclass(frozen=True)
class E2ERunOptions:
    database_url: str | None = None
    normal_database_url: str | None = None
    artifacts_dir: Path = Path("var/e2e_artifacts")
    keep_artifacts: bool = False
    headed: bool = False
    skip_dashboard: bool = False
    streamlit_port: int | None = None
    run_api_smoke: bool = True
    run_id: str | None = None


@dataclass(frozen=True)
class E2EStageResult:
    name: str
    status: str
    details: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class E2ERunResult:
    success: bool
    run_id: str
    run_artifacts_dir: Path
    stages: list[E2EStageResult]
    failed_stage: str | None = None


class E2EStageError(RuntimeError):
    def __init__(self, stage: str, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.stage = stage
        self.details = details or {}


@dataclass
class E2ERunContext:
    options: E2ERunOptions
    run_id: str
    run_artifacts_dir: Path
    work_dir: Path
    state: dict[str, object] = field(default_factory=dict)


class E2EExecutionEnvironment(Protocol):
    def run_stage(self, stage_name: str, context: E2ERunContext) -> dict[str, object]:
        ...


class RealE2EExecutionEnvironment:
    def run_stage(self, stage_name: str, context: E2ERunContext) -> dict[str, object]:
        stage = getattr(self, f"_stage_{stage_name}", None)
        if stage is None:
            raise E2EStageError(stage_name, f"Unknown E2E stage: {stage_name}")
        return stage(context)

    def _stage_migrations(self, context: E2ERunContext) -> dict[str, object]:
        settings = _e2e_settings(context)
        migrations_dir = _project_root() / "migrations"
        with connect(settings) as conn:
            with conn.transaction():
                apply_migrations(conn, migrations_dir)
        return {"migrations_dir": str(migrations_dir)}

    def _stage_fixture_excel_import(self, context: E2ERunContext) -> dict[str, object]:
        fixture_path = context.work_dir / "fixtures" / "e2e_usyd_courses.xlsx"
        write_representative_fixture_excel(fixture_path)
        with _temporary_database_url(context.options.database_url or ""):
            from src.cli import import_excel_to_postgres

            import_excel_to_postgres(str(fixture_path), migrate_first=False)

        settings = _e2e_settings(context)
        with connect(settings) as conn:
            course_ids = _fetch_fixture_course_ids(conn)
        missing = sorted({course.cricos for course in E2E_FIXTURE_COURSES} - set(course_ids))
        if missing:
            raise E2EStageError(
                "fixture_excel_import",
                "Imported fixture courses were not visible downstream.",
                details={"missing_cricos": missing},
            )
        context.state["fixture_course_ids"] = course_ids
        return {"fixture_path": str(fixture_path), "course_count": len(course_ids)}

    def _stage_admissions_fixture_enrichment(self, context: E2ERunContext) -> dict[str, object]:
        from src.crawl.models import AcademicPathway, AdmissionsPayload, ApplicationDetails, LanguageTestScore
        from src.crawl.storage import upsert_crawled_admission_requirement

        course_ids = _course_ids_from_context(context)
        settings = _e2e_settings(context)
        with connect(settings) as conn:
            with conn.transaction():
                for course in E2E_FIXTURE_COURSES:
                    payload = AdmissionsPayload(
                        course_id=course_ids[course.cricos],
                        course_name=course.course_name,
                        cricos=course.cricos,
                        source_url=course.source_url,
                        canonical_url=course.source_url,
                        academic_requirement_text=course.academic_requirement_text,
                        academic_pathways=[
                            AcademicPathway(
                                summary=course.pathway_summary,
                                qualification="bachelor's degree",
                                discipline=course.pathway_discipline,
                                grade_requirement=course.pathway_grade,
                            )
                        ],
                        raw_english_requirement=course.raw_english_requirement,
                        language_tests=[
                            LanguageTestScore(
                                test_name="IELTS Academic",
                                overall=str(course.ielts_overall),
                                component_scores={
                                    "listening": str(course.ielts_min_band),
                                    "reading": str(course.ielts_min_band),
                                    "speaking": str(course.ielts_min_band),
                                    "writing": str(course.ielts_min_band),
                                },
                                raw_text=course.raw_english_requirement,
                                source_url=course.source_url,
                                source_type="explicit_course_page",
                                source_priority=1,
                            )
                        ],
                        application_details=ApplicationDetails(**course.application_details),
                        supplementary_metadata=course.supplementary_metadata,
                        source_map={
                            "academic_requirement_text": course.source_url,
                            "raw_english_requirement": course.source_url,
                            "application_details_json": course.source_url,
                        },
                        notes=["Hermetic E2E fixture; no live USYD request was made."],
                    )
                    upsert_crawled_admission_requirement(conn, payload)

        with connect(settings) as conn:
            enriched = _fetch_current_fixture_requirements(conn, list(course_ids.values()))
        if len(enriched) != len(E2E_FIXTURE_COURSES):
            raise E2EStageError(
                "admissions_fixture_enrichment",
                "Fixture admissions enrichment did not cover every fixture course.",
                details={"enriched_count": len(enriched), "fixture_count": len(E2E_FIXTURE_COURSES)},
            )
        if not any(row["application_details_json"].get("requires_portfolio") for row in enriched):
            raise E2EStageError(
                "admissions_fixture_enrichment",
                "Application-material fixture did not preserve portfolio details.",
            )
        return {"enriched_count": len(enriched), "source": "local_fixture"}

    def _stage_deterministic_vector_retrieval(self, context: E2ERunContext) -> dict[str, object]:
        settings = _e2e_settings(context)
        vector_store = ChromaVectorStore(
            persist_directory=_vector_dir(context),
            collection_name=_vector_collection_name(context),
        )
        embedding_client = DeterministicEmbeddingClient()
        with connect(settings) as conn:
            stats = vectorize_admissions(
                conn,
                vector_store=vector_store,
                embedding_client=embedding_client,
                embedding_model=E2E_EMBEDDING_MODEL,
                source="usyd_web_crawl",
                batch_size=8,
                force=True,
                dry_run=False,
            )
            fallback_result = _build_rag_service(
                settings=settings,
                vector_store=vector_store,
                embedding_client=None,
            ).search(
                conn,
                user_profile=_e2e_user_profile("data"),
                request_id=f"{context.run_id}-fallback",
            )
        results = search_admissions(
            vector_store=vector_store,
            embedding_client=embedding_client,
            embedding_model=E2E_EMBEDDING_MODEL,
            query="portfolio design application",
            top_k=3,
        )
        if not any("Design" in result.course_name for result in results):
            raise E2EStageError(
                "deterministic_vector_retrieval",
                "Semantic fixture search did not return the expected design course.",
                details={"result_courses": [result.course_name for result in results]},
            )
        if not fallback_result.degraded_retrieval or not fallback_result.candidates:
            raise E2EStageError(
                "deterministic_vector_retrieval",
                "Vector-unavailable fallback did not degrade to keyword retrieval.",
            )
        context.state["vector_store"] = vector_store
        context.state["embedding_client"] = embedding_client
        return {
            "records_vectorized": stats.records_vectorized,
            "chunks_embedded": stats.chunks_embedded,
            "search_top_course": results[0].course_name if results else "",
            "fallback_candidate_count": len(fallback_result.candidates),
        }

    def _stage_course_feature_profiles(self, context: E2ERunContext) -> dict[str, object]:
        course_ids = _course_ids_from_context(context)
        settings = _e2e_settings(context)
        repository = CourseFeatureRepository()
        legacy_null_profile_safe = False
        with connect(settings) as conn:
            with conn.transaction():
                for course in E2E_FIXTURE_COURSES:
                    record = repository.fetch_course(conn, course_id=course_ids[course.cricos])
                    if record is None:
                        continue
                    if record.course_features is None:
                        legacy_null_profile_safe = True
                    override = {}
                    if course.cricos == "222222B":
                        override = {"discipline_tags": ["business analytics"], "risk_level": 4}
                    profile = generate_course_features(record.source, manual_override=override)
                    repository.save_course_features(
                        conn,
                        course_id=record.course_id,
                        course_features=profile,
                        manual_overrides=override,
                    )

        with connect(settings) as conn:
            business = repository.fetch_course(conn, course_id=course_ids["222222B"])
        if business is None or business.course_features is None:
            raise E2EStageError("course_feature_profiles", "Business fixture feature profile was not persisted.")
        regenerated = generate_course_features(business.source, manual_override=business.manual_overrides)
        if regenerated.risk_level != 4 or regenerated.discipline_tags != ["business analytics"]:
            raise E2EStageError(
                "course_feature_profiles",
                "Manual feature overrides were overwritten during regeneration.",
            )
        return {
            "profiled_count": len(E2E_FIXTURE_COURSES),
            "manual_override_course": business.course_name,
            "legacy_null_profile_safe": legacy_null_profile_safe,
        }

    def _stage_recommendation_service(self, context: E2ERunContext) -> dict[str, object]:
        settings = _e2e_settings(context)
        vector_store = _require_state(context, "vector_store")
        embedding_client = _require_state(context, "embedding_client")
        service = RecommendationService(
            settings=settings,
            planning_agent=_build_planning_agent(
                settings=settings,
                vector_store=vector_store,
                embedding_client=embedding_client,
            ),
            connection_factory=lambda _: connect(settings),
        )
        response = service.recommend(_e2e_recommendation_request("data"), request_id=f"{context.run_id}-recommend")
        recommended_names = _recommended_course_names(response)
        if not any("Data" in name or "Business Analytics" in name for name in recommended_names):
            raise E2EStageError(
                "recommendation_service",
                "Recommendation fixture did not surface expected data or analytics courses.",
                details={"recommended_courses": recommended_names},
            )
        if not _response_has_evidence(response):
            raise E2EStageError("recommendation_service", "Recommendation response did not include evidence snippets.")
        if not _response_has_feature_match(response):
            raise E2EStageError(
                "recommendation_service",
                "Recommendation response did not surface Course Feature Profile matching.",
            )

        fallback_service = RecommendationService(
            settings=settings,
            planning_agent=_build_planning_agent(
                settings=settings,
                vector_store=vector_store,
                embedding_client=None,
            ),
            connection_factory=lambda _: connect(settings),
        )
        fallback_response = fallback_service.recommend(
            _e2e_recommendation_request("engineering"),
            request_id=f"{context.run_id}-fallback-recommend",
        )
        if not fallback_response.metadata.degraded_retrieval:
            raise E2EStageError("recommendation_service", "Fallback recommendation did not report degraded retrieval.")
        if not fallback_response.excluded_programs and not fallback_response.high_risk_programs:
            raise E2EStageError(
                "recommendation_service",
                "Negative-path fixture did not produce excluded or high-risk programs.",
            )
        return {
            "recommended_courses": recommended_names,
            "degraded_retrieval_checked": True,
            "excluded_count": len(fallback_response.excluded_programs),
        }

    def _stage_api_schema_smoke(self, context: E2ERunContext) -> dict[str, object]:
        if not context.options.run_api_smoke:
            return {"skipped": True}
        try:
            from fastapi.testclient import TestClient
        except Exception as exc:  # pragma: no cover - dependency safety net
            raise E2EStageError("api_schema_smoke", "FastAPI TestClient is unavailable.") from exc

        course_ids = _course_ids_from_context(context)
        with _temporary_env(_api_smoke_env(context)):
            from src.api import app

            client = TestClient(app)
            feature_response = client.get(f"/courses/{course_ids['111111A']}/features")
            recommendation_response = client.post(
                "/recommendations/usyd",
                json=_e2e_recommendation_request("data").model_dump(mode="json"),
            )
        if feature_response.status_code != 200:
            raise E2EStageError(
                "api_schema_smoke",
                "Course Feature Profile API smoke failed.",
                details={"status_code": feature_response.status_code, "body": feature_response.text[:500]},
            )
        if recommendation_response.status_code != 200:
            raise E2EStageError(
                "api_schema_smoke",
                "Recommendation API smoke failed.",
                details={
                    "status_code": recommendation_response.status_code,
                    "body": recommendation_response.text[:500],
                },
            )
        feature_payload = feature_response.json()
        recommendation_payload = recommendation_response.json()
        if "course_features" not in feature_payload or "metadata" not in recommendation_payload:
            raise E2EStageError("api_schema_smoke", "API smoke responses did not match expected public shapes.")
        return {"feature_status": feature_response.status_code, "recommendation_status": recommendation_response.status_code}

    def _stage_dashboard_playwright(self, context: E2ERunContext) -> dict[str, object]:
        port = context.options.streamlit_port or _free_port()
        base_url = f"http://127.0.0.1:{port}"
        log_path = context.run_artifacts_dir / "streamlit.log"
        screenshot_path = context.run_artifacts_dir / "dashboard_failure.png"
        env = _dashboard_env(context)
        command = [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "src/dashboard.py",
            "--server.port",
            str(port),
            "--server.headless",
            "true",
            "--server.runOnSave",
            "false",
        ]
        with log_path.open("w", encoding="utf-8") as log_file:
            process = subprocess.Popen(
                command,
                cwd=str(_project_root()),
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
            )
            try:
                _wait_for_http(base_url)
                _run_dashboard_playwright_checks(
                    base_url=base_url,
                    headed=context.options.headed,
                    screenshot_path=screenshot_path,
                )
            except Exception as exc:
                details: dict[str, object] = {"base_url": base_url, "streamlit_log": str(log_path)}
                if screenshot_path.exists():
                    details["screenshot"] = str(screenshot_path)
                raise E2EStageError("dashboard_playwright", f"Dashboard Playwright checks failed: {exc}", details=details) from exc
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
        return {
            "base_url": base_url,
            "headless": not context.options.headed,
            "streamlit_log": str(log_path),
        }


def run_e2e_regression(
    options: E2ERunOptions,
    *,
    environment: E2EExecutionEnvironment | None = None,
) -> E2ERunResult:
    run_id = options.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    run_artifacts_dir = Path(options.artifacts_dir) / run_id
    run_artifacts_dir.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix=f"usyd-e2e-{run_id}-"))
    context = E2ERunContext(options=options, run_id=run_id, run_artifacts_dir=run_artifacts_dir, work_dir=work_dir)
    environment = environment or RealE2EExecutionEnvironment()
    stages: list[E2EStageResult] = []
    current_stage = "database_guard"

    try:
        _run_database_guard(options)
        stages.append(E2EStageResult(name="database_guard", status="passed"))
        for stage_name in E2E_STAGE_SEQUENCE[1:]:
            current_stage = stage_name
            if stage_name == "dashboard_playwright" and options.skip_dashboard:
                stages.append(E2EStageResult(name=stage_name, status="skipped"))
                continue
            details = environment.run_stage(stage_name, context)
            stages.append(E2EStageResult(name=stage_name, status="passed", details=details))
    except E2EStageError as exc:
        stages.append(E2EStageResult(name=exc.stage, status="failed", details={"error": str(exc), **exc.details}))
        result = E2ERunResult(
            success=False,
            run_id=run_id,
            run_artifacts_dir=run_artifacts_dir,
            stages=stages,
            failed_stage=exc.stage,
        )
        _write_summary(result)
        _cleanup_work_dir(context)
        return result
    except Exception as exc:
        stages.append(E2EStageResult(name=current_stage, status="failed", details={"error": str(exc)}))
        result = E2ERunResult(
            success=False,
            run_id=run_id,
            run_artifacts_dir=run_artifacts_dir,
            stages=stages,
            failed_stage=current_stage,
        )
        _write_summary(result)
        _cleanup_work_dir(context)
        return result

    result = E2ERunResult(
        success=True,
        run_id=run_id,
        run_artifacts_dir=run_artifacts_dir,
        stages=stages,
    )
    _write_summary(result)
    _cleanup_work_dir(context)
    return result


def _run_database_guard(options: E2ERunOptions) -> None:
    if not str(options.database_url or "").strip():
        raise E2EStageError(
            "database_guard",
            "E2E_DATABASE_URL is required and must point at an isolated E2E database.",
        )
    if options.normal_database_url and options.normal_database_url == options.database_url:
        raise E2EStageError(
            "database_guard",
            "E2E_DATABASE_URL must not be the same value as DATABASE_URL.",
        )


def _write_summary(result: E2ERunResult) -> None:
    payload = {
        "run_id": result.run_id,
        "success": result.success,
        "failed_stage": result.failed_stage,
        "stages": [
            {
                "name": stage.name,
                "status": stage.status,
                "details": stage.details,
            }
            for stage in result.stages
        ],
    }
    (result.run_artifacts_dir / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


@dataclass(frozen=True)
class E2EFixtureCourse:
    course_name: str
    cricos: str
    raw_english_requirement: str
    commencing_semester: str
    duration_years: str
    tuition_fee_aud: str
    source_url: str
    academic_requirement_text: str
    pathway_summary: str
    pathway_discipline: str
    pathway_grade: str
    ielts_overall: float
    ielts_min_band: float
    application_details: dict[str, object]
    supplementary_metadata: dict[str, object]


E2E_EMBEDDING_MODEL = "e2e-deterministic-local"

E2E_FIXTURE_COURSES = [
    E2EFixtureCourse(
        course_name="Master of Data Science",
        cricos="111111A",
        raw_english_requirement="IELTS Academic 6.5 overall, no band below 6.0.",
        commencing_semester="Feb/Jul",
        duration_years="1.5",
        tuition_fee_aud="56500",
        source_url="https://www.sydney.edu.au/courses/courses/pc/master-of-data-science.html",
        academic_requirement_text=(
            "Admission requires a bachelor's degree with a credit average. Prior study in "
            "mathematics, statistics, programming, machine learning, artificial intelligence "
            "or data analytics is recommended."
        ),
        pathway_summary="Admission requires a bachelor's degree in a related discipline with a credit average.",
        pathway_discipline="related discipline",
        pathway_grade="credit average",
        ielts_overall=6.5,
        ielts_min_band=6.0,
        application_details={
            "raw_text": "Applications are made online. No portfolio is required for this data science course.",
            "required_documents": [],
            "requires_portfolio": False,
            "requires_personal_statement": False,
            "requires_supplementary_form": False,
            "requires_cv_or_resume": False,
            "requires_references": False,
            "requires_work_experience": False,
            "limited_places": False,
            "quota_applies": False,
            "selection_notes": [],
        },
        supplementary_metadata={
            "faculty": "Faculty of Engineering",
            "school": "School of Computer Science",
            "campus": "Camperdown/Darlington",
            "study_mode": "On campus",
        },
    ),
    E2EFixtureCourse(
        course_name="Master of Business Analytics",
        cricos="222222B",
        raw_english_requirement="IELTS Academic 7.0 overall, no band below 6.0.",
        commencing_semester="Feb/Jul",
        duration_years="1.5",
        tuition_fee_aud="58500",
        source_url="https://www.sydney.edu.au/courses/courses/pc/master-of-business-analytics.html",
        academic_requirement_text=(
            "Admission requires a bachelor's degree. The program covers business analytics, "
            "statistics, econometrics, data visualisation, management and consulting projects."
        ),
        pathway_summary="Admission requires a bachelor's degree in business, economics or a related field.",
        pathway_discipline="business",
        pathway_grade="credit average",
        ielts_overall=7.0,
        ielts_min_band=6.0,
        application_details={
            "raw_text": "Applicants may include a personal statement describing analytics experience.",
            "required_documents": ["Personal statement"],
            "requires_portfolio": False,
            "requires_personal_statement": True,
            "requires_supplementary_form": False,
            "requires_cv_or_resume": False,
            "requires_references": False,
            "requires_work_experience": False,
            "limited_places": False,
            "quota_applies": False,
            "selection_notes": [],
        },
        supplementary_metadata={
            "faculty": "University of Sydney Business School",
            "school": "Business School",
            "campus": "Camperdown/Darlington",
            "study_mode": "On campus",
        },
    ),
    E2EFixtureCourse(
        course_name="Master of Interaction Design and Electronic Arts",
        cricos="333333C",
        raw_english_requirement="IELTS Academic 6.5 overall, no band below 6.0.",
        commencing_semester="Feb",
        duration_years="1.5",
        tuition_fee_aud="50500",
        source_url="https://www.sydney.edu.au/courses/courses/pc/master-of-interaction-design-and-electronic-arts.html",
        academic_requirement_text=(
            "Admission requires a bachelor's degree or equivalent qualification. Applicants "
            "from design, arts, communication or computing backgrounds are considered."
        ),
        pathway_summary="Admission requires a bachelor's degree in design, arts, communication or a related field.",
        pathway_discipline="design",
        pathway_grade="credit average",
        ielts_overall=6.5,
        ielts_min_band=6.0,
        application_details={
            "raw_text": "A portfolio is required. Limited places apply and selection is competitive.",
            "required_documents": ["Portfolio"],
            "requires_portfolio": True,
            "requires_personal_statement": False,
            "requires_supplementary_form": False,
            "requires_cv_or_resume": False,
            "requires_references": False,
            "requires_work_experience": False,
            "limited_places": True,
            "quota_applies": False,
            "selection_notes": ["Limited places apply and selection is competitive."],
        },
        supplementary_metadata={
            "faculty": "Faculty of Arts and Social Sciences",
            "school": "Sydney School of Architecture, Design and Planning",
            "campus": "Camperdown/Darlington",
            "study_mode": "On campus",
        },
    ),
    E2EFixtureCourse(
        course_name="Master of Professional Engineering",
        cricos="444444D",
        raw_english_requirement="IELTS Academic 6.5 overall, no band below 6.0.",
        commencing_semester="Jul",
        duration_years="3",
        tuition_fee_aud="61000",
        source_url="https://www.sydney.edu.au/courses/courses/pc/master-of-professional-engineering.html",
        academic_requirement_text=(
            "Admission requires a bachelor's degree in engineering or a related discipline. "
            "Assumed knowledge includes mathematics, physics and engineering design."
        ),
        pathway_summary="Admission requires a bachelor's degree in engineering or a related discipline.",
        pathway_discipline="engineering",
        pathway_grade="credit average",
        ielts_overall=6.5,
        ielts_min_band=6.0,
        application_details={
            "raw_text": "Applications require evidence of prior engineering study and relevant documents.",
            "required_documents": ["Prior engineering study evidence"],
            "requires_portfolio": False,
            "requires_personal_statement": False,
            "requires_supplementary_form": False,
            "requires_cv_or_resume": False,
            "requires_references": False,
            "requires_work_experience": False,
            "limited_places": False,
            "quota_applies": False,
            "selection_notes": [],
        },
        supplementary_metadata={
            "faculty": "Faculty of Engineering",
            "school": "School of Engineering",
            "campus": "Camperdown/Darlington",
            "study_mode": "On campus",
        },
    ),
]


class DeterministicEmbeddingClient:
    vocabulary = [
        "data",
        "analytics",
        "statistics",
        "machine learning",
        "artificial intelligence",
        "business",
        "portfolio",
        "design",
        "engineering",
        "mathematics",
        "programming",
        "ielts",
        "personal statement",
        "work experience",
        "education",
        "finance",
    ]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def _embed(self, text: str) -> list[float]:
        lowered = f" {text.casefold()} "
        vector = [float(lowered.count(term)) for term in self.vocabulary]
        if not any(vector):
            vector[0] = 0.01
        return vector


def write_representative_fixture_excel(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = [
        "Course Name",
        "CRICOS",
        "IELTS Academic",
        "Commencing Semester",
        "Duration (Years)",
        "Tuition Fee ($AUD)",
    ]
    rows = [
        [
            course.course_name,
            course.cricos,
            course.raw_english_requirement,
            course.commencing_semester,
            course.duration_years,
            course.tuition_fee_aud,
        ]
        for course in E2E_FIXTURE_COURSES
    ]
    _write_minimal_xlsx(path, headers=headers, rows=rows)


def _write_minimal_xlsx(path: Path, *, headers: list[str], rows: list[list[str]]) -> None:
    sheet_rows = [headers, *rows]
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _content_types_xml())
        archive.writestr("_rels/.rels", _root_rels_xml())
        archive.writestr("xl/workbook.xml", _workbook_xml())
        archive.writestr("xl/_rels/workbook.xml.rels", _workbook_rels_xml())
        archive.writestr("xl/worksheets/sheet1.xml", _worksheet_xml(sheet_rows))


def _worksheet_xml(rows: list[list[str]]) -> str:
    row_xml = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for column_index, value in enumerate(row):
            ref = f"{_column_letters(column_index)}{row_index}"
            cells.append(
                f'<c r="{ref}" t="inlineStr"><is><t>{html.escape(str(value))}</t></is></c>'
            )
        row_xml.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(row_xml)}</sheetData>'
        "</worksheet>"
    )


def _column_letters(index: int) -> str:
    letters = ""
    value = index + 1
    while value:
        value, remainder = divmod(value - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def _content_types_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        "</Types>"
    )


def _root_rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        "</Relationships>"
    )


def _workbook_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="E2E Fixture" sheetId="1" r:id="rId1"/></sheets>'
        "</workbook>"
    )


def _workbook_rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        "</Relationships>"
    )


def _e2e_settings(context: E2ERunContext) -> Settings:
    return Settings(
        database_url=context.options.database_url or "",
        openai_api_key=None,
        embedding_model=E2E_EMBEDDING_MODEL,
        embedding_dimensions=len(DeterministicEmbeddingClient.vocabulary),
        embedding_batch_size=8,
        chroma_persist_directory=str(_vector_dir(context)),
        chroma_collection_name=_vector_collection_name(context),
        recommendation=RecommendationConfig(),
    )


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _vector_dir(context: E2ERunContext) -> Path:
    return context.work_dir / "chroma"


def _vector_collection_name(context: E2ERunContext) -> str:
    return "course_admission_chunks_e2e"


def _fetch_fixture_course_ids(conn) -> dict[str, str]:
    cricos_values = [course.cricos for course in E2E_FIXTURE_COURSES]
    placeholders = ", ".join(["%s"] * len(cricos_values))
    with conn.cursor() as cur:
        cur.execute(
            f"""
            select cricos, id::text
            from courses
            where cricos in ({placeholders})
            """,
            cricos_values,
        )
        return {row[0]: row[1] for row in cur.fetchall()}


def _fetch_current_fixture_requirements(conn, course_ids: list[str]) -> list[dict[str, object]]:
    placeholders = ", ".join(["%s"] * len(course_ids))
    with conn.cursor() as cur:
        cur.execute(
            f"""
            select
                course_id::text,
                requirement_source,
                academic_requirement_text,
                raw_english_requirement,
                application_details_json,
                source_map_json,
                source_url
            from course_admission_requirements
            where is_current = true
              and course_id in ({placeholders})
            """,
            course_ids,
        )
        return [
            {
                "course_id": row[0],
                "requirement_source": row[1],
                "academic_requirement_text": row[2],
                "raw_english_requirement": row[3],
                "application_details_json": row[4] if isinstance(row[4], dict) else {},
                "source_map_json": row[5] if isinstance(row[5], dict) else {},
                "source_url": row[6],
            }
            for row in cur.fetchall()
        ]


def _course_ids_from_context(context: E2ERunContext) -> dict[str, str]:
    course_ids = context.state.get("fixture_course_ids")
    if not isinstance(course_ids, dict):
        raise E2EStageError("fixture_excel_import", "Fixture course IDs are unavailable from the import stage.")
    return {str(key): str(value) for key, value in course_ids.items()}


def _build_rag_service(
    *,
    settings: Settings,
    vector_store: ChromaVectorStore,
    embedding_client: DeterministicEmbeddingClient | None,
) -> AdmissionsRAGService:
    repository = RecommendationRepository()
    return AdmissionsRAGService(
        repository=repository,
        query_builder=QueryBuilder(),
        keyword_retriever=KeywordRetriever(repository),
        vector_retriever=VectorRetriever(
            repository,
            embedding_client=embedding_client,
            embedding_model=settings.embedding_model,
            vector_store=vector_store,
        ),
        candidate_merger=CandidateMerger(),
        config=settings.recommendation,
    )


def _build_planning_agent(
    *,
    settings: Settings,
    vector_store: ChromaVectorStore,
    embedding_client: DeterministicEmbeddingClient | None,
) -> PlanningAgent:
    repository = RecommendationRepository()
    return PlanningAgent(
        parse_user_profile_tool=ParseUserProfileTool(UserProfileParser()),
        search_program_tool=SearchProgramTool(
            AdmissionsRAGService(
                repository=repository,
                query_builder=QueryBuilder(),
                keyword_retriever=KeywordRetriever(repository),
                vector_retriever=VectorRetriever(
                    repository,
                    embedding_client=embedding_client,
                    embedding_model=settings.embedding_model,
                    vector_store=vector_store,
                ),
                candidate_merger=CandidateMerger(),
                config=settings.recommendation,
            )
        ),
        get_admission_requirement_tool=GetAdmissionRequirementTool(
            RequirementService(repository=repository, normalizer=RequirementNormalizer())
        ),
        run_eligibility_gate_tool=RunEligibilityGateTool(EligibilityGate()),
        calculate_match_score_tool=CalculateMatchScoreTool(
            ScoringService(
                score_calculator=ScoreCalculator(settings.recommendation),
                band_classifier=BandClassifier(settings.recommendation),
            )
        ),
        generate_plan_tool=GeneratePlanTool(PlanAssembler(settings.recommendation)),
    )


def _e2e_user_profile(target_major_keyword: str) -> UserProfile:
    return UserProfile(
        target_major_keyword=target_major_keyword,
        gpa_user=82,
        gpa_scale=100,
        ielts_overall_user=7.0,
        ielts_min_band_user=6.5,
        ielts_listening_user=6.5,
        ielts_reading_user=6.5,
        ielts_speaking_user=6.5,
        ielts_writing_user=6.5,
        academic_background="211",
        prior_major="Computer Science",
        completed_courses=["Programming", "Statistics", "Database Systems"],
        preferred_intake=["FEB", "JUL"],
        budget_range=RangePreference(max=70000),
        duration_preference=RangePreference(max=2),
        campus_preference=[],
        study_mode_preference=[],
        accepts_pathway=False,
    )


def _e2e_recommendation_request(target_major_keyword: str) -> RecommendationRequest:
    return RecommendationRequest(
        target_major_keyword=target_major_keyword,
        gpa_user=82,
        gpa_scale=100,
        ielts_overall_user=7.0,
        ielts_min_band_user=6.5,
        ielts_listening_user=6.5,
        ielts_reading_user=6.5,
        ielts_speaking_user=6.5,
        ielts_writing_user=6.5,
        academic_background="211",
        prior_major="Computer Science",
        completed_courses=["Programming", "Statistics", "Database Systems"],
        preferred_intake=["FEB", "JUL"],
        budget_range=RangePreference(max=70000),
        duration_preference=RangePreference(max=2),
        accepts_pathway=False,
    )


def _recommended_course_names(response) -> list[str]:
    programs = response.reach_programs + response.match_programs + response.safety_programs
    return [program.course_name for program in programs]


def _response_has_evidence(response) -> bool:
    programs = response.reach_programs + response.match_programs + response.safety_programs
    return any(program.evidence_snippets or program.source_url for program in programs)


def _response_has_feature_match(response) -> bool:
    programs = response.reach_programs + response.match_programs + response.safety_programs
    return any(program.feature_match is not None for program in programs)


def _require_state(context: E2ERunContext, key: str):
    value = context.state.get(key)
    if value is None:
        raise E2EStageError("recommendation_service", f"Required E2E state is missing: {key}")
    return value


@contextmanager
def _temporary_database_url(database_url: str):
    with _temporary_env({"DATABASE_URL": database_url}):
        yield


@contextmanager
def _temporary_env(values: dict[str, str]):
    previous = {key: os.environ.get(key) for key in values}
    for key, value in values.items():
        os.environ[key] = value
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _api_smoke_env(context: E2ERunContext) -> dict[str, str]:
    return {
        "DATABASE_URL": context.options.database_url or "",
        "CHROMA_PERSIST_DIRECTORY": str(_vector_dir(context)),
        "CHROMA_COLLECTION_NAME": _vector_collection_name(context),
        "OPENAI_API_KEY": "",
    }


def _dashboard_env(context: E2ERunContext) -> dict[str, str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = context.options.database_url or ""
    env["CHROMA_PERSIST_DIRECTORY"] = str(_vector_dir(context))
    env["CHROMA_COLLECTION_NAME"] = _vector_collection_name(context)
    env["OPENAI_API_KEY"] = ""
    return env


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_http(base_url: str) -> None:
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base_url, timeout=2) as response:
                if response.status < 500:
                    return
        except Exception:
            time.sleep(1)
    raise RuntimeError(f"Dashboard did not become ready at {base_url}")


def _run_dashboard_playwright_checks(*, base_url: str, headed: bool, screenshot_path: Path) -> None:
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not headed)
        page = browser.new_page()
        try:
            page.goto(base_url, wait_until="domcontentloaded")
            expect(page.get_by_text("USYD Recommendation Console", exact=True)).to_be_visible(timeout=20_000)
            expect(page.get_by_text("Recommendation Plan", exact=True)).to_be_visible()
            expect(page.get_by_role("link", name="Docs")).to_have_attribute("href", re.compile(r"README\.md"))

            page.get_by_text("Course Search", exact=True).click()
            expect(page.get_by_text("Admissions semantic search", exact=True)).to_be_visible(timeout=20_000)
            expect(page.get_by_text("Master of Data Science").first).to_be_visible(timeout=20_000)
            expect(page.get_by_text("Feature Profile", exact=True)).to_be_visible(timeout=20_000)
            expect(page.get_by_text("Edit Feature Profile", exact=True)).to_be_visible(timeout=20_000)

            page.get_by_label("Admissions semantic search").fill("portfolio")
            page.get_by_role("button", name="Search").click()
            expect(page.get_by_text("OPENAI_API_KEY").first).to_be_visible(timeout=10_000)

            page.get_by_text("Recommendation Plan", exact=True).click()
            page.get_by_role("button", name="Run Eligibility Screening").click()
            expect(page.get_by_text("Next-Layer Match Bands", exact=True)).to_be_visible(timeout=30_000)

            page.get_by_text("中文", exact=True).click()
            expect(page.get_by_text("USYD 留学方案工作台", exact=True)).to_be_visible(timeout=10_000)
            expect(page.get_by_role("link", name="文档")).to_have_attribute("href", re.compile(r"README\.zh\.md"))
            page.get_by_text("课程查询", exact=True).click()
            expect(page.get_by_text("录取要求语义搜索", exact=True)).to_be_visible(timeout=10_000)
        except Exception:
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(screenshot_path), full_page=True)
            raise
        finally:
            browser.close()


def _cleanup_work_dir(context: E2ERunContext) -> None:
    if context.options.keep_artifacts:
        return
    shutil.rmtree(context.work_dir, ignore_errors=True)
