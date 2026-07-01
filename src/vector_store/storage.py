from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from src.vector_store.chunking import AdmissionChunk


@dataclass(frozen=True)
class AdmissionRecord:
    course_id: str
    requirement_id: str
    course_name: str
    cricos: str
    requirement_source: str
    source_url: str | None
    academic_requirement_text: str
    raw_english_requirement: str
    application_details_json: dict[str, Any]
    source_fingerprint: str | None


@dataclass(frozen=True)
class SearchResult:
    course_id: str
    course_name: str
    cricos: str
    chunk_kind: str
    content: str
    source_url: str | None
    similarity: float
    metadata: dict[str, Any]


class ChromaVectorStoreError(RuntimeError):
    pass


class ChromaVectorStore:
    def __init__(
        self,
        *,
        persist_directory: str | Path,
        collection_name: str,
        collection: Any | None = None,
    ) -> None:
        self.persist_directory = Path(persist_directory)
        self.collection_name = collection_name
        self._collection = collection

    @classmethod
    def from_settings(cls, settings: Any) -> "ChromaVectorStore":
        return cls(
            persist_directory=settings.chroma_persist_directory,
            collection_name=settings.chroma_collection_name,
        )

    @property
    def collection(self) -> Any:
        if self._collection is None:
            self._collection = self._create_collection()
        return self._collection

    def ensure_ready(self) -> None:
        self.persist_directory.mkdir(parents=True, exist_ok=True)
        self.collection.count()

    def chunks_are_current(
        self,
        *,
        requirement_id: str,
        chunks: list[AdmissionChunk],
        embedding_model: str,
    ) -> bool:
        if not chunks:
            return False

        expected_ids = {_chunk_id(requirement_id, chunk) for chunk in chunks}
        expected_hashes = {chunk.content_hash for chunk in chunks}
        result = self.collection.get(ids=list(expected_ids), include=["metadatas"])
        existing_ids = set(result.get("ids") or [])
        metadatas = [metadata for metadata in result.get("metadatas") or [] if isinstance(metadata, dict)]

        return (
            existing_ids == expected_ids
            and {metadata.get("content_hash") for metadata in metadatas} == expected_hashes
            and all(metadata.get("embedding_model") == embedding_model for metadata in metadatas)
            and all(metadata.get("embedded_at") for metadata in metadatas)
        )

    def replace_admission_chunks(
        self,
        *,
        course_id: str,
        requirement_id: str,
        chunks: list[AdmissionChunk],
        embeddings: list[list[float]],
        embedding_model: str,
        source_url: str | None,
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("Chunk and embedding counts must match.")

        self._delete_requirement_chunks(requirement_id)
        if not chunks:
            return

        embedded_at = datetime.now(timezone.utc).isoformat()
        ids = [_chunk_id(requirement_id, chunk) for chunk in chunks]
        documents = [chunk.content for chunk in chunks]
        metadatas = [
            _build_chroma_metadata(
                course_id=course_id,
                requirement_id=requirement_id,
                chunk=chunk,
                embedding_model=embedding_model,
                source_url=source_url,
                embedded_at=embedded_at,
            )
            for chunk in chunks
        ]
        self.collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )

    def search_admission_chunks(
        self,
        *,
        query_embedding: list[float],
        embedding_model: str,
        top_k: int = 5,
    ) -> list[SearchResult]:
        result = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where={"embedding_model": embedding_model},
            include=["documents", "metadatas", "distances"],
        )
        documents = _first_batch(result.get("documents"))
        metadatas = _first_batch(result.get("metadatas"))
        distances = _first_batch(result.get("distances"))

        search_results: list[SearchResult] = []
        for document, metadata, distance in zip(documents, metadatas, distances, strict=False):
            if not isinstance(metadata, dict):
                continue
            course_id = str(metadata.get("course_id") or "").strip()
            if not course_id:
                continue
            source_url = str(metadata.get("source_url") or "").strip() or None
            search_results.append(
                SearchResult(
                    course_id=course_id,
                    course_name=str(metadata.get("course_name") or ""),
                    cricos=str(metadata.get("cricos") or ""),
                    chunk_kind=str(metadata.get("chunk_kind") or ""),
                    content=str(document or ""),
                    source_url=source_url,
                    similarity=1 - float(distance),
                    metadata=dict(metadata),
                )
            )
        return search_results

    def _create_collection(self) -> Any:
        try:
            import chromadb
        except ImportError as exc:
            raise ChromaVectorStoreError(
                "chromadb is required for vector storage. Install project dependencies with `pip install -e .`."
            ) from exc

        self.persist_directory.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=str(self.persist_directory))
        return client.get_or_create_collection(
            name=self.collection_name,
            metadata={"description": "USYD admissions chunks with externally generated embeddings"},
            configuration={"hnsw": {"space": "cosine"}},
        )

    def _delete_requirement_chunks(self, requirement_id: str) -> None:
        existing = self.collection.get(where={"requirement_id": requirement_id}, include=[])
        ids = existing.get("ids") or []
        if ids:
            self.collection.delete(ids=ids)


