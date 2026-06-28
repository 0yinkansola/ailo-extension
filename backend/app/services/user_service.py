"""
AILO User Service — in-memory user profile store.

For MVP this is entirely in-memory.  Replace with Postgres + SQLAlchemy for production.
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict

from ..models.schemas import (
    InterestCategory,
    Language,
    MusicPreferences,
    ProficiencyLevel,
    UserProfile,
    UserProfileUpdate,
)

_DEFAULT_MUSIC: MusicPreferences = MusicPreferences(
    genres=["r&b", "alternative pop", "neo soul"],
    favorite_artists=[],
    moods=["chill", "dreamy"],
)


class UserService:

    def __init__(self) -> None:
        self._users: dict[str, UserProfile] = {}

    def create_user(
        self,
        target_language: Language,
        proficiency_level: ProficiencyLevel = ProficiencyLevel.A2,
        interests: list[InterestCategory] | None = None,
        music_preferences: MusicPreferences | None = None,
    ) -> UserProfile:
        user_id = str(uuid.uuid4())
        profile = UserProfile(
            user_id=user_id,
            target_language=target_language,
            proficiency_level=proficiency_level,
            interests=interests or [
                InterestCategory.music,
                InterestCategory.lifestyle,
                InterestCategory.fashion,
            ],
            music_preferences=music_preferences or _DEFAULT_MUSIC,
        )
        self._users[user_id] = profile
        return profile

    def get_user(self, user_id: str) -> UserProfile | None:
        return self._users.get(user_id)

    def update_user(self, user_id: str, update: UserProfileUpdate) -> UserProfile | None:
        profile = self._users.get(user_id)
        if not profile:
            return None

        data = profile.model_dump()
        if update.target_language is not None:
            data["target_language"] = update.target_language
        if update.proficiency_level is not None:
            data["proficiency_level"] = update.proficiency_level
        if update.interests is not None:
            data["interests"] = update.interests
        if update.music_preferences is not None:
            data["music_preferences"] = update.music_preferences.model_dump()

        self._users[user_id] = UserProfile(**data)
        return self._users[user_id]

    def update_preference_weights(
        self,
        user_id: str,
        new_weights: dict[str, float],
    ) -> None:
        profile = self._users.get(user_id)
        if not profile:
            return
        merged = {**profile.preference_weights, **new_weights}
        data = profile.model_dump()
        data["preference_weights"] = merged
        self._users[user_id] = UserProfile(**data)

    def set_spotify_tokens(
        self,
        user_id: str,
        access_token: str,
        refresh_token: str | None = None,
    ) -> None:
        profile = self._users.get(user_id)
        if not profile:
            return
        data = profile.model_dump()
        data["spotify_access_token"] = access_token
        if refresh_token:
            data["spotify_refresh_token"] = refresh_token
        self._users[user_id] = UserProfile(**data)

    def get_or_create_demo_user(self, language: str = "fr") -> UserProfile:
        """Returns a reusable demo user for the onboarding/preview experience."""
        demo_id = f"demo-{language}"
        if demo_id not in self._users:
            lang = Language(language)
            profile = UserProfile(
                user_id=demo_id,
                target_language=lang,
                proficiency_level=ProficiencyLevel.A2,
                interests=[
                    InterestCategory.music,
                    InterestCategory.fashion,
                    InterestCategory.lifestyle,
                    InterestCategory.arts,
                ],
                music_preferences=MusicPreferences(
                    genres=["neo soul", "r&b", "alternative pop"],
                    favorite_artists=["SZA", "Brent Faiyaz", "Frank Ocean", "Tems"],
                    moods=["chill", "dreamy", "emotional"],
                ),
            )
            self._users[demo_id] = profile
        return self._users[demo_id]


# Singleton
user_service = UserService()
