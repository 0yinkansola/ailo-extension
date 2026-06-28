"""
AILO ML Scoring Service — model inference.

Loads pre-trained models from app/data/models/ and exposes two methods:

  score_spotify_artist(artist, user_taste, user_cefr) -> float  [0-1]
  score_youtube_video(...)                             -> float  [0-1]

YouTube model supports two artifact formats:
  - model_type="gradient_boosting"  sklearn GBC (new, preferred)
  - no model_type key               pure-Python logistic regression (legacy fallback)

Both return predicted P(watched=1). Falls back to 0.5 if model not found.
"""

from __future__ import annotations

import math
import pickle
import re
from pathlib import Path

try:
    import numpy as np
    _NUMPY_OK = True
except ImportError:
    _NUMPY_OK = False

_MODEL_DIR = Path(__file__).parent.parent / "data" / "models"

_CEFR_ORDER = {"A1": 0, "A2": 1, "B1": 2, "B2": 3, "C1": 4, "C2": 5}

_SPOTIFY_DEFAULTS = {
    "tempo": 120.0,
    "speechiness": 0.1,
    "popularity": 50.0,
}

_YOUTUBE_DEFAULTS = {
    "speech_speed": 130.0,
    "engagement_score": 0.5,
}

# ── Genre / interest normalisation ───────────────────────────────────────────
# Maps the rich catalog genre strings (and Spotify API genres) to the 5-entry
# training vocabulary: afrobeat | chill | hiphop | latin | pop
# Uses substring matching so accented variants are handled automatically.

_GENRE_KEYWORDS: list[tuple[list[str], str]] = [
    # hiphop — must come before "pop" to avoid "hip hop" matching "pop"
    (["hip hop", "hip-hop", "hiphop", "rap", "trap", "drill",
      "r&b", "rnb", "neo soul"], "hiphop"),
    # afrobeat
    (["afrobeat", "afropop", "afro"], "afrobeat"),
    # latin — covers French/Spanish catalog entries
    (["latin", "reggaeton", "urbano", "urban latin", "flamenco",
      "balada", "espa", "cancion", "canci"], "latin"),
    # chill
    (["chill", "lo-fi", "lofi", "folk", "indie", "dream pop",
      "ambient", "psychedelic", "synth", "post punk"], "chill"),
]

def _normalize_genre(raw: str) -> str:
    """Map a raw genre string to the model's 5-entry genre vocabulary."""
    s = raw.lower()
    for keywords, target in _GENRE_KEYWORDS:
        if any(kw in s for kw in keywords):
            return target
    return "pop"   # default


# Maps InterestCategory values not in the YouTube model vocab to the nearest
# vocab entry: comedy | cooking | fashion | fitness | gaming | lifestyle | sports | vlogs
_INTEREST_MAP: dict[str, str] = {
    "music":        "lifestyle",
    "travel":       "vlogs",
    "technology":   "gaming",
    "arts":         "lifestyle",
    "education":    "lifestyle",
    "news":         "lifestyle",
    "animation":    "comedy",
    "beauty":       "fashion",
}

_YOUTUBE_VOCAB = {
    "comedy", "cooking", "fashion", "fitness",
    "gaming", "lifestyle", "sports", "vlogs",
}

def _normalize_interest(raw: str) -> str:
    """Map an InterestCategory value to the YouTube model's 8-entry vocab."""
    if raw in _YOUTUBE_VOCAB:
        return raw
    return _INTEREST_MAP.get(raw, "lifestyle")


# Training vocab for Spotify taste — used to identify taste keys in pref weights
_SPOTIFY_TASTE_VOCAB = {"afrobeat", "chill", "hiphop", "latin", "pop"}


def _sigmoid(z: float) -> float:
    z = max(-500.0, min(500.0, z))
    return 1.0 / (1.0 + math.exp(-z))


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _iso_duration_to_minutes(duration: str) -> float:
    try:
        match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration or "")
        if not match:
            return 10.0
        hours   = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = int(match.group(3) or 0)
        return max(0.0, hours * 60 + minutes + seconds / 60)
    except Exception:
        return 10.0


