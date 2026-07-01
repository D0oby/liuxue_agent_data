from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import re
from typing import Any


@dataclass(frozen=True)
class TextSection:
    kind: str
    title: str
    body: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AdmissionChunk:
    kind: str
    chunk_index: int
    content: str
    content_hash: str
    metadata: dict[str, Any]


def build_chunks(
    *,
    course_name: str,
    cricos: str,
    sections: list[TextSection],
    max_chars: int = 1200,
    overlap_chars: int = 160,
) -> list[AdmissionChunk]:
    chunks: list[AdmissionChunk] = []
    for section in sections:
        body = normalize_text(section.body)
        if not body:
            continue

        prefixed_text = "\n".join(
            [
                f"Course: {course_name}",
                f"CRICOS: {cricos}",
                f"Section: {section.title}",
                "",
                body,
            ]
        )
        for index, chunk_text in enumerate(split_text(prefixed_text, max_chars, overlap_chars)):
            metadata = dict(section.metadata)
            metadata.update(
                {
                    "course_name": course_name,
                    "cricos": cricos,
                    "section": section.title,
                }
            )
            chunks.append(
                AdmissionChunk(
                    kind=section.kind,
                    chunk_index=index,
                    content=chunk_text,
                    content_hash=hash_content(chunk_text),
                    metadata=metadata,
                )
            )
    return chunks


def split_text(text: str, max_chars: int = 1200, overlap_chars: int = 160) -> list[str]:
    if max_chars <= 0:
        raise ValueError("max_chars must be greater than zero.")
    if overlap_chars < 0:
        raise ValueError("overlap_chars cannot be negative.")
    if overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be smaller than max_chars.")

    normalized = normalize_text(text)
    if not normalized:
        return []
    if len(normalized) <= max_chars:
        return [normalized]

    chunks: list[str] = []
    current_parts: list[str] = []
    current_length = 0

    for part in _sentence_parts(normalized):
        if len(part) > max_chars:
            if current_parts:
                chunks.append(" ".join(current_parts).strip())
                current_parts = []
                current_length = 0
            chunks.extend(_split_long_part(part, max_chars, overlap_chars))
            continue

        separator_length = 1 if current_parts else 0
        would_exceed = current_length + separator_length + len(part) > max_chars
        if would_exceed and current_parts:
            chunk = " ".join(current_parts).strip()
            chunks.append(chunk)
            overlap = _tail_overlap(chunk, overlap_chars)
            current_parts = [overlap] if overlap and len(overlap) + 1 + len(part) <= max_chars else []
            current_length = len(overlap) if current_parts else 0

        if current_parts:
            current_length += 1 + len(part)
        else:
            current_length = len(part)
        current_parts.append(part)

    if current_parts:
        chunks.append(" ".join(current_parts).strip())

    return [chunk for chunk in chunks if chunk]


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def hash_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _sentence_parts(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", text)
    return [part.strip() for part in parts if part.strip()]


def _split_long_part(part: str, max_chars: int, overlap_chars: int) -> list[str]:
    chunks: list[str] = []
    start = 0
    while start < len(part):
        end = min(start + max_chars, len(part))
        if end < len(part):
            break_at = part.rfind(" ", start, end)
            if break_at > start:
                end = break_at
        chunk = part[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(part):
            break
        start = max(end - overlap_chars, start + 1)
        while start < len(part) and part[start].isspace():
            start += 1
    return chunks


def _tail_overlap(chunk: str, overlap_chars: int) -> str:
    if overlap_chars == 0 or len(chunk) <= overlap_chars:
        return ""
    tail = chunk[-overlap_chars:].strip()
    first_space = tail.find(" ")
    if first_space > 0:
        tail = tail[first_space + 1 :].strip()
    return tail
