# Stabilize Study Abroad Python API

Study Abroad Knowledge RAG V1 will expose a narrow Python API: `StudyAbroadRAGIndex.from_sources(...)`, `StudyAbroadRAGIndex.from_path(...)`, `index.search(...)`, and `index.find_related(...)`. Callers receive project DTOs and serializable results, while loader, chunker, sparse index, dense index, RRF fusion, and Ranking Policy internals remain hidden; fusion weights are not exposed directly and ranking behavior is controlled through query intent and configuration.
