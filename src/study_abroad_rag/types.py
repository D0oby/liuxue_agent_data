from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RankingConfig:
    trust_tier_boosts: dict[str, float] = field(
        default_factory=lambda: {
            "official_university": 0.3,
            "official_government": 0.3,
        }
    )
    source_type_boosts: dict[str, float] = field(default_factory=dict)
    source_type_penalties: dict[str, float] = field(default_factory=dict)
    filter_match_boost: float = 0.08
    mismatch_penalty: float = 0.08
    privacy_summary_penalty: float = 0.05
    privacy_blocked_penalty: float = 0.5
    same_source_saturation_penalty: float = 0.35
    same_source_saturation: dict[str, int] = field(
        default_factory=lambda: {
            "source_id": 1,
            "source_type": 2,
            "domain": 2,
        }
    )
    staleness_penalty: float = 0.1
    freshness_year: int = 2026
    query_intent_boosts: dict[str, float] = field(
        default_factory=lambda: {
            "requirement_intent_official_boost": 0.25,
            "not_official_requirement_source": -0.10,
            "student_experience_intent_boost": 0.45,
            "student_experience_official_context_penalty": -0.05,
            "similar_background_case_boost": 0.55,
            "official_context_retained": 0.05,
            "program_recommendation_fit_boost": 0.25,
        }
    )


@dataclass(frozen=True, slots=True)
class StudyAbroadRAGConfig:
    ranking: RankingConfig = field(default_factory=RankingConfig)


@dataclass(frozen=True, slots=True)
class SourceConfig:
    source_id: str
    source_type: str
    title: str
    locator: str
    content_path: Path
    trust_tier: str
    language: str
    updated_at: str | None = None
    effective_date: str | None = None
    privacy_level: str = "public"
    country: str | None = None
    institution: str | None = None
    program: str | None = None
    degree_level: str | None = None
    intake: str | None = None
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "content_path", Path(self.content_path))
        if isinstance(self.tags, list):
            object.__setattr__(self, "tags", tuple(str(tag) for tag in self.tags))
        missing = [
            field_name
            for field_name in [
                "source_id",
                "source_type",
                "title",
                "locator",
                "trust_tier",
                "language",
                "privacy_level",
            ]
            if not str(getattr(self, field_name) or "").strip()
        ]
        if not self.updated_at and not self.effective_date:
            missing.append("updated_at_or_effective_date")
        if missing:
            raise ValueError(f"SourceConfig missing required metadata: {', '.join(missing)}")

    def manifest_record(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "title": self.title,
            "locator": self.locator,
            "content_path": str(self.content_path),
            "trust_tier": self.trust_tier,
            "language": self.language,
            "updated_at": self.updated_at,
            "effective_date": self.effective_date,
            "privacy_level": self.privacy_level,
            "country": self.country,
            "institution": self.institution,
            "program": self.program,
            "degree_level": self.degree_level,
            "intake": self.intake,
            "tags": list(self.tags),
        }


@dataclass(frozen=True, slots=True)
class IndexMetadata:
    schema_version: str
    chunker_version: str
    tokenizer_version: str
    model_name: str
    source_manifest_hash: str
    source_content_hashes: dict[str, str]
    created_at: str

    @classmethod
    def build(
        cls,
        sources: list[SourceConfig],
        *,
        schema_version: str,
        chunker_version: str,
        tokenizer_version: str,
        model_name: str,
    ) -> "IndexMetadata":
        return cls(
            schema_version=schema_version,
            chunker_version=chunker_version,
            tokenizer_version=tokenizer_version,
            model_name=model_name,
            source_manifest_hash=_hash_json([source.manifest_record() for source in sources]),
            source_content_hashes=_source_content_hashes(sources),
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def is_valid_for(
        self,
        sources: list[SourceConfig],
        *,
        schema_version: str,
        chunker_version: str,
        tokenizer_version: str,
        model_name: str,
    ) -> bool:
        expected = IndexMetadata.build(
            sources,
            schema_version=schema_version,
            chunker_version=chunker_version,
            tokenizer_version=tokenizer_version,
            model_name=model_name,
        )
        return (
            self.schema_version == expected.schema_version
            and self.chunker_version == expected.chunker_version
            and self.tokenizer_version == expected.tokenizer_version
            and self.model_name == expected.model_name
            and self.source_manifest_hash == expected.source_manifest_hash
            and self.source_content_hashes == expected.source_content_hashes
        )


@dataclass(frozen=True, slots=True)
class StudyAbroadChunk:
    source_id: str
    source_type: str
    source_title: str
    locator: str
    content: str
    trust_tier: str
    language: str
    privacy_level: str = "public"
    updated_at: str | None = None
    effective_date: str | None = None
    metadata: tuple[tuple[str, str], ...] = ()
    country: str | None = None
    institution: str | None = None
    program: str | None = None
    degree_level: str | None = None
    intake: str | None = None
    tags: tuple[str, ...] = ()

    @property
    def search_text(self) -> str:
        metadata_text = " ".join(value for _, value in self.metadata)
        filter_text = " ".join(
            [
                self.country or "",
                self.institution or "",
                self.program or "",
                self.degree_level or "",
                self.intake or "",
                " ".join(self.tags),
            ]
        )
        return " ".join([self.source_title, self.locator, metadata_text, filter_text, self.content]).casefold()


@dataclass(frozen=True, slots=True)
class StudyAbroadSearchResult:
    source_id: str
    source_type: str
    source_title: str
    locator: str
    content: str
    trust_tier: str
    language: str
    privacy_level: str
    rrf_score: float
    final_score: float
    ranking_reasons: tuple[str, ...]
    updated_at: str | None = None
    effective_date: str | None = None
    country: str | None = None
    institution: str | None = None
    program: str | None = None
    degree_level: str | None = None
    intake: str | None = None
    tags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["ranking_reasons"] = list(self.ranking_reasons)
        data["tags"] = list(self.tags)
        return data


def _source_content_hashes(sources: list[SourceConfig]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for source in sources:
        hashes[source.source_id] = hashlib.sha256(source.content_path.read_bytes()).hexdigest()
    return hashes


def _hash_json(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
