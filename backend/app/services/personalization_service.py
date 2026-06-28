"""
AILO Personalization Service — Thompson Sampling preference engine.

Each user has a dict of feature keys (genre/mood/artist) mapped to Beta
distribution parameters (alpha, beta).

Exploration (Thompson Sampling):
  When generating recommendations, we draw from Beta(alpha, beta) instead of
  using the mean. Features with few interactions have high variance, so they
  get natural explore/exploit balance without tuning.

Temporal decay:
  On load we decay (alpha, beta) toward the prior (1, 1) using a 30-day
  half-life. Recent behaviour dominates; stale preferences fade gently.

Persistence:
  Weights are stored in the user_preferences SQLite table so they survive
  server restarts.

Cross-modal transfer:
  YouTube topic engagement can be piped in via transfer_youtube_signals() to
  shift Spotify mood/energy preferences softly.
"""

from __future__ import annotations

import math
import random
import time
from collections import defaultdict

from ..core.database import db_get_preferences, db_save_preferences
from ..models.schemas import (
    InteractionType,
    PreferenceWeightUpdate,
    TrackInteraction,
)

# ─── Beta update increments ───────────────────────────────────────────────────

_ALPHA_DELTA: dict[str, float] = {
    InteractionType.like.value:           1.2,
    InteractionType.save.value:           1.5,
    InteractionType.replay.value:         1.0,
    InteractionType.more_like_this.value: 1.8,
    InteractionType.complete.value:       0.5,
}

_BETA_DELTA: dict[str, float] = {
    InteractionType.skip.value:    1.2,
    InteractionType.dislike.value: 2.0,
}

_DECAY_HALFLIFE_DAYS = 30
_MAX_HISTORY = 200
_PRIOR_ALPHA = 1.0
_PRIOR_BETA = 1.0


