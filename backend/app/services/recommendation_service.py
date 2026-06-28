"""
AILO Recommendation Pipeline — interest-first, CEFR-aware scoring.

Core philosophy:
  The user wants to watch what they already enjoy — just IN their target language.
  If they watch cooking, sports, and gaming in English, show them cooking, sports,
  and gaming content made by native French/Spanish creators.

  CEFR proficiency (A2) shapes HOW we score results (prefer captions, medium length,
  simpler vocabulary in titles) — it does NOT restrict WHAT we search for.
  Searching for "apprendre français pour débutants" returns language-lesson content.
  Searching for "recette simple française" returns native French cooking content.
  These are completely different experiences.

Topic weight model (from user feedback + YouTube DOM inference):
  - Positive weight: liked videos in this topic → more queries allocated
  - Negative weight: disliked topics → fewer/no queries
  - Neutral (0): equal allocation
  Range: -1.0 (skip) to +1.0 (maximum allocation)
"""

import json
import random
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from ..models.schemas import (
    InterestCategory,
    Language,
    ProficiencyLevel,
    RecommendationRequest,
    RecommendationResponse,
    VideoRecommendation,
    YouTubeVideoItem,
)
from ..services.youtube_service import YouTubeService, YouTubeQuotaExceeded
from ..services.classification_service import infer_level
from ..services.language_intelligence_service import (
    language_intelligence_service,
    ContentAnalysis,
)
from ..services.ml_scoring_service import ml_scoring_service


# ─── Topic translations ───────────────────────────────────────────────────────

_TRANSLATIONS_PATH = Path(__file__).parent.parent / "data" / "topic_translations.json"
_TOPIC_TRANSLATIONS: dict[str, dict[str, list[str]]] = json.loads(
    _TRANSLATIONS_PATH.read_text(encoding="utf-8")
)

# ─── CEFR level ordering (used for scoring only, not query building) ──────────


# ─── Scoring ──────────────────────────────────────────────────────────────────

def _score_video(
    item: YouTubeVideoItem,
    analysis: ContentAnalysis,
    topic: str | None,
    topic_weights: dict[str, float] | None,
    ml_prob: float = 0.5,
) -> float:
    """
    Hybrid scoring: logistic regression (ML) + AI acquisition analysis + engagement.

    50% — ML watch probability (trained on 1500-row dataset)
    30% — AI acquisition score (i+1 comprehensibility, speech clarity, vocab, culture)
    20% — Engagement signal (topic interest weight + recency)
    """
    # ── ML component ──────────────────────────────────────────────────────────
    ml_score = float(ml_prob)

    # ── Acquisition component (AI) ────────────────────────────────────────────
    acquisition = analysis.acquisition_score
    if item.has_captions:
        acquisition = min(1.0, acquisition + 0.12)

    # ── Engagement component ──────────────────────────────────────────────────
    engagement = 0.5
    if topic and topic_weights:
        w = topic_weights.get(topic, 0.0)
        engagement = 0.5 + w * 0.5

    try:
        published = datetime.fromisoformat(item.published_at.replace("Z", "+00:00"))
        age_days = (datetime.now(timezone.utc) - published).days
        if age_days < 90:     engagement += 0.15
        elif age_days < 365:  engagement += 0.05
        elif age_days > 1095: engagement -= 0.15
    except Exception:
        pass

    engagement = max(0.0, min(1.0, engagement))

    final = 0.50 * ml_score + 0.30 * acquisition + 0.20 * engagement
    final += random.uniform(0, 0.04)
    return final


# ─── Query builder ────────────────────────────────────────────────────────────

def _build_queries(
    interests: list[InterestCategory],
    language: Language,
    topic_weights: dict[str, float] | None = None,
    max_per_interest: int = 1,
) -> list[tuple[str, str]]:
    """
    Returns a list of (query_string, topic_name) pairs.

    KEY DESIGN: queries are native-language topic searches — NOT language-lesson searches.
    The user wants French cooking vlogs, not "learn French with cooking recipes".

    Topic weights from user feedback control query allocation:
    - weight > 0.5: allocate 3 queries (user loves this topic)
    - weight 0 to 0.5: allocate 2 queries (default)
    - weight -0.5 to 0: allocate 1 query (mild dislike)
    - weight < -0.7: skip entirely (strong dislike)
    """
    lang_code = language.value
    lang_map = _TOPIC_TRANSLATIONS.get(lang_code, {})

    # Sort interests by preference weight (highest first)
    sorted_interests = sorted(
        interests,
        key=lambda i: (topic_weights or {}).get(i.value, 0.0),
        reverse=True,
    )

    results: list[tuple[str, str]] = []

    for interest in sorted_interests:
        weight = (topic_weights or {}).get(interest.value, 0.0)

        # Skip strongly disliked topics
        if weight < -0.7:
            print(f"  [Rec] skipping disliked topic: {interest.value} (weight={weight:.2f})")
            continue

        # Allocate query slots based on preference strength
        if weight >= 0.6:
            slot_count = 2
        elif weight >= 0.0:
            slot_count = max_per_interest
        else:
            slot_count = 1

        topic_queries = list(lang_map.get(interest.value, []))
        random.shuffle(topic_queries)

        for q in topic_queries[:slot_count]:
            results.append((q, interest.value))

    # Guaranteed fallback — plain language content in case translations are missing
    if not results:
        if lang_code == "fr":
            fallback = [
                ("vlog france", "lifestyle"),
                ("musique française", "music"),
                ("cuisine française", "cooking"),
            ]
        else:
            fallback = [
                ("vlog españa", "lifestyle"),
                ("música española", "music"),
                ("cocina española", "cooking"),
            ]
        print("[Rec] WARN using fallback queries (interests empty or no translations)")
        results = fallback

    return results


