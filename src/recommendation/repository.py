from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.models.recommendation import RawAdmissionRequirement


@dataclass(frozen=True)
class CourseSearchRow:
    course_id: str
    course_name: str
    course_name_raw: str
    cricos: str
    duration_min_years: float | None
    duration_max_years: float | None
    tuition_fee_aud: float | None
    academic_requirement_text: str
    raw_english_requirement: str
    ielts_overall_required: float | None
    ielts_min_band_required: float | None
    source_url: str | None
    ielts_listening_required: float | None = None
    ielts_reading_required: float | None = None
    ielts_speaking_required: float | None = None
    ielts_writing_required: float | None = None
    academic_requirements_json: dict[str, Any] | None = None
    application_details_json: dict[str, Any] | None = None
    supplementary_metadata_json: dict[str, Any] | None = None


class RecommendationRepository:
    def search_courses_by_keywords(
        self,
        conn,
        *,
        keywords: list[str],
        limit: int,
    ) -> list[CourseSearchRow]:
        normalized_keywords = [keyword.strip() for keyword in keywords if keyword.strip()]
        if not normalized_keywords:
            return []

        clauses: list[str] = []
        params: list[object] = []
        for keyword in normalized_keywords:
            pattern = f"%{keyword}%"
            clauses.append(
                """(
                    c.course_name ilike %s
                    or c.course_name_raw ilike %s
                    or c.cricos ilike %s
                    or coalesce(car.academic_requirement_text, '') ilike %s
                    or coalesce(car.raw_english_requirement, '') ilike %s
                )"""
            )
            params.extend([pattern, pattern, pattern, pattern, pattern])
        params.append(limit)

        with conn.cursor() as cur:
            cur.execute(
                f"""
                select
                    c.id::text,
                    c.course_name,
                    c.course_name_raw,
                    c.cricos,
                    c.duration_min_years::float,
                    c.duration_max_years::float,
                    c.tuition_fee_aud::float,
                    coalesce(car.academic_requirement_text, ''),
                    coalesce(car.raw_english_requirement, ''),
                    car.ielts_overall::float,
                    car.ielts_min_band::float,
                    car.source_url,
                    car.ielts_listening::float,
                    car.ielts_reading::float,
                    car.ielts_speaking::float,
                    car.ielts_writing::float,
                    car.academic_requirements_json,
                    car.application_details_json,
                    car.supplementary_metadata_json
                from courses c
                left join course_admission_requirements car
                  on car.course_id = c.id
                 and car.is_current = true
                where {" or ".join(clauses)}
                order by c.course_name, c.source_row_number
                limit %s
                """,
                params,
            )
            return [self._map_course_search_row(row) for row in cur.fetchall()]

    def fetch_courses_by_ids(self, conn, *, course_ids: list[str]) -> dict[str, CourseSearchRow]:
        if not course_ids:
            return {}
        placeholders = ", ".join(["%s"] * len(course_ids))
        with conn.cursor() as cur:
            cur.execute(
                f"""
                select
                    c.id::text,
                    c.course_name,
                    c.course_name_raw,
                    c.cricos,
                    c.duration_min_years::float,
                    c.duration_max_years::float,
                    c.tuition_fee_aud::float,
                    coalesce(car.academic_requirement_text, ''),
                    coalesce(car.raw_english_requirement, ''),
                    car.ielts_overall::float,
                    car.ielts_min_band::float,
                    car.source_url,
                    car.ielts_listening::float,
                    car.ielts_reading::float,
                    car.ielts_speaking::float,
                    car.ielts_writing::float,
                    car.academic_requirements_json,
                    car.application_details_json,
                    car.supplementary_metadata_json
                from courses c
                left join course_admission_requirements car
                  on car.course_id = c.id
                 and car.is_current = true
                where c.id in ({placeholders})
                """,
                course_ids,
            )
            rows = [self._map_course_search_row(row) for row in cur.fetchall()]
        return {row.course_id: row for row in rows}

    def fetch_intakes_by_course_ids(self, conn, *, course_ids: list[str]) -> dict[str, list[str]]:
        if not course_ids:
            return {}
        placeholders = ", ".join(["%s"] * len(course_ids))
        with conn.cursor() as cur:
            cur.execute(
                f"""
                select course_id::text, intake_month
                from course_intakes
                where course_id in ({placeholders})
                order by course_id, sort_order
                """,
                course_ids,
            )
            rows = cur.fetchall()

        intakes: dict[str, list[str]] = {}
        for course_id, intake_month in rows:
            intakes.setdefault(course_id, []).append(intake_month)
        return intakes

    def fetch_current_requirements_by_course_ids(
        self,
        conn,
        *,
        course_ids: list[str],
    ) -> dict[str, RawAdmissionRequirement]:
        if not course_ids:
            return {}
        placeholders = ", ".join(["%s"] * len(course_ids))
        with conn.cursor() as cur:
            cur.execute(
                f"""
                select
                    course_id::text,
                    coalesce(academic_requirement_text, ''),
                    coalesce(raw_english_requirement, ''),
                    ielts_overall::float,
                    ielts_min_band::float,
                    ielts_listening::float,
                    ielts_reading::float,
                    ielts_speaking::float,
                    ielts_writing::float,
                    english_req_details,
                    academic_requirements_json,
                    application_details_json,
                    supplementary_metadata_json,
                    source_url
                from course_admission_requirements
                where is_current = true
                  and course_id in ({placeholders})
                """,
                course_ids,
            )
            requirements: dict[str, RawAdmissionRequirement] = {}
            for row in cur.fetchall():
                requirement = RawAdmissionRequirement(
                    course_id=row[0],
                    academic_requirement_text=row[1],
                    raw_english_requirement=row[2],
                    ielts_overall=row[3],
                    ielts_min_band=row[4],
                    ielts_listening=row[5],
                    ielts_reading=row[6],
                    ielts_speaking=row[7],
                    ielts_writing=row[8],
                    english_req_details=_as_dict(row[9]),
                    academic_requirements_json=_as_dict(row[10]),
                    application_details_json=_as_dict(row[11]),
                    supplementary_metadata_json=_as_dict(row[12]),
                    source_url=row[13],
                )
                requirements[requirement.course_id] = requirement
        return requirements

    def _map_course_search_row(self, row: tuple[Any, ...]) -> CourseSearchRow:
        return CourseSearchRow(
            course_id=row[0],
            course_name=row[1],
            course_name_raw=row[2],
            cricos=row[3],
            duration_min_years=row[4],
            duration_max_years=row[5],
            tuition_fee_aud=row[6],
            academic_requirement_text=row[7],
            raw_english_requirement=row[8],
            ielts_overall_required=row[9],
            ielts_min_band_required=row[10],
            source_url=row[11],
            ielts_listening_required=row[12],
            ielts_reading_required=row[13],
            ielts_speaking_required=row[14],
            ielts_writing_required=row[15],
            academic_requirements_json=_as_dict(row[16]),
            application_details_json=_as_dict(row[17]),
            supplementary_metadata_json=_as_dict(row[18]),
        )


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
