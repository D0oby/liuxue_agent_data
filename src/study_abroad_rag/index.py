from __future__ import annotations

import csv
from dataclasses import dataclass
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import re
from typing import Protocol
from urllib.parse import urlparse

from src.study_abroad_rag.types import IndexMetadata, RankingConfig, SourceConfig, StudyAbroadChunk, StudyAbroadRAGConfig, StudyAbroadSearchResult


_RRF_K = 60


class Embedder(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...


class StudyAbroadRAGIndex:
    def __init__(
        self,
        chunks: list[StudyAbroadChunk],
        *,
        cache_metadata: IndexMetadata,
        config: StudyAbroadRAGConfig,
        embedder: Embedder | None = None,
    ) -> None:
        self._chunks = chunks
        self._cache_metadata = cache_metadata
        self._config = config
        self._embedder = embedder
        self._chunk_embeddings = embedder.embed_texts([chunk.search_text for chunk in chunks]) if embedder else []

    @property
    def cache_metadata(self) -> IndexMetadata:
        return self._cache_metadata

    @classmethod
    def from_sources(
        cls,
        sources: list[SourceConfig],
        *,
        config: StudyAbroadRAGConfig | None = None,
        embedder: Embedder | None = None,
        schema_version: str = "study-rag-v1",
        chunker_version: str = "study-rag-chunker-v1",
        tokenizer_version: str = "study-rag-tokenizer-v1",
        model_name: str = "none",
    ) -> "StudyAbroadRAGIndex":
        resolved_config = config or StudyAbroadRAGConfig()
        chunks: list[StudyAbroadChunk] = []
        for source in sources:
            chunks.extend(_load_chunks(source))
        return cls(
            chunks,
            cache_metadata=IndexMetadata.build(
                sources,
                schema_version=schema_version,
                chunker_version=chunker_version,
                tokenizer_version=tokenizer_version,
                model_name=model_name,
            ),
            config=resolved_config,
            embedder=embedder,
        )

    @classmethod
    def from_path(
        cls,
        path: str | Path,
        *,
        config: StudyAbroadRAGConfig | None = None,
        embedder: Embedder | None = None,
        schema_version: str = "study-rag-v1",
        chunker_version: str = "study-rag-chunker-v1",
        tokenizer_version: str = "study-rag-tokenizer-v1",
        model_name: str = "none",
    ) -> "StudyAbroadRAGIndex":
        root = Path(path)
        manifest_path = root / "source_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, list):
            raise ValueError("source_manifest.json must contain a list of sources.")
        sources = [_source_from_manifest_record(root, record) for record in manifest]
        return cls.from_sources(
            sources,
            config=config,
            embedder=embedder,
            schema_version=schema_version,
            chunker_version=chunker_version,
            tokenizer_version=tokenizer_version,
            model_name=model_name,
        )

    def search(self, query: str, *, top_k: int = 8, filters: object | None = None, query_intent: str | None = None) -> list[StudyAbroadSearchResult]:
        tokens = _tokenize(query)
        if not tokens:
            return []
        filter_map = _normalize_filters(filters)

        sparse_scores: dict[StudyAbroadChunk, float] = {}
        for chunk in self._chunks:
            content = chunk.search_text
            match_count = sum(1 for token in tokens if token in content)
            if match_count:
                sparse_scores[chunk] = float(match_count)

        dense_scores = self._dense_scores(query)
        sparse_rrf = _rrf_scores(sparse_scores)
        dense_rrf = _rrf_scores(dense_scores)
        all_chunks = sorted({*sparse_rrf, *dense_rrf}, key=lambda chunk: chunk.locator)
        combined = {chunk: sparse_rrf.get(chunk, 0.0) + dense_rrf.get(chunk, 0.0) for chunk in all_chunks}

        ranked = sorted(combined, key=lambda chunk: (-combined[chunk], chunk.locator))
        preliminary: list[StudyAbroadSearchResult] = []
        for chunk in ranked:
            rrf_score = combined[chunk]
            ranking_config = self._config.ranking
            trust_boost = _trust_boost(chunk.trust_tier, ranking_config)
            source_type_adjustment, source_type_reasons = _source_type_adjustment(chunk, ranking_config)
            display_content, privacy_penalty, privacy_reasons = _display_content_and_privacy(chunk, ranking_config)
            policy_adjustment, policy_reasons = _ranking_policy_adjustment(chunk, query_intent, ranking_config)
            filter_adjustment, filter_reasons = _filter_adjustment(chunk, filter_map, ranking_config)
            staleness_penalty, staleness_reasons = _staleness_penalty(chunk, ranking_config)
            final_score = (
                rrf_score
                + trust_boost
                + source_type_adjustment
                + policy_adjustment
                + filter_adjustment
                - privacy_penalty
                - staleness_penalty
            )
            reasons = [f"rrf_score:{rrf_score:.4f}"]
            if chunk in sparse_rrf:
                reasons.append(f"sparse_rrf:+{sparse_rrf[chunk]:.4f}")
            if chunk in dense_rrf:
                reasons.append(f"dense_rrf:+{dense_rrf[chunk]:.4f}")
            if trust_boost:
                reasons.append(f"{chunk.trust_tier}_boost:+{trust_boost:.2f}")
            reasons.extend(source_type_reasons)
            reasons.extend(policy_reasons)
            reasons.extend(filter_reasons)
            reasons.extend(privacy_reasons)
            reasons.extend(staleness_reasons)
            preliminary.append(
                StudyAbroadSearchResult(
                    source_id=chunk.source_id,
                    source_type=chunk.source_type,
                    source_title=chunk.source_title,
                    locator=chunk.locator,
                    content=display_content,
                    trust_tier=chunk.trust_tier,
                    language=chunk.language,
                    privacy_level=chunk.privacy_level,
                    updated_at=chunk.updated_at,
                    effective_date=chunk.effective_date,
                    country=chunk.country,
                    institution=chunk.institution,
                    program=chunk.program,
                    degree_level=chunk.degree_level,
                    intake=chunk.intake,
                    tags=chunk.tags,
                    rrf_score=rrf_score,
                    final_score=final_score,
                    ranking_reasons=tuple(reasons),
                )
            )
        return _apply_same_source_saturation(preliminary, self._config.ranking)[:top_k]

    def find_related(self, source: StudyAbroadSearchResult | StudyAbroadChunk, *, top_k: int = 5) -> list[StudyAbroadSearchResult]:
        results = self.search(source.content, top_k=top_k + 1)
        return [result for result in results if result.locator != source.locator][:top_k]

    def _dense_scores(self, query: str) -> dict[StudyAbroadChunk, float]:
        if not self._embedder or not self._chunks:
            return {}
        query_vector = self._embedder.embed_texts([query])[0]
        scores: dict[StudyAbroadChunk, float] = {}
        for chunk, chunk_vector in zip(self._chunks, self._chunk_embeddings, strict=False):
            score = _cosine_similarity(query_vector, chunk_vector)
            if score > 0:
                scores[chunk] = score
        return scores


def _load_chunks(source: SourceConfig) -> list[StudyAbroadChunk]:
    suffix = source.content_path.suffix.casefold()
    if suffix in {".html", ".htm"}:
        return _load_html_chunks(source)
    if suffix == ".csv":
        return _load_csv_chunks(source)
    if suffix == ".jsonl":
        return _load_jsonl_chunks(source)
    return _load_markdown_chunks(source)


def _source_from_manifest_record(root: Path, record: object) -> SourceConfig:
    if not isinstance(record, dict):
        raise ValueError("Each source manifest entry must be an object.")
    data = dict(record)
    content_path = Path(str(data.get("content_path") or ""))
    if not content_path.is_absolute():
        content_path = root / content_path
    data["content_path"] = content_path
    if isinstance(data.get("tags"), list):
        data["tags"] = tuple(str(tag) for tag in data["tags"])
    return SourceConfig(**data)


def _load_markdown_chunks(source: SourceConfig) -> list[StudyAbroadChunk]:
    content = source.content_path.read_text(encoding="utf-8")
    sections = _split_markdown_sections(content)
    return [
        StudyAbroadChunk(
            source_id=source.source_id,
            source_type=source.source_type,
            source_title=source.title,
            locator=f"{source.locator}{section.anchor}",
            content=section.content,
            trust_tier=source.trust_tier,
            language=source.language,
            privacy_level=source.privacy_level,
            updated_at=source.updated_at,
            effective_date=source.effective_date,
            country=source.country,
            institution=source.institution,
            program=source.program,
            degree_level=source.degree_level,
            intake=source.intake,
            tags=source.tags,
        )
        for section in sections
        if section.content.strip()
    ]


def _load_html_chunks(source: SourceConfig) -> list[StudyAbroadChunk]:
    parser = _HTMLSectionParser()
    parser.feed(source.content_path.read_text(encoding="utf-8"))
    sections = parser.sections()
    return [
        StudyAbroadChunk(
            source_id=source.source_id,
            source_type=source.source_type,
            source_title=source.title,
            locator=f"{source.locator}{section.anchor}",
            content=section.content,
            trust_tier=source.trust_tier,
            language=source.language,
            privacy_level=source.privacy_level,
            updated_at=source.updated_at,
            effective_date=source.effective_date,
            country=source.country,
            institution=source.institution,
            program=source.program,
            degree_level=source.degree_level,
            intake=source.intake,
            tags=source.tags,
        )
        for section in sections
        if section.content.strip()
    ]


def _load_csv_chunks(source: SourceConfig) -> list[StudyAbroadChunk]:
    with source.content_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    chunks: list[StudyAbroadChunk] = []
    for index, row in enumerate(rows, start=1):
        chunks.append(_record_chunk(source, row, fallback_record_id=str(index), row_number=index))
    return chunks


def _load_jsonl_chunks(source: SourceConfig) -> list[StudyAbroadChunk]:
    chunks: list[StudyAbroadChunk] = []
    for index, line in enumerate(source.content_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        parsed = json.loads(line)
        if not isinstance(parsed, dict):
            continue
        chunks.append(_record_chunk(source, parsed, fallback_record_id=str(index), row_number=index))
    return chunks


def _record_chunk(
    source: SourceConfig,
    row: dict[str, object],
    *,
    fallback_record_id: str,
    row_number: int,
) -> StudyAbroadChunk:
    record_id = str(row.get("record_id") or row.get("id") or fallback_record_id).strip()
    title = str(row.get("title") or source.title).strip()
    content = str(row.get("content") or row.get("summary") or row.get("text") or "").strip()
    privacy_level = str(row.get("privacy_level") or source.privacy_level).strip() or source.privacy_level
    metadata = tuple((str(key), str(value)) for key, value in row.items() if value is not None and key != "content")
    return StudyAbroadChunk(
        source_id=source.source_id,
        source_type=source.source_type,
        source_title=title,
        locator=f"{source.locator}:record={record_id},row={row_number}",
        content=content,
        trust_tier=source.trust_tier,
        language=source.language,
        privacy_level=privacy_level,
        updated_at=source.updated_at,
        effective_date=source.effective_date,
        metadata=metadata,
        country=source.country,
        institution=source.institution,
        program=source.program,
        degree_level=source.degree_level,
        intake=source.intake,
        tags=source.tags,
    )


@dataclass(frozen=True)
class _MarkdownSection:
    anchor: str
    content: str


class _HTMLSectionParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._sections: list[_MarkdownSection] = []
        self._current_heading = ""
        self._current_lines: list[str] = []
        self._active_tag = ""
        self._active_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "td", "th"}:
            self._active_tag = tag
            self._active_text = []

    def handle_data(self, data: str) -> None:
        if self._active_tag:
            self._active_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != self._active_tag:
            return
        text = _normalize_inline_text(" ".join(self._active_text))
        self._active_tag = ""
        self._active_text = []
        if not text:
            return
        if tag.startswith("h"):
            self._flush()
            self._current_heading = text
            self._current_lines = [f"# {text}"]
            return
        self._current_lines.append(text)

    def sections(self) -> list[_MarkdownSection]:
        self._flush()
        return self._sections

    def _flush(self) -> None:
        if self._current_lines:
            self._sections.append(
                _MarkdownSection(anchor=_heading_anchor(self._current_heading), content=_clean_lines(self._current_lines))
            )
            self._current_lines = []


def _split_markdown_sections(content: str) -> list[_MarkdownSection]:
    sections: list[_MarkdownSection] = []
    current_heading = ""
    current_lines: list[str] = []

    for line in content.splitlines():
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading:
            if current_lines:
                sections.append(_MarkdownSection(anchor=_heading_anchor(current_heading), content=_clean_lines(current_lines)))
            current_heading = heading.group(2)
            current_lines = [line]
            continue
        current_lines.append(line)

    if current_lines:
        sections.append(_MarkdownSection(anchor=_heading_anchor(current_heading), content=_clean_lines(current_lines)))
    return sections


def _heading_anchor(heading: str) -> str:
    if not heading:
        return ""
    slug = re.sub(r"[^a-z0-9]+", "-", heading.casefold()).strip("-")
    return f"#{slug}" if slug else ""


def _clean_lines(lines: list[str]) -> str:
    return "\n".join(line.rstrip() for line in lines).strip()


def _normalize_inline_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _tokenize(text: str) -> list[str]:
    return [token.casefold() for token in re.findall(r"[a-zA-Z0-9]+(?:\.[0-9]+)?|[\u4e00-\u9fff]+", text)]


def _rrf_scores(scores: dict[StudyAbroadChunk, float]) -> dict[StudyAbroadChunk, float]:
    ranked = sorted(scores, key=lambda chunk: (-scores[chunk], chunk.locator))
    return {chunk: 1.0 / (_RRF_K + rank) for rank, chunk in enumerate(ranked, start=1)}


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _display_content_and_privacy(chunk: StudyAbroadChunk, ranking: RankingConfig) -> tuple[str, float, list[str]]:
    if chunk.privacy_level == "raw_anonymous_internal_record" or _contains_personal_identifier(chunk.content):
        return (
            "Evidence suppressed by privacy policy.",
            ranking.privacy_blocked_penalty,
            [f"privacy_blocked_reason:raw_or_identifier:-{ranking.privacy_blocked_penalty:.2f}"],
        )
    if chunk.privacy_level == "anonymous_summary":
        return chunk.content, ranking.privacy_summary_penalty, [f"privacy_summary_only_penalty:-{ranking.privacy_summary_penalty:.2f}"]
    return chunk.content, 0.0, []


def _contains_personal_identifier(content: str) -> bool:
    if re.search(r"\b[\w.\-]+@[\w.\-]+\.\w+\b", content):
        return True
    return False


def _ranking_policy_adjustment(
    chunk: StudyAbroadChunk,
    query_intent: str | None,
    ranking: RankingConfig,
) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0
    if query_intent in {"requirement", "deadline", "fee", "policy"}:
        if chunk.source_type in {"official_university", "official_government", "course_handbook"}:
            boost = ranking.query_intent_boosts.get("requirement_intent_official_boost", 0.0)
            score += boost
            if boost:
                reasons.append(f"requirement_intent_official_boost:+{boost:.2f}")
        if chunk.source_type in {"public_forum_post", "student_experience_post", "anonymous_internal_source"}:
            penalty = abs(ranking.query_intent_boosts.get("not_official_requirement_source", 0.0))
            score -= penalty
            if penalty:
                reasons.append(f"not_official_requirement_source:-{penalty:.2f}")
    if query_intent == "student_experience":
        if chunk.source_type in {"student_experience_post", "public_forum_post"}:
            boost = ranking.query_intent_boosts.get("student_experience_intent_boost", 0.0)
            score += boost
            if boost:
                reasons.append(f"student_experience_intent_boost:+{boost:.2f}")
        if chunk.source_type in {"official_university", "official_government"}:
            penalty = abs(ranking.query_intent_boosts.get("student_experience_official_context_penalty", 0.0))
            score -= penalty
            if penalty:
                reasons.append(f"student_experience_official_context_penalty:-{penalty:.2f}")
    if query_intent in {"applicant_fit", "chance_estimation"}:
        if chunk.source_type in {"anonymous_internal_source", "verified_internal_case"}:
            boost = ranking.query_intent_boosts.get("similar_background_case_boost", 0.0)
            score += boost
            if boost:
                reasons.append(f"similar_background_case_boost:+{boost:.2f}")
        if chunk.source_type in {"official_university", "official_government"}:
            boost = ranking.query_intent_boosts.get("official_context_retained", 0.0)
            score += boost
            if boost:
                reasons.append(f"official_context_retained:+{boost:.2f}")
    if query_intent == "program_recommendation":
        if any(term in chunk.search_text for term in ["curriculum", "career", "background fit", "program fit"]):
            boost = ranking.query_intent_boosts.get("program_recommendation_fit_boost", 0.0)
            score += boost
            if boost:
                reasons.append(f"program_recommendation_fit_boost:+{boost:.2f}")
    return score, reasons


def _normalize_filters(filters: object | None) -> dict[str, str]:
    if not isinstance(filters, dict):
        return {}
    normalized: dict[str, str] = {}
    for key, value in filters.items():
        label = str(value or "").strip()
        if label:
            normalized[str(key)] = label
    return normalized


def _filter_adjustment(chunk: StudyAbroadChunk, filters: dict[str, str], ranking: RankingConfig) -> tuple[float, list[str]]:
    if not filters:
        return 0.0, []
    score = 0.0
    reasons: list[str] = []
    for field_name, expected in filters.items():
        actual = _chunk_filter_value(chunk, field_name)
        if actual is None:
            continue
        if actual.casefold() == expected.casefold():
            score += ranking.filter_match_boost
            reasons.append(f"filter_match_boost:{field_name}=+{ranking.filter_match_boost:.2f}")
        else:
            score -= ranking.mismatch_penalty
            reasons.append(f"mismatch_penalty:{field_name}=-{ranking.mismatch_penalty:.2f}")
    return score, reasons


def _chunk_filter_value(chunk: StudyAbroadChunk, field_name: str) -> str | None:
    if field_name == "country":
        return chunk.country
    if field_name == "institution":
        return chunk.institution
    if field_name == "program":
        return chunk.program
    if field_name == "degree_level":
        return chunk.degree_level
    if field_name == "intake":
        return chunk.intake
    if field_name == "tags" and chunk.tags:
        return " ".join(chunk.tags)
    return None


def _apply_same_source_saturation(results: list[StudyAbroadSearchResult], ranking: RankingConfig) -> list[StudyAbroadSearchResult]:
    selected: list[StudyAbroadSearchResult] = []
    counts: dict[str, dict[str, int]] = {"source_id": {}, "source_type": {}, "domain": {}}
    for result in sorted(results, key=lambda item: (-item.final_score, item.locator)):
        total_penalty = 0.0
        saturation_reasons: list[str] = []
        for scope, key in _saturation_keys(result).items():
            threshold = ranking.same_source_saturation.get(scope)
            if threshold is None or threshold < 1:
                continue
            already_selected = counts[scope].get(key, 0)
            if already_selected >= threshold:
                penalty = ranking.same_source_saturation_penalty * (already_selected - threshold + 1)
                total_penalty += penalty
                saturation_reasons.append(f"same_source_saturation_penalty:{scope}={key}:-{penalty:.2f}")
        if total_penalty:
            reasons = (*result.ranking_reasons, *saturation_reasons)
            result = StudyAbroadSearchResult(
                source_id=result.source_id,
                source_type=result.source_type,
                source_title=result.source_title,
                locator=result.locator,
                content=result.content,
                trust_tier=result.trust_tier,
                language=result.language,
                privacy_level=result.privacy_level,
                updated_at=result.updated_at,
                effective_date=result.effective_date,
                country=result.country,
                institution=result.institution,
                program=result.program,
                degree_level=result.degree_level,
                intake=result.intake,
                tags=result.tags,
                rrf_score=result.rrf_score,
                final_score=result.final_score - total_penalty,
                ranking_reasons=reasons,
            )
        selected.append(result)
        for scope, key in _saturation_keys(result).items():
            counts[scope][key] = counts[scope].get(key, 0) + 1
    return sorted(selected, key=lambda item: (-item.final_score, item.locator))


def _saturation_keys(result: StudyAbroadSearchResult) -> dict[str, str]:
    keys = {"source_id": result.source_id, "source_type": result.source_type}
    domain = urlparse(result.locator).netloc.casefold()
    if domain:
        keys["domain"] = domain
    return keys


def _source_type_adjustment(chunk: StudyAbroadChunk, ranking: RankingConfig) -> tuple[float, list[str]]:
    boost = ranking.source_type_boosts.get(chunk.source_type, 0.0)
    penalty = ranking.source_type_penalties.get(chunk.source_type, 0.0)
    reasons: list[str] = []
    if boost:
        reasons.append(f"{chunk.source_type}_boost:+{boost:.2f}")
    if penalty:
        reasons.append(f"{chunk.source_type}_penalty:-{penalty:.2f}")
    return boost - penalty, reasons


def _staleness_penalty(chunk: StudyAbroadChunk, ranking: RankingConfig) -> tuple[float, list[str]]:
    source_year = _source_year(chunk.updated_at or chunk.effective_date)
    if source_year is None or source_year >= ranking.freshness_year:
        return 0.0, []
    return ranking.staleness_penalty, [f"stale_source_penalty:-{ranking.staleness_penalty:.2f}"]


def _source_year(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"\b(20\d{2})\b", value)
    return int(match.group(1)) if match else None


def _trust_boost(trust_tier: str, ranking: RankingConfig) -> float:
    return ranking.trust_tier_boosts.get(trust_tier, 0.0)
