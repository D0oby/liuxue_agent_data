from __future__ import annotations


MONTH_MAP = {
    "JAN": "JAN",
    "JANUARY": "JAN",
    "FEB": "FEB",
    "FEBRUARY": "FEB",
    "MAR": "MAR",
    "MARCH": "MAR",
    "JUL": "JUL",
    "JULY": "JUL",
    "AUG": "AUG",
    "AUGUST": "AUG",
    "OCT": "OCT",
    "OCTOBER": "OCT",
}

MONTH_ORDER = ["JAN", "FEB", "MAR", "JUL", "AUG", "OCT"]


def parse_intakes(raw: str) -> list[str]:
    raw_text = str(raw).strip()
    if not raw_text:
        raise ValueError("Commencing Semester cannot be empty")

    normalized: list[str] = []
    for part in raw_text.replace(",", "/").split("/"):
        token = part.strip().upper()
        if not token:
            continue
        if token not in MONTH_MAP:
            raise ValueError(f"Unsupported intake token: {part}")
        month = MONTH_MAP[token]
        if month not in normalized:
            normalized.append(month)

    return sorted(normalized, key=MONTH_ORDER.index)