# CEFR → typical native-speaker speech speed the learner can handle
_CEFR_SPEED: dict[str, float] = {
    "A1": 100.0, "A2": 120.0, "B1": 140.0,
    "B2": 155.0, "C1": 165.0, "C2": 175.0,
}


# ─── Service ──────────────────────────────────────────────────────────────────

class RecommendationService:
    def __init__(self, youtube: YouTubeService) -> None:
        self._youtube = youtube

    async def get_recommendations(
        self,
        request: RecommendationRequest,
    ) -> RecommendationResponse:

        print(f"\n{'='*64}")
        print(
            f"[Rec] lang={request.targetLanguage.value}"
            f"  level={request.proficiencyLevel.value}"
            f"  interests=[{', '.join(i.value for i in request.interests)}]"
            f"  count={request.count}"
        )
        if request.topicWeights:
            print(f"[Rec] topicWeights={request.topicWeights}")

        query_pairs = _build_queries(
            request.interests,
            request.targetLanguage,
            request.topicWeights,
        )

        print(f"[Rec] {len(query_pairs)} queries: {[q for q, _ in query_pairs]}")

        # ── Primary fetch ─────────────────────────────────────────────────────
        try:
            tasks_results = await self._youtube.batch_search_with_queries(
                query_pairs,
                request.targetLanguage,
                proficiency=request.proficiencyLevel,
                max_per_query=_max_results(),
            )
        except YouTubeQuotaExceeded as exc:
            raise HTTPException(status_code=503, detail=str(exc))

        raw_videos: list[tuple[YouTubeVideoItem, str]] = []  # (video, topic)
        for item, topic in tasks_results:
            raw_videos.append((item, topic))

        print(f"[Rec] raw videos: {len(raw_videos)}")

        # ── Fallback if primary returns nothing ───────────────────────────────
        if not raw_videos:
            print("[Rec] WARN primary search empty -- trying language-only fallback")
            fallback_q = [
                ("vlog france", "lifestyle"),
                ("musique francaise", "music"),
                ("actualite france", "news"),
            ] if request.targetLanguage.value == "fr" else [
                ("vlog espana", "lifestyle"),
                ("musica espanola", "music"),
                ("noticias espana", "news"),
            ]
            try:
                raw_videos = await self._youtube.batch_search_with_queries(
                    fallback_q,
                    request.targetLanguage,
                    proficiency=request.proficiencyLevel,
                    max_per_query=5,
                )
            except YouTubeQuotaExceeded as exc:
                raise HTTPException(status_code=503, detail=str(exc))
            print(f"[Rec] fallback got {len(raw_videos)} videos")

        if not raw_videos:
            print("[Rec] ERROR no videos after fallback -- quota likely exhausted")
            raise HTTPException(
                status_code=503,
                detail=(
                    "YouTube returned no results. The API quota is likely exhausted "
                    "— resets at midnight Pacific Time."
                ),
            )

        # ── AI acquisition analysis (parallel) ───────────────────────────────
        lang_code = request.targetLanguage.value
        user_level = request.proficiencyLevel.value

        video_tuples = [
            (item.video_id, item.title, item.description)
            for item, _ in raw_videos
        ]
        analyses = await language_intelligence_service.analyze_batch(
            video_tuples, lang_code, user_level
        )
        print(f"[Rec] AI analyses complete for {len(analyses)} videos")

        # ── Score and rank ────────────────────────────────────────────────────
        scored: list[tuple[float, VideoRecommendation]] = []

        # User's primary interest = the category they've engaged with most via feedback.
        # Falls back to first listed interest if no weights exist yet.
        primary_interest: str = (
            max(
                request.interests,
                key=lambda i: (request.topicWeights or {}).get(i.value, 0.0),
            ).value
            if request.interests else "lifestyle"
        )
        speech_speed = _CEFR_SPEED.get(user_level, 130.0)

        for (item, topic), analysis in zip(raw_videos, analyses):
            inferred = infer_level(item.title, request.proficiencyLevel)
            if analysis.estimated_cefr and analysis.estimated_cefr in [
                pl.value for pl in ProficiencyLevel
            ]:
                try:
                    inferred = ProficiencyLevel(analysis.estimated_cefr)
                except ValueError:
                    pass

            # user_interest = what the user actually likes
            # video_category = what this specific video is about (from its search query)
            # When they differ, interest_match=0 → lower ML score → demoted in ranking
            ml_prob = ml_scoring_service.score_youtube_video(
                duration_str=item.duration,
                has_subtitles=item.has_captions,
                engagement_score=analysis.acquisition_score,
                speech_speed=speech_speed,
                user_interest=primary_interest,
                video_category=topic or "lifestyle",
                user_cefr=user_level,
                target_language=lang_code,
            )
            score = _score_video(item, analysis, topic, request.topicWeights, ml_prob)

            try:
                video_topics = [InterestCategory(topic)]
            except ValueError:
                video_topics = []

            video = VideoRecommendation(
                id=item.video_id,
                title=item.title,
                channelName=item.channel_name,
                channelId=item.channel_id,
                thumbnailUrl=item.thumbnail_url,
                viewCount=item.view_count,
                publishedAt=item.published_at,
                duration=item.duration,
                language=request.targetLanguage,
                proficiencyLevel=inferred,
                topics=video_topics,
                hasSubtitles=item.has_captions,
                videoUrl=f"https://www.youtube.com/watch?v={item.video_id}",
            )
            scored.append((score, video))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = [v for _, v in scored[: request.count]]

        print(f"[Rec] OK returning {len(top)} videos")

        return RecommendationResponse(
            videos=top,
            generatedAt=int(time.time() * 1000),
            cacheHit=False,
        )


def _max_results() -> int:
    from ..core.config import settings
    return settings.max_results_per_topic
