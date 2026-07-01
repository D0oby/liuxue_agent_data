from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from src.vector_store.chunking import TextSection, build_chunks, normalize_text
from src.vector_store.storage import (
    AdmissionRecord,
    ChromaVectorStore,
    SearchResult,
    fetch_admission_records,
)


class EmbeddingClient(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...


@dataclass(frozen=True)
class VectorizeStats:
    records_seen: int = 0
    records_vectorized: int = 0
    records_skipped: int = 0
    chunks_built: int = 0
    chunks_embedded: int = 0


def vectorize_admissions(
    conn,
    *,
    vector_store: ChromaVectorStore,
    embedding_client: EmbeddingClient | None,
    embedding_model: str,
    source: str | None = "usyd_web_crawl",
    limit: int | None = None,
    batch_size: int = 64,
    force: bool = False,
    dry_run: bool = False,
    max_chars: int = 1200,
    overlap_chars: int = 160,
) -> VectorizeStats:
    if not dry_run and embedding_client is None:
        raise ValueError("embedding_client is required unless dry_run is true.")
    if not dry_run:
        vector_store.ensure_ready()

    records = fetch_admission_records(conn, source=source, limit=limit)
    stats = VectorizeStats(records_seen=len(records))
    vectorized = 0
    skipped = 0
    chunks_built = 0
    chunks_embedded = 0

    for record in records:
        chunks = build_chunks(
            course_name=record.course_name,
            cricos=record.cricos,
            sections=build_sections(record),
            max_chars=max_chars,
            overlap_chars=overlap_chars,
        )
        chunks_built += len(chunks)
        if not chunks:
            skipped += 1
            continue

        if dry_run:
            vectorized += 1
            continue

        if not force and vector_store.chunks_are_current(
            requirement_id=record.requirement_id,
            chunks=chunks,
            embedding_model=embedding_model,
        ):
            skipped += 1
            continue

        embeddings: list[list[float]] = []
        for batch in _batches([chunk.content for chunk in chunks], batch_size):
            embeddings.extend(embedding_client.embed_texts(batch))

        vector_store.replace_admission_chunks(
            course_id=record.course_id,
            requirement_id=record.requirement_id,
            chunks=chunks,
            embeddings=embeddings,
            embedding_model=embedding_model,
            source_url=record.source_url,
        )
        vectorized += 1
        chunks_embedded += len(chunks)

    return VectorizeStats(
        records_seen=stats.records_seen,
        records_vectorized=vectorized,
        records_skipped=skipped,
        chunks_built=chunks_built,
        chunks_embedded=chunks_embedded,
    )


def search_admissions(
    *,
    vector_store: ChromaVectorStore,
    embedding_client: EmbeddingClient,
    embedding_model: str,
    query: str,
    top_k: int,
) -> list[SearchResult]:
    vector_store.ensure_ready()
    query_embedding = embedding_client.embed_texts([query])[0]
    return vector_store.search_admission_chunks(
        query_embedding=query_embedding,
        embedding_model=embedding_model,
        top_k=top_k,
    )


def build_sections(record: AdmissionRecord) -> list[TextSection]:
    sections: list[TextSection] = []
    base_metadata = {
        "requirement_id": record.requirement_id,
        "requirement_source": record.requirement_source,
        "source_fingerprint": record.source_fingerprint,
    }

    if normalize_text(record.academic_requirement_text):
        sections.append(
            TextSection(
                kind="academic",
                title="Academic admission requirements",
                body=record.academic_requirement_text,
                metadata={**base_metadata, "field": "academic_requirement_text"},
            )
        )

    if normalize_text(record.raw_english_requirement):
        sections.append(
            TextSection(
                kind="english",
                title="English language requirements",
                body=record.raw_english_requirement,
                metadata={**base_metadata, "field": "raw_english_requirement"},
            )
        )

    application_text = _format_application_details(record.application_details_json)
    if application_text:
        sections.append(
            TextSection(
                kind="application",
                title="Application details",
                body=application_text,
                metadata={**base_metadata, "field": "application_details_json"},
            )
        )
    return sections


def _format_application_details(details: dict) -> str:
    if not details:
        return ""

    lines: list[str] = []
    raw_text = normalize_text(details.get("raw_text"))
    if raw_text:
        lines.append(raw_text)

    documents = [
        normalize_text(item)
        for item in details.get("required_documents", [])
        if normalize_text(item)
    ]
    if documents:
        lines.append("Required documents: " + "; ".join(documents))

    flag_labels = {
        "requires_portfolio": "Portfolio required",
        "requires_personal_statement": "Personal statement required",
        "requires_supplementary_form": "Supplementary form required",
        "requires_cv_or_resume": "CV or resume required",
        "requires_references": "References required",
        "requires_work_experience": "Work experience required",
        "limited_places": "Limited places",
        "quota_applies": "Quota applies",
    }
    enabled_flags = [label for key, label in flag_labels.items() if details.get(key)]
    if enabled_flags:
        lines.append("Application flags: " + "; ".join(enabled_flags))

    selection_notes = [
        normalize_text(item)
        for item in details.get("selection_notes", [])
        if normalize_text(item)
    ]
    if selection_notes:
        lines.append("Selection notes: " + "; ".join(selection_notes))

    return normalize_text(" ".join(lines))


def _batches(items: list[str], batch_size: int) -> list[list[str]]:
    return [items[index : index + batch_size] for index in range(0, len(items), batch_size)]
