from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

from src.models.recommendation import (
    CheckStatus,
    CourseCandidate,
    EligibilityDecision,
    EligibilityStatus,
    EligibilitySummary,
    EvidenceSnippet,
    NormalizedRequirement,
    RawAdmissionRequirement,
    RequirementCheck,
    UserProfile,
)
from src.recommendation.query_builder import QueryBuilder
from src.recommendation.requirements import RequirementResult
from src.transform.parse_english_requirement import parse_english_requirement


CRITICAL_PREREQ_MARKERS = (
    "prerequisite",
    "pre-requisite",
    "assumed knowledge",
    "background in",
    "prior study in",
    "bachelor in relevant discipline",
    "bachelor's degree in a relevant discipline",
    "bachelor degree in a relevant discipline",
    "bachelor's degree in a related discipline",
    "bachelor degree in a related discipline",
    "relevant discipline",
    "cognate discipline",
    "related discipline",
    "mathematics",
    "statistics",
    "computer science",
    "programming",
    "economics",
)

SUBJECT_ALIASES = {
    "mathematics": ("mathematics", "math", "maths", "calculus", "linear algebra", "数学", "高数", "微积分"),
    "statistics": ("statistics", "statistical", "stats", "probability", "统计", "概率"),
    "computer science": (
        "computer science",
        "computing",
        "software",
        "information technology",
        "programming",
        "data science",
        "计算机",
        "软件",
        "编程",
        "信息技术",
    ),
    "programming": ("programming", "python", "java", "c++", "software", "编程", "程序"),
    "economics": ("economics", "economic", "econometrics", "finance", "business", "经济", "金融", "计量"),
}

PATHWAY_MARKERS = (
    "pathway",
    "graduate certificate",
    "graduate diploma",
    "pre-master",
    "premaster",
    "qualifying program",
    "bridging",
    "alternative entry",
)


@dataclass(frozen=True)
class EligibilityOutcome:
    decisions: list[EligibilityDecision]
    eligible_candidates: list[CourseCandidate]

    @property
    def eligible_decisions(self) -> list[EligibilityDecision]:
        return [decision for decision in self.decisions if decision.eligibility_status == EligibilityStatus.ELIGIBLE]

    @property
    def high_risk_decisions(self) -> list[EligibilityDecision]:
        return [
            decision
            for decision in self.decisions
            if decision.eligibility_status
            in {
                EligibilityStatus.HIGH_RISK,
                EligibilityStatus.UNKNOWN,
                EligibilityStatus.PATHWAY_REQUIRED,
            }
        ]

    @property
    def ineligible_decisions(self) -> list[EligibilityDecision]:
        return [decision for decision in self.decisions if decision.eligibility_status == EligibilityStatus.INELIGIBLE]

    @property
    def summary(self) -> EligibilitySummary:
        return EligibilitySummary(
            total_candidates=len(self.decisions),
            eligible_count=sum(
                decision.eligibility_status == EligibilityStatus.ELIGIBLE for decision in self.decisions
            ),
            high_risk_count=sum(
                decision.eligibility_status == EligibilityStatus.HIGH_RISK for decision in self.decisions
            ),
            ineligible_count=sum(
                decision.eligibility_status == EligibilityStatus.INELIGIBLE for decision in self.decisions
            ),
            unknown_count=sum(
                decision.eligibility_status == EligibilityStatus.UNKNOWN for decision in self.decisions
            ),
            pathway_required_count=sum(
                decision.eligibility_status == EligibilityStatus.PATHWAY_REQUIRED for decision in self.decisions
            ),
        )


@dataclass(frozen=True)
class _CheckEvaluation:
    check: RequirementCheck
    blocking: bool = False
    warning: bool = False
    unknown_blocking: bool = False
    pathway_required: bool = False
    missing_field: str | None = None


