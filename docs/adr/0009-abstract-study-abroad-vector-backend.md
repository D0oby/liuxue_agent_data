# Abstract Study Abroad Vector Backend

Study Abroad Knowledge RAG will define narrow protocols for embedding, dense search, sparse search, and index storage instead of binding the core retrieval path directly to Chroma or OpenAI. The default runtime can use OpenAI embeddings and Chroma persistent storage, while deterministic test embedders and future local or pgvector-backed implementations can share the same search and Ranking Policy behavior.
