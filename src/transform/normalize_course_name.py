from __future__ import annotations


def normalize_course_name(raw: str) -> tuple[str, str]:
    raw_value = "" if raw is None else str(raw)
    normalized = raw_value.strip()
    if not normalized:
        raise ValueError("Course Name cannot be empty")
    return normalized, raw_value

