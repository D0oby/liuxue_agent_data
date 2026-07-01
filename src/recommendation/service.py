from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import asdict
from datetime import datetime, timezone
import logging
from typing import Any, Callable
from uuid import uuid4

from src.config import Settings, load_settings
from src.db import connect
from src.models.recommendation import RecommendationMetadata, RecommendationRequest, RecommendationResponse
from src.recommendation.agent import (
    CalculateMatchScoreTool,
    GeneratePlanTool,
    GetAdmissionRequirementTool,
    ParseUserProfileTool,
    PlanningAgent,
    RunEligibilityGateTool,
    SearchProgramTool,
)
from src.recommendation.eligibility import EligibilityGate
from src.recommendation.plan import PlanAssembler
from src.recommendation.profile import UserProfileParser
from src.recommendation.query_builder import QueryBuilder
from src.recommendation.repository import RecommendationRepository
from src.recommendation.requirements import RequirementNormalizer, RequirementService
from src.recommendation.retrieval import AdmissionsRAGService, CandidateMerger, KeywordRetriever, VectorRetriever
from src.recommendation.scoring import BandClassifier, ScoreCalculator, ScoringService
from src.vector_store.embeddings import OpenAIEmbeddingClient
from src.vector_store.storage import ChromaVectorStore


logger = logging.getLogger(__name__)


MODEL_VERSION = "usyd-rag-agent-mvp-v1"


class RecommendationServiceError(RuntimeError):
    pass


class RecommendationService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        planning_agent: PlanningAgent | None = None,
        connection_factory: Callable[[Settings], AbstractContextManager[Any]] = connect,
    ) -> None:
        self.settings = settings or load_settings()
        self.planning_agent = planning_agent or build_default_planning_agent(self.settings)
        self.connection_factory = connection_factory

    def recommend(
        self,
        request: RecommendationRequest | dict[str, Any],
        *,
        request_id: str | None = None,
    ) -> RecommendationResponse:
        normalized_request = (
            request if isinstance(request, RecommendationRequest) else RecommendationRequest.model_validate(request)
        )
        resolved_request_id = request_id or str(uuid4())

        try:
            with self.connection_factory(self.settings) as conn:
                result = self.planning_agent.run(
                    conn,
                    request=normalized_request,
                    request_id=resolved_request_id,
                )
        except Exception as exc:
            logger.error(
                "recommendation request failed",
                extra={"request_id": resolved_request_id},
                exc_info=True,
            )
            raise RecommendationServiceError("Recommendation request failed.") from exc

        metadata = RecommendationMetadata(
            request_id=resolved_request_id,
            model_version=MODEL_VERSION,
            scoring_config=asdict(self.settings.recommendation),
            generated_at=datetime.now(timezone.utc),
            candidate_count=len(result.retrieval_result.candidates),
            scored_candidate_count=len(result.scoring_outcome.scored_candidates),
            degraded_retrieval=result.retrieval_result.degraded_retrieval,
        )
        query_spec = result.retrieval_result.query_spec
        query_summary = {
            "target_major_keyword": query_spec.target_major_keyword,
            "keyword_query": query_spec.keyword_query,
            "semantic_query": query_spec.semantic_query,
            "candidate_count": len(result.retrieval_result.candidates),
            "degraded_retrieval": result.retrieval_result.degraded_retrieval,
        }
        plan = result.plan
        eligibility_outcome = result.eligibility_outcome
        return RecommendationResponse(
            user_profile=result.user_profile,
            query_summary=query_summary,
            eligibility_summary=eligibility_outcome.summary,
            next_layer_candidates=eligibility_outcome.eligible_decisions,
            eligible_programs=eligibility_outcome.eligible_decisions,
            reach_programs=plan.reach_programs,
            match_programs=plan.match_programs,
            safety_programs=plan.safety_programs,
            high_risk_programs=eligibility_outcome.high_risk_decisions,
            excluded_programs=eligibility_outcome.ineligible_decisions,
            metadata=metadata,
            explanation=self._build_explanation(plan, eligibility_outcome),
        )

    def _build_explanation(self, plan, eligibility_outcome) -> str:
        summary = eligibility_outcome.summary
        return (
            f"Generated {len(plan.reach_programs)} reach, {len(plan.match_programs)} match, "
            f"{len(plan.safety_programs)} safety recommendations from "
            f"{summary.eligible_count} hard-filter eligible programs; "
            f"{summary.ineligible_count} ineligible and "
            f"{summary.high_risk_count + summary.unknown_count + summary.pathway_required_count} "
            "risk/unknown programs were separated before scoring."
        )


def build_default_planning_agent(settings: Settings) -> PlanningAgent:
    repository = RecommendationRepository()
    query_builder = QueryBuilder()
    keyword_retriever = KeywordRetriever(repository)
    vector_retriever = VectorRetriever(
        repository,
        embedding_client=_build_embedding_client(settings),
        embedding_model=settings.embedding_model,
        vector_store=_build_vector_store(settings),
    )
    rag_service = AdmissionsRAGService(
        repository=repository,
        query_builder=query_builder,
        keyword_retriever=keyword_retriever,
        vector_retriever=vector_retriever,
        candidate_merger=CandidateMerger(),
        config=settings.recommendation,
    )
    requirement_service = RequirementService(
        repository=repository,
        normalizer=RequirementNormalizer(),
    )
    scoring_service = ScoringService(
        score_calculator=ScoreCalculator(settings.recommendation),
        band_classifier=BandClassifier(settings.recommendation),
    )
    plan_assembler = PlanAssembler(settings.recommendation)
    return PlanningAgent(
        parse_user_profile_tool=ParseUserProfileTool(UserProfileParser()),
        search_program_tool=SearchProgramTool(rag_service),
        get_admission_requirement_tool=GetAdmissionRequirementTool(requirement_service),
        run_eligibility_gate_tool=RunEligibilityGateTool(EligibilityGate()),
        calculate_match_score_tool=CalculateMatchScoreTool(scoring_service),
        generate_plan_tool=GeneratePlanTool(plan_assembler),
    )


def _build_embedding_client(settings: Settings) -> OpenAIEmbeddingClient | None:
    if not settings.openai_api_key:
        return None
    return OpenAIEmbeddingClient(
        api_key=settings.openai_api_key,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        base_url=settings.openai_base_url,
        api_mode=settings.embedding_api_mode,
        max_workers=settings.embedding_max_workers,
    )


def _build_vector_store(settings: Settings) -> ChromaVectorStore:
    return ChromaVectorStore.from_settings(settings)
