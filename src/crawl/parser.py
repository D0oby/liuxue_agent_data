from __future__ import annotations

import hashlib
import html
import json
import re
from urllib.parse import urlparse, urlunparse


WHITESPACE_RE = re.compile(r"\s+")
IELTS_RE = re.compile(
    r"ielts(?:\s+academic)?[^0-9]{0,20}(?P<overall>[4-9](?:\.[05])?)"
    r"(?:[^0-9]{0,40}(?:no\s+(?:band|component)\s+below|min(?:imum)?\s+band(?:\s+of)?|each(?:\s+band)?\s+at)\s*(?P<band>[4-9](?:\.[05])?))?",
    re.IGNORECASE,
)
TOEFL_RE = re.compile(r"toefl(?:\s+ibt)?[^0-9]{0,20}(?P<overall>\d{2,3})", re.IGNORECASE)
PTE_RE = re.compile(r"pte(?:\s+academic)?[^0-9]{0,20}(?P<overall>\d{2,3})", re.IGNORECASE)
LANGUAGECERT_RE = re.compile(
    r"languagecert(?:\s+academic(?:\s+\(in-person\))?)?[^0-9]{0,20}(?P<overall>\d{2,3})",
    re.IGNORECASE,
)
CAMBRIDGE_RE = re.compile(
    r"cambridge\s+(?P<level>c1\s+advanced|c2\s+proficiency)[^0-9]{0,20}(?P<overall>\d{2,3})",
    re.IGNORECASE,
)


def normalize_text(value: str) -> str:
    decoded = html.unescape(value.replace("\xa0", " "))
    cleaned = WHITESPACE_RE.sub(" ", decoded).strip(" \n\t-:")
    return cleaned


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def extract_relevant_blocks(text: str) -> dict[str, str]:
    normalized = normalize_text(text)
    sections = {
        "academic": _extract_window(
            normalized,
            [
                "admission requirement",
                "admission requirements",
                "academic requirements",
                "entry requirements",
                "admission to candidature",
            ],
            [
                "credit for previous study",
                "how to apply",
                "fees",
                "careers",
                "what you'll study",
                "what you will study",
                "requirements for award",
            ],
        ),
        "language": _extract_window(
            normalized,
            [
                "english language proficiency",
                "english language requirement",
                "english requirements",
                "english language skills",
            ],
            [
                "how to apply",
                "fees",
                "credit for previous study",
                "admission requirement",
            ],
        ),
        "application": _extract_window(
            normalized,
            [
                "how to apply",
                "applications are made",
                "additional admission criteria",
                "limited places",
                "quota applies",
                "supplementary form",
                "portfolio",
            ],
            [
                "careers",
                "what you'll study",
                "fees",
                "the sydney experience",
            ],
        ),
    }
    return sections


def _extract_window(text: str, starts: list[str], ends: list[str]) -> str:
    positions = [text.casefold().find(marker) for marker in starts if text.casefold().find(marker) != -1]
    if not positions:
        return ""
    start = min(positions)
    lower = text.casefold()
    candidates = [lower.find(marker, start + 1) for marker in ends]
    ends_found = [position for position in candidates if position != -1]
    end = min(ends_found) if ends_found else min(len(text), start + 2400)
    return text[start:end].strip()


def parse_academic_pathways(text: str) -> list[dict[str, str]]:
    if not text:
        return []

    normalized = normalize_text(text)
    normalized = re.sub(r"\s+or\s+", ". OR ", normalized, flags=re.IGNORECASE)
    sentences = re.split(r"(?<=[.;])\s+", normalized)
    pathways: list[dict[str, str]] = []
    for sentence in sentences:
        snippet = normalize_text(sentence)
        lowered = snippet.casefold()
        if len(snippet) < 24:
            continue
        if "requirements for award" in lowered or "credit points" in lowered:
            continue
        if not any(
            keyword in lowered
            for keyword in [
                "bachelor",
                "degree",
                "honours",
                "master",
                "thesis",
                "law degree",
                "common law",
                "qualification",
                "equivalent qualification",
                "experience",
                "admissions test",
                "credit average",
                "pass average",
                "graduate certificate",
                "graduate diploma",
                "undergraduate program",
                "cognate discipline",
                "related field",
                "80%",
                "65 percent",
                "concurrently enrolled",
                "legal reasoning",
            ]
        ):
            continue
        pathway = {
            "summary": snippet,
            "qualification": _find_first(
                snippet,
                [
                    r"bachelor(?:'s)? degree",
                    r"postgraduate degree",
                    r"master(?:'s)? degree",
                    r"honours(?: degree)?",
                    r"graduate certificate",
                    r"graduate diploma",
                    r"undergraduate program",
                    r"qualification",
                    r"higher degree",
                    r"thesis",
                ],
            ),
            "discipline": _find_first(
                snippet,
                [
                    r"business",
                    r"commerce",
                    r"law",
                    r"common law",
                    r"related discipline",
                    r"cognate discipline",
                    r"non-business",
                    r"architecture",
                    r"design",
                    r"engineering",
                    r"computer science",
                    r"health",
                    r"policy",
                    r"project management",
                    r"related field",
                    r"any discipline",
                ],
            ),
            "grade_requirement": _find_first(
                snippet,
                [
                    r"credit average(?:\s*\(\d+\s*percent\))?",
                    r"pass average",
                    r"distinction",
                    r"standard acceptable",
                    r"first class honours",
                    r"second class honours",
                    r"outstanding results",
                    r"at least \d+\s*%",
                    r"\d+\s*percent",
                    r"average mark of at least \d+",
                ],
            ),
            "work_experience": _find_first(
                snippet,
                [
                    r"\b\d+\s+year[s]?\s+relevant work experience",
                    r"\b\d+\s+year[s]?\s+of\s+work experience",
                    r"\b\d+\s+year[s]?\s+of\s+relevant professional experience",
                    r"professional experience",
                    r"work experience",
                ],
            ),
            "admissions_test": _find_first(snippet, [r"admissions test", r"legal reasoning", r"statement of intent", r"research proposal"]),
            "logic": "OR",
        }
        if any(value for key, value in pathway.items() if key not in {"summary", "logic"}):
            pathways.append(pathway)
    return pathways


