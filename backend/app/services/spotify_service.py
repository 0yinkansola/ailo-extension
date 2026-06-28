"""
AILO Spotify Service — taste-matching recommendation engine.

Architecture:
  1. SpotifyOAuthService  — handles Spotify OAuth flow (authorization URL → token exchange)
  2. SpotifyTasteAnalyzer — extracts a taste vector from the user's Spotify listening history
  3. ArtistMatcher        — maps English-language taste → target-language artists from the
                            curated catalog using cosine similarity + genre/mood overlap
  4. PlaylistBuilder      — assembles a themed DailyPlaylist from matched artists

When a Spotify access token is available the engine uses real listening data.
Without a token it falls back to the user's declared preferences (favorite_artists,
favorite_genres, preferred_moods from the request).
"""

from __future__ import annotations

import json
import math
import random
import secrets
import time
import urllib.parse
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from ..core.config import settings
from ..services.ml_scoring_service import ml_scoring_service
from ..models.schemas import (
    ArtistRecommendation,
    DailyPlaylist,
    Language,
    PlaylistTheme,
    ProficiencyLevel,
    SpotifyAuthURL,
    SpotifyRecommendationRequest,
    SpotifyRecommendationResponse,
    TrackItem,
)

# ─── Catalog ──────────────────────────────────────────────────────────────────

_CATALOG_PATH = Path(__file__).parent.parent / "data" / "artist_catalog.json"
_CATALOG: dict[str, Any] = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))

_ARTISTS_BY_LANG: dict[str, list[dict]] = {
    "fr": _CATALOG["fr"],
    "es": _CATALOG["es"],
}
_COMPARABLE_MAP: dict[str, dict[str, list[str]]] = _CATALOG["comparable_english_to_target"]
_MOOD_MAP: dict[str, dict[str, list[str]]] = _CATALOG["mood_to_artists"]

# Artist lookup by id across both languages
_ARTIST_BY_ID: dict[str, dict] = {
    a["id"]: a
    for lang_artists in _ARTISTS_BY_LANG.values()
    for a in lang_artists
}

# ─── Constants ────────────────────────────────────────────────────────────────

_SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
_SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
_SPOTIFY_API_BASE = "https://api.spotify.com/v1"

_SCOPES = " ".join([
    "user-top-read",
    "user-read-recently-played",
    "user-library-read",
    "playlist-modify-private",
])

# Playlist themes with display metadata
_PLAYLIST_THEMES: dict[str, dict] = {
    "morning_immersion": {
        "title_fr": "Réveil en Français",
        "title_es": "Despertar en Español",
        "desc_fr": "Start your morning immersed in the language — smooth, energizing, and clear.",
        "desc_es": "Empieza tu mañana inmerso en el idioma — suave, energizante y claro.",
        "gradient": ["#FF9A9E", "#FECFEF"],
        "moods": ["warm", "energetic", "fun"],
        "energy_range": (0.5, 0.9),
    },
    "chill_study": {
        "title_fr": "Session Étude Française",
        "title_es": "Sesión de Estudio",
        "desc_fr": "Low-key, focused immersion for deep work and language absorption.",
        "desc_es": "Inmersión tranquila y enfocada para trabajo profundo y absorción del idioma.",
        "gradient": ["#A18CD1", "#FBC2EB"],
        "moods": ["chill", "introspective", "smooth"],
        "energy_range": (0.2, 0.55),
    },
    "late_night": {
        "title_fr": "Nuits Parisiennes",
        "title_es": "Noches de Madrugada",
        "desc_fr": "Dark, atmospheric French sounds for late-night immersion.",
        "desc_es": "Sonidos nocturnos, atmósferos para inmersión de madrugada.",
        "gradient": ["#2C3E7A", "#0A0A2E"],
        "moods": ["late-night", "dreamy", "melancholic"],
        "energy_range": (0.25, 0.55),
    },
    "energy_boost": {
        "title_fr": "Énergie Française",
        "title_es": "Energía Latina",
        "desc_fr": "High-energy French tracks to keep you moving and the language flowing.",
        "desc_es": "Temas de alta energía para mantenerte en movimiento y el idioma fluyendo.",
        "gradient": ["#F093FB", "#F5576C"],
        "moods": ["energetic", "bold", "party"],
        "energy_range": (0.65, 1.0),
    },
    "emotional_depth": {
        "title_fr": "Profondeur Émotionnelle",
        "title_es": "Profundidad Emocional",
        "desc_fr": "Raw, emotional French music that connects language to feeling.",
        "desc_es": "Música emotiva que conecta el idioma con el sentimiento.",
        "gradient": ["#4A00E0", "#8E2DE2"],
        "moods": ["emotional", "introspective", "poetic"],
        "energy_range": (0.3, 0.6),
    },
    "discover_weekly": {
        "title_fr": "Découvertes de la Semaine",
        "title_es": "Descubrimientos de la Semana",
        "desc_fr": "Fresh French-language artists matched to your exact taste.",
        "desc_es": "Artistas hispanohablantes frescos, calibrados a tu gusto exacto.",
        "gradient": ["#11998E", "#38EF7D"],
        "moods": ["chill", "dreamy", "smooth"],
        "energy_range": (0.3, 0.7),
    },
}

