"""
AILO User Profile routes.

Endpoints:
  POST /api/users                  — create a user profile
  GET  /api/users/{user_id}        — get profile
  PATCH /api/users/{user_id}       — update profile
  GET  /api/users/demo/{language}  — get or create demo profile
"""

from fastapi import APIRouter, HTTPException

from ...models.schemas import (
    Language,
    MusicPreferences,
    ProficiencyLevel,
    UserProfile,
    UserProfileUpdate,
)
from ...services.user_service import user_service

router = APIRouter(prefix="/api/users")


class CreateUserRequest(UserProfileUpdate):
    target_language: Language  # required on create
    proficiency_level: ProficiencyLevel = ProficiencyLevel.A2
    music_preferences: MusicPreferences | None = None


@router.post("", response_model=UserProfile, tags=["users"])
async def create_user(body: CreateUserRequest) -> UserProfile:
    return user_service.create_user(
        target_language=body.target_language,
        proficiency_level=body.proficiency_level,
        interests=body.interests,
        music_preferences=body.music_preferences,
    )


@router.get("/{user_id}", response_model=UserProfile, tags=["users"])
async def get_user(user_id: str) -> UserProfile:
    profile = user_service.get_user(user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="User not found")
    return profile


@router.patch("/{user_id}", response_model=UserProfile, tags=["users"])
async def update_user(user_id: str, body: UserProfileUpdate) -> UserProfile:
    profile = user_service.update_user(user_id, body)
    if not profile:
        raise HTTPException(status_code=404, detail="User not found")
    return profile


@router.get("/demo/{language}", response_model=UserProfile, tags=["users"])
async def get_demo_user(language: str = "fr") -> UserProfile:
    try:
        Language(language)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unsupported language: {language}")
    return user_service.get_or_create_demo_user(language)
