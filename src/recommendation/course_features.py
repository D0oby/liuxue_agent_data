from __future__ import annotations

from dataclasses import is_dataclass, asdict
from typing import Any

from src.config import FeatureMatchingConfig
from src.models.course_features import (
    CourseFeatureAuditFinding,
    CourseFeatureProfile,
    MatchResult,
    UserFeatureProfile,
)
from src.models.feature_taxonomy import TAG_KEYWORDS


def generate_course_features(
    course_raw_data: dict[str, Any] | Any,
    manual_override: dict[str, Any] | CourseFeatureProfile | None = None,
) -> CourseFeatureProfile:
    raw = _as_mapping(course_raw_data)
    text = _course_text(raw)
    profile_data: dict[str, Any] = {
        "discipline_tags": _matched_tags(text, TAG_KEYWORDS["discipline_tags"]),
        "knowledge_tags": _matched_tags(text, TAG_KEYWORDS["knowledge_tags"]),
        "career_tags": _matched_tags(text, TAG_KEYWORDS["career_tags"]),
        "background_fit_tags": _matched_tags(text, TAG_KEYWORDS["background_fit_tags"]),
        "math_intensity": _score(text, (("calculus", "linear algebra", "mathematics", "maths", "quantitative"), 4)),
        "coding_intensity": _score(text, (("programming", "python", "java", "coding", "software"), 4)),
        "theory_intensity": _score(text, (("theory", "theoretical", "foundations"), 3)),
        "business_intensity": _score(text, (("business", "commerce", "management", "marketing"), 4)),
        "ai_relevance": _score(text, (("artificial intelligence", "machine learning", "deep learning", " ai "), 5)),
        "data_relevance": _score(text, (("data science", "data analytics", "data visualisation", "statistics"), 5)),
        "conversion_friendliness": 5 if _contains_any(text, ("any discipline", "conversion", "wide range")) else 0,
        "risk_level": 1,
        "annual_fee_aud": raw.get("tuition_fee_aud") or raw.get("annual_fee_aud"),
        "duration_years": raw.get("duration_max_years") or raw.get("duration_years"),
        "intake_tags": _coerce_list(raw.get("intakes") or raw.get("intake_tags")),
        "campus_tags": _coerce_list(raw.get("campus_tags") or raw.get("campus")),
    }
    if "relevant background required" in profile_data["background_fit_tags"]:
        profile_data["requires_relevant_background"] = True
        profile_data["risk_level"] = 2
    if profile_data["ai_relevance"] >= 4 or profile_data["data_relevance"] >= 4:
        profile_data["risk_level"] = max(profile_data["risk_level"], 3)
    return merge_course_feature_override(CourseFeatureProfile.model_validate(profile_data), manual_override)


def merge_course_feature_override(
    generated_profile: CourseFeatureProfile | dict[str, Any] | None,
    manual_override: dict[str, Any] | CourseFeatureProfile | None,
) -> CourseFeatureProfile:
    base = _profile(generated_profile).model_dump()
    if manual_override is None:
        return CourseFeatureProfile.model_validate(base)
    override_data = manual_override.model_dump() if isinstance(manual_override, CourseFeatureProfile) else manual_override
    return CourseFeatureProfile.model_validate({**base, **override_data})


def match_course_to_user(
    course_features: CourseFeatureProfile | dict[str, Any],
    user_features: UserFeatureProfile | dict[str, Any],
    *,
    config: FeatureMatchingConfig | None = None,
) -> MatchResult:
    config = config or FeatureMatchingConfig()
    course = _profile(course_features)
    user = user_features if isinstance(user_features, UserFeatureProfile) else UserFeatureProfile.model_validate(user_features)
    tag_score, matched_tags = _tag_score(course, user)
    numeric_score = _numeric_score(course, user)
    penalty, weaknesses, missing = _penalties(course, user, config)
    total_weight = config.tag_weight + config.numeric_weight
    base_score = 50 if total_weight == 0 else (
        (config.tag_weight * tag_score + config.numeric_weight * numeric_score) / total_weight
    )
    score = _clamp(base_score - penalty, 0, 100)
    strengths = []
    if matched_tags:
        strengths.append("Course tags overlap with the user's interests.")
    if course.ai_relevance >= 4 and user.ai_interest >= 4:
        strengths.append("Strong AI interest match.")
    if course.data_relevance >= 4 and user.data_interest >= 4:
        strengths.append("Strong data interest match.")
    return MatchResult(
        score=round(score, 2),
        risk_level=round(_clamp(course.risk_level + penalty / 25, 0, 5), 2),
        strengths=strengths or ["Course profile has a moderate feature match."],
        weaknesses=weaknesses,
        matched_tags=matched_tags,
        missing_requirements=missing,
        tag_overlap_score=round(tag_score, 2),
        numeric_profile_score=round(numeric_score, 2),
        penalty_score=round(penalty, 2),
    )


