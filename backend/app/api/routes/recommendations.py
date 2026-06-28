import time

from cachetools import TTLCache
from fastapi import APIRouter, Depends, HTTPException

from ...core.config import settings
from ...models.schemas import RecommendationRequest, RecommendationResponse
from ...services.recommendation_service import RecommendationService
from ...services.youtube_service import YouTubeService

router = APIRouter()

# ─── Simple in-process cache ──────────────────────────────────────────────────
# Key: (language, proficiency, sorted_interests_tuple)
# This avoids hammering the YouTube API on repeated identical requests.

_cache: TTLCache[str, RecommendationResponse] = TTLCache(
    maxsize=256,
    ttl=settings.cache_ttl_seconds,
)


def _cache_key(req: RecommendationRequest) -> str:
    interests_str = ",".join(sorted(i.value for i in req.interests))
    # Include a snapshot of topic weights so different feedback states get different cache slots.
    weights_str = ""
    if req.topicWeights:
        weights_str = "|" + ",".join(
            f"{k}={round(v, 1)}" for k, v in sorted(req.topicWeights.items())
        )
    return f"{req.targetLanguage.value}:{req.proficiencyLevel.value}:{interests_str}{weights_str}"


# ─── Dependency ───────────────────────────────────────────────────────────────

def get_recommendation_service() -> RecommendationService:
    return RecommendationService(YouTubeService())


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.post("/recommendations", response_model=RecommendationResponse)
async def get_recommendations(
    request: RecommendationRequest,
    service: RecommendationService = Depends(get_recommendation_service),
) -> RecommendationResponse:
    """
    Return a ranked list of target-language YouTube videos that match the
    user's interests and proficiency level.
    """
    if not settings.youtube_api_key:
        raise HTTPException(
            status_code=503,
            detail="YouTube API key is not configured. Set YOUTUBE_API_KEY in .env",
        )

    key = _cache_key(request)
    if key in _cache:
        cached = _cache[key]
        return RecommendationResponse(
            videos=cached.videos,
            generatedAt=cached.generatedAt,
            cacheHit=True,
        )

    result = await service.get_recommendations(request)
    _cache[key] = result
    return result
