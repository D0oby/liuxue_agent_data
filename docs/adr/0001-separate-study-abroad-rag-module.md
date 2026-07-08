# Separate Study Abroad RAG From USYD Recommendation

The Study Abroad Knowledge RAG will be built as an independent retrieval module rather than by expanding the existing USYD recommendation layer. This preserves the current read-only USYD admissions recommendation boundary while allowing the new system to index broader source types such as official policy pages, study-abroad posts, and anonymous internal datasets with its own hybrid retrieval, ranking, and evidence contracts.
