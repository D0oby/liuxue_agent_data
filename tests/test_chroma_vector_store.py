from __future__ import annotations

from pathlib import Path
import unittest

from src.vector_store.chunking import AdmissionChunk, hash_content
from src.vector_store.storage import ChromaVectorStore


class ChromaVectorStoreTests(unittest.TestCase):
    def test_replace_chunks_upserts_documents_embeddings_and_metadata(self) -> None:
        collection = FakeChromaCollection()
        store = ChromaVectorStore(
            persist_directory=Path("unused"),
            collection_name="course_admission_chunks",
            collection=collection,
        )
        chunk = _chunk("Academic requirement text.")

        store.replace_admission_chunks(
            course_id="course-1",
            requirement_id="requirement-1",
            chunks=[chunk],
            embeddings=[[0.1, 0.2, 0.3]],
            embedding_model="test-model",
            source_url="https://www.sydney.edu.au/courses/test.html",
        )

        record = collection.records["requirement-1:academic:0"]
        self.assertEqual(record["document"], "Academic requirement text.")
        self.assertEqual(record["embedding"], [0.1, 0.2, 0.3])
        self.assertEqual(record["metadata"]["course_id"], "course-1")
        self.assertEqual(record["metadata"]["requirement_id"], "requirement-1")
        self.assertEqual(record["metadata"]["embedding_model"], "test-model")
        self.assertEqual(record["metadata"]["course_name"], "Master of Computer Science")

    def test_chunks_are_current_checks_hashes_model_and_embedded_timestamp(self) -> None:
        collection = FakeChromaCollection()
        store = ChromaVectorStore(
            persist_directory=Path("unused"),
            collection_name="course_admission_chunks",
            collection=collection,
        )
        chunk = _chunk("Academic requirement text.")
        store.replace_admission_chunks(
            course_id="course-1",
            requirement_id="requirement-1",
            chunks=[chunk],
            embeddings=[[0.1, 0.2, 0.3]],
            embedding_model="test-model",
            source_url=None,
        )

        self.assertTrue(
            store.chunks_are_current(
                requirement_id="requirement-1",
                chunks=[chunk],
                embedding_model="test-model",
            )
        )
        self.assertFalse(
            store.chunks_are_current(
                requirement_id="requirement-1",
                chunks=[chunk],
                embedding_model="other-model",
            )
        )

    def test_search_maps_chroma_query_results(self) -> None:
        collection = FakeChromaCollection(distances=[0.18])
        store = ChromaVectorStore(
            persist_directory=Path("unused"),
            collection_name="course_admission_chunks",
            collection=collection,
        )
        store.replace_admission_chunks(
            course_id="course-1",
            requirement_id="requirement-1",
            chunks=[_chunk("Portfolio required.")],
            embeddings=[[0.1, 0.2, 0.3]],
            embedding_model="test-model",
            source_url="https://www.sydney.edu.au/courses/test.html",
        )

        results = store.search_admission_chunks(
            query_embedding=[0.1, 0.2, 0.3],
            embedding_model="test-model",
            top_k=5,
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].course_id, "course-1")
        self.assertEqual(results[0].course_name, "Master of Computer Science")
        self.assertAlmostEqual(results[0].similarity, 0.82)
        self.assertEqual(results[0].content, "Portfolio required.")


class FakeChromaCollection:
    def __init__(self, distances: list[float] | None = None) -> None:
        self.records: dict[str, dict] = {}
        self.distances = distances or []

    def count(self) -> int:
        return len(self.records)

    def upsert(self, *, ids, embeddings, documents, metadatas) -> None:
        for record_id, embedding, document, metadata in zip(ids, embeddings, documents, metadatas, strict=True):
            self.records[record_id] = {
                "embedding": embedding,
                "document": document,
                "metadata": metadata,
            }

    def get(self, *, ids=None, where=None, include=None):
        matching_ids = self._matching_ids(ids=ids, where=where)
        result = {"ids": matching_ids}
        if include and "metadatas" in include:
            result["metadatas"] = [self.records[record_id]["metadata"] for record_id in matching_ids]
        if include and "documents" in include:
            result["documents"] = [self.records[record_id]["document"] for record_id in matching_ids]
        return result

    def delete(self, *, ids=None, where=None) -> None:
        matching_ids = self._matching_ids(ids=ids, where=where)
        for record_id in matching_ids:
            self.records.pop(record_id, None)

    def query(self, *, query_embeddings, n_results, where=None, include=None):
        matching_ids = self._matching_ids(where=where)[:n_results]
        distances = self.distances or [0.0 for _ in matching_ids]
        return {
            "ids": [matching_ids],
            "documents": [[self.records[record_id]["document"] for record_id in matching_ids]],
            "metadatas": [[self.records[record_id]["metadata"] for record_id in matching_ids]],
            "distances": [distances[: len(matching_ids)]],
        }

    def _matching_ids(self, *, ids=None, where=None) -> list[str]:
        candidate_ids = list(ids) if ids is not None else list(self.records)
        if not where:
            return [record_id for record_id in candidate_ids if record_id in self.records]
        return [
            record_id
            for record_id in candidate_ids
            if record_id in self.records
            and all(self.records[record_id]["metadata"].get(key) == value for key, value in where.items())
        ]


def _chunk(content: str) -> AdmissionChunk:
    return AdmissionChunk(
        kind="academic",
        chunk_index=0,
        content=content,
        content_hash=hash_content(content),
        metadata={
            "course_name": "Master of Computer Science",
            "cricos": "123456A",
            "section": "Academic admission requirements",
        },
    )


if __name__ == "__main__":
    unittest.main()