class _SpotifyScorer:
    def __init__(self, artifact: dict) -> None:
        self._weights       = artifact["weights"]
        self._bias          = artifact["bias"]
        self._scaler_means  = artifact["scaler_means"]
        self._scaler_stds   = artifact["scaler_stds"]
        self._tastes        = artifact["tastes"]
        self._genres        = artifact["genres"]
        self._n_numeric     = artifact.get("n_numeric", 7)

    def _onehot(self, value: str, vocab: list[str]) -> list[float]:
        return [1.0 if value == v else 0.0 for v in vocab]

    def _scale(self, row: list[float]) -> list[float]:
        out = list(row)
        for j in range(self._n_numeric):
            std = self._scaler_stds[j] if self._scaler_stds[j] > 1e-8 else 1.0
            out[j] = (out[j] - self._scaler_means[j]) / std
        return out

    def predict(
        self,
        artist: dict,
        user_taste: str,
        user_cefr: str,
        target_language: str,
    ) -> float:
        try:
            energy       = float(artist.get("energy_level", 0.5))
            danceability = float(artist.get("danceability", 0.6))
            valence      = float(artist.get("valence", 0.4))
            tempo        = float(artist.get("tempo", _SPOTIFY_DEFAULTS["tempo"]))
            speechiness  = float(artist.get("speechiness", _SPOTIFY_DEFAULTS["speechiness"]))
            popularity   = float(artist.get("popularity", _SPOTIFY_DEFAULTS["popularity"]))
            cefr_norm    = _CEFR_ORDER.get(user_cefr, 2) / 5.0
            lang_match   = 1.0

            # Normalise to model vocab using keyword matching
            taste = _normalize_genre(user_taste)
            if taste not in self._tastes:
                taste = self._tastes[0] if self._tastes else "pop"
            raw_genre = (artist.get("genres") or ["pop"])[0].lower()
            genre = _normalize_genre(raw_genre)
            if genre not in self._genres:
                genre = self._genres[0] if self._genres else "pop"

            raw = (
                [energy, danceability, valence, tempo / 200.0,
                 speechiness, popularity / 100.0, cefr_norm]
                + [lang_match]
                + self._onehot(taste, self._tastes)
                + self._onehot(genre, self._genres)
            )

            scaled = self._scale(raw)
            prob = _sigmoid(_dot(self._weights, scaled) + self._bias)
            return max(0.0, min(1.0, prob))

        except Exception:
            return 0.5


