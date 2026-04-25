from __future__ import annotations

import json

from src.models.dto import AdmissionRequirementRecord


def replace_admission_requirement(conn, course_id, requirement: AdmissionRequirementRecord) -> None:
    with conn.cursor() as cur:
        cur.execute("delete from course_admission_requirements where course_id = %s", (course_id,))
        cur.execute(
            """
            insert into course_admission_requirements (
                course_id,
                requirement_version,
                requirement_source,
                raw_english_requirement,
                ielts_overall,
                ielts_min_band,
                ielts_listening,
                ielts_reading,
                ielts_speaking,
                ielts_writing,
                english_req_details,
                is_current
            )
            values (%s, 1, 'excel_seed', %s, %s, %s, %s, %s, %s, %s, %s::jsonb, true)
            """,
            (
                course_id,
                requirement.raw_english_requirement,
                requirement.ielts_overall,
                requirement.ielts_min_band,
                requirement.ielts_listening,
                requirement.ielts_reading,
                requirement.ielts_speaking,
                requirement.ielts_writing,
                json.dumps(requirement.english_req_details, ensure_ascii=False),
            ),
        )
