from __future__ import annotations

from src.models.recommendation import QuerySpec


class QueryBuilder:
    DIRECTION_MAP: dict[str, tuple[list[str], str]] = {
        "计算机": (
            [
                "computer science",
                "information technology",
                "computing",
                "software engineering",
                "artificial intelligence",
                "data systems",
            ],
            "Master programs related to computer science, IT, software engineering, AI and data systems",
        ),
        "computer": (
            [
                "computer science",
                "information technology",
                "computing",
                "software engineering",
                "artificial intelligence",
            ],
            "Master programs related to computer science, IT, software engineering and AI",
        ),
        "数据分析": (
            [
                "data science",
                "data analytics",
                "business analytics",
                "analytics",
                "statistics",
                "data systems",
            ],
            "Master programs related to data science, data analytics, business analytics and statistics",
        ),
        "data": (
            [
                "data science",
                "data analytics",
                "business analytics",
                "analytics",
                "statistics",
            ],
            "Master programs related to data science, analytics and statistics",
        ),
        "商科": (
            [
                "commerce",
                "business",
                "management",
                "finance",
                "accounting",
                "marketing",
            ],
            "Master programs related to commerce, business, management, finance, accounting and marketing",
        ),
        "business": (
            [
                "commerce",
                "business",
                "management",
                "finance",
                "accounting",
                "marketing",
            ],
            "Master programs related to commerce, business, management, finance, accounting and marketing",
        ),
    }

    def build(self, target_major_keyword: str) -> QuerySpec:
        normalized = " ".join(target_major_keyword.split()).strip()
        matched_key = self._match_direction(normalized)
        if matched_key:
            keywords, semantic_query = self.DIRECTION_MAP[matched_key]
        else:
            keywords = [normalized]
            semantic_query = f"Master programs related to {normalized}"

        keyword_query = " OR ".join(keywords)
        return QuerySpec(
            target_major_keyword=normalized,
            keyword_query=keyword_query,
            semantic_query=semantic_query,
            keywords=keywords,
        )

    def _match_direction(self, target_major_keyword: str) -> str | None:
        lowered = target_major_keyword.casefold()
        for key in self.DIRECTION_MAP:
            if key.casefold() in lowered:
                return key
        return None
