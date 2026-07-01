from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Protocol

from src.config import RecommendationConfig
from src.models.recommendation import (
    CourseCandidate,
    EvidenceSnippet,
    KeywordSearchHit,
    QuerySpec,
    UserProfile,
    VectorSearchHit,
)
from src.recommendation.query_builder import QueryBuilder
from src.recommendation.repository import CourseSearchRow, RecommendationRepository
from src.vector_store.storage import SearchResult


logger = logging.getLogger(__name__)


class EmbeddingClient(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...


class VectorSearchStore(Protocol):
    def search_admission_chunks(
        self,
        *,
        query_embedding: list[float],
        embedding_model: str,
        top_k: int,
    ) -> list[SearchResult]:
        ...


@dataclass(frozen=True)
class RetrievalResult:
    query_spec: QuerySpec
    candidates: list[CourseCandidate]
    degraded_retrieval: bool = False


class KeywordRetriever:
    FIELD_WEIGHTS = {
        "course_name": 0.55,
        "course_name_raw": 0.45,
        "cricos": 0.3,
        "academic_requirement_text": 0.25,
        "raw_english_requirement": 0.15,
    }

    def __init__(self, repository: RecommendationRepository) -> None:
        self.repository = repository

    def retrieve(
        self,
        conn,
        *,
        query_spec: QuerySpec,
        top_k: int,
        request_id: str,
    ) -> list[KeywordSearchHit]:
        rows = self.repository.search_courses_by_keywords(
            conn,
            keywords=query_spec.keywords,
            limit=top_k,
        )
        hits: list[KeywordSearchHit] = []
        for row in rows:
            hit_fields = self._matched_fields(row, query_spec.keywords)
            keyword_score = min(sum(self.FIELD_WEIGHTS[field] for field in hit_fields), 1.0)
            if keyword_score <= 0:
                continue
            hits.append(
                KeywordSearchHit(
                    course_id=row.course_id,
                    course_name=row.course_name,
                    cricos=row.cricos,
                    duration_min_years=row.duration_min_years,
                    duration_max_years=row.duration_max_years,
                    tuition_fee_aud=row.tuition_fee_aud,
                    academic_requirement_text=row.academic_requirement_text,
                    raw_english_requirement=row.raw_english_requirement,
                    ielts_overall_required=row.ielts_overall_required,
                    ielts_min_band_required=row.ielts_min_band_required,
                    ielts_listening_required=row.ielts_listening_required,
                    ielts_reading_required=row.ielts_reading_required,
                    ielts_speaking_required=row.ielts_speaking_required,
                    ielts_writing_required=row.ielts_writing_required,
                    academic_requirements_json=row.academic_requirements_json or {},
                    application_details_json=row.application_details_json or {},
                    supplementary_metadata_json=row.supplementary_metadata_json or {},
                    course_features=row.course_features,
                    source_url=row.source_url,
                    hit_fields=hit_fields,
                    keyword_score=keyword_score,
                    retrieval_reason=self._build_reason(hit_fields, query_spec.keywords),
                    evidence_snippets=self._build_evidence(row, query_spec.keywords),
                )
            )
        logger.info("keyword retrieval completed", extra={"request_id": request_id, "count": len(hits)})
        return hits

    def _matched_fields(self, row: CourseSearchRow, keywords: list[str]) -> list[str]:
        field_values = {
            "course_name": row.course_name,
            "course_name_raw": row.course_name_raw,
            "cricos": row.cricos,
            "academic_requirement_text": row.academic_requirement_text,
            "raw_english_requirement": row.raw_english_requirement,
        }
        matched_fields: list[str] = []
        for field_name, value in field_values.items():
            lowered = value.casefold()
            if any(keyword.casefold() in lowered for keyword in keywords):
                matched_fields.append(field_name)
        return matched_fields

    def _build_reason(self, hit_fields: list[str], keywords: list[str]) -> str:
        return f"Keyword matched {', '.join(hit_fields)} for: {', '.join(keywords)}"

    def _build_evidence(self, row: CourseSearchRow, keywords: list[str]) -> list[EvidenceSnippet]:
        snippets: list[EvidenceSnippet] = []
        for source, text in [
            ("course_name", row.course_name),
            ("academic_requirement_text", row.academic_requirement_text),
            ("raw_english_requirement", row.raw_english_requirement),
        ]:
            snippet = _extract_snippet(text, keywords)
            if snippet:
                snippets.append(EvidenceSnippet(text=snippet, source_url=row.source_url, source=source))
        return snippets


class VectorRetriever:
    def __init__(
        self,
        repository: RecommendationRepository,
        *,
        embedding_client: EmbeddingClient | None,
        embedding_model: str,
        vector_store: VectorSearchStore | None = None,
    ) -> None:
        self.repository = repository
        self.embedding_client = embedding_client
        self.embedding_model = embedding_model
        self.vector_store = vector_store

    def retrieve(
        self,
        conn,
        *,
        query_spec: QuerySpec,
        top_k: int,
        request_id: str,
    ) -> list[VectorSearchHit]:
        if self.embedding_client is None:
            raise RuntimeError("Vector retrieval requires an embedding client.")
        if self.vector_store is None:
            raise RuntimeError("Vector retrieval requires a ChromaDB vector store.")
        query_embedding = self.embedding_client.embed_texts([query_spec.semantic_query])[0]
        rows = self.vector_store.search_admission_chunks(
            query_embedding=query_embedding,
            embedding_model=self.embedding_model,
            top_k=top_k,
        )
        hits = [
            VectorSearchHit(
                course_id=row.course_id,
                course_name=row.course_name,
                cricos=row.cricos,
                chunk_text=row.content,
                chunk_source=row.chunk_kind,
                source_url=row.source_url,
                vector_score=row.similarity,
                retrieval_reason=f"Semantic admissions chunk matched query: {query_spec.semantic_query}",
                evidence_snippets=[
                    EvidenceSnippet(
                        text=_trim_text(row.content),
                        source_url=row.source_url,
                        source=row.chunk_kind,
                    )
                ],
            )
            for row in rows
        ]
        logger.info("vector retrieval completed", extra={"request_id": request_id, "count": len(hits)})
        return hits


class CandidateMerger:
    def merge(
        self,
        *,
        keyword_hits: list[KeywordSearchHit],
        vector_hits: list[VectorSearchHit],
        course_rows: dict[str, CourseSearchRow],
        intakes_by_course_id: dict[str, list[str]],
        final_candidate_limit: int,
        evidence_snippet_limit: int,
    ) -> list[CourseCandidate]:
        merged: dict[str, CourseCandidate] = {}

        for hit in keyword_hits:
            merged[hit.course_id] = CourseCandidate(
                course_id=hit.course_id,
                course_name=hit.course_name,
                cricos=hit.cricos,
                duration_min_years=hit.duration_min_years,
                duration_max_years=hit.duration_max_years,
                tuition_fee_aud=hit.tuition_fee_aud,
                intakes=intakes_by_course_id.get(hit.course_id, []),
                academic_requirement_text=hit.academic_requirement_text,
                raw_english_requirement=hit.raw_english_requirement,
                ielts_overall_required=hit.ielts_overall_required,
                ielts_min_band_required=hit.ielts_min_band_required,
                ielts_listening_required=hit.ielts_listening_required,
                ielts_reading_required=hit.ielts_reading_required,
                ielts_speaking_required=hit.ielts_speaking_required,
                ielts_writing_required=hit.ielts_writing_required,
                academic_requirements_json=hit.academic_requirements_json,
                application_details_json=hit.application_details_json,
                supplementary_metadata_json=hit.supplementary_metadata_json,
                course_features=hit.course_features,
                degree_type=_infer_degree_type(hit.course_name),
                faculty=_extract_metadata_text(hit.supplementary_metadata_json, "faculty"),
                school=_extract_metadata_text(hit.supplementary_metadata_json, "school"),
                campus=_extract_metadata_text(hit.supplementary_metadata_json, "campus"),
                study_mode=_extract_metadata_text(hit.supplementary_metadata_json, "study_mode"),
                retrieval_score=hit.keyword_score,
                retrieval_reason=hit.retrieval_reason,
                keyword_score=hit.keyword_score,
                vector_score=0.0,
                combined_retrieval_score=hit.keyword_score,
                evidence_snippets=hit.evidence_snippets[:evidence_snippet_limit],
                source_url=hit.source_url,
            )

        for hit in vector_hits:
            current = merged.get(hit.course_id)
            course_row = course_rows.get(hit.course_id)
            if current is None:
                if course_row is None:
                    continue
                current = CourseCandidate(
                    course_id=hit.course_id,
                    course_name=course_row.course_name,
                    cricos=course_row.cricos,
                    duration_min_years=course_row.duration_min_years,
                    duration_max_years=course_row.duration_max_years,
                    tuition_fee_aud=course_row.tuition_fee_aud,
                    intakes=intakes_by_course_id.get(hit.course_id, []),
                    academic_requirement_text=course_row.academic_requirement_text,
                    raw_english_requirement=course_row.raw_english_requirement,
                    ielts_overall_required=course_row.ielts_overall_required,
                    ielts_min_band_required=course_row.ielts_min_band_required,
                    ielts_listening_required=course_row.ielts_listening_required,
                    ielts_reading_required=course_row.ielts_reading_required,
                    ielts_speaking_required=course_row.ielts_speaking_required,
                    ielts_writing_required=course_row.ielts_writing_required,
                    academic_requirements_json=course_row.academic_requirements_json or {},
                    application_details_json=course_row.application_details_json or {},
                    supplementary_metadata_json=course_row.supplementary_metadata_json or {},
                    course_features=course_row.course_features,
                    degree_type=_infer_degree_type(course_row.course_name),
                    faculty=_extract_metadata_text(course_row.supplementary_metadata_json or {}, "faculty"),
                    school=_extract_metadata_text(course_row.supplementary_metadata_json or {}, "school"),
                    campus=_extract_metadata_text(course_row.supplementary_metadata_json or {}, "campus"),
                    study_mode=_extract_metadata_text(course_row.supplementary_metadata_json or {}, "study_mode"),
                    retrieval_score=hit.vector_score,
                    retrieval_reason=hit.retrieval_reason,
                    keyword_score=0.0,
                    vector_score=hit.vector_score,
                    combined_retrieval_score=hit.vector_score,
                    evidence_snippets=hit.evidence_snippets[:evidence_snippet_limit],
                    source_url=hit.source_url or course_row.source_url,
                )
                merged[hit.course_id] = current
                continue

            evidence = _dedupe_evidence(
                current.evidence_snippets + hit.evidence_snippets,
                evidence_snippet_limit,
            )
            best_vector_score = max(current.vector_score, hit.vector_score)
            combined_score = self._combined_score(current.keyword_score, best_vector_score)
            merged[hit.course_id] = current.model_copy(
                update={
                    "vector_score": best_vector_score,
                    "combined_retrieval_score": combined_score,
                    "retrieval_score": combined_score,
                    "retrieval_reason": f"{current.retrieval_reason}; {hit.retrieval_reason}",
                    "evidence_snippets": evidence,
                    "source_url": current.source_url or hit.source_url,
                }
            )

        return sorted(
            merged.values(),
            key=lambda candidate: candidate.combined_retrieval_score,
            reverse=True,
        )[:final_candidate_limit]

    def _combined_score(self, keyword_score: float, vector_score: float) -> float:
        if keyword_score > 0 and vector_score > 0:
            return min(keyword_score + vector_score + 0.15, 1.5)
        return max(keyword_score, vector_score)


class AdmissionsRAGService:
    def __init__(
        self,
        *,
        repository: RecommendationRepository,
        query_builder: QueryBuilder,
        keyword_retriever: KeywordRetriever,
        vector_retriever: VectorRetriever,
        candidate_merger: CandidateMerger,
        config: RecommendationConfig,
    ) -> None:
        self.repository = repository
        self.query_builder = query_builder
        self.keyword_retriever = keyword_retriever
        self.vector_retriever = vector_retriever
        self.candidate_merger = candidate_merger
        self.config = config

    def search(self, conn, *, user_profile: UserProfile, request_id: str) -> RetrievalResult:
        query_spec = self.query_builder.build(user_profile.target_major_keyword)
        keyword_hits = self.keyword_retriever.retrieve(
            conn,
            query_spec=query_spec,
            top_k=self.config.retrieval.keyword_top_k,
            request_id=request_id,
        )

        degraded_retrieval = False
        try:
            vector_hits = self.vector_retriever.retrieve(
                conn,
                query_spec=query_spec,
                top_k=self.config.retrieval.vector_top_k,
                request_id=request_id,
            )
        except Exception as exc:
            degraded_retrieval = True
            vector_hits = []
            logger.error(
                "vector retrieval failed; degrading to keyword retrieval",
                extra={"request_id": request_id},
                exc_info=True,
            )

        all_course_ids = sorted({hit.course_id for hit in keyword_hits} | {hit.course_id for hit in vector_hits})
        course_rows = self.repository.fetch_courses_by_ids(conn, course_ids=all_course_ids)
        intakes_by_course_id = self.repository.fetch_intakes_by_course_ids(conn, course_ids=all_course_ids)
        candidates = self.candidate_merger.merge(
            keyword_hits=keyword_hits,
            vector_hits=vector_hits,
            course_rows=course_rows,
            intakes_by_course_id=intakes_by_course_id,
            final_candidate_limit=self.config.retrieval.final_candidate_limit,
            evidence_snippet_limit=self.config.retrieval.evidence_snippet_limit,
        )
        return RetrievalResult(
            query_spec=query_spec,
            candidates=candidates,
            degraded_retrieval=degraded_retrieval,
        )


def _dedupe_evidence(snippets: list[EvidenceSnippet], limit: int) -> list[EvidenceSnippet]:
    deduped: list[EvidenceSnippet] = []
    seen: set[str] = set()
    for snippet in snippets:
        key = snippet.text.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(snippet)
        if len(deduped) >= limit:
            break
    return deduped


def _extract_snippet(text: str, keywords: list[str], limit: int = 240) -> str:
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return ""
    lowered = cleaned.casefold()
    first_match = min(
        (lowered.find(keyword.casefold()) for keyword in keywords if lowered.find(keyword.casefold()) != -1),
        default=-1,
    )
    if first_match == -1:
        return _trim_text(cleaned, limit=limit)
    start = max(first_match - 80, 0)
    end = min(start + limit, len(cleaned))
    return _trim_text(cleaned[start:end], limit=limit)


def _trim_text(text: str, limit: int = 240) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "..."


def _infer_degree_type(course_name: str) -> str | None:
    lowered = course_name.casefold()
    degree_patterns = [
        "master",
        "graduate diploma",
        "graduate certificate",
        "doctor",
        "juris doctor",
        "phd",
    ]
    for pattern in degree_patterns:
        if pattern in lowered:
            return pattern.title()
    return None


def _extract_metadata_text(metadata: dict[str, object], key: str) -> str | None:
    value = metadata.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        normalized = " ".join(value.split()).strip()
        return normalized or None
    if isinstance(value, list):
        labels = [" ".join(str(item).split()).strip() for item in value if str(item).strip()]
        return ", ".join(labels) or None
    return str(value)
