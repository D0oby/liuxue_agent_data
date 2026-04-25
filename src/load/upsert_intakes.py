from __future__ import annotations

from src.models.dto import IntakeRecord


def replace_intakes(conn, course_id, intakes: list[IntakeRecord]) -> None:
    with conn.cursor() as cur:
        cur.execute("delete from course_intakes where course_id = %s", (course_id,))
        for intake in intakes:
            cur.execute(
                """
                insert into course_intakes (course_id, intake_month, sort_order)
                values (%s, %s, %s)
                on conflict (course_id, intake_month) do update
                set sort_order = excluded.sort_order
                """,
                (course_id, intake.intake_month, intake.sort_order),
            )

