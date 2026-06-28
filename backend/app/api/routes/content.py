"""
AILO Daily Content routes.

Endpoints:
  GET /api/content/daily          — full daily content bundle (word + fact + prompt)
  GET /api/content/word-of-day    — word of the day only
  GET /api/content/fact           — daily fact only
  GET /api/content/prompt         — journal prompt only
"""

from datetime import date

from fastapi import APIRouter, HTTPException, Query

from ...models.schemas import (
    DailyContentResponse,
    DailyFact,
    JournalPrompt,
    Language,
    ProficiencyLevel,
    WordOfTheDay,
)
from ...services.content_service import content_service
from ...services.user_service import user_service

router = APIRouter(prefix="/api/content")


def _resolve_profile(
    user_id: str | None,
    language: str,
    level: str,
    interests: list[str],
) -> tuple[Language, ProficiencyLevel, list[str]]:
    """Resolve language/level/interests from user profile or explicit query params."""
    if user_id:
        profile = user_service.get_user(user_id)
        if profile:
            return (
                profile.target_language,
                profile.proficiency_level,
                [i.value for i in profile.interests],
            )

    try:
        lang = Language(language)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unsupported language: {language}")

    try:
        lvl = ProficiencyLevel(level.upper())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid proficiency level: {level}")

    return lang, lvl, interests


@router.get("/daily", response_model=DailyContentResponse, tags=["content"])
async def get_daily_content(
    user_id: str | None = Query(None),
    language: str = Query("fr"),
    level: str = Query("A2"),
    interests: list[str] = Query(default=["music", "fashion", "lifestyle"]),
    target_date: str | None = Query(None, description="YYYY-MM-DD override for testing"),
) -> DailyContentResponse:
    """Return the full daily content bundle for a user or explicit language/level."""
    lang, lvl, resolved_interests = _resolve_profile(user_id, language, level, interests)

    parsed_date = None
    if target_date:
        try:
            parsed_date = date.fromisoformat(target_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    return content_service.get_daily_content(
        language=lang,
        proficiency=lvl,
        interests=resolved_interests,
        target_date=parsed_date,
    )


@router.get("/word-of-day", response_model=WordOfTheDay, tags=["content"])
async def get_word_of_day(
    user_id: str | None = Query(None),
    language: str = Query("fr"),
    level: str = Query("A2"),
    interests: list[str] = Query(default=["music", "lifestyle"]),
) -> WordOfTheDay:
    lang, lvl, resolved_interests = _resolve_profile(user_id, language, level, interests)
    result = content_service.get_daily_content(lang, lvl, resolved_interests)
    return result.word_of_the_day


@router.get("/fact", response_model=DailyFact, tags=["content"])
async def get_daily_fact(
    user_id: str | None = Query(None),
    language: str = Query("fr"),
    level: str = Query("A2"),
) -> DailyFact:
    lang, lvl, _ = _resolve_profile(user_id, language, level, [])
    result = content_service.get_daily_content(lang, lvl, [])
    return result.daily_fact


@router.get("/prompt", response_model=JournalPrompt, tags=["content"])
async def get_journal_prompt(
    user_id: str | None = Query(None),
    language: str = Query("fr"),
    level: str = Query("A2"),
    interests: list[str] = Query(default=["music", "lifestyle"]),
) -> JournalPrompt:
    lang, lvl, resolved_interests = _resolve_profile(user_id, language, level, interests)
    result = content_service.get_daily_content(lang, lvl, resolved_interests)
    return result.journal_prompt