class EligibilityGate:
    def __init__(self) -> None:
        self.query_builder = QueryBuilder()

    def evaluate(
        self,
        *,
        user_profile: UserProfile,
        candidates: list[CourseCandidate],
        requirement_result: RequirementResult,
        request_id: str,
    ) -> EligibilityOutcome:
        del request_id
        decisions = [
            self._evaluate_one(
                user_profile=user_profile,
                candidate=candidate,
                requirement=requirement_result.requirements.get(candidate.course_id),
                raw_requirement=requirement_result.raw_requirements.get(candidate.course_id),
                requirement_error=requirement_result.errors.get(candidate.course_id),
            )
            for candidate in candidates
        ]
        eligible_ids = {
            decision.course_id
            for decision in decisions
            if decision.eligibility_status == EligibilityStatus.ELIGIBLE and decision.can_enter_next_layer
        }
        return EligibilityOutcome(
            decisions=decisions,
            eligible_candidates=[candidate for candidate in candidates if candidate.course_id in eligible_ids],
        )

    def _evaluate_one(
        self,
        *,
        user_profile: UserProfile,
        candidate: CourseCandidate,
        requirement: NormalizedRequirement | None,
        raw_requirement: RawAdmissionRequirement | None,
        requirement_error: str | None,
    ) -> EligibilityDecision:
        pathway_available, pathway_evidence = self._pathway_availability(candidate, raw_requirement)
        evaluations = [
            self._check_major_area(user_profile, candidate),
            self._check_degree_type(user_profile, candidate),
            self._check_faculty_school(user_profile, candidate, "faculty"),
            self._check_faculty_school(user_profile, candidate, "school"),
            self._check_gpa(user_profile, candidate, requirement, raw_requirement, pathway_available, pathway_evidence),
            self._check_ielts(user_profile, candidate, requirement, raw_requirement, requirement_error),
            self._check_prerequisites(user_profile, candidate, raw_requirement),
            self._check_intake(user_profile, candidate),
            self._check_deadline(candidate, raw_requirement),
            self._check_tuition(user_profile, candidate),
            self._check_duration(user_profile, candidate),
            self._check_preference_text(user_profile, candidate, "campus"),
            self._check_preference_text(user_profile, candidate, "study_mode"),
            self._check_pathway(user_profile, candidate, raw_requirement, pathway_available, pathway_evidence),
        ]
        blocking_reasons = [item.check.reason for item in evaluations if item.blocking]
        warnings = [item.check.reason for item in evaluations if item.warning or item.pathway_required]
        missing_fields = [
            item.missing_field
            for item in evaluations
            if item.missing_field is not None
        ]
        unknown_blocking_reasons = [item.check.reason for item in evaluations if item.unknown_blocking]

        if blocking_reasons:
            status = EligibilityStatus.INELIGIBLE
        elif any(item.pathway_required for item in evaluations):
            status = EligibilityStatus.PATHWAY_REQUIRED
        elif unknown_blocking_reasons:
            status = EligibilityStatus.UNKNOWN
        elif warnings:
            status = EligibilityStatus.HIGH_RISK
        else:
            status = EligibilityStatus.ELIGIBLE

        can_enter_next_layer = status == EligibilityStatus.ELIGIBLE
        summary = self._summary(status, blocking_reasons, warnings, unknown_blocking_reasons)
        return EligibilityDecision(
            course_id=candidate.course_id,
            course_name=candidate.course_name,
            cricos=candidate.cricos,
            eligibility_status=status,
            hard_filter_summary=summary,
            requirement_checks=[item.check for item in evaluations],
            blocking_reasons=blocking_reasons,
            warnings=warnings,
            missing_fields=missing_fields,
            can_enter_next_layer=can_enter_next_layer,
            reason=(blocking_reasons or warnings or unknown_blocking_reasons or [summary])[0],
            details=summary,
            degree_type=candidate.degree_type,
            faculty=candidate.faculty,
            school=candidate.school,
            tuition_fee_aud=candidate.tuition_fee_aud,
            duration=self._format_duration(candidate),
            duration_min_years=candidate.duration_min_years,
            duration_max_years=candidate.duration_max_years,
            campus=candidate.campus,
            study_mode=candidate.study_mode,
            intakes=candidate.intakes,
            source_url=candidate.source_url or (raw_requirement.source_url if raw_requirement else None),
            evidence_snippets=self._candidate_evidence(candidate, raw_requirement),
        )

    def _check_major_area(self, user_profile: UserProfile, candidate: CourseCandidate) -> _CheckEvaluation:
        query = self.query_builder.build(user_profile.target_major_keyword)
        haystack = self._candidate_text(candidate)
        matched_keywords = [keyword for keyword in query.keywords if keyword.casefold() in haystack]
        if matched_keywords:
            status: CheckStatus = "pass"
            reason = f"Target area matched candidate evidence via: {', '.join(matched_keywords)}."
        elif candidate.retrieval_reason:
            status = "warning"
            reason = "Candidate came from broad retrieval, but the target major was not explicit in course evidence."
        else:
            status = "unknown"
            reason = "Major area cannot be confirmed from course name or evidence."
        return _CheckEvaluation(
            self._check(
                "Major area",
                status,
                user_profile.target_major_keyword,
                candidate.course_name,
                reason,
                candidate,
                source_type="course",
            ),
            warning=status == "warning",
            unknown_blocking=status == "unknown",
            missing_field="major_area" if status == "unknown" else None,
        )

    def _check_degree_type(self, user_profile: UserProfile, candidate: CourseCandidate) -> _CheckEvaluation:
        preference = user_profile.degree_type_preference
        if not preference:
            status: CheckStatus = "pass" if candidate.degree_type else "unknown"
            reason = (
                "Degree type inferred from the course name."
                if candidate.degree_type
                else "Degree type is not structured; inferred value is unavailable."
            )
            return _CheckEvaluation(
                self._check("Degree type", status, None, candidate.degree_type, reason, candidate, source_type="course"),
                missing_field="degree_type" if status == "unknown" else None,
            )
        if not candidate.degree_type:
            return _CheckEvaluation(
                self._check(
                    "Degree type",
                    "unknown",
                    preference,
                    None,
                    "User set a degree type preference, but the course degree type is unavailable.",
                    candidate,
                    source_type="course",
                ),
                unknown_blocking=True,
                missing_field="degree_type",
            )
        matches = preference.casefold() in candidate.degree_type.casefold()
        return _CheckEvaluation(
            self._check(
                "Degree type",
                "pass" if matches else "fail",
                preference,
                candidate.degree_type,
                "Degree type matches the user's preference." if matches else "Degree type does not match preference.",
                candidate,
                source_type="course",
            ),
            blocking=not matches,
        )

    def _check_faculty_school(
        self,
        user_profile: UserProfile,
        candidate: CourseCandidate,
        field_name: str,
    ) -> _CheckEvaluation:
        preference = getattr(user_profile, f"{field_name}_preference")
        value = getattr(candidate, field_name)
        label = "Faculty" if field_name == "faculty" else "School"
        if not preference:
            status: CheckStatus = "pass" if value else "unknown"
            reason = (
                f"{label} is available for display."
                if value
                else f"{label} is not present in the current course data."
            )
            return _CheckEvaluation(
                self._check(label, status, None, value, reason, candidate, source_type="metadata"),
                missing_field=field_name if status == "unknown" else None,
            )
        if not value:
            return _CheckEvaluation(
                self._check(
                    label,
                    "unknown",
                    preference,
                    None,
                    f"User set a {field_name} preference, but the field is unavailable.",
                    candidate,
                    source_type="metadata",
                ),
                unknown_blocking=True,
                missing_field=field_name,
            )
        matches = preference.casefold() in value.casefold()
        return _CheckEvaluation(
            self._check(
                label,
                "pass" if matches else "fail",
                preference,
                value,
                f"{label} matches preference." if matches else f"{label} does not match preference.",
                candidate,
                source_type="metadata",
            ),
            blocking=not matches,
        )

    def _check_gpa(
        self,
        user_profile: UserProfile,
        candidate: CourseCandidate,
        requirement: NormalizedRequirement | None,
        raw_requirement: RawAdmissionRequirement | None,
        pathway_available: bool | None,
        pathway_evidence: str,
    ) -> _CheckEvaluation:
        required = requirement.gpa_min if requirement else None
        if required is None:
            return _CheckEvaluation(
                self._check(
                    "GPA / WAM",
                    "unknown",
                    user_profile.gpa_user,
                    None,
                    "Required GPA could not be normalized from the available requirement evidence.",
                    candidate,
                    raw_requirement=raw_requirement,
                    source_type="academic",
                ),
                unknown_blocking=True,
                missing_field="gpa_requirement",
            )
        if user_profile.gpa_user is None:
            return _CheckEvaluation(
                self._check(
                    "GPA / WAM",
                    "unknown",
                    None,
                    required,
                    "User GPA/WAM was not provided.",
                    candidate,
                    raw_requirement=raw_requirement,
                    source_type="profile",
                ),
                unknown_blocking=True,
                missing_field="user_gpa",
            )
        if user_profile.gpa_user >= required:
            return _CheckEvaluation(
                self._check(
                    "GPA / WAM",
                    "pass",
                    user_profile.gpa_user,
                    required,
                    "User GPA/WAM meets the normalized USYD threshold.",
                    candidate,
                    raw_requirement=raw_requirement,
                    source_type="academic",
                )
            )
        if user_profile.accepts_pathway and pathway_available is True:
            return _CheckEvaluation(
                self._check(
                    "GPA / WAM",
                    "warning",
                    user_profile.gpa_user,
                    required,
                    f"User GPA/WAM is below direct entry, but pathway evidence exists: {pathway_evidence}",
                    candidate,
                    raw_requirement=raw_requirement,
                    source_type="academic",
                ),
                pathway_required=True,
            )
        if user_profile.accepts_pathway and pathway_available is None:
            return _CheckEvaluation(
                self._check(
                    "GPA / WAM",
                    "unknown",
                    user_profile.gpa_user,
                    required,
                    "User GPA/WAM is below direct entry and pathway availability cannot be confirmed.",
                    candidate,
                    raw_requirement=raw_requirement,
                    source_type="academic",
                ),
                unknown_blocking=True,
                missing_field="pathway_availability",
            )
        return _CheckEvaluation(
            self._check(
                "GPA / WAM",
                "fail",
                user_profile.gpa_user,
                required,
                "User GPA/WAM is below the normalized USYD threshold.",
                candidate,
                raw_requirement=raw_requirement,
                source_type="academic",
            ),
            blocking=True,
        )

    def _check_ielts(
        self,
        user_profile: UserProfile,
        candidate: CourseCandidate,
        requirement: NormalizedRequirement | None,
        raw_requirement: RawAdmissionRequirement | None,
        requirement_error: str | None,
    ) -> _CheckEvaluation:
        required = self._resolve_ielts_requirement(candidate, requirement, raw_requirement)
        required_overall = required["overall"]
        required_min_band = required["min_band"]
        components = required["components"]
        raw_only = required["raw_only"]
        if required_overall is None or required_min_band is None:
            return _CheckEvaluation(
                self._check(
                    "IELTS",
                    "unknown",
                    self._format_user_ielts(user_profile),
                    None,
                    self._missing_ielts_reason(requirement_error, raw_requirement),
                    candidate,
                    raw_requirement=raw_requirement,
                    source_type="english",
                ),
                unknown_blocking=True,
                missing_field="ielts_requirement",
            )
        if user_profile.ielts_overall_user is None or user_profile.ielts_min_band_user is None:
            return _CheckEvaluation(
                self._check(
                    "IELTS",
                    "unknown",
                    self._format_user_ielts(user_profile),
                    self._format_required_ielts(required_overall, required_min_band, components),
                    "User IELTS overall or minimum band was not provided.",
                    candidate,
                    raw_requirement=raw_requirement,
                    source_type="profile",
                ),
                unknown_blocking=True,
                missing_field="user_ielts",
            )
        failures: list[str] = []
        unknowns: list[str] = []
        if user_profile.ielts_overall_user < required_overall:
            failures.append(f"overall {user_profile.ielts_overall_user:g} < {required_overall:g}")
        for component, required_score in components.items():
            user_score = self._user_component_score(user_profile, component)
            if user_score is None:
                unknowns.append(component)
            elif user_score < required_score:
                failures.append(f"{component} {user_score:g} < {required_score:g}")
        if failures:
            return _CheckEvaluation(
                self._check(
                    "IELTS",
                    "fail",
                    self._format_user_ielts(user_profile),
                    self._format_required_ielts(required_overall, required_min_band, components),
                    "IELTS does not meet requirement: " + "; ".join(failures) + ".",
                    candidate,
                    raw_requirement=raw_requirement,
                    source_type="english",
                ),
                blocking=True,
            )
        if unknowns:
            return _CheckEvaluation(
                self._check(
                    "IELTS",
                    "unknown",
                    self._format_user_ielts(user_profile),
                    self._format_required_ielts(required_overall, required_min_band, components),
                    "IELTS component scores are required but missing for: " + ", ".join(unknowns) + ".",
                    candidate,
                    raw_requirement=raw_requirement,
                    source_type="profile",
                ),
                unknown_blocking=True,
                missing_field="user_ielts_components",
            )
        reason = "User IELTS overall and component scores meet the requirement."
        if raw_only:
            reason += " Only raw English requirement was available; parsed values were used."
        return _CheckEvaluation(
            self._check(
                "IELTS",
                "pass",
                self._format_user_ielts(user_profile),
                self._format_required_ielts(required_overall, required_min_band, components),
                reason,
                candidate,
                raw_requirement=raw_requirement,
                source_type="english",
            )
        )

    def _check_prerequisites(
        self,
        user_profile: UserProfile,
        candidate: CourseCandidate,
        raw_requirement: RawAdmissionRequirement | None,
    ) -> _CheckEvaluation:
        text = self._academic_text(candidate, raw_requirement)
        if not text:
            return _CheckEvaluation(
                self._check(
                    "Prerequisites",
                    "unknown",
                    self._format_prior_study(user_profile),
                    None,
                    "Academic requirement text is unavailable, so prerequisites cannot be assessed.",
                    candidate,
                    raw_requirement=raw_requirement,
                    source_type="academic",
                ),
                unknown_blocking=True,
                missing_field="academic_requirement_text",
            )
        lowered = text.casefold()
        markers = [marker for marker in CRITICAL_PREREQ_MARKERS if marker in lowered]
        if not markers:
            return _CheckEvaluation(
                self._check(
                    "Prerequisites",
                    "pass",
                    self._format_prior_study(user_profile),
                    "No explicit prerequisite signal detected",
                    "No explicit prerequisite, assumed knowledge, or prior-study signal was detected in the evidence.",
                    candidate,
                    raw_requirement=raw_requirement,
                    source_type="academic",
                )
            )
        profile_text = self._profile_academic_text(user_profile)
        if not profile_text:
            return _CheckEvaluation(
                self._check(
                    "Prerequisites",
                    "unknown",
                    self._format_prior_study(user_profile),
                    ", ".join(markers),
                    "Prerequisite/background language exists, but prior major or completed courses were not provided.",
                    candidate,
                    raw_requirement=raw_requirement,
                    source_type="academic",
                ),
                unknown_blocking=True,
                missing_field="prior_major_or_courses",
            )
        required_subjects = self._required_subjects(lowered)
        if not required_subjects:
            if self._matches_relevant_discipline(user_profile, lowered):
                return _CheckEvaluation(
                    self._check(
                        "Prerequisites",
                        "pass",
                        self._format_prior_study(user_profile),
                        ", ".join(markers),
                        "User prior major/courses appear consistent with the stated relevant-discipline requirement.",
                        candidate,
                        raw_requirement=raw_requirement,
                        source_type="academic",
                    )
                )
            return _CheckEvaluation(
                self._check(
                    "Prerequisites",
                    "warning",
                    self._format_prior_study(user_profile),
                    ", ".join(markers),
                    "Relevant-discipline requirement exists and cannot be confidently matched; manual review required.",
                    candidate,
                    raw_requirement=raw_requirement,
                    source_type="academic",
                ),
                warning=True,
            )
        missing_subjects = [
            subject
            for subject in required_subjects
            if not self._subject_matches_profile(subject, profile_text)
        ]
        if missing_subjects:
            return _CheckEvaluation(
                self._check(
                    "Prerequisites",
                    "warning",
                    self._format_prior_study(user_profile),
                    ", ".join(required_subjects),
                    "Could not confirm prerequisite coverage for: " + ", ".join(missing_subjects) + ".",
                    candidate,
                    raw_requirement=raw_requirement,
                    source_type="academic",
                ),
                warning=True,
            )
        return _CheckEvaluation(
            self._check(
                "Prerequisites",
                "pass",
                self._format_prior_study(user_profile),
                ", ".join(required_subjects),
                "User prior major/completed courses match the prerequisite subject signals.",
                candidate,
                raw_requirement=raw_requirement,
                source_type="academic",
            )
        )

    def _check_intake(self, user_profile: UserProfile, candidate: CourseCandidate) -> _CheckEvaluation:
        if not user_profile.preferred_intake:
            return _CheckEvaluation(
                self._check(
                    "Intake",
                    "pass" if candidate.intakes else "unknown",
                    None,
                    ", ".join(candidate.intakes),
                    "No intake preference was set; available intakes are shown for review."
                    if candidate.intakes
                    else "Course intake data is unavailable.",
                    candidate,
                    source_type="intake",
                ),
                missing_field="intakes" if not candidate.intakes else None,
            )
        if not candidate.intakes:
            return _CheckEvaluation(
                self._check(
                    "Intake",
                    "unknown",
                    ", ".join(user_profile.preferred_intake),
                    None,
                    "User set a preferred intake, but course intake data is unavailable.",
                    candidate,
                    source_type="intake",
                ),
                unknown_blocking=True,
                missing_field="intakes",
            )
        overlap = sorted(set(user_profile.preferred_intake) & set(candidate.intakes))
        return _CheckEvaluation(
            self._check(
                "Intake",
                "pass" if overlap else "fail",
                ", ".join(user_profile.preferred_intake),
                ", ".join(candidate.intakes),
                "Preferred intake matches: " + ", ".join(overlap) + "."
                if overlap
                else "Preferred intake does not match the course intake list.",
                candidate,
                source_type="intake",
            ),
            blocking=not overlap,
        )

    def _check_deadline(
        self,
        candidate: CourseCandidate,
        raw_requirement: RawAdmissionRequirement | None,
    ) -> _CheckEvaluation:
        deadline_text = self._extract_deadline_text(candidate, raw_requirement)
        if deadline_text:
            return _CheckEvaluation(
                self._check(
                    "Application deadline",
                    "warning",
                    None,
                    deadline_text,
                    "Deadline evidence was found, but date comparison is not automated without application year.",
                    candidate,
                    raw_requirement=raw_requirement,
                    source_type="application",
                )
            )
        return _CheckEvaluation(
            self._check(
                "Application deadline",
                "unknown",
                None,
                None,
                "No application deadline was found in structured application details; manual review required.",
                candidate,
                raw_requirement=raw_requirement,
                source_type="application",
            ),
            missing_field="application_deadline",
        )

    def _check_tuition(self, user_profile: UserProfile, candidate: CourseCandidate) -> _CheckEvaluation:
        budget = user_profile.budget_range
        if budget.min is None and budget.max is None:
            return _CheckEvaluation(
                self._check(
                    "Tuition",
                    "pass" if candidate.tuition_fee_aud is not None else "unknown",
                    None,
                    candidate.tuition_fee_aud,
                    "No budget constraint was set; tuition is shown for review."
                    if candidate.tuition_fee_aud is not None
                    else "Tuition fee is unavailable.",
                    candidate,
                    source_type="course",
                ),
                missing_field="tuition_fee_aud" if candidate.tuition_fee_aud is None else None,
            )
        if candidate.tuition_fee_aud is None:
            return _CheckEvaluation(
                self._check(
                    "Tuition",
                    "unknown",
                    self._format_range(budget.min, budget.max),
                    None,
                    "User set a budget, but course tuition fee is unavailable.",
                    candidate,
                    source_type="course",
                ),
                unknown_blocking=True,
                missing_field="tuition_fee_aud",
            )
        fits = budget.contains_value(candidate.tuition_fee_aud)
        return _CheckEvaluation(
            self._check(
                "Tuition",
                "pass" if fits else "warning",
                self._format_range(budget.min, budget.max),
                candidate.tuition_fee_aud,
                "Tuition is within the user's budget range."
                if fits
                else "Tuition is outside the user's budget range; treat as high risk unless budget is flexible.",
                candidate,
                source_type="course",
            ),
            warning=not fits,
        )

    def _check_duration(self, user_profile: UserProfile, candidate: CourseCandidate) -> _CheckEvaluation:
        preference = user_profile.duration_preference
        if preference.min is None and preference.max is None:
            return _CheckEvaluation(
                self._check(
                    "Duration / study length",
                    "pass" if candidate.duration_min_years is not None or candidate.duration_max_years is not None else "unknown",
                    None,
                    self._format_duration(candidate),
                    "No duration preference was set; duration is shown for review."
                    if candidate.duration_min_years is not None or candidate.duration_max_years is not None
                    else "Course duration is unavailable.",
                    candidate,
                    source_type="course",
                ),
                missing_field="duration" if candidate.duration_min_years is None and candidate.duration_max_years is None else None,
            )
        if candidate.duration_min_years is None and candidate.duration_max_years is None:
            return _CheckEvaluation(
                self._check(
                    "Duration / study length",
                    "unknown",
                    self._format_range(preference.min, preference.max),
                    None,
                    "User set a duration preference, but course duration is unavailable.",
                    candidate,
                    source_type="course",
                ),
                unknown_blocking=True,
                missing_field="duration",
            )
        fits = preference.contains_interval(candidate.duration_min_years, candidate.duration_max_years)
        return _CheckEvaluation(
            self._check(
                "Duration / study length",
                "pass" if fits else "fail",
                self._format_range(preference.min, preference.max),
                self._format_duration(candidate),
                "Course duration matches the user's preference."
                if fits
                else "Course duration is outside the user's preferred range.",
                candidate,
                source_type="course",
            ),
            blocking=not fits,
        )

    def _check_preference_text(
        self,
        user_profile: UserProfile,
        candidate: CourseCandidate,
        field_name: str,
    ) -> _CheckEvaluation:
        preferences = getattr(user_profile, f"{field_name}_preference")
        value = getattr(candidate, field_name)
        label = "Campus" if field_name == "campus" else "Study mode"
        if not preferences:
            status: CheckStatus = "pass" if value else "unknown"
            return _CheckEvaluation(
                self._check(
                    label,
                    status,
                    None,
                    value,
                    f"No {field_name.replace('_', ' ')} preference was set; value is shown for review."
                    if value
                    else f"{label} is unavailable in current course data.",
                    candidate,
                    source_type="metadata",
                ),
                missing_field=field_name if status == "unknown" else None,
            )
        if not value:
            return _CheckEvaluation(
                self._check(
                    label,
                    "unknown",
                    ", ".join(preferences),
                    None,
                    f"User set a {field_name.replace('_', ' ')} preference, but the field is unavailable.",
                    candidate,
                    source_type="metadata",
                ),
                unknown_blocking=True,
                missing_field=field_name,
            )
        matches = any(preference.casefold() in value.casefold() for preference in preferences)
        return _CheckEvaluation(
            self._check(
                label,
                "pass" if matches else "fail",
                ", ".join(preferences),
                value,
                f"{label} matches preference." if matches else f"{label} does not match preference.",
                candidate,
                source_type="metadata",
            ),
            blocking=not matches,
        )

    def _check_pathway(
        self,
        user_profile: UserProfile,
        candidate: CourseCandidate,
        raw_requirement: RawAdmissionRequirement | None,
        pathway_available: bool | None,
        pathway_evidence: str,
    ) -> _CheckEvaluation:
        if pathway_available is True:
            return _CheckEvaluation(
                self._check(
                    "Pathway",
                    "pass" if user_profile.accepts_pathway else "warning",
                    user_profile.accepts_pathway,
                    pathway_evidence,
                    "Pathway evidence exists and the user accepts pathway."
                    if user_profile.accepts_pathway
                    else "Pathway evidence exists, but the user does not accept pathway.",
                    candidate,
                    raw_requirement=raw_requirement,
                    source_type="academic",
                )
            )
        if pathway_available is False:
            return _CheckEvaluation(
                self._check(
                    "Pathway",
                    "pass",
                    user_profile.accepts_pathway,
                    "No pathway signal detected",
                    "No explicit pathway signal was detected; direct-entry checks determine eligibility.",
                    candidate,
                    raw_requirement=raw_requirement,
                    source_type="academic",
                )
            )
        return _CheckEvaluation(
            self._check(
                "Pathway",
                "unknown",
                user_profile.accepts_pathway,
                None,
                "Pathway availability cannot be confirmed from current fields or evidence.",
                candidate,
                raw_requirement=raw_requirement,
                source_type="academic",
            ),
            missing_field="pathway_availability",
        )

    def _resolve_ielts_requirement(
        self,
        candidate: CourseCandidate,
        requirement: NormalizedRequirement | None,
        raw_requirement: RawAdmissionRequirement | None,
    ) -> dict[str, Any]:
        raw_text = raw_requirement.raw_english_requirement if raw_requirement else candidate.raw_english_requirement
        parsed = parse_english_requirement(raw_text)
        details = raw_requirement.english_req_details if raw_requirement else {}
        details_components = self._components_from_details(details)
        components = {
            "listening": self._first_present(
                raw_requirement.ielts_listening if raw_requirement else None,
                candidate.ielts_listening_required,
                details_components.get("listening"),
                parsed.get("ielts_listening"),
            ),
            "reading": self._first_present(
                raw_requirement.ielts_reading if raw_requirement else None,
                candidate.ielts_reading_required,
                details_components.get("reading"),
                parsed.get("ielts_reading"),
            ),
            "speaking": self._first_present(
                raw_requirement.ielts_speaking if raw_requirement else None,
                candidate.ielts_speaking_required,
                details_components.get("speaking"),
                parsed.get("ielts_speaking"),
            ),
            "writing": self._first_present(
                raw_requirement.ielts_writing if raw_requirement else None,
                candidate.ielts_writing_required,
                details_components.get("writing"),
                parsed.get("ielts_writing"),
            ),
        }
        components = {key: value for key, value in components.items() if value is not None}
        overall = self._first_present(
            requirement.ielts_overall_min if requirement else None,
            raw_requirement.ielts_overall if raw_requirement else None,
            candidate.ielts_overall_required,
            parsed.get("ielts_overall"),
        )
        min_band = self._first_present(
            requirement.ielts_min_band_min if requirement else None,
            raw_requirement.ielts_min_band if raw_requirement else None,
            candidate.ielts_min_band_required,
            parsed.get("ielts_min_band"),
        )
        if min_band is not None:
            for component in ["listening", "reading", "speaking", "writing"]:
                components.setdefault(component, min_band)
        raw_only = bool(raw_text) and not any(
            [
                raw_requirement and raw_requirement.ielts_overall is not None,
                raw_requirement and raw_requirement.ielts_min_band is not None,
                candidate.ielts_overall_required is not None,
                candidate.ielts_min_band_required is not None,
            ]
        )
        return {"overall": overall, "min_band": min_band, "components": components, "raw_only": raw_only}

    def _components_from_details(self, details: dict[str, Any]) -> dict[str, float]:
        raw_subscores = details.get("ielts_subscores")
        if not isinstance(raw_subscores, dict):
            return {}
        components: dict[str, float] = {}
        for key in ["listening", "reading", "speaking", "writing"]:
            value = raw_subscores.get(key)
            try:
                if value is not None:
                    components[key] = float(value)
            except (TypeError, ValueError):
                continue
        return components

    def _first_present(self, *values: Any) -> float | None:
        for value in values:
            if value is None:
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return None

    def _user_component_score(self, user_profile: UserProfile, component: str) -> float | None:
        explicit_value = getattr(user_profile, f"ielts_{component}_user")
        if explicit_value is not None:
            return explicit_value
        return user_profile.ielts_min_band_user

    def _pathway_availability(
        self,
        candidate: CourseCandidate,
        raw_requirement: RawAdmissionRequirement | None,
    ) -> tuple[bool | None, str]:
        text = self._academic_text(candidate, raw_requirement)
        lowered = text.casefold()
        for marker in PATHWAY_MARKERS:
            if marker in lowered:
                return True, self._extract_sentence(text, marker)
        academic_json = raw_requirement.academic_requirements_json if raw_requirement else candidate.academic_requirements_json
        pathways = academic_json.get("pathways") if isinstance(academic_json, dict) else None
        if isinstance(pathways, list):
            for pathway in pathways:
                if not isinstance(pathway, dict):
                    continue
                summary = str(pathway.get("summary", ""))
                if any(marker in summary.casefold() for marker in PATHWAY_MARKERS):
                    return True, self._trim(summary)
        if text:
            return False, "No explicit pathway evidence found."
        return None, ""

    def _required_subjects(self, lowered_requirement_text: str) -> list[str]:
        return [
            subject
            for subject, aliases in SUBJECT_ALIASES.items()
            if any(alias.casefold() in lowered_requirement_text for alias in aliases)
        ]

    def _subject_matches_profile(self, subject: str, profile_text: str) -> bool:
        aliases = SUBJECT_ALIASES.get(subject, (subject,))
        lowered = profile_text.casefold()
        return any(alias.casefold() in lowered for alias in aliases)

    def _matches_relevant_discipline(self, user_profile: UserProfile, requirement_text: str) -> bool:
        target_query = self.query_builder.build(user_profile.target_major_keyword)
        profile_text = self._profile_academic_text(user_profile)
        if any(keyword.casefold() in profile_text for keyword in target_query.keywords):
            return True
        return any(subject in requirement_text for subject in self._required_subjects(profile_text))

    def _profile_academic_text(self, user_profile: UserProfile) -> str:
        return " ".join([user_profile.prior_major or "", *user_profile.completed_courses]).casefold()

    def _format_prior_study(self, user_profile: UserProfile) -> str:
        parts = []
        if user_profile.prior_major:
            parts.append(user_profile.prior_major)
        if user_profile.completed_courses:
            parts.append(", ".join(user_profile.completed_courses))
        return " | ".join(parts)

    def _academic_text(
        self,
        candidate: CourseCandidate,
        raw_requirement: RawAdmissionRequirement | None,
    ) -> str:
        chunks = [candidate.academic_requirement_text]
        if raw_requirement:
            chunks.append(raw_requirement.academic_requirement_text)
            chunks.append(self._json_text(raw_requirement.academic_requirements_json))
        chunks.append(self._json_text(candidate.academic_requirements_json))
        return " ".join(chunk for chunk in chunks if chunk).strip()

    def _candidate_text(self, candidate: CourseCandidate) -> str:
        values = [
            candidate.course_name,
            candidate.academic_requirement_text,
            candidate.raw_english_requirement,
            candidate.retrieval_reason,
            self._json_text(candidate.academic_requirements_json),
            " ".join(snippet.text for snippet in candidate.evidence_snippets),
        ]
        return " ".join(values).casefold()

    def _json_text(self, value: Any) -> str:
        if not value:
            return ""
        try:
            return json.dumps(value, ensure_ascii=False)
        except TypeError:
            return str(value)

    def _extract_deadline_text(
        self,
        candidate: CourseCandidate,
        raw_requirement: RawAdmissionRequirement | None,
    ) -> str:
        details = raw_requirement.application_details_json if raw_requirement else candidate.application_details_json
        if isinstance(details, dict):
            for key in ["deadline", "application_deadline", "closing_date", "close_date"]:
                value = details.get(key)
                if value:
                    return self._trim(str(value))
            raw_text = str(details.get("raw_text", ""))
            for note in details.get("selection_notes", []):
                raw_text += " " + str(note)
            extracted = self._extract_deadline_from_text(raw_text)
            if extracted:
                return extracted
        extracted = self._extract_deadline_from_text(self._candidate_text(candidate))
        return extracted

    def _extract_deadline_from_text(self, text: str) -> str:
        if not text:
            return ""
        patterns = [
            r"[^.]{0,80}(?:deadline|closing date|applications close|apply by)[^.]{0,100}",
            r"[^.]{0,80}(?:rolling basis)[^.]{0,80}",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return self._trim(match.group(0))
        return ""

    def _candidate_evidence(
        self,
        candidate: CourseCandidate,
        raw_requirement: RawAdmissionRequirement | None,
    ) -> list[EvidenceSnippet]:
        if candidate.evidence_snippets:
            return candidate.evidence_snippets
        text = self._academic_text(candidate, raw_requirement) or candidate.raw_english_requirement
        if not text:
            return []
        return [
            EvidenceSnippet(
                text=self._trim(text),
                source_url=candidate.source_url or (raw_requirement.source_url if raw_requirement else None),
                source="eligibility",
            )
        ]

    def _check(
        self,
        name: str,
        status: CheckStatus,
        user_value: Any,
        required_value: Any,
        reason: str,
        candidate: CourseCandidate,
        *,
        raw_requirement: RawAdmissionRequirement | None = None,
        source_type: str | None = None,
    ) -> RequirementCheck:
        return RequirementCheck(
            name=name,
            status=status,
            user_value=user_value,
            required_value=required_value,
            reason=reason,
            evidence_snippets=self._candidate_evidence(candidate, raw_requirement),
            source_url=candidate.source_url or (raw_requirement.source_url if raw_requirement else None),
            source_type=source_type,
        )

    def _missing_ielts_reason(
        self,
        requirement_error: str | None,
        raw_requirement: RawAdmissionRequirement | None,
    ) -> str:
        if requirement_error:
            return f"IELTS requirement could not be normalized: {requirement_error}."
        if raw_requirement and raw_requirement.raw_english_requirement:
            return "Only raw English requirement is available and it could not be parsed into IELTS thresholds."
        return "IELTS requirement is missing from current admission data."

    def _format_user_ielts(self, user_profile: UserProfile) -> str:
        if user_profile.ielts_overall_user is None and user_profile.ielts_min_band_user is None:
            return ""
        parts = [
            f"{user_profile.ielts_overall_user:g} overall" if user_profile.ielts_overall_user is not None else "",
            f"{user_profile.ielts_min_band_user:g} min band" if user_profile.ielts_min_band_user is not None else "",
        ]
        component_parts = []
        for key, label in [
            ("ielts_listening_user", "L"),
            ("ielts_reading_user", "R"),
            ("ielts_speaking_user", "S"),
            ("ielts_writing_user", "W"),
        ]:
            value = getattr(user_profile, key)
            if value is not None:
                component_parts.append(f"{label} {value:g}")
        if component_parts:
            parts.append(", ".join(component_parts))
        return ", ".join(part for part in parts if part)

    def _format_required_ielts(
        self,
        overall: float,
        min_band: float,
        components: dict[str, float],
    ) -> str:
        component_text = ", ".join(f"{key} {value:g}" for key, value in components.items())
        base = f"{overall:g} overall, {min_band:g} min band"
        return f"{base}, {component_text}" if component_text else base

    def _format_duration(self, candidate: CourseCandidate) -> str:
        if candidate.duration_min_years is None and candidate.duration_max_years is None:
            return ""
        if candidate.duration_min_years == candidate.duration_max_years:
            return f"{candidate.duration_min_years:g} years"
        return f"{candidate.duration_min_years:g}-{candidate.duration_max_years:g} years"

    def _format_range(self, lower: float | None, upper: float | None) -> str:
        if lower is None and upper is None:
            return ""
        if lower is None:
            return f"<= {upper:g}"
        if upper is None:
            return f">= {lower:g}"
        return f"{lower:g}-{upper:g}"

    def _extract_sentence(self, text: str, marker: str) -> str:
        match = re.search(rf"[^.]*{re.escape(marker)}[^.]*\.?", text, re.IGNORECASE)
        if not match:
            return marker
        return self._trim(match.group(0))

    def _trim(self, text: str, limit: int = 240) -> str:
        cleaned = " ".join(str(text or "").split())
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[: limit - 1].rstrip() + "..."

    def _summary(
        self,
        status: EligibilityStatus,
        blocking_reasons: list[str],
        warnings: list[str],
        unknown_reasons: list[str],
    ) -> str:
        if status == EligibilityStatus.ELIGIBLE:
            return "Meets hard requirements checked by GPA/WAM, IELTS, intake, budget, duration and available evidence."
        if status == EligibilityStatus.INELIGIBLE:
            return "Does not meet hard application requirements: " + " ".join(blocking_reasons)
        if status == EligibilityStatus.PATHWAY_REQUIRED:
            return "Direct entry is not met; pathway is required before this program should be considered."
        if status == EligibilityStatus.UNKNOWN:
            return "Insufficient information for hard filter; manual review required: " + " ".join(unknown_reasons)
        return "High-risk candidate; manual review required before final recommendation: " + " ".join(warnings)