class PersonalizationService:

    def __init__(self) -> None:
        # user_id → {feature_key: (alpha, beta)}
        self._params: dict[str, dict[str, tuple[float, float]]] = defaultdict(dict)
        # user_id → [interaction dicts]
        self._history: dict[str, list[dict]] = defaultdict(list)
        self._loaded: set[str] = set()

    # ── DB helpers ────────────────────────────────────────────────────────────

    def _ensure_loaded(self, user_id: str) -> None:
        if user_id in self._loaded:
            return
        self._loaded.add(user_id)

        data = db_get_preferences(user_id)
        if not data:
            return

        elapsed_days = (time.time() - data["updated_at"]) / 86400
        decay = math.exp(-elapsed_days * math.log(2) / _DECAY_HALFLIFE_DAYS)

        decayed: dict[str, tuple[float, float]] = {}
        for key, val in data.get("beta_params", {}).items():
            if isinstance(val, (list, tuple)) and len(val) == 2:
                a, b = float(val[0]), float(val[1])
                decayed[key] = (
                    _PRIOR_ALPHA + (a - _PRIOR_ALPHA) * decay,
                    _PRIOR_BETA  + (b - _PRIOR_BETA)  * decay,
                )

        self._params[user_id] = decayed
        self._history[user_id] = data.get("history", [])[-_MAX_HISTORY:]

    def _save(self, user_id: str) -> None:
        raw = {k: list(v) for k, v in self._params[user_id].items()}
        weights = self._mean_weights(user_id)
        history = self._history[user_id][-_MAX_HISTORY:]
        db_save_preferences(user_id, weights, raw, history)

    # ── Weight computation ────────────────────────────────────────────────────

    def _mean_weights(self, user_id: str) -> dict[str, float]:
        result: dict[str, float] = {}
        for key, (a, b) in self._params[user_id].items():
            result[key] = (a / (a + b) - 0.5) * 2.0  # [0,1] → [-1,1]
        return result

    def _sampled_weights(self, user_id: str) -> dict[str, float]:
        result: dict[str, float] = {}
        for key, (a, b) in self._params[user_id].items():
            sample = random.betavariate(max(a, 0.1), max(b, 0.1))
            result[key] = (sample - 0.5) * 2.0
        return result

    def _update_param(self, params: dict, key: str, iv: str) -> None:
        a, b = params.get(key, (_PRIOR_ALPHA, _PRIOR_BETA))
        if iv in _ALPHA_DELTA:
            a += _ALPHA_DELTA[iv]
        elif iv in _BETA_DELTA:
            b += _BETA_DELTA[iv]
        params[key] = (max(0.01, a), max(0.01, b))

    # ── Public API ────────────────────────────────────────────────────────────

    def record_interaction(self, interaction: TrackInteraction) -> PreferenceWeightUpdate:
        uid = interaction.user_id
        self._ensure_loaded(uid)
        params = self._params[uid]
        iv = interaction.interaction.value
        updated: list[str] = []

        def touch(key: str) -> None:
            self._update_param(params, key, iv)
            updated.append(key)

        touch(f"artist:{interaction.artist_id}")
        for g in interaction.genres:
            touch(f"genre:{g}")
        for m in interaction.moods:
            touch(f"mood:{m}")

        if interaction.energy_level is not None and iv in _ALPHA_DELTA:
            key = "energy_preference"
            a, b = params.get(key, (_PRIOR_ALPHA, _PRIOR_BETA))
            inc = _ALPHA_DELTA[iv]
            e = interaction.energy_level
            a += inc * e
            b += inc * (1.0 - e)
            params[key] = (max(0.01, a), max(0.01, b))
            updated.append(key)

        self._history[uid].append({
            "user_id":    interaction.user_id,
            "track_id":   interaction.track_id,
            "artist_id":  interaction.artist_id,
            "interaction": iv,
            "timestamp":  interaction.timestamp,
        })
        if len(self._history[uid]) > _MAX_HISTORY:
            self._history[uid] = self._history[uid][-_MAX_HISTORY:]

        self._save(uid)

        weights = self._mean_weights(uid)
        return PreferenceWeightUpdate(
            updated_keys=updated,
            new_weights={k: weights.get(k, 0.0) for k in updated},
        )

    def get_weights(self, user_id: str, explore: bool = False) -> dict[str, float]:
        self._ensure_loaded(user_id)
        return self._sampled_weights(user_id) if explore else self._mean_weights(user_id)

    def get_flat_weights(self, user_id: str, explore: bool = False) -> dict[str, float]:
        """Weights with namespace prefix stripped — pass directly to scorers."""
        return {
            k.split(":", 1)[-1]: v
            for k, v in self.get_weights(user_id, explore=explore).items()
        }

    def get_history(self, user_id: str, limit: int = 20) -> list[dict]:
        self._ensure_loaded(user_id)
        return list(reversed(self._history[user_id]))[:limit]

    def get_top_preferences(self, user_id: str, top_n: int = 5) -> dict[str, list[str]]:
        weights = self.get_weights(user_id)
        liked = sorted(
            [(k, v) for k, v in weights.items() if v > 0.1],
            key=lambda x: x[1], reverse=True,
        )[:top_n]
        disliked = sorted(
            [(k, v) for k, v in weights.items() if v < -0.1],
            key=lambda x: x[1],
        )[:top_n]
        return {
            "liked":    [k.split(":", 1)[-1] for k, _ in liked],
            "disliked": [k.split(":", 1)[-1] for k, _ in disliked],
        }

    def get_interaction_stats(self, user_id: str) -> dict:
        self._ensure_loaded(user_id)
        history = self._history.get(user_id, [])
        counts: dict[str, int] = {}
        for item in history:
            t = item.get("interaction", "unknown")
            counts[t] = counts.get(t, 0) + 1
        return {
            "total_interactions": len(history),
            "by_type": counts,
            "first_interaction_at": history[0]["timestamp"] if history else None,
            "last_interaction_at":  history[-1]["timestamp"] if history else None,
        }


# Singleton
personalization_service = PersonalizationService()