def fetch_admission_records(conn, *, source: str | None = "usyd_web_crawl", limit: int | None = None) -> list[AdmissionRecord]:
    where_clauses = [
        "car.is_current = true",
        """(
            coalesce(car.academic_requirement_text, '') <> ''
            or coalesce(car.raw_english_requirement, '') <> ''
            or coalesce(car.application_details_json->>'raw_text', '') <> ''
        )""",
    ]
    params: list[object] = []
    if source:
        where_clauses.append("car.requirement_source = %s")
        params.append(source)

    limit_sql = ""
    if limit is not None:
        limit_sql = "limit %s"
        params.append(limit)

    with conn.cursor() as cur:
        cur.execute(
            f"""
            select
                c.id::text,
                car.id::text,
                c.course_name,
                c.cricos,
                car.requirement_source,
                car.source_url,
                coalesce(car.academic_requirement_text, ''),
                coalesce(car.raw_english_requirement, ''),
                car.application_details_json,
                car.source_fingerprint
            from course_admission_requirements car
            join courses c on c.id = car.course_id
            where {" and ".join(where_clauses)}
            order by c.course_name, car.requirement_version desc
            {limit_sql}
            """,
            params,
        )
        return [
            AdmissionRecord(
                course_id=row[0],
                requirement_id=row[1],
                course_name=row[2],
                cricos=row[3],
                requirement_source=row[4],
                source_url=row[5],
                academic_requirement_text=row[6],
                raw_english_requirement=row[7],
                application_details_json=_as_dict(row[8]),
                source_fingerprint=row[9],
            )
            for row in cur.fetchall()
        ]


def _as_dict(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    return {}


def _chunk_id(requirement_id: str, chunk: AdmissionChunk) -> str:
    return f"{requirement_id}:{chunk.kind}:{chunk.chunk_index}"


def _build_chroma_metadata(
    *,
    course_id: str,
    requirement_id: str,
    chunk: AdmissionChunk,
    embedding_model: str,
    source_url: str | None,
    embedded_at: str,
) -> dict[str, str | int | float | bool]:
    metadata: dict[str, str | int | float | bool] = {
        "course_id": course_id,
        "requirement_id": requirement_id,
        "chunk_kind": chunk.kind,
        "chunk_index": chunk.chunk_index,
        "content_hash": chunk.content_hash,
        "embedding_model": embedding_model,
        "embedded_at": embedded_at,
    }
    if source_url:
        metadata["source_url"] = source_url

    for key, value in chunk.metadata.items():
        if value is None:
            continue
        if isinstance(value, (bool, int, float, str)):
            metadata[key] = value
        else:
            metadata[key] = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return metadata


def _first_batch(value: object) -> list[Any]:
    if not isinstance(value, list) or not value:
        return []
    first = value[0]
    return first if isinstance(first, list) else []
