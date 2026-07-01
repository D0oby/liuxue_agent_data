from __future__ import annotations

from dataclasses import dataclass
import logging

from src.config import RecommendationConfig
from src.models.recommendation import (
    CourseCandidate,
    ExcludedProgram,
    MatchBand,
    NormalizedRequirement,
    ScoredCourseCandidate,
    ScoreResult,
    UserProfile,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScoringOutcome:
    scored_candidates: list[ScoredCourseCandidate]
    excluded_programs: list[ExcludedProgram]


class ScoreCalculator:
    def __init__(self, config: RecommendationConfig) -> None:
        self.config = config

    def calculate(
        self,
        *,
        user_profile: UserProfile,
        requirement: NormalizedRequirement,
    ) -> tuple[float, float, float]:
        if user_profile.gpa_user is None:
            raise ValueError("user_profile.gpa_user is required for scoring.")
        if user_profile.ielts_overall_user is None:
            raise ValueError("user_profile.ielts_overall_user is required for scoring.")
        if requirement.gpa_min is None or requirement.gpa_min <= 0:
            raise ValueError("gpa_min must be greater than zero.")
        if requirement.ielts_overall_min is None or requirement.ielts_overall_min <= 0:
            raise ValueError("ielts_overall_min must be greater than zero.")
        gpa_component = user_profile.gpa_user / requirement.gpa_min
        ielts_component = user_profile.ielts_overall_user / requirement.ielts_overall_min
        final_score = (
            self.config.scoring.gpa_weight * gpa_component
            + self.config.scoring.ielts_weight * ielts_component
        )
        return gpa_component, ielts_component, final_score


class BandClassifier:
    def __init__(self, config: RecommendationConfig) -> None:
        self.config = config

    def classify(self, score: float) -> MatchBand:
        if score < self.config.band.reach_upper:
            return "REACH"
        if score <= self.config.band.match_upper:
            return "MATCH"
        return "SAFETY"


class ScoringService:
    def __init__(
        self,
        *,
        score_calculator: ScoreCalculator,
        band_classifier: BandClassifier,
    ) -> None:
        self.score_calculator = score_calculator
        self.band_classifier = band_classifier

    def score_candidates(
        self,
        *,
        user_profile: UserProfile,
        candidates: list[CourseCandidate],
        requirements: dict[str, NormalizedRequirement],
        requirement_errors: dict[str, str],
        request_id: str,
    ) -> ScoringOutcome:
        scored_candidates: list[ScoredCourseCandidate] = []
        excluded_programs: list[ExcludedProgram] = []

        for candidate in candidates:
            requirement = requirements.get(candidate.course_id)
            if requirement is None:
                reason = requirement_errors.get(candidate.course_id, "missing_requirement")
                excluded_programs.append(
                    ExcludedProgram(
                        course_id=candidate.course_id,
                        course_name=candidate.course_name,
                        reason=reason,
                        details=self._exclusion_details(reason),
                        source_url=candidate.source_url,
                        evidence_snippets=candidate.evidence_snippets,
                    )
                )
                continue

            try:
                scored_candidates.append(
                    self._score_one(
                        user_profile=user_profile,
                        candidate=candidate,
                        requirement=requirement,
                    )
                )
            except Exception:
                logger.warning(
                    "course scoring failed",
                    extra={"request_id": request_id, "course_id": candidate.course_id},
                    exc_info=True,
                )
                excluded_programs.append(
                    ExcludedProgram(
                        course_id=candidate.course_id,
                        course_name=candidate.course_name,
                        reason="scoring_failed",
                        details="This course could not be scored with the available normalized requirements.",
                        source_url=candidate.source_url or requirement.requirement_source_url,
                        evidence_snippets=candidate.evidence_snippets,
                    )
                )

        return ScoringOutcome(scored_candidates=scored_candidates, excluded_programs=excluded_programs)

    def _score_one(
        self,
        *,
        user_profile: UserProfile,
        candidate: CourseCandidate,
        requirement: NormalizedRequirement,
    ) -> ScoredCourseCandidate:
        gpa_component, ielts_component, final_score = self.score_calculator.calculate(
            user_profile=user_profile,
            requirement=requirement,
        )
        match_band = self.band_classifier.classify(final_score)
        score_result = ScoreResult(
            course_id=candidate.course_id,
            gpa_score_component=gpa_component,
            ielts_score_component=ielts_component,
            final_score=final_score,
            match_band=match_band,
            reason_tags=self._reason_tags(user_profile, requirement),
        )
        return ScoredCourseCandidate(
            **candidate.model_dump(),
            gpa_min=requirement.gpa_min,
            gpa_calculation_method=requirement.gpa_calculation_method,
            ielts_overall_min=requirement.ielts_overall_min,
            ielts_min_band_min=requirement.ielts_min_band_min,
            requirement_summary=requirement.requirement_summary,
            requirement_source_url=requirement.requirement_source_url,
            gpa_score_component=score_result.gpa_score_component,
            ielts_score_component=score_result.ielts_score_component,
            final_score=score_result.final_score,
            match_band=score_result.match_band,
            reason_tags=score_result.reason_tags,
            recommendation_reason=self._recommendation_reason(user_profile, requirement, score_result),
        )

    def _reason_tags(
        self,
        user_profile: UserProfile,
        requirement: NormalizedRequirement,
    ) -> list[str]:
        tags: list[str] = []
        if (
            user_profile.gpa_user is None
            or user_profile.ielts_overall_user is None
            or user_profile.ielts_min_band_user is None
            or requirement.gpa_min is None
            or requirement.ielts_overall_min is None
            or requirement.ielts_min_band_min is None
        ):
            return ["missing_scoring_input"]
        tags.append("gpa_meets_requirement" if user_profile.gpa_user >= requirement.gpa_min else "gpa_below_requirement")
        tags.append(
            "ielts_overall_meets_requirement"
            if user_profile.ielts_overall_user >= requirement.ielts_overall_min
            else "ielts_overall_below_requirement"
        )
        tags.append(
            "ielts_band_meets_requirement"
            if user_profile.ielts_min_band_user >= requirement.ielts_min_band_min
            else "ielts_band_below_requirement"
        )
        return tags

    def _recommendation_reason(
        self,
        user_profile: UserProfile,
        requirement: NormalizedRequirement,
        score_result: ScoreResult,
    ) -> str:
        return (
            f"GPA {user_profile.gpa_user:g} vs required {requirement.gpa_min:g}; "
            f"IELTS {user_profile.ielts_overall_user:g}/{user_profile.ielts_min_band_user:g} "
            f"vs required {requirement.ielts_overall_min:g}/{requirement.ielts_min_band_min:g}; "
            f"score {score_result.final_score:.3f} places it in {score_result.match_band}."
        )

    def _exclusion_details(self, reason: str) -> str:
        if reason == "missing_ielts_requirement":
            return "IELTS requirement is missing or could not be parsed from the current admission record."
        if reason == "missing_requirement":
            return "Current admission requirement is missing for this course."
        return "This course could not be scored because a required input was unavailable."
