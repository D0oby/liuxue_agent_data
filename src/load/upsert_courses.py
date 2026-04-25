from __future__ import annotations

from dataclasses import asdict
import hashlib
import json

from src.models.dto import AdmissionRequirementRecord, CourseRecord, IntakeRecord
from src.transform.normalize_course_name import normalize_course_name
from src.transform.parse_duration import parse_duration
from src.transform.parse_english_requirement import parse_english_requirement
from src.transform.parse_intakes import parse_intakes


def build_source_row_hash(
    row: dict,
    source_file_name: str,
    source_sheet_name: str,
    source_row_number: int,
) -> str:
    payload = {
        "source_file_name": source_file_name,
        "source_sheet_name": source_sheet_name,
        "source_row_number": source_row_number,
        "row": row,
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def build_course_record(raw_row, source_file_name: str, source_sheet_name: str, source_row_hash: str) -> CourseRecord:
    course_name, course_name_raw = normalize_course_name(raw_row.values["Course Name"])
    duration_min, duration_max, duration_raw = parse_duration(raw_row.values["Duration (Years)"])
    parsed_intakes = parse_intakes(raw_row.values["Commencing Semester"])
    english_requirement = parse_english_requirement(raw_row.values["IELTS Academic"])

    intakes = [
        IntakeRecord(intake_month=intake_month, sort_order=index + 1)
        for index, intake_month in enumerate(parsed_intakes)
    ]

    admission_requirement = AdmissionRequirementRecord(
        raw_english_requirement=english_requirement["raw_english_requirement"],
        ielts_overall=english_requirement["ielts_overall"],
        ielts_min_band=english_requirement["ielts_min_band"],
        ielts_listening=english_requirement["ielts_listening"],
        ielts_reading=english_requirement["ielts_reading"],
        ielts_speaking=english_requirement["ielts_speaking"],
        ielts_writing=english_requirement["ielts_writing"],
        english_req_details=english_requirement["english_req_details"],
    )

    return CourseRecord(
        course_name=course_name,
        course_name_raw=course_name_raw,
        cricos=raw_row.values["CRICOS"].strip(),
        duration_min_years=duration_min,
        duration_max_years=duration_max,
        duration_raw=duration_raw,
        commencing_semester_raw=raw_row.values["Commencing Semester"].strip(),
        tuition_fee_aud=float(raw_row.values["Tuition Fee ($AUD)"]),
        source_file_name=source_file_name,
        source_sheet_name=source_sheet_name,
        source_row_number=raw_row.source_row_number,
        source_row_hash=source_row_hash,
        intakes=intakes,
        admission_requirement=admission_requirement,
    )


def upsert_course(conn, course_record: CourseRecord):
    sql = """
        insert into courses (
            course_name,
            course_name_raw,
            cricos,
            duration_min_years,
            duration_max_years,
            duration_raw,
            commencing_semester_raw,
            tuition_fee_aud,
            source_file_name,
            source_sheet_name,
            source_row_number,
            source_row_hash
        )
        values (
            %(course_name)s,
            %(course_name_raw)s,
            %(cricos)s,
            %(duration_min_years)s,
            %(duration_max_years)s,
            %(duration_raw)s,
            %(commencing_semester_raw)s,
            %(tuition_fee_aud)s,
            %(source_file_name)s,
            %(source_sheet_name)s,
            %(source_row_number)s,
            %(source_row_hash)s
        )
        on conflict (source_row_hash) do update
        set
            course_name = excluded.course_name,
            course_name_raw = excluded.course_name_raw,
            cricos = excluded.cricos,
            duration_min_years = excluded.duration_min_years,
            duration_max_years = excluded.duration_max_years,
            duration_raw = excluded.duration_raw,
            commencing_semester_raw = excluded.commencing_semester_raw,
            tuition_fee_aud = excluded.tuition_fee_aud,
            source_file_name = excluded.source_file_name,
            source_sheet_name = excluded.source_sheet_name,
            source_row_number = excluded.source_row_number,
            updated_at = now()
        returning id
    """
    payload = asdict(course_record)
    payload.pop("intakes", None)
    payload.pop("admission_requirement", None)

    with conn.cursor() as cur:
        cur.execute(sql, payload)
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("Failed to upsert course row")
        return row[0]
