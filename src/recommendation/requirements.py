from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from src.models.recommendation import NormalizedRequirement, RawAdmissionRequirement
from src.recommendation.repository import RecommendationRepository
from src.transform.parse_english_requirement import parse_english_requirement


logger = logging.getLogger(__name__)

USYD_DOMESTIC_GPA_METHOD = "悉尼大学国内院校口径：所有科目的算术平均分"
USYD_DOMESTIC_GPA_METHOD_CODE = "usyd_arithmetic_average_all_courses"

BUSINESS_CORE_PATTERNS = (
    "master of commerce",
    "professional accounting",
    "professional accounting and business performance",
)
ENGINEERING_COMPUTING_PATTERNS = (
    "professional engineering",
    "master of engineering",
    "information technology",
    "it management",
    "computer science",
    "data science",
)
REFERENCE_75_80_PATTERNS = (
    "architecture",
    "architectural science",
    "urban regional planning",
    "urbanism",
    "economics",
    "juris doctor",
    "jd",
    "pharmacy",
)


class RequirementNormalizationError(ValueError):
    pass


class MissingIeltsRequirementError(RequirementNormalizationError):
    pass


@dataclass(frozen=True)
class RequirementResult:
    requirements: dict[str, NormalizedRequirement]
    errors: dict[str, str]
    raw_requirements: dict[str, RawAdmissionRequirement]


class RequirementNormalizer:
    def normalize(
        self,
        requirement: RawAdmissionRequirement,
        *,
        academic_background: str,
        course_name: str = "",
    ) -> NormalizedRequirement:
        ielts_values = self._resolve_ielts_values(requirement)
        gpa_min = self.resolve_gpa_min(academic_background, course_name=course_name)
        return NormalizedRequirement(
            course_id=requirement.course_id,
            gpa_min=gpa_min,
            gpa_calculation_method=USYD_DOMESTIC_GPA_METHOD_CODE,
            ielts_overall_min=ielts_values["overall"],
            ielts_min_band_min=ielts_values["min_band"],
            requirement_summary=self._build_summary(requirement, ielts_values, gpa_min),
            requirement_source_url=requirement.source_url,
        )

    def resolve_gpa_min(self, academic_background: str, *, course_name: str = "") -> float:
        background_category = self._resolve_domestic_background_category(academic_background)
        normalized_course_name = course_name.casefold()

        if self._matches_any(normalized_course_name, BUSINESS_CORE_PATTERNS):
            return {
                "c9": 65.0,
                "tier1": 65.0,
                "985": 75.0,
                "211": 75.0,
                "non_211": 87.0,
            }[background_category]

        if self._matches_any(normalized_course_name, ENGINEERING_COMPUTING_PATTERNS):
            return 80.0 if background_category == "non_211" else 75.0

        if self._matches_any(normalized_course_name, REFERENCE_75_80_PATTERNS):
            return 80.0 if background_category == "non_211" else 75.0

        return 80.0 if background_category == "non_211" else 75.0

    def _resolve_domestic_background_category(self, academic_background: str) -> str:
        lowered = academic_background.casefold()
        if "双非" in academic_background or "非211" in academic_background:
            return "non_211"
        if "non-211" in lowered or "non 211" in lowered or "double non" in lowered:
            return "non_211"
        if "c9" in lowered:
            return "c9"
        if "tier1" in lowered or "tier 1" in lowered or "tier-1" in lowered:
            return "tier1"
        if "985" in lowered:
            return "985"
        if "211" in lowered:
            return "211"
        return "non_211"

    def _matches_any(self, normalized_course_name: str, patterns: tuple[str, ...]) -> bool:
        return any(pattern in normalized_course_name for pattern in patterns)

    def _resolve_ielts_values(self, requirement: RawAdmissionRequirement) -> dict[str, float | None]:
        parsed = parse_english_requirement(requirement.raw_english_requirement)
        overall = requirement.ielts_overall if requirement.ielts_overall is not None else parsed.get("ielts_overall")
        band_values = [
            requirement.ielts_min_band,
            requirement.ielts_listening,
            requirement.ielts_reading,
            requirement.ielts_speaking,
            requirement.ielts_writing,
            *self._subscores_from_details(requirement.english_req_details),
            parsed.get("ielts_min_band"),
            parsed.get("ielts_listening"),
            parsed.get("ielts_reading"),
            parsed.get("ielts_speaking"),
            parsed.get("ielts_writing"),
        ]
        min_band = self._max_present(band_values)

        return {"overall": overall, "min_band": min_band}

    def _subscores_from_details(self, details: dict[str, Any]) -> list[float | None]:
        raw_subscores = details.get("ielts_subscores")
        if not isinstance(raw_subscores, dict):
            return []
        values: list[float | None] = []
        for key in ["listening", "reading", "speaking", "writing"]:
            value = raw_subscores.get(key)
            try:
                values.append(float(value) if value is not None else None)
            except (TypeError, ValueError):
                values.append(None)
        return values

    def _max_present(self, values: list[float | None]) -> float | None:
        present = [float(value) for value in values if value is not None]
        if not present:
            return None
        return max(present)

    def _build_summary(
        self,
        requirement: RawAdmissionRequirement,
        ielts_values: dict[str, float | None],
        gpa_min: float,
    ) -> str:
        academic_text = " ".join(requirement.academic_requirement_text.split()).strip()
        if len(academic_text) > 220:
            academic_text = academic_text[:219].rstrip() + "..."
        gpa_text = f"{USYD_DOMESTIC_GPA_METHOD}，最低均分 {gpa_min:g}%。"
        language = f"IELTS {ielts_values['overall']} overall, minimum band {ielts_values['min_band']}."
        if ielts_values["overall"] is None or ielts_values["min_band"] is None:
            language = "IELTS requirement unavailable in structured or parseable evidence."
        if academic_text:
            return f"{academic_text} {gpa_text} {language}"
        return f"{gpa_text} {language}"


class RequirementService:
    def __init__(
        self,
        *,
        repository: RecommendationRepository,
        normalizer: RequirementNormalizer,
    ) -> None:
        self.repository = repository
        self.normalizer = normalizer

    def get_requirements(
        self,
        conn,
        *,
        course_ids: list[str],
        academic_background: str,
        request_id: str,
        course_names_by_id: dict[str, str] | None = None,
    ) -> RequirementResult:
        raw_requirements = self.repository.fetch_current_requirements_by_course_ids(
            conn,
            course_ids=course_ids,
        )
        requirements: dict[str, NormalizedRequirement] = {}
        errors: dict[str, str] = {}

        for course_id in course_ids:
            raw_requirement = raw_requirements.get(course_id)
            if raw_requirement is None:
                errors[course_id] = "missing_requirement"
                logger.warning(
                    "admission requirement missing",
                    extra={"request_id": request_id, "course_id": course_id},
                )
                continue
            try:
                requirements[course_id] = self.normalizer.normalize(
                    raw_requirement,
                    academic_background=academic_background,
                    course_name=(course_names_by_id or {}).get(course_id, ""),
                )
            except MissingIeltsRequirementError:
                errors[course_id] = "missing_ielts_requirement"
                logger.warning(
                    "ielts requirement missing",
                    extra={"request_id": request_id, "course_id": course_id},
                )
            except RequirementNormalizationError:
                errors[course_id] = "requirement_normalization_failed"
                logger.warning(
                    "requirement normalization failed",
                    extra={"request_id": request_id, "course_id": course_id},
                    exc_info=True,
                )

        return RequirementResult(requirements=requirements, errors=errors, raw_requirements=raw_requirements)
