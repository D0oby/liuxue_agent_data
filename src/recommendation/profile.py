from __future__ import annotations

from src.models.recommendation import RecommendationRequest, UserProfile


INTAKE_ALIASES = {
    "JAN": "JAN",
    "JANUARY": "JAN",
    "FEB": "FEB",
    "FEBRUARY": "FEB",
    "MAR": "MAR",
    "MARCH": "MAR",
    "JUL": "JUL",
    "JULY": "JUL",
    "AUG": "AUG",
    "AUGUST": "AUG",
    "OCT": "OCT",
    "OCTOBER": "OCT",
    "S1": "FEB",
    "SEM1": "FEB",
    "SEMESTER 1": "FEB",
    "S2": "JUL",
    "SEM2": "JUL",
    "SEMESTER 2": "JUL",
}


class UserProfileParser:
    def parse(self, request: RecommendationRequest) -> UserProfile:
        return UserProfile(
            target_major_keyword=request.target_major_keyword,
            gpa_user=self._normalize_gpa(request.gpa_user, request.gpa_scale),
            gpa_scale=100,
            ielts_overall_user=request.ielts_overall_user,
            ielts_min_band_user=request.ielts_min_band_user,
            ielts_listening_user=request.ielts_listening_user,
            ielts_reading_user=request.ielts_reading_user,
            ielts_speaking_user=request.ielts_speaking_user,
            ielts_writing_user=request.ielts_writing_user,
            academic_background=request.academic_background,
            prior_major=request.prior_major,
            completed_courses=request.completed_courses,
            preferred_intake=self._normalize_intakes(request.preferred_intake),
            budget_range=request.budget_range,
            duration_preference=request.duration_preference,
            campus_preference=self._normalize_optional_list(request.campus_preference),
            study_mode_preference=self._normalize_optional_list(request.study_mode_preference),
            degree_type_preference=request.degree_type_preference,
            faculty_preference=request.faculty_preference,
            school_preference=request.school_preference,
            accepts_pathway=request.accepts_pathway,
        )

    def _normalize_gpa(self, gpa_user: float | None, gpa_scale: float) -> float | None:
        if gpa_user is None:
            return None
        if gpa_scale == 100:
            return gpa_user
        return round((gpa_user / gpa_scale) * 100, 4)

    def _normalize_intakes(self, value: str | list[str]) -> list[str]:
        raw_values = [value] if isinstance(value, str) else value
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in raw_values:
            for chunk in str(raw).replace("/", ",").split(","):
                label = " ".join(chunk.split()).strip().upper()
                if not label:
                    continue
                intake = INTAKE_ALIASES.get(label, label)
                if intake not in seen:
                    seen.add(intake)
                    normalized.append(intake)
        return normalized

    def _normalize_optional_list(self, value: str | list[str] | None) -> list[str]:
        if value is None:
            return []
        raw_values = [value] if isinstance(value, str) else value
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in raw_values:
            for chunk in str(raw).replace("/", ",").split(","):
                label = " ".join(chunk.split()).strip()
                key = label.casefold()
                if label and key not in seen:
                    seen.add(key)
                    normalized.append(label)
        return normalized
