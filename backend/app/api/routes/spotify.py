"""
AILO Spotify API routes.

Endpoints:
  GET  /api/spotify/auth/{user_id}         — get Spotify OAuth URL
  GET  /api/spotify/callback               — OAuth callback handler
  POST /api/spotify/recommendations        — get personalized artist + playlist recs
  POST /api/spotify/interact               — record a track interaction
  GET  /api/spotify/preferences/{user_id}  — get current preference weights
"""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

class SpotifyExchangeRequest(BaseModel):
    code: str
    state: str

class SpotifyExchangeResponse(BaseModel):
    access_token: str
    refresh_token: str | None = None
    expires_in: int = 3600

class SpotifyPlaylistRequest(BaseModel):
    language: str = "fr"
    access_token: str | None = None


from ...core.config import settings
from ...models.schemas import (
    Language,
    ProficiencyLevel,
    SpotifyCallbackResult,
    SpotifyAuthURL,
    SpotifyRecommendationRequest,
    SpotifyRecommendationResponse,
    TrackInteraction,
    PreferenceWeightUpdate,
)
from ...services.spotify_service import spotify_recommendation_service
from ...services.personalization_service import personalization_service
from ...services.user_service import user_service

router = APIRouter(prefix="/api/spotify")


@router.get("/auth/{user_id}", response_model=SpotifyAuthURL, tags=["spotify"])
async def get_spotify_auth_url(user_id: str) -> SpotifyAuthURL:
    """Return the Spotify OAuth authorization URL for this user."""
    if not settings.spotify_client_id:
        raise HTTPException(
            status_code=503,
            detail="Spotify integration not configured. Add SPOTIFY_CLIENT_ID to .env",
        )
    return spotify_recommendation_service.get_auth_url(user_id)


@router.get("/callback", tags=["spotify"])
async def spotify_callback(
    code: str = Query(...),
    state: str = Query(...),
    error: str | None = Query(None),
) -> RedirectResponse:
    """
    Spotify redirects here after the user authorizes.
    We exchange the code for tokens, store them on the user profile,
    then redirect back to the dashboard.
    """
    if error:
        return RedirectResponse(
            url=f"{settings.frontend_url}/dashboard?spotify_error={error}"
        )

    token_data = await spotify_recommendation_service.handle_callback(code, state)
    if not token_data:
        return RedirectResponse(
            url=f"{settings.frontend_url}/dashboard?spotify_error=invalid_state"
        )

    user_id = token_data["user_id"]
    user_service.set_spotify_tokens(
        user_id=user_id,
        access_token=token_data["access_token"],
        refresh_token=token_data.get("refresh_token"),
    )

    return RedirectResponse(
        url=f"{settings.frontend_url}/dashboard?spotify_connected=true"
    )


@router.post(
    "/recommendations",
    response_model=SpotifyRecommendationResponse,
    tags=["spotify"],
)
async def get_recommendations(
    request: SpotifyRecommendationRequest,
) -> SpotifyRecommendationResponse:
    """
    Return personalized target-language artist and playlist recommendations.

    Works with or without a connected Spotify account:
    - With Spotify: uses real listening history + audio features
    - Without: uses declared preferences (favorite_artists, genres, moods)
    """
    profile = user_service.get_user(request.user_id)
    access_token = profile.spotify_access_token if profile else None

    # Merge user music prefs into request if not provided
    if profile and not request.favorite_artists:
        request.favorite_artists = profile.music_preferences.favorite_artists
    if profile and not request.favorite_genres:
        request.favorite_genres = profile.music_preferences.genres
    if profile and not request.preferred_moods:
        request.preferred_moods = profile.music_preferences.moods

    # explore=True → Thompson Sampling: each fetch draws from Beta distributions
    preference_weights = personalization_service.get_flat_weights(request.user_id, explore=True)

    return await spotify_recommendation_service.get_recommendations(
        request=request,
        access_token=access_token,
        preference_weights=preference_weights,
    )


@router.post(
    "/interact",
    response_model=PreferenceWeightUpdate,
    tags=["spotify"],
)
async def record_interaction(interaction: TrackInteraction) -> PreferenceWeightUpdate:
    """
    Record a user interaction (like, skip, replay, etc.) and update preference weights.
    The response contains the keys that changed and their new values.
    """
    result = personalization_service.record_interaction(interaction)

    # Persist updated weights to user profile
    user_service.update_preference_weights(interaction.user_id, result.new_weights)

    return result


@router.get(
    "/preferences/{user_id}",
    tags=["spotify"],
)
async def get_preferences(user_id: str) -> dict:
    """Return the user's current taste profile — top liked/disliked features and stats."""
    return {
        "top_preferences": personalization_service.get_top_preferences(user_id),
        "stats": personalization_service.get_interaction_stats(user_id),
        "recent_history": personalization_service.get_history(user_id, limit=10),
    }


@router.post("/exchange", response_model=SpotifyExchangeResponse, tags=["spotify"])
async def exchange_spotify_code(body: SpotifyExchangeRequest) -> SpotifyExchangeResponse:
    """Exchange an authorization code for Spotify tokens. Called by the frontend callback page."""
    token_data = await spotify_recommendation_service.handle_callback(body.code, body.state)
    if not token_data:
        raise HTTPException(status_code=400, detail="Invalid code or state — try connecting again.")
    return SpotifyExchangeResponse(
        access_token=token_data["access_token"],
        refresh_token=token_data.get("refresh_token"),
        expires_in=token_data.get("expires_in", 3600),
    )


@router.post("/playlist", response_model=SpotifyRecommendationResponse, tags=["spotify"])
async def get_playlist(body: SpotifyPlaylistRequest) -> SpotifyRecommendationResponse:
    """
    Generate a weekly playlist of 15 target-language tracks.
    If access_token is provided, uses the user's real Spotify listening history.
    Otherwise falls back to Client Credentials + curated catalog.
    """
    try:
        lang = Language(body.language)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unsupported language: {body.language}")

    demo = user_service.get_or_create_demo_user(body.language)

    request = SpotifyRecommendationRequest(
        user_id=demo.user_id,
        target_language=lang,
        proficiency_level=demo.proficiency_level,
        favorite_artists=demo.music_preferences.favorite_artists,
        favorite_genres=demo.music_preferences.genres,
        preferred_moods=demo.music_preferences.moods,
        count=15,
    )

    return await spotify_recommendation_service.get_recommendations(
        request=request,
        access_token=body.access_token,
        preference_weights={},
    )


@router.get(
    "/demo/{language}",
    response_model=SpotifyRecommendationResponse,
    tags=["spotify"],
)
async def get_demo_recommendations(language: str = "fr") -> SpotifyRecommendationResponse:
    """
    Returns recommendations for the built-in demo user.
    Useful for onboarding previews before a real user profile is created.
    """
    try:
        lang = Language(language)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unsupported language: {language}")

    demo = user_service.get_or_create_demo_user(language)

    request = SpotifyRecommendationRequest(
        user_id=demo.user_id,
        target_language=lang,
        proficiency_level=demo.proficiency_level,
        favorite_artists=demo.music_preferences.favorite_artists,
        favorite_genres=demo.music_preferences.genres,
        preferred_moods=demo.music_preferences.moods,
        count=15,
    )

    return await spotify_recommendation_service.get_recommendations(
        request=request,
        access_token=None,
        preference_weights={},
    )