# ─── OAuth ─────────────────────────────────────────────────────────────────────

class SpotifyOAuthService:
    """Handles Spotify OAuth 2.0 Authorization Code flow."""

    # In-memory state storage for MVP (use Redis in production)
    _pending_states: dict[str, str] = {}  # state → user_id

    def get_auth_url(self, user_id: str) -> SpotifyAuthURL:
        state = secrets.token_urlsafe(16)
        self._pending_states[state] = user_id

        params = {
            "client_id": settings.spotify_client_id,
            "response_type": "code",
            "redirect_uri": settings.spotify_redirect_uri,
            "scope": _SCOPES,
            "state": state,
            "show_dialog": "false",
        }
        auth_url = f"{_SPOTIFY_AUTH_URL}?{urllib.parse.urlencode(params)}"
        return SpotifyAuthURL(auth_url=auth_url, state=state)

    async def exchange_code(self, code: str, state: str) -> dict | None:
        user_id = self._pending_states.pop(state, None)
        if user_id is None:
            return None

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                _SPOTIFY_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": settings.spotify_redirect_uri,
                },
                auth=(settings.spotify_client_id, settings.spotify_client_secret),
            )
            if resp.status_code != 200:
                return None

            token_data = resp.json()
            return {"user_id": user_id, **token_data}

    async def refresh_token(self, refresh_token: str) -> dict | None:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                _SPOTIFY_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                auth=(settings.spotify_client_id, settings.spotify_client_secret),
            )
            if resp.status_code != 200:
                return None
            return resp.json()


# ─── Taste Analyzer ───────────────────────────────────────────────────────────

