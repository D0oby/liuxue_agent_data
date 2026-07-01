from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


MatchBand = Literal["REACH", "MATCH", "SAFETY"]
CheckStatus = Literal["pass", "fail", "warning", "unknown", "skip"]


class EligibilityStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    HIGH_RISK = "HIGH_RISK"
    UNKNOWN = "UNKNOWN"
    PATHWAY_REQUIRED = "PATHWAY_REQUIRED"


class RangePreference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min: float | None = None
    max: float | None = None

    @model_validator(mode="after")
    def validate_bounds(self) -> "RangePreference":
        if self.min is not None and self.max is not None and self.max < self.min:
            raise ValueError("Range max must be greater than or equal to min.")
        return self

    def contains_interval(self, lower: float | None, upper: float | None) -> bool:
        if lower is None and upper is None:
            return True
        interval_lower = lower if lower is not None else upper
        interval_upper = upper if upper is not None else lower
        if interval_lower is None or interval_upper is None:
            return True
        if self.min is not None and interval_upper < self.min:
            return False
        if self.max is not None and interval_lower > self.max:
            return False
        return True

    def contains_value(self, value: float | None) -> bool:
        if value is None:
            return True
        if self.min is not None and value < self.min:
            return False
        if self.max is not None and value > self.max:
            return False
        return True


class RecommendationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_major_keyword: str
    gpa_user: float | None = Field(default=None, gt=0)
    gpa_scale: float = Field(default=100, gt=0)
    ielts_overall_user: float | None = Field(default=None, gt=0, le=9)
    ielts_min_band_user: float | None = Field(default=None, gt=0, le=9)
    ielts_listening_user: float | None = Field(default=None, gt=0, le=9)
    ielts_reading_user: float | None = Field(default=None, gt=0, le=9)
    ielts_speaking_user: float | None = Field(default=None, gt=0, le=9)
    ielts_writing_user: float | None = Field(default=None, gt=0, le=9)
    academic_background: str
    prior_major: str | None = None
    completed_courses: list[str] = Field(default_factory=list)
    preferred_intake: str | list[str] = Field(default_factory=list)
    budget_range: RangePreference = Field(default_factory=RangePreference)
    duration_preference: RangePreference = Field(default_factory=RangePreference)
    campus_preference: str | list[str] | None = None
    study_mode_preference: str | list[str] | None = None
    degree_type_preference: str | None = None
    faculty_preference: str | None = None
    school_preference: str | None = None
    accepts_pathway: bool = False

    @field_validator("target_major_keyword", "academic_background")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = " ".join(value.split()).strip()
        if not normalized:
            raise ValueError("Text field cannot be empty.")
        return normalized

    @field_validator(
        "prior_major",
        "degree_type_preference",
        "faculty_preference",
        "school_preference",
    )
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split()).strip()
        return normalized or None

    @field_validator("completed_courses")
    @classmethod
    def normalize_completed_courses(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            label = " ".join(str(item).split()).strip()
            key = label.casefold()
            if label and key not in seen:
                seen.add(key)
                normalized.append(label)
        return normalized


class UserProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_major_keyword: str
    gpa_user: float | None = None
    gpa_scale: float = 100
    ielts_overall_user: float | None = None
    ielts_min_band_user: float | None = None
    ielts_listening_user: float | None = None
    ielts_reading_user: float | None = None
    ielts_speaking_user: float | None = None
    ielts_writing_user: float | None = None
    academic_background: str
    prior_major: str | None = None
    completed_courses: list[str] = Field(default_factory=list)
    preferred_intake: list[str]
    budget_range: RangePreference
    duration_preference: RangePreference
    campus_preference: list[str] = Field(default_factory=list)
    study_mode_preference: list[str] = Field(default_factory=list)
    degree_type_preference: str | None = None
    faculty_preference: str | None = None
    school_preference: str | None = None
    accepts_pathway: bool = False


class QuerySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_major_keyword: str
    keyword_query: str
    semantic_query: str
    keywords: list[str] = Field(default_factory=list)


class EvidenceSnippet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    source_url: str | None = None
    source: str | None = None


class KeywordSearchHit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_id: str
    course_name: str
    cricos: str
    duration_min_years: float | None = None
    duration_max_years: float | None = None
    tuition_fee_aud: float | None = None
    academic_requirement_text: str = ""
    raw_english_requirement: str = ""
    ielts_overall_required: float | None = None
    ielts_min_band_required: float | None = None
    ielts_listening_required: float | None = None
    ielts_reading_required: float | None = None
    ielts_speaking_required: float | None = None
    ielts_writing_required: float | None = None
    academic_requirements_json: dict[str, Any] = Field(default_factory=dict)
    application_details_json: dict[str, Any] = Field(default_factory=dict)
    supplementary_metadata_json: dict[str, Any] = Field(default_factory=dict)
    source_url: str | None = None
    hit_fields: list[str] = Field(default_factory=list)
    keyword_score: float = 0.0
    retrieval_reason: str = ""
    evidence_snippets: list[EvidenceSnippet] = Field(default_factory=list)


class VectorSearchHit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_id: str
    course_name: str
    cricos: str
    chunk_text: str
    chunk_source: str | None = None
    source_url: str | None = None
    vector_score: float
    retrieval_reason: str = ""
    evidence_snippets: list[EvidenceSnippet] = Field(default_factory=list)


class CourseCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_id: str
    course_name: str
    cricos: str
    duration_min_years: float | None = None
    duration_max_years: float | None = None
    tuition_fee_aud: float | None = None
    intakes: list[str] = Field(default_factory=list)
    academic_requirement_text: str = ""
    raw_english_requirement: str = ""
    ielts_overall_required: float | None = None
    ielts_min_band_required: float | None = None
    ielts_listening_required: float | None = None
    ielts_reading_required: float | None = None
    ielts_speaking_required: float | None = None
    ielts_writing_required: float | None = None
    academic_requirements_json: dict[str, Any] = Field(default_factory=dict)
    application_details_json: dict[str, Any] = Field(default_factory=dict)
    supplementary_metadata_json: dict[str, Any] = Field(default_factory=dict)
    degree_type: str | None = None
    faculty: str | None = None
    school: str | None = None
    campus: str | None = None
    study_mode: str | None = None
    retrieval_score: float = 0.0
    retrieval_reason: str = ""
    keyword_score: float = 0.0
    vector_score: float = 0.0
    combined_retrieval_score: float = 0.0
    evidence_snippets: list[EvidenceSnippet] = Field(default_factory=list)
    source_url: str | None = None


class RawAdmissionRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_id: str
    academic_requirement_text: str = ""
    raw_english_requirement: str = ""
    ielts_overall: float | None = None
    ielts_min_band: float | None = None
    ielts_listening: float | None = None
    ielts_reading: float | None = None
    ielts_speaking: float | None = None
    ielts_writing: float | None = None
    english_req_details: dict[str, Any] = Field(default_factory=dict)
    academic_requirements_json: dict[str, Any] = Field(default_factory=dict)
    application_details_json: dict[str, Any] = Field(default_factory=dict)
    supplementary_metadata_json: dict[str, Any] = Field(default_factory=dict)
    source_url: str | None = None


class NormalizedRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_id: str
    gpa_min: float | None = None
    gpa_calculation_method: str = "usyd_arithmetic_average_all_courses"
    ielts_overall_min: float | None = None
    ielts_min_band_min: float | None = None
    requirement_summary: str
    requirement_source_url: str | None = None


class ScoreResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_id: str
    gpa_score_component: float
    ielts_score_component: float
    final_score: float
    match_band: MatchBand
    reason_tags: list[str] = Field(default_factory=list)


class ScoredCourseCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_id: str
    course_name: str
    cricos: str
    duration_min_years: float | None = None
    duration_max_years: float | None = None
    tuition_fee_aud: float | None = None
    intakes: list[str] = Field(default_factory=list)
    academic_requirement_text: str = ""
    raw_english_requirement: str = ""
    ielts_overall_required: float | None = None
    ielts_min_band_required: float | None = None
    ielts_listening_required: float | None = None
    ielts_reading_required: float | None = None
    ielts_speaking_required: float | None = None
    ielts_writing_required: float | None = None
    academic_requirements_json: dict[str, Any] = Field(default_factory=dict)
    application_details_json: dict[str, Any] = Field(default_factory=dict)
    supplementary_metadata_json: dict[str, Any] = Field(default_factory=dict)
    degree_type: str | None = None
    faculty: str | None = None
    school: str | None = None
    campus: str | None = None
    study_mode: str | None = None
    retrieval_score: float = 0.0
    retrieval_reason: str = ""
    keyword_score: float = 0.0
    vector_score: float = 0.0
    combined_retrieval_score: float = 0.0
    evidence_snippets: list[EvidenceSnippet] = Field(default_factory=list)
    source_url: str | None = None
    gpa_min: float
    gpa_calculation_method: str = "usyd_arithmetic_average_all_courses"
    ielts_overall_min: float
    ielts_min_band_min: float
    requirement_summary: str
    requirement_source_url: str | None = None
    gpa_score_component: float
    ielts_score_component: float
    final_score: float
    match_band: MatchBand
    reason_tags: list[str] = Field(default_factory=list)
    recommendation_reason: str = ""


class ExcludedProgram(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_id: str
    course_name: str = ""
    reason: str
    details: str = ""
    source_url: str | None = None
    evidence_snippets: list[EvidenceSnippet] = Field(default_factory=list)


class RecommendedProgram(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_id: str
    course_name: str
    cricos: str
    duration: str
    intakes: list[str]
    tuition_fee_aud: float | None = None
    ielts_requirement: str
    academic_requirement_summary: str
    gpa_calculation_method: str = "usyd_arithmetic_average_all_courses"
    score: float
    band: MatchBand
    recommendation_reason: str
    evidence_snippets: list[EvidenceSnippet] = Field(default_factory=list)
    source_url: str | None = None


class RequirementCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    status: CheckStatus
    user_value: Any = None
    required_value: Any = None
    reason: str
    evidence_snippets: list[EvidenceSnippet] = Field(default_factory=list)
    source_url: str | None = None
    source_type: str | None = None


class EligibilityDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_id: str
    course_name: str
    cricos: str = ""
    eligibility_status: EligibilityStatus
    hard_filter_summary: str
    requirement_checks: list[RequirementCheck] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    can_enter_next_layer: bool
    reason: str = ""
    details: str = ""
    degree_type: str | None = None
    faculty: str | None = None
    school: str | None = None
    tuition_fee_aud: float | None = None
    duration: str = ""
    duration_min_years: float | None = None
    duration_max_years: float | None = None
    campus: str | None = None
    study_mode: str | None = None
    intakes: list[str] = Field(default_factory=list)
    source_url: str | None = None
    evidence_snippets: list[EvidenceSnippet] = Field(default_factory=list)


class EligibilitySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_candidates: int = 0
    eligible_count: int = 0
    high_risk_count: int = 0
    ineligible_count: int = 0
    unknown_count: int = 0
    pathway_required_count: int = 0


class RecommendationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reach_programs: list[RecommendedProgram] = Field(default_factory=list)
    match_programs: list[RecommendedProgram] = Field(default_factory=list)
    safety_programs: list[RecommendedProgram] = Field(default_factory=list)
    excluded_programs: list[ExcludedProgram] = Field(default_factory=list)


class RecommendationMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    model_version: str
    scoring_config: dict[str, Any]
    generated_at: datetime
    candidate_count: int
    scored_candidate_count: int
    degraded_retrieval: bool = False


class RecommendationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_profile: UserProfile
    query_summary: dict[str, Any]
    eligibility_summary: EligibilitySummary = Field(default_factory=EligibilitySummary)
    next_layer_candidates: list[EligibilityDecision] = Field(default_factory=list)
    eligible_programs: list[EligibilityDecision] = Field(default_factory=list)
    reach_programs: list[RecommendedProgram] = Field(default_factory=list)
    match_programs: list[RecommendedProgram] = Field(default_factory=list)
    safety_programs: list[RecommendedProgram] = Field(default_factory=list)
    high_risk_programs: list[EligibilityDecision] = Field(default_factory=list)
    excluded_programs: list[EligibilityDecision] = Field(default_factory=list)
    metadata: RecommendationMetadata
    explanation: str = ""
