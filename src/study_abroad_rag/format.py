from __future__ import annotations

from src.study_abroad_rag.types import StudyAbroadSearchResult


def format_search_results(query: str, results: list[StudyAbroadSearchResult]) -> dict[str, object]:
    return {
        "query": query,
        "results": [result.to_dict() for result in results],
    }
