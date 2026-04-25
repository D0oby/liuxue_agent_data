from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class IntakeRecord:
    intake_month: str
    sort_order: int


@dataclass(frozen=True)
class AdmissionRequirementRecord:
    raw_english_requirement: str
    ielts_overall: float | None
    ielts_min_band: float | None
    ielts_listening: float | None = None
    ielts_reading: float | None = None
    ielts_speaking: float | None = None
    ielts_writing: float | None = None
    english_req_details: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CourseRecord:
    course_name: str
    course_name_raw: str
    cricos: str
    duration_min_years: float
    duration_max_years: float
    duration_raw: str
    commencing_semester_raw: str
    tuition_fee_aud: float
    source_file_name: str
    source_sheet_name: str
    source_row_number: int
    source_row_hash: str
    intakes: list[IntakeRecord]
    admission_requirement: AdmissionRequirementRecord
