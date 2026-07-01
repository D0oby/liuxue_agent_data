from __future__ import annotations

import logging

from src.config import RecommendationConfig
from src.models.recommendation import (
    EvidenceSnippet,
    ExcludedProgram,
    RecommendationPlan,
    RecommendedProgram,
    ScoredCourseCandidate,
    UserProfile,
)


logger = logging.getLogger(__name__)


class PlanAssembler:
    def __init__(self, config: RecommendationConfig) -> None:
        self.config = config

    def assemble(
        self,
        *,
        user_profile: UserProfile,
        scored_candidates: list[ScoredCourseCandidate],
        excluded_programs: list[ExcludedProgram],
        request_id: str,
    ) -> RecommendationPlan:
        eligible: list[ScoredCourseCandidate] = []
        exclusions = list(excluded_programs)

        for candidate in scored_candidates:
            reason = self._exclusion_reason(user_profile, candidate)
            if reason:
                logger.warning(
                    "course excluded from recommendation plan",
                    extra={"request_id": request_id, "course_id": candidate.course_id, "reason": reason},
                )
                exclusions.append(self._to_excluded_program(candidate, reason))
                continue
            eligible.append(candidate)

        reach = self._build_band(eligible, user_profile=user_profile, band="REACH")
        match = self._build_band(eligible, user_profile=user_profile, band="MATCH")
        safety = self._build_band(eligible, user_profile=user_profile, band="SAFETY")
        return RecommendationPlan(
            reach_programs=reach,
            match_programs=match,
            safety_programs=safety,
            excluded_programs=exclusions,
        )

    def _exclusion_reason(
        self,
        user_profile: UserProfile,
        candidate: ScoredCourseCandidate,
    ) -> str | None:
        if candidate.combined_retrieval_score < self.config.retrieval.min_retrieval_score:
            return "low_retrieval_relevance"
        if (
            self.config.rules.enable_ielts_band_gate
            and user_profile.ielts_min_band_user is not None
            and candidate.ielts_min_band_min is not None
            and user_profile.ielts_min_band_user < candidate.ielts_min_band_min
        ):
            return "ielts_band_below_requirement"
        if not user_profile.duration_preference.contains_interval(
            candidate.duration_min_years,
            candidate.duration_max_years,
        ):
            return "duration_mismatch"
        if not user_profile.budget_range.contains_value(candidate.tuition_fee_aud):
            return "budget_mismatch"
        return None

    def _build_band(
        self,
        candidates: list[ScoredCourseCandidate],
        *,
        user_profile: UserProfile,
        band: str,
    ) -> list[RecommendedProgram]:
        band_candidates = [candidate for candidate in candidates if candidate.match_band == band]
        sorted_candidates = sorted(
            band_candidates,
            key=lambda candidate: self._sort_key(user_profile, candidate),
        )
        return [
            self._to_recommended_program(user_profile, candidate)
            for candidate in sorted_candidates[: self.config.output.max_programs_per_band]
        ]

    def _sort_key(
        self,
        user_profile: UserProfile,
        candidate: ScoredCourseCandidate,
    ) -> tuple[float, float, float, int, int, int]:
        if candidate.match_band == "REACH":
            score_distance = abs(candidate.final_score - self.config.band.reach_upper)
        elif candidate.match_band == "MATCH":
            target = (self.config.band.reach_upper + self.config.band.match_upper) / 2
            score_distance = abs(candidate.final_score - target)
        else:
            score_distance = abs(candidate.final_score - self.config.band.match_upper)
        ielts_margin = user_profile.ielts_overall_user - candidate.ielts_overall_min
        duration_fit = int(
            user_profile.duration_preference.contains_interval(
                candidate.duration_min_years,
                candidate.duration_max_years,
            )
        )
        budget_fit = int(user_profile.budget_range.contains_value(candidate.tuition_fee_aud))
        intake_fit = int(
            not user_profile.preferred_intake
            or bool(set(user_profile.preferred_intake) & set(candidate.intakes))
        )
        return (
            score_distance,
            -candidate.combined_retrieval_score,
            -ielts_margin,
            -budget_fit,
            -duration_fit,
            -intake_fit,
        )

    def _to_recommended_program(
        self,
        user_profile: UserProfile,
        candidate: ScoredCourseCandidate,
    ) -> RecommendedProgram:
        evidence = self._ensure_evidence(candidate)
        source_url = candidate.source_url or candidate.requirement_source_url or ""
        return RecommendedProgram(
            course_id=candidate.course_id,
            course_name=candidate.course_name,
            cricos=candidate.cricos,
            duration=self._format_duration(candidate),
            intakes=candidate.intakes,
            tuition_fee_aud=candidate.tuition_fee_aud,
            ielts_requirement=(
                f"IELTS {candidate.ielts_overall_min:g} overall, "
                f"minimum band {candidate.ielts_min_band_min:g}"
            ),
            academic_requirement_summary=candidate.requirement_summary,
            gpa_calculation_method=candidate.gpa_calculation_method,
            score=round(candidate.final_score, 4),
            band=candidate.match_band,
            recommendation_reason=self._build_recommendation_reason(user_profile, candidate, evidence, source_url),
            evidence_snippets=evidence,
            source_url=source_url,
        )

    def _to_excluded_program(
        self,
        candidate: ScoredCourseCandidate,
        reason: str,
    ) -> ExcludedProgram:
        details = {
            "ielts_band_below_requirement": (
                f"IELTS minimum band is below requirement {candidate.ielts_min_band_min:g}."
            ),
            "duration_mismatch": "Course duration is outside the preferred duration range.",
            "budget_mismatch": "Course tuition fee is outside the preferred budget range.",
            "low_retrieval_relevance": "Retrieval relevance is below the configured minimum score.",
        }.get(reason, "Course did not pass recommendation filters.")
        return ExcludedProgram(
            course_id=candidate.course_id,
            course_name=candidate.course_name,
            reason=reason,
            details=details,
            source_url=candidate.source_url or candidate.requirement_source_url or "",
            evidence_snippets=self._ensure_evidence(candidate),
        )

    def _build_recommendation_reason(
        self,
        user_profile: UserProfile,
        candidate: ScoredCourseCandidate,
        evidence: list[EvidenceSnippet],
        source_url: str | None,
    ) -> str:
        evidence_text = evidence[0].text if evidence else candidate.requirement_summary
        source_text = source_url or "source URL unavailable"
        return (
            f"GPA: user {user_profile.gpa_user:g} using {self._format_gpa_method(candidate.gpa_calculation_method)} "
            f"vs required {candidate.gpa_min:g}. "
            f"IELTS: user {user_profile.ielts_overall_user:g}/{user_profile.ielts_min_band_user:g} "
            f"vs required {candidate.ielts_overall_min:g}/{candidate.ielts_min_band_min:g}. "
            f"Relevance: {candidate.retrieval_reason}. "
            f"Evidence: {evidence_text}. Source: {source_text}."
        )

    def _ensure_evidence(self, candidate: ScoredCourseCandidate) -> list[EvidenceSnippet]:
        if candidate.evidence_snippets:
            return candidate.evidence_snippets
        return [
            EvidenceSnippet(
                text=candidate.requirement_summary,
                source_url=candidate.source_url or candidate.requirement_source_url or "",
                source="requirement_summary",
            )
        ]

    def _format_duration(self, candidate: ScoredCourseCandidate) -> str:
        if candidate.duration_min_years is None and candidate.duration_max_years is None:
            return ""
        if candidate.duration_min_years == candidate.duration_max_years:
            return f"{candidate.duration_min_years:g} years"
        return f"{candidate.duration_min_years:g}-{candidate.duration_max_years:g} years"

    def _format_gpa_method(self, method: str) -> str:
        labels = {
            "usyd_arithmetic_average_all_courses": "USYD arithmetic average across all courses",
        }
        return labels.get(method, method)
