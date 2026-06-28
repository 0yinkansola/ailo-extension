from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


# ─── Enums ────────────────────────────────────────────────────────────────────

class Language(str, Enum):
    fr = "fr"
    es = "es"


class ProficiencyLevel(str, Enum):
    """CEFR language proficiency scale (A1–C2).

    A1 Beginner     – very basic phrases, survival vocabulary (~500 words)
    A2 Elementary   – everyday expressions, simple direct communication (~1500 words)
    B1 Intermediate – main points of clear standard speech, simple connected text
    B2 Upper-Inter  – complex text, spontaneous fluent interaction
    C1 Advanced     – implicit meaning, demanding longer texts
    C2 Mastery      – virtually everything, near-native fluency
    """
    A1 = "A1"
    A2 = "A2"
    B1 = "B1"
    B2 = "B2"
    C1 = "C1"
    C2 = "C2"


class InterestCategory(str, Enum):
    fashion    = "fashion"
    music      = "music"
    sports     = "sports"
    gaming     = "gaming"
    cooking    = "cooking"
    travel     = "travel"
    comedy     = "comedy"
    technology = "technology"
    fitness    = "fitness"
    arts       = "arts"
    education  = "education"
    lifestyle  = "lifestyle"
    news       = "news"
    animation  = "animation"
    beauty     = "beauty"


# ─── Default interests ────────────────────────────────────────────────────────
# Broad set used when the AILO user system has not yet provided inferred interests.
# Covers high-recall topics that work well at A2 level across both languages.

_DEFAULT_INTERESTS: list[InterestCategory] = list(InterestCategory)


def _default_interests() -> list[InterestCategory]:
    return list(_DEFAULT_INTERESTS)


# ─── Request / Response ───────────────────────────────────────────────────────

class RecommendationRequest(BaseModel):
    targetLanguage: Language

    # ── Proficiency ──────────────────────────────────────────────────────────
    # Hardcoded A2 (CEFR Elementary) until the AILO user profile system is
    # integrated and can supply per-user per-language proficiency levels.
    proficiencyLevel: ProficiencyLevel = ProficiencyLevel.A2

    # ── Interests ────────────────────────────────────────────────────────────
    # Broad defaults until YouTube watch-history behaviour analysis is wired in.
    interests: list[InterestCategory] = Field(
        default_factory=_default_interests,
        max_length=15,
    )

    # ── Topic weights ─────────────────────────────────────────────────────────
    # Per-topic preference scores derived from user like/dislike feedback and
    # YouTube DOM watch-history inference.  Range: -1.0 (skip) → +1.0 (boost).
    # None means treat all topics equally.
    topicWeights: dict[str, float] | None = None

    count: int = Field(default=40, ge=1, le=50)


class VideoRecommendation(BaseModel):
    id: str
    title: str
    channelName: str
    channelId: str
    thumbnailUrl: str
    viewCount: str
    publishedAt: str
    duration: str
    language: Language
    proficiencyLevel: ProficiencyLevel
    topics: list[InterestCategory]
    hasSubtitles: bool
    videoUrl: str


class RecommendationResponse(BaseModel):
    videos: list[VideoRecommendation]
    generatedAt: int        # unix ms
    cacheHit: bool = False


# ─── YouTube API raw shapes ───────────────────────────────────────────────────

class YouTubeVideoItem(BaseModel):
    video_id: str
    title: str
    channel_name: str
    channel_id: str
    thumbnail_url: str
    published_at: str
    duration: str = "PT0S"
    view_count: str = "0"
    has_captions: bool = False
    description: str = ""


# ═══════════════════════════════════════════════════════════════════════════════
# USER PROFILE
# ═══════════════════════════════════════════════════════════════════════════════

class MusicPreferences(BaseModel):
    genres: list[str] = Field(default_factory=list)
    favorite_artists: list[str] = Field(default_factory=list)
    moods: list[str] = Field(default_factory=list)


class UserProfile(BaseModel):
    user_id: str
    target_language: Language
    proficiency_level: ProficiencyLevel = ProficiencyLevel.A2
    interests: list[InterestCategory] = Field(default_factory=_default_interests)
    music_preferences: MusicPreferences = Field(default_factory=MusicPreferences)
    # Adaptive weights: genre/mood/artist keys → score (-1.0 to +1.0)
    preference_weights: dict[str, float] = Field(default_factory=dict)
    spotify_access_token: str | None = None
    spotify_refresh_token: str | None = None
    created_at: int = Field(default_factory=lambda: int(__import__("time").time()))


class UserProfileUpdate(BaseModel):
    target_language: Language | None = None
    proficiency_level: ProficiencyLevel | None = None
    interests: list[InterestCategory] | None = None
    music_preferences: MusicPreferences | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# SPOTIFY / MUSIC RECOMMENDATION
