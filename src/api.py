from __future__ import annotations

from fastapi import FastAPI, HTTPException

from src.models.recommendation import RecommendationRequest, RecommendationResponse
from src.recommendation.service import RecommendationService, RecommendationServiceError


app = FastAPI(title="USYD Recommendation API")


@app.post("/recommendations/usyd", response_model=RecommendationResponse)
def create_usyd_recommendation(request: RecommendationRequest) -> RecommendationResponse:
    try:
        return RecommendationService().recommend(request)
    except RecommendationServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
