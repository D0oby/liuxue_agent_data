from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from src.models.course_features import CourseFeatureProfile


@dataclass(frozen=True)
class CourseFeatureRecord:
    course_id: str
    course_name: str
    source: dict[str, Any]
    course_features: CourseFeatureProfile | None
    manual_overrides: dict[str, Any]


class CourseFeatureRepository:
    def fetch_course_ids_for_generation(
        self,
        conn,
        *,
        limit: int | None = None,
        only_missing: bool = True,
    ) -> list[str]:
        where_sql = "where c.course_features is null" if only_missing else ""
        limit_sql = "limit %s" if limit is not None else ""
        params: list[object] = [limit] if limit is not None else []
        with conn.cursor() as cur:
            cur.execute(
                f"""
                select c.id::text
                from courses c
                {where_sql}
                order by c.course_name, c.source_row_number
                {limit_sql}
                """,
                params,
            )
            return [row[0] for row in cur.fetchall()]

    def fetch_feature_audit_rows(self, conn, *, limit: int | None = None) -> list[dict[str, Any]]:
        limit_sql = "limit %s" if limit is not None else ""
        params: list[object] = [limit] if limit is not None else []
        with conn.cursor() as cur:
            cur.execute(
                f"""
                select id::text, course_name, course_features
                from courses
                order by course_name, source_row_number
                {limit_sql}
                """,
                params,
            )
            return [
                {
                    "course_id": row[0],
                    "course_name": row[1],
                    "course_features": _as_dict(row[2]) or None,
                }
                for row in cur.fetchall()
            ]

    def fetch_course(self, conn, *, course_id: str) -> CourseFeatureRecord | None:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                    c.id::text,
                    c.course_name,
                    c.course_name_raw,
                    c.cricos,
                    c.duration_max_years::float,
                    c.tuition_fee_aud::float,
                    c.course_features,
                    c.course_feature_overrides,
                    coalesce(car.academic_requirement_text, ''),
                    car.ielts_overall::float,
                    car.ielts_min_band::float
                from courses c
                left join course_admission_requirements car
                  on car.course_id = c.id
                 and car.is_current = true
                where c.id = %s
                """,
                [course_id],
            )
            row = cur.fetchone()
            if row is None:
                return None
        raw_profile = _as_dict(row[6])
        source = {
            "course_id": row[0],
            "course_name": row[1],
            "course_name_raw": row[2],
            "cricos": row[3],
            "duration_max_years": row[4],
            "tuition_fee_aud": row[5],
            "academic_requirement_text": row[8],
            "ielts_overall_min": row[9],
            "ielts_min_band_min": row[10],
        }
        return CourseFeatureRecord(
            course_id=row[0],
            course_name=row[1],
            source=source,
            course_features=CourseFeatureProfile.model_validate(raw_profile) if raw_profile else None,
            manual_overrides=_as_dict(row[7]),
        )

    def save_course_features(
        self,
        conn,
        *,
        course_id: str,
        course_features: CourseFeatureProfile,
        manual_overrides: dict[str, Any] | None = None,
    ) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                update courses
                set
                    course_features = %s::jsonb,
                    course_feature_overrides = %s::jsonb,
                    updated_at = now()
                where id = %s
                """,
                [
                    json.dumps(course_features.model_dump(), ensure_ascii=False),
                    json.dumps(manual_overrides or {}, ensure_ascii=False),
                    course_id,
                ],
            )


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
