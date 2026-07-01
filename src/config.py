from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path


@dataclass(frozen=True)
class ScoringConfig:
    gpa_weight: float = 0.7
    ielts_weight: float = 0.3


@dataclass(frozen=True)
class BandConfig:
    reach_upper: float = 0.95
    match_upper: float = 1.1


@dataclass(frozen=True)
class RetrievalConfig:
    keyword_top_k: int = 30
    vector_top_k: int = 30
    final_candidate_limit: int = 50
    evidence_snippet_limit: int = 3
    min_retrieval_score: float = 0.05


@dataclass(frozen=True)
class OutputConfig:
    max_programs_per_band: int = 5


@dataclass(frozen=True)
class RulesConfig:
    enable_ielts_band_gate: bool = True


@dataclass(frozen=True)
class RecommendationConfig:
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    band: BandConfig = field(default_factory=BandConfig)
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    rules: RulesConfig = field(default_factory=RulesConfig)


@dataclass(frozen=True)
class Settings:
    database_url: str
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int | None = 1536
    embedding_batch_size: int = 64
    embedding_api_mode: str = "openai"
    embedding_max_workers: int = 8
    chroma_persist_directory: str = "var/chroma"
    chroma_collection_name: str = "course_admission_chunks"
    recommendation: RecommendationConfig = field(default_factory=RecommendationConfig)


def _load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return

    for line in dotenv_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'").strip('"'))


def load_settings() -> Settings:
    project_root = Path(__file__).resolve().parents[1]
    _load_dotenv(project_root / ".env")

    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise ValueError("DATABASE_URL is required. Set it in .env or the environment.")

    return Settings(
        database_url=database_url,
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip() or None,
        openai_base_url=_read_first_env(
            ["OPENAI_API_BASE", "OPENAI_BASE_URL"],
            "https://api.openai.com/v1",
        ).rstrip("/"),
        embedding_model=_read_first_env(
            ["DOUBAO_ENDPOINT_ID", "OPENAI_EMBEDDING_MODEL"],
            "text-embedding-3-small",
        ),
        embedding_dimensions=_read_optional_int_env("OPENAI_EMBEDDING_DIMENSIONS", 1536),
        embedding_batch_size=_read_int_env("EMBEDDING_BATCH_SIZE", 64),
        embedding_api_mode=_read_first_env(["EMBEDDING_API_MODE"], "openai"),
        embedding_max_workers=_read_int_env("EMBEDDING_MAX_WORKERS", 8),
        chroma_persist_directory=_read_first_env(
            ["CHROMA_PERSIST_DIRECTORY"],
            str(project_root / "var" / "chroma"),
        ),
        chroma_collection_name=_read_first_env(["CHROMA_COLLECTION_NAME"], "course_admission_chunks"),
        recommendation=load_recommendation_config(),
    )


def load_recommendation_config() -> RecommendationConfig:
    return RecommendationConfig(
        scoring=ScoringConfig(
            gpa_weight=_read_float_env("RECOMMENDATION_SCORING_GPA_WEIGHT", 0.7),
            ielts_weight=_read_float_env("RECOMMENDATION_SCORING_IELTS_WEIGHT", 0.3),
        ),
        band=BandConfig(
            reach_upper=_read_float_env("RECOMMENDATION_BAND_REACH_UPPER", 0.95),
            match_upper=_read_float_env("RECOMMENDATION_BAND_MATCH_UPPER", 1.1),
        ),
        retrieval=RetrievalConfig(
            keyword_top_k=_read_int_env("RECOMMENDATION_RETRIEVAL_KEYWORD_TOP_K", 30),
            vector_top_k=_read_int_env("RECOMMENDATION_RETRIEVAL_VECTOR_TOP_K", 30),
            final_candidate_limit=_read_int_env("RECOMMENDATION_RETRIEVAL_FINAL_CANDIDATE_LIMIT", 50),
            evidence_snippet_limit=_read_int_env("RECOMMENDATION_RETRIEVAL_EVIDENCE_SNIPPET_LIMIT", 3),
            min_retrieval_score=_read_float_env("RECOMMENDATION_RETRIEVAL_MIN_SCORE", 0.05),
        ),
        output=OutputConfig(
            max_programs_per_band=_read_int_env("RECOMMENDATION_OUTPUT_MAX_PROGRAMS_PER_BAND", 5),
        ),
        rules=RulesConfig(
            enable_ielts_band_gate=_read_bool_env("RECOMMENDATION_RULES_ENABLE_IELTS_BAND_GATE", True),
        ),
    )


def _read_first_env(names: list[str], default: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return default


def _read_optional_int_env(name: str, default: int | None = None) -> int | None:
    raw_value = os.getenv(name, "").strip()
    if raw_value.lower() in {"", "none", "null", "auto"}:
        return default
    return _parse_positive_int(name, raw_value)


def _read_int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    return _parse_positive_int(name, raw_value)


def _read_float_env(name: str, default: float) -> float:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number.") from exc
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero.")
    return value


def _read_bool_env(name: str, default: bool) -> bool:
    raw_value = os.getenv(name, "").strip().casefold()
    if not raw_value:
        return default
    if raw_value in {"1", "true", "yes", "y", "on"}:
        return True
    if raw_value in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value.")


def _parse_positive_int(name: str, raw_value: str) -> int:
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer.") from exc
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero.")
    return value
