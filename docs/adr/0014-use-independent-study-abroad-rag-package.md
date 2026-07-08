# Use Independent Study Abroad RAG Package

Study Abroad Knowledge RAG V1 will live in its own `src/study_abroad_rag/` package with Semble-inspired internal modules for types, config, manifests, loaders, chunking, tokenization, sparse and dense retrieval, fusion, ranking, privacy, cache, index, and formatting. The public surface remains the index and DTO contract, while `src/recommendation/` and `src/vector_store/` keep their existing USYD-specific responsibilities.