class SpotifyTasteAnalyzer:
    """
    Fetches user listening data from Spotify and extracts a taste vector.

    Taste vector keys:
      energy        — average track energy (0.0–1.0)
      valence       — average emotional positivity (0.0–1.0)
      acousticness  — acoustic vs electronic preference
      danceability  — rhythm preference
      genres        — weighted list of genres the user listens to
      moods         — inferred moods from audio features
    """

    async def get_taste_vector(self, access_token: str) -> dict | None:
        headers = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient() as client:
            top_tracks = await self._fetch_top_tracks(client, headers)
            if not top_tracks:
                return None

            top_artists = await self._fetch_top_artists(client, headers)
            audio_features = await self._fetch_audio_features(
                client, headers, [t["id"] for t in top_tracks[:20]]
            )

        return self._compute_taste_vector(top_tracks, top_artists, audio_features)

    async def _fetch_top_tracks(
        self, client: httpx.AsyncClient, headers: dict
    ) -> list[dict]:
        resp = await client.get(
            f"{_SPOTIFY_API_BASE}/me/top/tracks",
            headers=headers,
            params={"limit": 20, "time_range": "medium_term"},
        )
        if resp.status_code != 200:
            return []
        return resp.json().get("items", [])

    async def _fetch_top_artists(
        self, client: httpx.AsyncClient, headers: dict
    ) -> list[dict]:
        resp = await client.get(
            f"{_SPOTIFY_API_BASE}/me/top/artists",
            headers=headers,
            params={"limit": 20, "time_range": "medium_term"},
        )
        if resp.status_code != 200:
            return []
        return resp.json().get("items", [])

    async def _fetch_audio_features(
        self,
        client: httpx.AsyncClient,
        headers: dict,
        track_ids: list[str],
    ) -> list[dict]:
        if not track_ids:
            return []
        resp = await client.get(
            f"{_SPOTIFY_API_BASE}/audio-features",
            headers=headers,
            params={"ids": ",".join(track_ids)},
        )
        if resp.status_code != 200:
            return []
        return [f for f in resp.json().get("audio_features", []) if f]

    def _compute_taste_vector(
        self,
        tracks: list[dict],
        artists: list[dict],
        features: list[dict],
    ) -> dict:
        if not features:
            return {}

        energy = sum(f["energy"] for f in features) / len(features)
        valence = sum(f["valence"] for f in features) / len(features)
        acousticness = sum(f["acousticness"] for f in features) / len(features)
        danceability = sum(f["danceability"] for f in features) / len(features)

        # Collect genres from top artists (Spotify tags artists, not tracks)
        genre_counts: dict[str, int] = {}
        for artist in artists:
            for genre in artist.get("genres", []):
                genre_counts[genre] = genre_counts.get(genre, 0) + 1
        top_genres = sorted(genre_counts, key=lambda g: genre_counts[g], reverse=True)[:8]

        # Infer moods from audio feature profile
        moods = _infer_moods(energy, valence, acousticness, danceability)

        # Artist names for comparable-map lookup
        artist_names = [a["name"] for a in artists[:10]]

        return {
            "energy": energy,
            "valence": valence,
            "acousticness": acousticness,
            "danceability": danceability,
            "genres": top_genres,
            "moods": moods,
            "top_artist_names": artist_names,
        }


def _infer_moods(
    energy: float, valence: float, acousticness: float, danceability: float
) -> list[str]:
    moods = []
    if energy < 0.4 and valence < 0.4:
        moods.append("melancholic")
    if energy < 0.45:
        moods.append("chill")
    if energy > 0.65:
        moods.append("energetic")
    if valence < 0.35:
        moods.append("introspective")
    if acousticness > 0.5:
        moods.append("acoustic")
    if danceability > 0.7:
        moods.append("party")
    if energy < 0.5 and valence < 0.45 and acousticness < 0.4:
        moods.append("dreamy")
    if energy < 0.5 and valence < 0.4:
        moods.append("late-night")
    if valence > 0.6 and energy > 0.5:
        moods.append("fun")
    return moods or ["chill"]


# ─── Artist Matcher ───────────────────────────────────────────────────────────

