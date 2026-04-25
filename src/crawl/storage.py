from __future__ import annotations

import json
from datetime import datetime, timezone

from src.crawl.parser import build_english_req_details, build_source_fingerprint


def upsert_crawled_admission_requirement(conn, payload) -> None:
    details = build_english_req_details(payload)
    ielts_test = next(
        (test for test in payload.language_tests if test.test_name == "IELTS Academic"),
        None,
    )
    current_timestamp = datetime.now(timezone.utc)
    source_fingerprint = build_source_fingerprint(payload)

    with conn.cursor() as cur:
        cur.execute(
            """
            select id
            from course_admission_requirements
            where course_id = %s
              and is_current = true
              and source_fingerprint = %s
            """,
            (payload.course_id, source_fingerprint),
        )
        existing_row = cur.fetchone()
        if existing_row:
            cur.execute(
                """
                update course_admission_requirements
                set
                    last_verified_at = %s,
                    updated_at = %s,
                    notes = %s,
                    source_url = %s
                where id = %s
                """,
                (
                    current_timestamp,
                    current_timestamp,
                    "\n".join(payload.notes),
                    payload.canonical_url,
                    existing_row[0],
                ),
            )
            return

        cur.execute(
            """
            update course_admission_requirements
            set is_current = false,
                updated_at = %s
            where course_id = %s
              and is_current = true
            """,
            (current_timestamp, payload.course_id),
        )
        cur.execute(
            """
            insert into course_admission_requirements (
                course_id,
                requirement_version,
                requirement_source,
                source_url,
                academic_requirement_text,
                raw_english_requirement,
                academic_requirements_json,
                ielts_overall,
                ielts_min_band,
                ielts_listening,
                ielts_reading,
                ielts_speaking,
                ielts_writing,
                english_req_details,
                application_details_json,
                supplementary_metadata_json,
                source_map_json,
                source_fingerprint,
                notes,
                is_current,
                last_verified_at
            )
            values (
                %s,
                coalesce(
                    (
                        select max(requirement_version) + 1
                        from course_admission_requirements
                        where course_id = %s
                    ),
                    1
                ),
                'usyd_web_crawl',
                %s,
                %s,
                %s,
                %s::jsonb,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s::jsonb,
                %s::jsonb,
                %s::jsonb,
                %s::jsonb,
                %s,
                %s,
                true,
                %s
            )
            """,
            (
                payload.course_id,
                payload.course_id,
                payload.canonical_url,
                payload.academic_requirement_text,
                payload.raw_english_requirement,
                json.dumps(
                    {
                        "raw_text": payload.academic_requirement_text,
                        "pathways": [pathway.model_dump() for pathway in payload.academic_pathways],
                    },
                    ensure_ascii=False,
                ),
                _to_float(ielts_test.overall if ielts_test else None),
                _to_float(ielts_test.component_scores.get("listening") if ielts_test else None),
                _to_float(ielts_test.component_scores.get("listening") if ielts_test else None),
                _to_float(ielts_test.component_scores.get("reading") if ielts_test else None),
                _to_float(ielts_test.component_scores.get("speaking") if ielts_test else None),
                _to_float(ielts_test.component_scores.get("writing") if ielts_test else None),
                json.dumps(details, ensure_ascii=False),
                json.dumps(payload.application_details.model_dump(), ensure_ascii=False),
                json.dumps(payload.supplementary_metadata, ensure_ascii=False),
                json.dumps(payload.source_map, ensure_ascii=False),
                source_fingerprint,
                "\n".join(payload.notes),
                current_timestamp,
            ),
        )


def _to_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)
