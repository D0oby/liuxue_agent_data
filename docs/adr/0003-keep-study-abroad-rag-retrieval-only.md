# Keep Study Abroad RAG Retrieval-Only

Study Abroad Knowledge RAG will return structured evidence search results and will not generate final answers, admissions advice, or conflict-resolved conclusions in its first version. Keeping answer generation in the caller preserves a narrow index contract, makes ranking testable without LLM behavior, and forces downstream agents to cite retrieved sources when answering high-risk study-abroad questions.
