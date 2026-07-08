# Start With Cache Metadata Before Persistent Cache

Study Abroad Knowledge RAG V1 will define cache metadata and invalidation checks before investing in full persistent index caching. The initial implementation can run primarily in memory, but it must model schema version, chunker version, tokenizer version, model name, source manifest hash, source content hashes, and creation time so later persistent caching can be added without changing the public index contract.
