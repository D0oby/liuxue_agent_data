# Separate RRF Fusion From Ranking Policy

Study Abroad Knowledge RAG will keep hybrid retrieval fusion and domain ranking separate: dense and sparse retrievers are fused with RRF to produce an `rrf_score`, then a configurable Ranking Policy computes `final_score` and `ranking_reasons`. Ranking Policy owns trust-tier boosts, source-type boosts and penalties, freshness penalties, filter-match boosts, mismatch penalties, privacy penalties, source saturation, and query-intent boosts, so search fusion remains mechanical while study-abroad evidence judgment stays configurable and explainable.
