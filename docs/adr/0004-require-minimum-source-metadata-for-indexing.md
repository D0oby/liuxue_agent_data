# Require Minimum Source Metadata For Indexing

Study Abroad Knowledge RAG will reject manifest entries that do not provide `source_id`, `source_type`, `title`, a stable locator, a content locator, freshness metadata, `trust_tier`, and `language`. This makes freshness penalties, trust boosts, cache invalidation, and source attribution reliable; optional fields such as country, institution, program, degree level, intake, and tags can improve filtering and ranking when present without becoming V1 indexing blockers.