def parse_language_tests(text: str, source_url: str, source_type: str, source_priority: int) -> list[dict]:
    normalized = normalize_text(text)
    matches: list[dict] = []
    for pattern, test_name in [
        (IELTS_RE, "IELTS Academic"),
        (TOEFL_RE, "TOEFL iBT"),
        (PTE_RE, "PTE Academic"),
        (LANGUAGECERT_RE, "LanguageCert Academic"),
    ]:
        match = pattern.search(normalized)
        if match:
            component_scores = {}
            band = match.groupdict().get("band")
            if band:
                component_scores = {
                    "listening": band,
                    "reading": band,
                    "speaking": band,
                    "writing": band,
                }
            matches.append(
                {
                    "test_name": test_name,
                    "overall": match.group("overall"),
                    "component_scores": component_scores,
                    "raw_text": normalized,
                    "source_url": source_url,
                    "source_type": source_type,
                    "source_priority": source_priority,
                }
            )
    for match in CAMBRIDGE_RE.finditer(normalized):
        level = normalize_text(match.group("level")).title()
        matches.append(
            {
                "test_name": f"Cambridge {level}",
                "overall": match.group("overall"),
                "component_scores": {},
                "raw_text": normalized,
                "source_url": source_url,
                "source_type": source_type,
                "source_priority": source_priority,
            }
        )
    return matches


def parse_application_details(text: str) -> dict:
    normalized = normalize_text(text)
    lowered = normalized.casefold()
    required_documents: list[str] = []
    doc_markers = {
        "portfolio": "Portfolio",
        "personal statement": "Personal statement",
        "statement of intent": "Personal statement",
        "supplementary form": "Supplementary form",
        "cv": "CV",
        "resume": "Resume",
        "references": "References",
        "referees": "References",
        "work experience": "Work experience evidence",
    }
    for needle, label in doc_markers.items():
        if needle in lowered:
            required_documents.append(label)

    selection_notes: list[str] = []
    for marker in ["limited places", "quota applies", "rolling basis", "approval and availability"]:
        if marker in lowered:
            selection_notes.append(_extract_sentence(normalized, marker))

    return {
        "required_documents": required_documents,
        "requires_portfolio": "portfolio" in lowered,
        "requires_personal_statement": "personal statement" in lowered or "statement of intent" in lowered,
        "requires_supplementary_form": "supplementary form" in lowered,
        "requires_cv_or_resume": "cv" in lowered or "resume" in lowered,
        "requires_references": "references" in lowered or "referees" in lowered,
        "requires_work_experience": "work experience" in lowered,
        "limited_places": "limited places" in lowered,
        "quota_applies": "quota applies" in lowered,
        "selection_notes": selection_notes,
        "raw_text": normalized,
    }


def build_english_req_details(payload) -> dict:
    tests = []
    ielts = None
    for test in payload.language_tests:
        test_row = test.model_dump()
        tests.append(test_row)
        if test.test_name == "IELTS Academic":
            ielts = test
    return {
        "language_tests": tests,
        "academic_pathways": [pathway.model_dump() for pathway in payload.academic_pathways],
        "application_details": payload.application_details.model_dump(),
        "supplementary_metadata": payload.supplementary_metadata,
        "source_map": payload.source_map,
        "source_notes": payload.notes,
        "ielts_subscores": ielts.component_scores if ielts else {},
    }


def build_source_fingerprint(payload) -> str:
    serialized = {
        "canonical_url": payload.canonical_url,
        "academic_requirement_text": payload.academic_requirement_text,
        "raw_english_requirement": payload.raw_english_requirement,
        "language_tests": [test.model_dump() for test in payload.language_tests],
        "application_details": payload.application_details.model_dump(),
        "supplementary_metadata": payload.supplementary_metadata,
    }
    blob = json.dumps(serialized, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _find_first(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return normalize_text(match.group(0))
    return None


def _extract_sentence(text: str, marker: str) -> str:
    match = re.search(rf"[^.]*{re.escape(marker)}[^.]*\.?", text, re.IGNORECASE)
    if not match:
        return marker
    return normalize_text(match.group(0))