class _YouTubeScorer:
    def __init__(self, artifact: dict) -> None:
        self._interests  = artifact["interests"]
        self._categories = artifact["categories"]

        if artifact.get("model_type") == "gradient_boosting":
            self._mode      = "gbc"
            self._gbc       = artifact["sklearn_model"]
        else:
            self._mode          = "lr"
            self._weights       = artifact["weights"]
            self._bias          = artifact["bias"]
            self._scaler_means  = artifact["scaler_means"]
            self._scaler_stds   = artifact["scaler_stds"]
            self._n_numeric     = artifact.get("n_numeric", 5)

    def _onehot(self, value: str, vocab: list[str]) -> list[float]:
        return [1.0 if value == v else 0.0 for v in vocab]

    def _scale_lr(self, row: list[float]) -> list[float]:
        out = list(row)
        for j in range(self._n_numeric):
            std = self._scaler_stds[j] if self._scaler_stds[j] > 1e-8 else 1.0
            out[j] = (out[j] - self._scaler_means[j]) / std
        return out

    def _build_features(
        self,
        duration_min: float,
        has_subtitles: bool,
        engagement_score: float,
        speech_speed: float,
        interest: str,
        category: str,
        cefr_idx: float,
        lang_match: float,
    ) -> list[float]:
        cefr_norm     = cefr_idx / 5.0
        ideal_ceil    = 96.0 + cefr_idx * 16.0
        speed_penalty = max(0.0, speech_speed - ideal_ceil) / 100.0
        subtitle      = 1.0 if has_subtitles else 0.0
        eng           = max(0.0, min(1.0, engagement_score))
        int_match     = 1.0 if interest == category else 0.0

        # 8 base features (must match train_models.py: build_youtube_row_gbc)
        f: list[float] = [
            math.log1p(max(0.0, duration_min)) / math.log1p(40),
            speech_speed / 200.0,
            speed_penalty,
            subtitle,
            eng,
            cefr_norm,
            lang_match,
            int_match,
        ]
        # 4 interaction features
        f.append(int_match * subtitle)
        f.append(int_match * eng)
        f.append(subtitle * eng)
        f.append(int_match * max(0.0, 1.0 - speed_penalty))
        # 15 + 15 one-hot (both LR and GBC artifacts include these)
        f.extend(self._onehot(interest, self._interests))
        f.extend(self._onehot(category, self._categories))
        return f

    def predict(
        self,
        duration_str: str,
        has_subtitles: bool,
        engagement_score: float,
        speech_speed: float,
        user_interest: str,
        video_category: str,
        user_cefr: str,
        target_language: str,
    ) -> float:
        try:
            duration_min  = _iso_duration_to_minutes(duration_str)
            cefr_idx      = float(_CEFR_ORDER.get(user_cefr, 2))
            lang_match    = 1.0
            speed         = float(speech_speed)

            # Map interest/category to model vocab
            if self._mode == "gbc":
                # GBC model covers all 15 categories natively
                interest = user_interest if user_interest in self._interests else (self._interests[0] if self._interests else "lifestyle")
                category = video_category if video_category in self._categories else interest
            else:
                # Legacy LR model used 8-category vocab
                interest = _normalize_interest(user_interest)
                if interest not in self._interests:
                    interest = self._interests[0] if self._interests else "lifestyle"
                category = _normalize_interest(video_category)
                if category not in self._categories:
                    category = interest

            raw = self._build_features(
                duration_min, has_subtitles, engagement_score,
                speed, interest, category, cefr_idx, lang_match,
            )

            if self._mode == "gbc":
                if not _NUMPY_OK:
                    return 0.5
                prob = float(self._gbc.predict_proba(
                    [[v for v in raw]]
                )[0][1])
            else:
                scaled = self._scale_lr(raw)
                prob = _sigmoid(_dot(self._weights, scaled) + self._bias)

            return max(0.0, min(1.0, prob))

        except Exception:
            return 0.5


class MLScoringService:

    def __init__(self) -> None:
        self._spotify: _SpotifyScorer | None = None
        self._youtube: _YouTubeScorer | None = None
        self._load()

    def _load(self) -> None:
        sp_path = _MODEL_DIR / "spotify_model.pkl"
        yt_path = _MODEL_DIR / "youtube_model.pkl"

        if sp_path.exists():
            try:
                with open(sp_path, "rb") as f:
                    self._spotify = _SpotifyScorer(pickle.load(f))
                print("[ML] Spotify model loaded")
            except Exception as e:
                print(f"[ML] WARN failed to load spotify model: {e}")
        else:
            print("[ML] WARN spotify_model.pkl not found -- run scripts/train_models.py")

        if yt_path.exists():
            try:
                with open(yt_path, "rb") as f:
                    self._youtube = _YouTubeScorer(pickle.load(f))
                print("[ML] YouTube model loaded")
            except Exception as e:
                print(f"[ML] WARN failed to load youtube model: {e}")
        else:
            print("[ML] WARN youtube_model.pkl not found -- run scripts/train_models.py")

    def score_spotify_artist(
        self,
        artist: dict,
        user_taste: str,
        user_cefr: str,
        target_language: str = "fr",
    ) -> float:
        if self._spotify is None:
            return 0.5
        return self._spotify.predict(artist, user_taste, user_cefr, target_language)

    def score_youtube_video(
        self,
        duration_str: str,
        has_subtitles: bool,
        engagement_score: float,
        speech_speed: float,
        user_interest: str,
        video_category: str,
        user_cefr: str,
        target_language: str = "fr",
    ) -> float:
        if self._youtube is None:
            return 0.5
        return self._youtube.predict(
            duration_str, has_subtitles, engagement_score,
            speech_speed, user_interest, video_category,
            user_cefr, target_language,
        )

    @property
    def models_loaded(self) -> bool:
        return self._spotify is not None and self._youtube is not None


# Singleton — loaded once on first import
ml_scoring_service = MLScoringService()
