from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CourseSeed:
    course_id: str
    course_name: str
    cricos: str
    source_url: str | None


def fetch_course_seeds(conn, limit: int, only_missing: bool = True, retry_dlq: bool = False) -> list[CourseSeed]:
    sql = """
        select
            c.id::text,
            c.course_name,
            c.cricos,
            coalesce(
                max(car.source_url) filter (where car.is_current),
                max(dlq.source_url)
            ) as source_url,
            bool_or(
                coalesce(car.academic_requirement_text, '') <> ''
                and car.requirement_source = 'usyd_web_crawl'
                and car.is_current
            ) as has_crawled_admissions,
            bool_or(dlq.cricos is not null) as has_dlq
        from courses c
        left join course_admission_requirements car on car.course_id = c.id
        left join course_admission_dlq dlq on dlq.cricos = c.cricos
        group by c.id, c.course_name, c.cricos
        order by c.course_name
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()

    seeds = [
        CourseSeed(course_id=row[0], course_name=row[1], cricos=row[2], source_url=row[3])
        for row in rows
        if (
            (retry_dlq and not row[4] and row[5])
            or (not retry_dlq and (not only_missing or (not row[4] and not row[5])))
        )
    ]
    return seeds[:limit]