class ArtistMatcher:
    """
    Scores each artist in the catalog against the user's taste vector.

    Scoring components:
      - Audio feature cosine similarity (energy, valence, acousticness, danceability)
      - Genre overlap (user's Spotify genres ↔ artist's catalog genres)
      - Mood overlap (inferred moods ↔ artist moods)
      - Comparable-artist bonus (user's top artists appear in catalog's comparable_english list)
      - Proficiency filter (penalize artists with difficulty above user's level)
    """

    _CEFR_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2"]

    def score_artists(
        self,
        language: str,
        taste_vector: dict,
        proficiency: ProficiencyLevel,
        preference_weights: dict[str, float],
        count: int = 8,
    ) -> list[ArtistRecommendation]:
        candidates = _ARTISTS_BY_LANG.get(language, [])
        scored: list[tuple[float, dict, str]] = []

        user_level_idx = self._CEFR_ORDER.index(proficiency.value)

        # Derive user taste for ML from highest-weighted genre in preference weights.
        # Keys may arrive with "genre:" namespace prefix (from get_weights) or flat
        # (from get_flat_weights). Both forms are handled below.
        _TASTE_VOCAB = {"afrobeat", "chill", "hiphop", "latin", "pop"}
        user_taste = "pop"
        for key in sorted(preference_weights, key=lambda k: preference_weights[k], reverse=True):
            clean = key.split(":", 1)[-1] if ":" in key else key
            if clean in _TASTE_VOCAB and preference_weights[key] > 0:
                user_taste = clean
                break

        for artist in candidates:
            score, reason = self._score(
                artist, taste_vector, user_level_idx, preference_weights
            )
            # ── ML like-probability boost ─────────────────────────────────────
            ml_prob = ml_scoring_service.score_spotify_artist(
                artist,
                user_taste=user_taste,
                user_cefr=proficiency.value,
                target_language=language,
            )
            score += ml_prob * 2.0
            scored.append((score, artist, reason))

        scored.sort(key=lambda x: x[0], reverse=True)
        # Oversample then re-rank for diversity via MMR
        pool = scored[: min(len(scored), count * 2)]
        final = self._mmr_rerank(pool, count)

        return [
            self._to_recommendation(artist, score, reason, language)
            for score, artist, reason in final
        ]

    def _mmr_rerank(
        self,
        pool: list[tuple[float, dict, str]],
        count: int,
        lambda_: float = 0.7,
    ) -> list[tuple[float, dict, str]]:
        """Maximal Marginal Relevance: balance relevance with audio diversity."""
        if not pool:
            return []
        max_s = pool[0][0]
        min_s = pool[-1][0]
        span = max_s - min_s if max_s != min_s else 1.0

        selected: list[tuple[float, dict, str]] = []
        remaining = list(pool)

        while len(selected) < count and remaining:
            if not selected:
                best = remaining[0]
            else:
                sel_vecs = [self._audio_vec(a) for _, a, _ in selected]

                def _mmr_score(item: tuple[float, dict, str], sv=sel_vecs) -> float:
                    rel = (item[0] - min_s) / span
                    vec = self._audio_vec(item[1])
                    max_sim = max(_cosine_similarity(vec, s) for s in sv)
                    return lambda_ * rel - (1 - lambda_) * max_sim

                best = max(remaining, key=_mmr_score)

            selected.append(best)
            remaining.remove(best)

        return selected

    def _audio_vec(self, artist: dict) -> list[float]:
        return [
            artist.get("energy_level", 0.5),
            artist.get("valence", 0.5),
            artist.get("acousticness", 0.3),
            artist.get("danceability", 0.6),
        ]

    def _score(
        self,
        artist: dict,
        taste: dict,
        user_level_idx: int,
        pref_weights: dict[str, float],
    ) -> tuple[float, str]:
        score = 0.0
        reasons: list[str] = []

        # ── Audio feature cosine similarity ──────────────────────────────────
        if taste:
            a_vec = [
                artist["energy_level"],
                artist["valence"],
                artist["acousticness"],
                artist["danceability"],
            ]
            u_vec = [
                taste.get("energy", 0.5),
                taste.get("valence", 0.5),
                taste.get("acousticness", 0.3),
                taste.get("danceability", 0.6),
            ]
            sim = _cosine_similarity(a_vec, u_vec)
            score += sim * 4.0
            if sim > 0.92:
                reasons.append("sonic match")

        # ── Comparable-artist bonus ───────────────────────────────────────────
        user_artists = [n.lower() for n in taste.get("top_artist_names", [])]
        comp_english = [c.lower() for c in artist.get("comparable_english", [])]
        overlap_artists = set(user_artists) & set(comp_english)
        if overlap_artists:
            score += len(overlap_artists) * 1.5
            reasons.append(f"sounds like {', '.join(overlap_artists)}")

        # ── Genre overlap ─────────────────────────────────────────────────────
        user_genres_raw = [g.lower() for g in taste.get("genres", [])]
        artist_genres = [g.lower() for g in artist.get("genres", [])]
        genre_hits = sum(
            1 for ug in user_genres_raw
            for ag in artist_genres
            if ug in ag or ag in ug
        )
        score += genre_hits * 0.8

        # ── Mood overlap ──────────────────────────────────────────────────────
        user_moods = [m.lower() for m in taste.get("moods", [])]
        artist_moods = [m.lower() for m in artist.get("moods", [])]
        mood_hits = len(set(user_moods) & set(artist_moods))
        score += mood_hits * 0.6
        if mood_hits >= 2:
            reasons.append("matches your vibe")

        # ── Preference weight boost ───────────────────────────────────────────
        for genre in artist_genres:
            w = pref_weights.get(genre, 0.0)
            score += w * 1.2
        for mood in artist_moods:
            w = pref_weights.get(mood, 0.0)
            score += w * 0.8
        artist_weight = pref_weights.get(artist["id"], 0.0)
        score += artist_weight * 2.0

        # ── Proficiency suitability ───────────────────────────────────────────
        friendly_levels = artist.get("proficiency_friendly", [])
        level_ok = any(
            abs(self._CEFR_ORDER.index(lvl) - user_level_idx) <= 1
            for lvl in friendly_levels
            if lvl in self._CEFR_ORDER
        )
        if not level_ok:
            score -= 1.5  # penalty — possible but not ideal

        # ── Novelty tiebreaker ────────────────────────────────────────────────
        score += random.uniform(0, 0.3)

        reason = reasons[0] if reasons else "matches your style"
        return score, reason

    def _to_recommendation(
        self,
        artist: dict,
        score: float,
        reason: str,
        language: str,
    ) -> ArtistRecommendation:
        return ArtistRecommendation(
            id=artist["id"],
            name=artist["name"],
            spotify_id=artist.get("spotify_id", ""),
            language=Language(language),
            genres=artist.get("genres", []),
            moods=artist.get("moods", []),
            energy_level=artist.get("energy_level", 0.5),
            valence=artist.get("valence", 0.5),
            comparable_english=artist.get("comparable_english", []),
            description=artist.get("description", ""),
            match_score=round(score, 2),
            match_reason=reason,
            spotify_url=f"https://open.spotify.com/artist/{artist.get('spotify_id', '')}",
        )


