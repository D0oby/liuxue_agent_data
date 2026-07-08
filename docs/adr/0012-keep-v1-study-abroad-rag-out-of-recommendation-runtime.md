# Keep V1 Study Abroad RAG Out Of Recommendation Runtime

Study Abroad Knowledge RAG V1 will not be wired into `RecommendationService`, `PlanningAgent`, the dashboard recommendation flow, or existing USYD scoring and eligibility logic. It may later provide supplemental evidence to a caller, but it must not alter USYD recommendation scores, eligibility gates, or the existing admissions recommendation contract in V1.
