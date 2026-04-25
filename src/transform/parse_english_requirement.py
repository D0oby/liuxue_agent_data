from __future__ import annotations

import re


OVERALL_RE = re.compile(r"^\s*(\d(?:\.\d)?)")
PARENS_RE = re.compile(r"\((.*?)\)")

LETTER_MAP = {
    "R": "reading",
    "L": "listening",
    "S": "speaking",
    "W": "writing",
}


def _parse_subscores(detail_text: str) -> dict[str, float]:
    subscores: dict[str, float] = {}
    for chunk in detail_text.split(";"):
        cleaned = chunk.strip()
        if not cleaned:
            continue
        match = re.match(r"(\d(?:\.\d)?)\s+([A-Z/]+)$", cleaned)
        if not match:
            continue
        score = float(match.group(1))
        labels = [label for label in match.group(2).split("/") if label]
        for label in labels:
            field_name = LETTER_MAP.get(label)
            if field_name:
                subscores[field_name] = score
    return subscores


def parse_english_requirement(raw: str) -> dict:
    raw_text = str(raw).strip()
    if not raw_text:
        return {
            "raw_english_requirement": "",
            "ielts_overall": None,
            "ielts_min_band": None,
            "ielts_listening": None,
            "ielts_reading": None,
            "ielts_speaking": None,
            "ielts_writing": None,
            "english_req_details": {},
        }

    overall_match = OVERALL_RE.search(raw_text)
    overall = float(overall_match.group(1)) if overall_match else None

    parens_match = PARENS_RE.search(raw_text)
    details: dict = {}
    min_band = None
    subscores: dict[str, float] = {}

    if parens_match:
        inside = parens_match.group(1).strip()
        simple_match = re.fullmatch(r"(\d(?:\.\d)?)", inside)
        if simple_match:
            min_band = float(simple_match.group(1))
            subscores = {
                "listening": min_band,
                "reading": min_band,
                "speaking": min_band,
                "writing": min_band,
            }
        else:
            parsed_subscores = _parse_subscores(inside)
            if parsed_subscores:
                subscores = parsed_subscores
                min_band = min(subscores.values())
                details = {
                    "raw": raw_text,
                    "ielts_subscores": subscores,
                }
            else:
                number_match = re.search(r"(\d(?:\.\d)?)", inside)
                min_band = float(number_match.group(1)) if number_match else None
                details = {"raw": raw_text, "unparsed_detail": inside}

    return {
        "raw_english_requirement": raw_text,
        "ielts_overall": overall,
        "ielts_min_band": min_band,
        "ielts_listening": subscores.get("listening"),
        "ielts_reading": subscores.get("reading"),
        "ielts_speaking": subscores.get("speaking"),
        "ielts_writing": subscores.get("writing"),
        "english_req_details": details,
    }