def filter_courses_by_features(
    rows: list[dict[str, Any]],
    *,
    discipline_tags: list[str] | None = None,
    knowledge_tags: list[str] | None = None,
    min_ai_relevance: float | None = None,
    min_data_relevance: float | None = None,
    max_risk_level: float | None = None,
    min_conversion_friendliness: float | None = None,
) -> list[dict[str, Any]]:
    result = []
    wanted_disciplines = {tag.casefold() for tag in discipline_tags or []}
    wanted_knowledge = {tag.casefold() for tag in knowledge_tags or []}
    for row in rows:
        profile = _optional_profile(row.get("course_features"))
        if profile is None:
            continue
        if wanted_disciplines and not (wanted_disciplines & set(profile.discipline_tags)):
            continue
        if wanted_knowledge and not (wanted_knowledge & set(profile.knowledge_tags)):
            continue
        if min_ai_relevance is not None and profile.ai_relevance < min_ai_relevance:
            continue
        if min_data_relevance is not None and profile.data_relevance < min_data_relevance:
            continue
        if max_risk_level is not None and profile.risk_level > max_risk_level:
            continue
        if min_conversion_friendliness is not None and profile.conversion_friendliness < min_conversion_friendliness:
            continue
        result.append(row)
    return result


def audit_course_feature_profiles(rows: list[dict[str, Any]]) -> list[CourseFeatureAuditFinding]:
    findings: list[CourseFeatureAuditFinding] = []
    for row in rows:
        course_id = str(row.get("course_id") or row.get("id") or "")
        course_name = str(row.get("course_name") or "")
        profile = _optional_profile(row.get("course_features"))
        if profile is None:
            findings.append(_finding(course_id, course_name, "missing_profile", "Course has no feature profile."))
            continue
        if not (profile.discipline_tags or profile.knowledge_tags or profile.career_tags or profile.background_fit_tags):
            findings.append(_finding(course_id, course_name, "empty_profile", "Course profile has no tags."))
        numeric_values = [
            profile.math_intensity,
            profile.coding_intensity,
            profile.theory_intensity,
            profile.business_intensity,
            profile.ai_relevance,
            profile.data_relevance,
        ]
        if all(value == 0 for value in numeric_values):
            findings.append(_finding(course_id, course_name, "all_zero_scores", "Course profile has all-zero scores."))
        if profile.risk_level >= 5:
            findings.append(_finding(course_id, course_name, "high_risk_profile", "Course profile has maximum risk."))
    return findings


def user_profile_to_features(user_profile: Any) -> UserFeatureProfile:
    explicit = getattr(user_profile, "user_features", None)
    if explicit is not None:
        return explicit
    text = f" {getattr(user_profile, 'target_major_keyword', '')} {getattr(user_profile, 'prior_major', '')} {' '.join(getattr(user_profile, 'completed_courses', []) or [])} ".casefold()
    data = {
        "discipline_interests": _matched_tags(text, TAG_KEYWORDS["discipline_tags"]),
        "knowledge_interests": _matched_tags(text, TAG_KEYWORDS["knowledge_tags"]),
        "academic_background_tags": _matched_tags(text, TAG_KEYWORDS["background_fit_tags"]),
        "math_strength": 4 if _contains_any(text, ("math", "statistics", "quantitative")) else 2,
        "coding_strength": 4 if _contains_any(text, ("computer", "programming", "software", "python", "java")) else 2,
        "business_interest": 4 if _contains_any(text, ("business", "commerce", "management")) else 2,
        "ai_interest": 5 if _contains_any(text, ("artificial intelligence", "machine learning", " ai ")) else 2,
        "data_interest": 5 if _contains_any(text, ("data", "analytics", "statistics")) else 2,
        "gpa": getattr(user_profile, "gpa_user", None),
        "ielts_overall": getattr(user_profile, "ielts_overall_user", None),
        "ielts_min_band": getattr(user_profile, "ielts_min_band_user", None),
        "budget_per_year_aud": getattr(getattr(user_profile, "budget_range", None), "max", None),
        "preferred_duration_years": getattr(getattr(user_profile, "duration_preference", None), "max", None),
        "preferred_intake_tags": getattr(user_profile, "preferred_intake", []),
        "preferred_campus_tags": getattr(user_profile, "campus_preference", []),
    }
    return UserFeatureProfile.model_validate(data)


def _finding(course_id: str, course_name: str, code: str, message: str) -> CourseFeatureAuditFinding:
    return CourseFeatureAuditFinding(course_id=course_id, course_name=course_name, code=code, message=message)


