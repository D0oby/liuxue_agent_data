from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ALLOWED_TEST_NAMES = {
    "IELTS Academic",
    "TOEFL iBT",
    "PTE Academic",
    "LanguageCert Academic",
    "Cambridge C1 Advanced",
    "Cambridge C2 Proficiency",
}


class LanguageTestScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    test_name: str
    overall: str | None = None
    component_scores: dict[str, str] = Field(default_factory=dict)
    raw_text: str
    source_url: str
    source_type: str
    source_priority: int

    @field_validator("test_name")
    @classmethod
    def validate_test_name(cls, value: str) -> str:
        if value not in ALLOWED_TEST_NAMES:
            raise ValueError(f"Unsupported test name: {value}")
        return value

    @field_validator("source_type")
    @classmethod
    def validate_source_type(cls, value: str) -> str:
        allowed = {"explicit_course_page", "derived_concordance", "global_standard_reference"}
        if value not in allowed:
            raise ValueError(f"Unsupported language source type: {value}")
        return value


class AcademicPathway(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    qualification: str | None = None
    discipline: str | None = None
    grade_requirement: str | None = None
    work_experience: str | None = None
    admissions_test: str | None = None
    logic: str = "OR"

    @model_validator(mode="after")
    def ensure_meaningful_pathway(self) -> "AcademicPathway":
        if not any(
            [
                self.qualification,
                self.discipline,
                self.grade_requirement,
                self.work_experience,
                self.admissions_test,
            ]
        ):
            raise ValueError("Academic pathway must contain at least one structured signal.")
        return self


class ApplicationDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_documents: list[str] = Field(default_factory=list)
    requires_portfolio: bool = False
    requires_personal_statement: bool = False
    requires_supplementary_form: bool = False
    requires_cv_or_resume: bool = False
    requires_references: bool = False
    requires_work_experience: bool = False
    limited_places: bool = False
    quota_applies: bool = False
    selection_notes: list[str] = Field(default_factory=list)
    raw_text: str = ""

    @field_validator("required_documents")
    @classmethod
    def dedupe_documents(cls, value: list[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for item in value:
            normalized = item.strip()
            key = normalized.casefold()
            if normalized and key not in seen:
                seen.add(key)
                deduped.append(normalized)
        return deduped

    @model_validator(mode="after")
    def ensure_flags_have_evidence(self) -> "ApplicationDetails":
        raw_lower = self.raw_text.casefold()
        evidence_map = {
            "requires_portfolio": ("portfolio",),
            "requires_personal_statement": ("personal statement", "statement of intent"),
            "requires_supplementary_form": ("supplementary form",),
            "requires_cv_or_resume": ("cv", "resume"),
            "requires_references": ("reference", "referee"),
            "requires_work_experience": ("work experience",),
            "limited_places": ("limited places",),
            "quota_applies": ("quota applies",),
        }
        for field_name, snippets in evidence_map.items():
            if getattr(self, field_name) and not any(snippet in raw_lower for snippet in snippets):
                raise ValueError(f"{field_name} is true but no textual evidence was preserved.")
        return self


class AdmissionsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_id: str
    course_name: str
    cricos: str
    source_url: str
    canonical_url: str
    academic_requirement_text: str
    academic_pathways: list[AcademicPathway] = Field(default_factory=list)
    raw_english_requirement: str
    language_tests: list[LanguageTestScore] = Field(default_factory=list)
    application_details: ApplicationDetails = Field(default_factory=ApplicationDetails)
    supplementary_metadata: dict = Field(default_factory=dict)
    source_map: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)

    @field_validator("cricos")
    @classmethod
    def validate_cricos(cls, value: str) -> str:
        normalized = value.strip().upper()
        if len(normalized) != 7 or not normalized[:6].isdigit() or not normalized[6].isalnum():
            raise ValueError("CRICOS must match the Australian provider/course code format.")
        return normalized

    @field_validator("course_name", "academic_requirement_text", "raw_english_requirement")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        normalized = " ".join(value.split()).strip()
        if len(normalized) < 12:
            raise ValueError("Text content is too short to be trustworthy.")
        return normalized

    @field_validator("source_url", "canonical_url")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.startswith("https://www.sydney.edu.au/"):
            raise ValueError("Source URLs must stay on the Sydney University official domain.")
        return normalized

    @model_validator(mode="after")
    def ensure_language_signal(self) -> "AdmissionsPayload":
        if not self.language_tests and "standard english" not in self.raw_english_requirement.casefold():
            raise ValueError("Language requirements must contain at least one test or standard English reference.")
        return self

    @model_validator(mode="after")
    def ensure_academic_content_is_not_award_only(self) -> "AdmissionsPayload":
        lowered = self.academic_requirement_text.casefold()
        if "requirements for award" in lowered and "admission" not in lowered:
            raise ValueError("Academic requirements block appears to contain award rules instead of admissions criteria.")
        if not self.academic_pathways and not any(
            marker in lowered
            for marker in [
                "bachelor",
                "qualification",
                "equivalent qualification",
                "honours",
                "master",
                "thesis",
                "experience",
                "admissions test",
                "average",
                "gpa",
                "degree",
                "graduate certificate",
                "graduate diploma",
                "undergraduate program",
                "cognate discipline",
                "related field",
                "law degree",
                "common law",
                "concurrently enrolled",
                "legal reasoning",
                "80%",
                "65 percent",
            ]
        ):
            raise ValueError("Academic requirements block does not contain recognizable admission signals.")
        return self
