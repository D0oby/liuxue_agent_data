from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _score_field() -> Any:
    return Field(default=0.0, ge=0, le=5)


class CourseFeatureProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    discipline_tags: list[str] = Field(default_factory=list)
    knowledge_tags: list[str] = Field(default_factory=list)
    career_tags: list[str] = Field(default_factory=list)
    background_fit_tags: list[str] = Field(default_factory=list)

    math_intensity: float = _score_field()
    coding_intensity: float = _score_field()
    theory_intensity: float = _score_field()
    business_intensity: float = _score_field()
    ai_relevance: float = _score_field()
    data_relevance: float = _score_field()
    conversion_friendliness: float = _score_field()
    risk_level: float = _score_field()
    admission_gpa_min: float | None = Field(default=None, ge=0, le=100)
    ielts_overall_min: float | None = Field(default=None, ge=0, le=9)
    ielts_min_band_min: float | None = Field(default=None, ge=0, le=9)
    annual_fee_aud: float | None = Field(default=None, ge=0)
    duration_years: float | None = Field(default=None, gt=0)
    intake_tags: list[str] = Field(default_factory=list)
    campus_tags: list[str] = Field(default_factory=list)
    requires_relevant_background: bool = False

    @field_validator(
        "discipline_tags",
        "knowledge_tags",
        "career_tags",
        "background_fit_tags",
        "intake_tags",
        "campus_tags",
        mode="before",
    )
    @classmethod
    def validate_string_array(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("Tag fields must be arrays of strings.")
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, str):
                raise ValueError("Tag fields must contain strings only.")
            label = " ".join(item.split()).strip().casefold()
            if label and label not in seen:
                seen.add(label)
                normalized.append(label)
        return normalized


class UserFeatureProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    discipline_interests: list[str] = Field(default_factory=list)
    knowledge_interests: list[str] = Field(default_factory=list)
    career_goals: list[str] = Field(default_factory=list)
    academic_background_tags: list[str] = Field(default_factory=list)

    math_strength: float = _score_field()
    coding_strength: float = _score_field()
    theory_interest: float = _score_field()
    business_interest: float = _score_field()
    ai_interest: float = _score_field()
    data_interest: float = _score_field()
    wants_conversion_friendly: bool = False

    gpa: float | None = Field(default=None, ge=0, le=100)
    ielts_overall: float | None = Field(default=None, ge=0, le=9)
    ielts_min_band: float | None = Field(default=None, ge=0, le=9)
    budget_per_year_aud: float | None = Field(default=None, ge=0)
    preferred_duration_years: float | None = Field(default=None, gt=0)
    preferred_intake_tags: list[str] = Field(default_factory=list)
    preferred_campus_tags: list[str] = Field(default_factory=list)

    @field_validator(
        "discipline_interests",
        "knowledge_interests",
        "career_goals",
        "academic_background_tags",
        "preferred_intake_tags",
        "preferred_campus_tags",
        mode="before",
    )
    @classmethod
    def validate_string_array(cls, value: Any) -> list[str]:
        return CourseFeatureProfile.validate_string_array(value)


class MatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: float = Field(ge=0, le=100)
    risk_level: float = Field(ge=0, le=5)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    matched_tags: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    tag_overlap_score: float = Field(default=0, ge=0, le=100)
    numeric_profile_score: float = Field(default=0, ge=0, le=100)
    penalty_score: float = Field(default=0, ge=0)


class CourseFeatureResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_id: str
    course_name: str
    course_features: CourseFeatureProfile | None = None
    manual_overrides: dict[str, Any] = Field(default_factory=dict)


class CourseFeatureGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manual_override: dict[str, Any] | None = None
    persist: bool = False
    replace_existing: bool = False


class CourseMatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_features: UserFeatureProfile
    course_id: str | None = None
    course_features: CourseFeatureProfile | None = None


class CourseFeatureAuditFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_id: str
    course_name: str = ""
    code: str
    message: str
