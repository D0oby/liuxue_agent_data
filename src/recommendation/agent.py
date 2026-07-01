from __future__ import annotations

from dataclasses import dataclass

from src.models.recommendation import CourseCandidate, RecommendationPlan, RecommendationRequest, UserProfile
from src.recommendation.eligibility import EligibilityGate, EligibilityOutcome
from src.recommendation.profile import UserProfileParser
from src.recommendation.requirements import RequirementResult, RequirementService
from src.recommendation.retrieval import AdmissionsRAGService, RetrievalResult
from src.recommendation.scoring import ScoringOutcome, ScoringService


class ParseUserProfileTool:
    def __init__(self, parser: UserProfileParser) -> None:
        self.parser = parser

    def run(self, request: RecommendationRequest, *, request_id: str) -> UserProfile:
        return self.parser.parse(request)


class SearchProgramTool:
    def __init__(self, rag_service: AdmissionsRAGService) -> None:
        self.rag_service = rag_service

    def run(self, conn, *, user_profile: UserProfile, request_id: str) -> RetrievalResult:
        return self.rag_service.search(conn, user_profile=user_profile, request_id=request_id)


class GetAdmissionRequirementTool:
    def __init__(self, requirement_service: RequirementService) -> None:
        self.requirement_service = requirement_service

    def run(
        self,
        conn,
        *,
        candidates: list[CourseCandidate],
        user_profile: UserProfile,
        request_id: str,
    ) -> RequirementResult:
        return self.requirement_service.get_requirements(
            conn,
            course_ids=[candidate.course_id for candidate in candidates],
            academic_background=user_profile.academic_background,
            request_id=request_id,
            course_names_by_id={candidate.course_id: candidate.course_name for candidate in candidates},
        )


class CalculateMatchScoreTool:
    def __init__(self, scoring_service: ScoringService) -> None:
        self.scoring_service = scoring_service

    def run(
        self,
        *,
        user_profile: UserProfile,
        candidates: list[CourseCandidate],
        requirement_result: RequirementResult,
        request_id: str,
    ) -> ScoringOutcome:
        return self.scoring_service.score_candidates(
            user_profile=user_profile,
            candidates=candidates,
            requirements=requirement_result.requirements,
            requirement_errors=requirement_result.errors,
            request_id=request_id,
        )


class RunEligibilityGateTool:
    def __init__(self, eligibility_gate: EligibilityGate) -> None:
        self.eligibility_gate = eligibility_gate

    def run(
        self,
        *,
        user_profile: UserProfile,
        candidates: list[CourseCandidate],
        requirement_result: RequirementResult,
        request_id: str,
    ) -> EligibilityOutcome:
        return self.eligibility_gate.evaluate(
            user_profile=user_profile,
            candidates=candidates,
            requirement_result=requirement_result,
            request_id=request_id,
        )


class GeneratePlanTool:
    def __init__(self, plan_assembler) -> None:
        self.plan_assembler = plan_assembler

    def run(
        self,
        *,
        user_profile: UserProfile,
        scoring_outcome: ScoringOutcome,
        request_id: str,
    ) -> RecommendationPlan:
        return self.plan_assembler.assemble(
            user_profile=user_profile,
            scored_candidates=scoring_outcome.scored_candidates,
            excluded_programs=scoring_outcome.excluded_programs,
            request_id=request_id,
        )


@dataclass(frozen=True)
class PlanningAgentResult:
    user_profile: UserProfile
    retrieval_result: RetrievalResult
    requirement_result: RequirementResult
    eligibility_outcome: EligibilityOutcome
    scoring_outcome: ScoringOutcome
    plan: RecommendationPlan


class PlanningAgent:
    def __init__(
        self,
        *,
        parse_user_profile_tool: ParseUserProfileTool,
        search_program_tool: SearchProgramTool,
        get_admission_requirement_tool: GetAdmissionRequirementTool,
        run_eligibility_gate_tool: RunEligibilityGateTool,
        calculate_match_score_tool: CalculateMatchScoreTool,
        generate_plan_tool: GeneratePlanTool,
    ) -> None:
        self.parse_user_profile_tool = parse_user_profile_tool
        self.search_program_tool = search_program_tool
        self.get_admission_requirement_tool = get_admission_requirement_tool
        self.run_eligibility_gate_tool = run_eligibility_gate_tool
        self.calculate_match_score_tool = calculate_match_score_tool
        self.generate_plan_tool = generate_plan_tool

    def run(self, conn, *, request: RecommendationRequest, request_id: str) -> PlanningAgentResult:
        user_profile = self.parse_user_profile_tool.run(request, request_id=request_id)
        retrieval_result = self.search_program_tool.run(
            conn,
            user_profile=user_profile,
            request_id=request_id,
        )
        requirement_result = self.get_admission_requirement_tool.run(
            conn,
            candidates=retrieval_result.candidates,
            user_profile=user_profile,
            request_id=request_id,
        )
        eligibility_outcome = self.run_eligibility_gate_tool.run(
            user_profile=user_profile,
            candidates=retrieval_result.candidates,
            requirement_result=requirement_result,
            request_id=request_id,
        )
        scoring_outcome = self.calculate_match_score_tool.run(
            user_profile=user_profile,
            candidates=eligibility_outcome.eligible_candidates,
            requirement_result=requirement_result,
            request_id=request_id,
        )
        plan = self.generate_plan_tool.run(
            user_profile=user_profile,
            scoring_outcome=scoring_outcome,
            request_id=request_id,
        )
        return PlanningAgentResult(
            user_profile=user_profile,
            retrieval_result=retrieval_result,
            requirement_result=requirement_result,
            eligibility_outcome=eligibility_outcome,
            scoring_outcome=scoring_outcome,
            plan=plan,
        )
