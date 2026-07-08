# Use Manifest-Backed Sources For Study Abroad RAG

Study Abroad Knowledge RAG will index only read-only sources declared through a source manifest in its first version, even when the underlying content comes from posts or anonymous internal datasets. This keeps source identity, freshness, trust metadata, and filter metadata explicit, instead of coupling retrieval to ad hoc scans of future business database tables.