def _tag_score(course: CourseFeatureProfile, user: UserFeatureProfile) -> tuple[float, list[str]]:
    pairs = [
        (course.discipline_tags, user.discipline_interests),
        (course.knowledge_tags, user.knowledge_interests),
        (course.career_tags, user.career_goals),
        (course.background_fit_tags, user.academic_background_tags),
    ]
    scores = []
    matched: list[str] = []
    for course_tags, user_tags in pairs:
        user_set = set(user_tags)
        if not user_set:
            continue
        overlap = sorted(set(course_tags) & user_set)
        matched.extend(overlap)
        scores.append((len(overlap) / len(user_set)) * 100)
    return (sum(scores) / len(scores), _dedupe(matched)) if scores else (50, [])


def _numeric_score(course: CourseFeatureProfile, user: UserFeatureProfile) -> float:
    pairs = [
        (course.math_intensity, user.math_strength),
        (course.coding_intensity, user.coding_strength),
        (course.theory_intensity, user.theory_interest),
        (course.business_intensity, user.business_interest),
        (course.ai_relevance, user.ai_interest),
        (course.data_relevance, user.data_interest),
    ]
    return sum((1 - abs(course_value - user_value) / 5) * 100 for course_value, user_value in pairs) / len(pairs)


def _penalties(
    course: CourseFeatureProfile,
    user: UserFeatureProfile,
    config: FeatureMatchingConfig,
) -> tuple[float, list[str], list[str]]:
    penalty = 0.0
    weaknesses: list[str] = []
    missing: list[str] = []
    if course.admission_gpa_min is not None and user.gpa is not None and user.gpa < course.admission_gpa_min:
        penalty += config.gpa_penalty
        missing.append("gpa_below_admission_min")
        weaknesses.append("GPA is below the course threshold.")
    if course.ielts_overall_min is not None and user.ielts_overall is not None and user.ielts_overall < course.ielts_overall_min:
        penalty += config.ielts_penalty
        missing.append("ielts_overall_below_min")
        weaknesses.append("IELTS overall is below the course threshold.")
    if course.annual_fee_aud is not None and user.budget_per_year_aud is not None and course.annual_fee_aud > user.budget_per_year_aud:
        penalty += config.budget_penalty
        missing.append("fee_above_budget")
        weaknesses.append("Annual fee is above the user's budget.")
    if course.duration_years is not None and user.preferred_duration_years is not None and course.duration_years > user.preferred_duration_years:
        penalty += config.duration_penalty
        missing.append("duration_above_preference")
        weaknesses.append("Duration is above the user's preference.")
    if course.requires_relevant_background and "relevant background required" not in user.academic_background_tags:
        penalty += config.background_penalty
        missing.append("relevant_background_required")
        weaknesses.append("Program requires a relevant background.")
    return penalty, weaknesses, missing


def _course_text(raw: dict[str, Any]) -> str:
    parts = [
        raw.get("course_name"),
        raw.get("program_name"),
        raw.get("faculty"),
        raw.get("school"),
        raw.get("course_description"),
        raw.get("academic_requirement_text"),
        raw.get("admission_requirements"),
        raw.get("prerequisites"),
        " ".join(_coerce_list(raw.get("units"))),
        " ".join(_coerce_list(raw.get("career_outcomes"))),
    ]
    return f" {' '.join(str(part or '') for part in parts).casefold()} "


def _matched_tags(text: str, mapping: dict[str, tuple[str, ...]]) -> list[str]:
    return [label for label, keywords in mapping.items() if _contains_any(text, keywords)]


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword.casefold() in text for keyword in keywords)


def _score(text: str, rule: tuple[tuple[str, ...], float]) -> float:
    keywords, value = rule
    return value if _contains_any(text, keywords) else 0.0


def _profile(value: CourseFeatureProfile | dict[str, Any] | None) -> CourseFeatureProfile:
    if isinstance(value, CourseFeatureProfile):
        return value
    return CourseFeatureProfile.model_validate(value or {})


def _optional_profile(value: CourseFeatureProfile | dict[str, Any] | None) -> CourseFeatureProfile | None:
    if value is None:
        return None
    return _profile(value)


def _coerce_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [chunk.strip() for chunk in str(value).replace("/", ",").split(",") if chunk.strip()]


def _as_mapping(value: dict[str, Any] | Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return {
        key: getattr(value, key)
        for key in dir(value)
        if not key.startswith("_") and not callable(getattr(value, key))
    }


def _dedupe(values: list[str]) -> list[str]:
    deduped = []
    seen = set()
    for value in values:
        key = " ".join(value.split()).casefold()
        if key and key not in seen:
            seen.add(key)
            deduped.append(key)
    return deduped


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))
