from __future__ import annotations

from typing import Any

from fastapi import Body, FastAPI, HTTPException
from pydantic import ValidationError

from src.config import load_settings
from src.db import connect
from src.models.course_features import (
    CourseFeatureGenerationRequest,
    CourseFeatureProfile,
    CourseFeatureResponse,
    CourseMatchRequest,
    MatchResult,
)
from src.models.recommendation import RecommendationRequest, RecommendationResponse
from src.recommendation.course_features import (
    filter_courses_by_features,
    generate_course_features,
    match_course_to_user,
    merge_course_feature_override,
)
from src.recommendation.feature_repository import CourseFeatureRecord, CourseFeatureRepository
from src.recommendation.service import RecommendationService, RecommendationServiceError


app = FastAPI(title="USYD Recommendation API")


@app.post("/recommendations/usyd", response_model=RecommendationResponse)
def create_usyd_recommendation(request: RecommendationRequest) -> RecommendationResponse:
    try:
        return RecommendationService().recommend(request)
    except RecommendationServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/courses/{course_id}/features", response_model=CourseFeatureResponse)
def get_course_features(course_id: str) -> CourseFeatureResponse:
    record = _fetch_course_feature_record(course_id)
    return CourseFeatureResponse(
        course_id=record.course_id,
        course_name=record.course_name,
        course_features=record.course_features,
        manual_overrides=record.manual_overrides,
    )


@app.post("/courses/{course_id}/generate-features", response_model=CourseFeatureResponse)
def generate_features_for_course(
    course_id: str,
    request: CourseFeatureGenerationRequest | None = None,
) -> CourseFeatureResponse:
    request = request or CourseFeatureGenerationRequest()
    record = _fetch_course_feature_record(course_id)
    overrides = request.manual_override or {}
    if not request.replace_existing:
        overrides = {**record.manual_overrides, **overrides}
    try:
        profile = generate_course_features(record.source, manual_override=overrides)
    except (TypeError, ValueError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if request.persist:
        _save_course_feature_record(course_id, profile, overrides)
    return CourseFeatureResponse(
        course_id=record.course_id,
        course_name=record.course_name,
        course_features=profile,
        manual_overrides=overrides,
    )


@app.patch("/courses/{course_id}/features", response_model=CourseFeatureResponse)
def patch_course_features(
    course_id: str,
    patch: dict[str, Any] = Body(...),
) -> CourseFeatureResponse:
    record = _fetch_course_feature_record(course_id)
    overrides = {**record.manual_overrides, **patch}
    generated = generate_course_features(record.source)
    try:
        profile = merge_course_feature_override(generated, overrides)
    except (TypeError, ValueError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _save_course_feature_record(course_id, profile, overrides)
    return CourseFeatureResponse(
        course_id=record.course_id,
        course_name=record.course_name,
        course_features=profile,
        manual_overrides=overrides,
    )


@app.post("/courses/match", response_model=MatchResult)
def match_course(request: CourseMatchRequest) -> MatchResult:
    if request.course_features is None and request.course_id is None:
        raise HTTPException(status_code=400, detail="Provide course_id or course_features.")
    course_features = request.course_features
    if course_features is None:
        record = _fetch_course_feature_record(request.course_id or "")
        course_features = record.course_features or CourseFeatureProfile()
    return match_course_to_user(course_features, request.user_features)


@app.get("/courses/filter-features")
def filter_featured_courses(
    discipline_tag: str | None = None,
    knowledge_tag: str | None = None,
    min_ai_relevance: float | None = None,
    min_data_relevance: float | None = None,
    max_risk_level: float | None = None,
) -> list[dict[str, Any]]:
    settings = load_settings()
    try:
        with connect(settings) as conn:
            rows = CourseFeatureRepository().fetch_feature_audit_rows(conn)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Course feature storage is unavailable. Run database migrations and retry.",
        ) from exc
    return filter_courses_by_features(
        rows,
        discipline_tags=[discipline_tag] if discipline_tag else None,
        knowledge_tags=[knowledge_tag] if knowledge_tag else None,
        min_ai_relevance=min_ai_relevance,
        min_data_relevance=min_data_relevance,
        max_risk_level=max_risk_level,
    )


def _fetch_course_feature_record(course_id: str) -> CourseFeatureRecord:
    settings = load_settings()
    try:
        with connect(settings) as conn:
            record = CourseFeatureRepository().fetch_course(conn, course_id=course_id)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Course feature storage is unavailable. Run database migrations and retry.",
        ) from exc
    if record is None:
        raise HTTPException(status_code=404, detail="Course not found.")
    return record


def _save_course_feature_record(
    course_id: str,
    profile: CourseFeatureProfile,
    overrides: dict[str, Any],
) -> None:
    settings = load_settings()
    try:
        with connect(settings) as conn:
            with conn.transaction():
                CourseFeatureRepository().save_course_features(
                    conn,
                    course_id=course_id,
                    course_features=profile,
                    manual_overrides=overrides,
                )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Course feature storage is unavailable. Run database migrations and retry.",
        ) from exc