# ─── Playlist Builder ─────────────────────────────────────────────────────────

class PlaylistBuilder:
    """
    Assembles a DailyPlaylist from matched artists.

    For each artist it creates representative TrackItem stubs.
    When a real Spotify access token is available it fetches actual top tracks.
    """

    async def build_daily_playlist(
        self,
        artists: list[ArtistRecommendation],
        theme: PlaylistTheme,
        language: Language,
        access_token: str | None = None,
    ) -> DailyPlaylist:
        theme_meta = _PLAYLIST_THEMES.get(theme.value, _PLAYLIST_THEMES["discover_weekly"])
        lang = language.value

        title = theme_meta.get(f"title_{lang}", f"Daily {lang.upper()} Playlist")
        desc = theme_meta.get(f"desc_{lang}", "Your personalized immersion playlist.")
        gradient = theme_meta["gradient"]

        energy_min, energy_max = theme_meta["energy_range"]
        # Filter artists whose energy profile fits the theme
        filtered = [
            a for a in artists
            if energy_min <= a.energy_level <= energy_max
        ] or artists  # fall back to full list if none match

        tracks: list[TrackItem] = []

        if access_token:
            tracks = await self._fetch_real_tracks(
                filtered[:5], access_token, energy_min, energy_max
            )

        if not tracks:
            tracks = self._build_stub_tracks(filtered[:6], energy_min, energy_max)

        return DailyPlaylist(
            id=f"playlist-{lang}-{date.today().isoformat()}",
            title=title,
            description=desc,
            theme=theme,
            language=language,
            tracks=tracks[:15],
            generated_at=int(time.time() * 1000),
            cover_gradient=gradient,
        )

    async def _fetch_real_tracks(
        self,
        artists: list[ArtistRecommendation],
        access_token: str,
        energy_min: float,
        energy_max: float,
    ) -> list[TrackItem]:
        tracks: list[TrackItem] = []
        headers = {"Authorization": f"Bearer {access_token}"}

        async with httpx.AsyncClient() as client:
            for artist in artists[:5]:
                if not artist.spotify_id:
                    continue
                resp = await client.get(
                    f"{_SPOTIFY_API_BASE}/artists/{artist.spotify_id}/top-tracks",
                    headers=headers,
                    params={"market": "US"},
                )
                if resp.status_code != 200:
                    continue

                raw_tracks = resp.json().get("tracks", [])[:3]
                for t in raw_tracks:
                    album = t.get("album", {})
                    images = album.get("images", [])
                    image_url = images[0]["url"] if images else None
                    tracks.append(TrackItem(
                        id=t["id"],
                        title=t["name"],
                        artist=artist.name,
                        artist_id=artist.id,
                        language=artist.language,
                        genres=artist.genres,
                        mood=artist.moods[0] if artist.moods else "chill",
                        energy_level=artist.energy_level,
                        valence=artist.valence,
                        danceability=0.65,
                        explicit=t.get("explicit", False),
                        preview_url=t.get("preview_url"),
                        spotify_url=t.get("external_urls", {}).get("spotify", ""),
                        image_url=image_url,
                        duration_ms=t.get("duration_ms", 0),
                    ))

        return tracks

    def _build_stub_tracks(
        self,
        artists: list[ArtistRecommendation],
        energy_min: float,
        energy_max: float,
    ) -> list[TrackItem]:
        """Create representative track stubs from catalog artists (no Spotify auth needed)."""
        tracks: list[TrackItem] = []
        for artist in artists:
            # Each artist contributes 2 stub tracks
            for i in range(2):
                tracks.append(TrackItem(
                    id=f"stub-{artist.id}-{i}",
                    title=f"{artist.name} — Track {i + 1}",
                    artist=artist.name,
                    artist_id=artist.id,
                    language=artist.language,
                    genres=artist.genres,
                    mood=artist.moods[0] if artist.moods else "chill",
                    energy_level=artist.energy_level,
                    valence=artist.valence,
                    danceability=0.65,
                    explicit=False,
                    spotify_url=f"https://open.spotify.com/artist/{artist.spotify_id}",
                    image_url=None,
                    duration_ms=210_000,
                ))
        return tracks


