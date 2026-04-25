from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def append_dlq_record(output_path: Path, record: dict) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"created_at": datetime.now(timezone.utc).isoformat(), **record}
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def insert_dlq_record(conn, record: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into course_admission_dlq (
                cricos,
                course_name,
                source_url,
                stage,
                error_code,
                error_message,
                raw_payload_json,
                raw_html_excerpt,
                source_context_json,
                retryable
            )
            values (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s::jsonb,
                %s,
                %s::jsonb,
                %s
            )
            """,
            (
                record.get("cricos"),
                record.get("course_name"),
                record.get("source_url"),
                record.get("stage"),
                record.get("error_code"),
                record.get("error_message"),
                json.dumps(record.get("raw_payload_json", {}), ensure_ascii=False),
                record.get("raw_html_excerpt"),
                json.dumps(record.get("source_context_json", {}), ensure_ascii=False),
                record.get("retryable", True),
            ),
        )