# ═══════════════════════════════════════════════════════════════════════════════

class LyricComplexity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    very_high = "very_high"


class EnergyLevel(str, Enum):
    very_low = "very_low"
    low = "low"
    medium = "medium"
    high = "high"
    very_high = "very_high"


class ArtistRecommendation(BaseModel):
    id: str
    name: str
    spotify_id: str
    language: Language
    genres: list[str]
    moods: list[str]
    energy_level: float
    valence: float
    comparable_english: list[str]
    description: str
    match_score: float = 0.0
    match_reason: str = ""
    image_url: str | None = None
    spotify_url: str = ""


class TrackItem(BaseModel):
    id: str
    title: str
    artist: str
    artist_id: str
    language: Language
    genres: list[str]
    mood: str
    energy_level: float
    valence: float
    danceability: float
    lyric_complexity: LyricComplexity = LyricComplexity.medium
    explicit: bool = False
    preview_url: str | None = None
    spotify_url: str = ""
    image_url: str | None = None
    duration_ms: int = 0


class PlaylistTheme(str, Enum):
    morning_immersion = "morning_immersion"
    chill_study = "chill_study"
    late_night = "late_night"
    energy_boost = "energy_boost"
    emotional_depth = "emotional_depth"
    discover_weekly = "discover_weekly"


class DailyPlaylist(BaseModel):
    id: str
    title: str
    description: str
    theme: PlaylistTheme
    language: Language
    tracks: list[TrackItem]
    generated_at: int
    cover_gradient: list[str]  # CSS gradient stop colors


class SpotifyRecommendationRequest(BaseModel):
    user_id: str
    target_language: Language
    proficiency_level: ProficiencyLevel = ProficiencyLevel.A2
    favorite_artists: list[str] = Field(default_factory=list)
    favorite_genres: list[str] = Field(default_factory=list)
    preferred_moods: list[str] = Field(default_factory=list)
    count: int = Field(default=10, ge=1, le=30)


class SpotifyRecommendationResponse(BaseModel):
    artists: list[ArtistRecommendation]
    daily_playlist: DailyPlaylist
    generated_at: int


# ═══════════════════════════════════════════════════════════════════════════════
# PERSONALIZATION — interaction tracking
# ═══════════════════════════════════════════════════════════════════════════════

class InteractionType(str, Enum):
    like = "like"
    skip = "skip"
    save = "save"
    replay = "replay"
    more_like_this = "more_like_this"
    dislike = "dislike"
    complete = "complete"


class TrackInteraction(BaseModel):
    user_id: str
    track_id: str
    artist_id: str
    interaction: InteractionType
    genres: list[str] = Field(default_factory=list)
    moods: list[str] = Field(default_factory=list)
    energy_level: float | None = None
    timestamp: int = Field(default_factory=lambda: int(__import__("time").time()))


class PreferenceWeightUpdate(BaseModel):
    """Returned after processing an interaction — shows what changed."""
    updated_keys: list[str]
    new_weights: dict[str, float]


# ═══════════════════════════════════════════════════════════════════════════════
# DAILY CONTENT — words, facts, prompts
# ═══════════════════════════════════════════════════════════════════════════════

class WordOfTheDay(BaseModel):
    word: str
    pronunciation: str
    part_of_speech: str
    meaning: str
    example: str
    translation: str
    casual_usage: str
    cultural_context: str
    internet_usage: str
    difficulty: str
    category: str
    language: Language
    date: str  # YYYY-MM-DD


class DailyFact(BaseModel):
    title: str
    fact: str
    category: str
    difficulty: str
    emoji: str
    language: Language
    date: str


class JournalPrompt(BaseModel):
    id: str
    prompt: str
    english_hint: str
    starter_phrase: str
    category: str
    interests: list[str]
    language: Language
    proficiency_level: ProficiencyLevel
    date: str


class DailyContentResponse(BaseModel):
    word_of_the_day: WordOfTheDay
    daily_fact: DailyFact
    journal_prompt: JournalPrompt
    language: Language
    date: str


# ═══════════════════════════════════════════════════════════════════════════════
# SPOTIFY OAUTH
# ═══════════════════════════════════════════════════════════════════════════════

class SpotifyAuthURL(BaseModel):
    auth_url: str
    state: str


class SpotifyCallbackResult(BaseModel):
    success: bool
    user_id: str | None = None
    message: str = ""


# ═══════════════════════════════════════════════════════════════════════════════
# AUTH
# ═══════════════════════════════════════════════════════════════════════════════

class UserCreate(BaseModel):
    username: str
    email: str
    password: str
    target_language: Language


class UserLogin(BaseModel):
    email: str
    password: str


class AuthUser(BaseModel):
    user_id: str
    username: str
    email: str
    target_language: Language
    proficiency_level: ProficiencyLevel
    interests: list[InterestCategory]


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: AuthUser
