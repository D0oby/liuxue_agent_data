from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.models.course_features import CourseFeatureProfile
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
    course_features: CourseFeatureProfile | dict[str, Any] | None = None


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

        sql = self._build_course_search_sql(
            where_clause="where " + " or ".join(clauses),
            order_and_limit="order by c.course_name, c.source_row_number\n                limit %s",
            include_feature_columns=True,
        )
        fallback_sql = self._build_course_search_sql(
            where_clause="where " + " or ".join(clauses),
            order_and_limit="order by c.course_name, c.source_row_number\n                limit %s",
            include_feature_columns=False,
        )
        rows = self._fetch_course_search_rows(conn, sql=sql, fallback_sql=fallback_sql, params=params)
        return [self._map_course_search_row(row) for row in rows]

    def fetch_courses_by_ids(self, conn, *, course_ids: list[str]) -> dict[str, CourseSearchRow]:
        if not course_ids:
            return {}
        placeholders = ", ".join(["%s"] * len(course_ids))
        sql = self._build_course_search_sql(
            where_clause=f"where c.id in ({placeholders})",
            order_and_limit="",
            include_feature_columns=True,
        )
        fallback_sql = self._build_course_search_sql(
            where_clause=f"where c.id in ({placeholders})",
            order_and_limit="",
            include_feature_columns=False,
        )
        rows = [
            self._map_course_search_row(row)
            for row in self._fetch_course_search_rows(
                conn,
                sql=sql,
                fallback_sql=fallback_sql,
                params=course_ids,
            )
        ]
        return {row.course_id: row for row in rows}

    def _build_course_search_sql(
        self,
        *,
        where_clause: str,
        order_and_limit: str,
        include_feature_columns: bool,
    ) -> str:
        feature_column = "c.course_features" if include_feature_columns else "null::jsonb as course_features"
        return f"""
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
                    car.supplementary_metadata_json,
                    {feature_column}
                from courses c
                left join course_admission_requirements car
                  on car.course_id = c.id
                 and car.is_current = true
                {where_clause}
                {order_and_limit}
                """

    def _fetch_course_search_rows(
        self,
        conn,
        *,
        sql: str,
        fallback_sql: str,
        params: list[object],
    ) -> list[tuple[Any, ...]]:
        try:
            return self._execute_course_search(conn, sql=sql, params=params)
        except Exception as exc:
            if not _is_missing_feature_column_error(exc):
                raise
            _rollback_failed_select(conn)
            return self._execute_course_search(conn, sql=fallback_sql, params=params)

    def _execute_course_search(self, conn, *, sql: str, params: list[object]) -> list[tuple[Any, ...]]:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

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
            course_features=_as_dict(row[19]) or None,
        )


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _is_missing_feature_column_error(exc: Exception) -> bool:
    current: BaseException | None = exc
    while current is not None:
        message = str(current).lower()
        if "course_feature" in message and "does not exist" in message:
            return True
        current = current.__cause__ or current.__context__
    return False


def _rollback_failed_select(conn) -> None:
    rollback = getattr(conn, "rollback", None)
    if callable(rollback):
        rollback()