# ─── Main Service ─────────────────────────────────────────────────────────────

class SpotifyRecommendationService:
    def __init__(self) -> None:
        self._oauth = SpotifyOAuthService()
        self._analyzer = SpotifyTasteAnalyzer()
        self._matcher = ArtistMatcher()
        self._builder = PlaylistBuilder()
        self._app_token: str | None = None
        self._app_token_expires: float = 0.0

    def get_auth_url(self, user_id: str) -> SpotifyAuthURL:
        return self._oauth.get_auth_url(user_id)

    async def handle_callback(self, code: str, state: str) -> dict | None:
        return await self._oauth.exchange_code(code, state)

    async def _get_app_token(self) -> str | None:
        """Client Credentials token — no user login required."""
        if not settings.spotify_client_id or not settings.spotify_client_secret:
            return None
        if self._app_token and time.time() < self._app_token_expires - 60:
            return self._app_token
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                _SPOTIFY_TOKEN_URL,
                data={"grant_type": "client_credentials"},
                auth=(settings.spotify_client_id, settings.spotify_client_secret),
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            self._app_token = data.get("access_token")
            self._app_token_expires = time.time() + data.get("expires_in", 3600)
            return self._app_token

    async def get_recommendations(
        self,
        request: SpotifyRecommendationRequest,
        access_token: str | None,
        preference_weights: dict[str, float],
    ) -> SpotifyRecommendationResponse:
        lang = request.target_language.value

        # ── Build taste vector ────────────────────────────────────────────────
        taste_vector: dict = {}

        if access_token:
            taste_vector = await self._analyzer.get_taste_vector(access_token) or {}

        if not taste_vector:
            taste_vector = self._synthesize_taste_vector(
                request.favorite_artists,
                request.favorite_genres,
                request.preferred_moods,
            )

        # ── Score and rank artists ────────────────────────────────────────────
        matched_artists = self._matcher.score_artists(
            language=lang,
            taste_vector=taste_vector,
            proficiency=request.proficiency_level,
            preference_weights=preference_weights,
            count=request.count,
        )

        # ── Choose playlist theme based on taste ──────────────────────────────
        theme = _pick_playlist_theme(taste_vector)

        # ── Use app token for real tracks when no user token available ────────
        effective_token = access_token or await self._get_app_token()

        # ── Build playlist ────────────────────────────────────────────────────
        playlist = await self._builder.build_daily_playlist(
            artists=matched_artists,
            theme=theme,
            language=request.target_language,
            access_token=effective_token,
        )

        return SpotifyRecommendationResponse(
            artists=matched_artists,
            daily_playlist=playlist,
            generated_at=int(time.time() * 1000),
        )

    def _synthesize_taste_vector(
        self,
        favorite_artists: list[str],
        favorite_genres: list[str],
        preferred_moods: list[str],
    ) -> dict:
        """Build a taste vector from declared preferences without Spotify data."""
        # Look up catalog artists that appear in comparable_english to find audio profile
        energy_samples, valence_samples = [], []

        for artist_name in favorite_artists:
            for comp_artist, lang_map in _COMPARABLE_MAP.items():
                if comp_artist.lower() == artist_name.lower():
                    # Found a match — look up a catalog artist for audio features
                    for lang_artists in lang_map.values():
                        for cat_id in lang_artists[:1]:
                            cat_artist = _ARTIST_BY_ID.get(cat_id, {})
                            if cat_artist:
                                energy_samples.append(cat_artist.get("energy_level", 0.5))
                                valence_samples.append(cat_artist.get("valence", 0.4))

        energy = (sum(energy_samples) / len(energy_samples)) if energy_samples else 0.5
        valence = (sum(valence_samples) / len(valence_samples)) if valence_samples else 0.4

        moods = list(preferred_moods) or _infer_moods(energy, valence, 0.3, 0.6)

        return {
            "energy": energy,
            "valence": valence,
            "acousticness": 0.3,
            "danceability": 0.65,
            "genres": favorite_genres,
            "moods": moods,
            "top_artist_names": favorite_artists,
        }


# ─── Utilities ────────────────────────────────────────────────────────────────

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def _pick_playlist_theme(taste_vector: dict) -> PlaylistTheme:
    energy = taste_vector.get("energy", 0.5)
    valence = taste_vector.get("valence", 0.4)
    moods = taste_vector.get("moods", [])

    if "late-night" in moods or (energy < 0.45 and valence < 0.4):
        return PlaylistTheme.late_night
    if energy > 0.65:
        return PlaylistTheme.energy_boost
    if "emotional" in moods or "melancholic" in moods:
        return PlaylistTheme.emotional_depth
    if energy < 0.45:
        return PlaylistTheme.chill_study
    return PlaylistTheme.discover_weekly


# Singleton
spotify_recommendation_service = SpotifyRecommendationService()
