"""
YouTube Data API v3 service.

Key design decisions:
- search_videos returns [] on any API failure (safe for batch usage)
- All failures are printed verbosely so the server log shows exactly what went wrong
- videoDuration=medium (4-20 min) is the default for A2 learners — short enough to
  complete without fatigue, long enough for meaningful immersion
- regionCode + relevanceLanguage together strongly bias results toward native content
"""

import asyncio
from typing import Any

import httpx

from ..core.config import settings
from ..models.schemas import YouTubeVideoItem, Language, ProficiencyLevel


YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"

# ─── Language-lesson filter ───────────────────────────────────────────────────
# Strips "learn French/Spanish" educational content — the user wants native
# content in the target language, not language-teaching videos aimed at English
# speakers.

_LESSON_PATTERNS: dict[str, list[str]] = {
    "fr": [
        "learn french", "french lesson", "french class", "french course",
        "french for beginners", "french grammar", "french vocabulary",
        "french pronunciation", "french tutorial", "how to speak french",
        "apprendre le français", "apprendre la langue", "cours de français",
        "leçon de français", "français pour débutants", "français débutant",
        "grammaire française", "vocabulaire français", "french with",
        "speak french", "study french",
    ],
    "es": [
        "learn spanish", "spanish lesson", "spanish class", "spanish course",
        "spanish for beginners", "spanish grammar", "spanish vocabulary",
        "spanish pronunciation", "spanish tutorial", "how to speak spanish",
        "aprender español", "aprender idiomas", "clase de español",
        "lección de español", "español para principiantes",
        "gramática española", "vocabulario español", "spanish with",
        "speak spanish", "study spanish",
    ],
}


def _is_language_lesson(title: str, lang_code: str) -> bool:
    title_lower = title.lower()
    return any(p in title_lower for p in _LESSON_PATTERNS.get(lang_code, []))


REGION_CODES: dict[Language, str] = {
    Language.fr: "FR",
    Language.es: "ES",
}

RELEVANCE_LANGUAGE: dict[Language, str] = {
    Language.fr: "fr",
    Language.es: "es",
}

_LEVEL_DURATION: dict[ProficiencyLevel, str] = {
    ProficiencyLevel.A1: "short",    # < 4 min
    ProficiencyLevel.A2: "medium",   # 4–20 min
    ProficiencyLevel.B1: "medium",
    ProficiencyLevel.B2: "any",
    ProficiencyLevel.C1: "any",
    ProficiencyLevel.C2: "any",
}


class YouTubeQuotaExceeded(Exception):
    """Raised when the YouTube Data API returns 403 or 429 (quota exhausted)."""


class YouTubeService:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=35.0)

    async def search_videos(
        self,
        query: str,
        language: Language,
        max_results: int = 10,
        proficiency: ProficiencyLevel = ProficiencyLevel.A2,
    ) -> list[YouTubeVideoItem]:

        if not settings.youtube_api_key:
            print("[YouTube] ERROR: No API key -- set YOUTUBE_API_KEY in backend/.env")
            return []

        duration_filter = _LEVEL_DURATION.get(proficiency, "medium")

        params: dict[str, Any] = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": max_results,
            "regionCode": REGION_CODES[language],
            "relevanceLanguage": RELEVANCE_LANGUAGE[language],
            "videoEmbeddable": "true",
            "safeSearch": "moderate",
            "key": settings.youtube_api_key,
        }

        # Only add duration filter when it's meaningful
        if duration_filter != "any":
            params["videoDuration"] = duration_filter

        try:
            response = await self._client.get(
                f"{YOUTUBE_API_BASE}/search",
                params=params,
            )

            if response.status_code in (403, 429):
                print(f"[YouTube] QUOTA exceeded (HTTP {response.status_code}) on query={query!r}")
                raise YouTubeQuotaExceeded(
                    f"YouTube API quota exceeded (HTTP {response.status_code}). "
                    "Daily limit reached — resets at midnight Pacific Time."
                )

            if response.status_code != 200:
                print(f"[YouTube] FAIL search status={response.status_code}  query={query!r}  body={response.text[:200]!r}")
                return []

            data = response.json()
            items: list[dict[str, Any]] = data.get("items", [])

            if not items:
                print(f"[YouTube] 0 results for query={query!r}")
                return []

            video_ids = [
                item["id"]["videoId"]
                for item in items
                if item.get("id", {}).get("videoId")
            ]

            details = await self._get_video_details(video_ids)
            result = self._merge(items, details, language)
            print(f"[YouTube] OK {len(result)} videos  query={query!r}")
            return result

        except YouTubeQuotaExceeded:
            raise
        except httpx.TimeoutException:
            print(f"[YouTube] TIMEOUT on query={query!r}")
            return []
        except Exception as exc:
            print(f"[YouTube] ERROR on query={query!r}: {exc}")
            return []

    async def _get_video_details(
        self,
        video_ids: list[str],
    ) -> dict[str, Any]:

        if not video_ids:
            return {}

        params: dict[str, Any] = {
            "part": "contentDetails,statistics,snippet",
            "id": ",".join(video_ids),
            "key": settings.youtube_api_key,
        }

        try:
            response = await self._client.get(
                f"{YOUTUBE_API_BASE}/videos",
                params=params,
            )

            if response.status_code != 200:
                print(f"[YouTube] FAIL video details status={response.status_code}")
                return {}

            data = response.json()
            return {item["id"]: item for item in data.get("items", [])}

        except Exception as exc:
            print(f"[YouTube] ERROR detail fetch: {exc}")
            return {}

    def _merge(
        self,
        search_items: list[dict[str, Any]],
        details: dict[str, Any],
        language: Language,
    ) -> list[YouTubeVideoItem]:

        results: list[YouTubeVideoItem] = []

        lang_code = language.value

        for item in search_items:
            vid_id: str = item.get("id", {}).get("videoId", "")
            if not vid_id:
                continue

            snippet: dict[str, Any] = item.get("snippet", {})

            if _is_language_lesson(snippet.get("title", ""), lang_code):
                continue
            detail = details.get(vid_id, {})

            thumbnail = (
                snippet.get("thumbnails", {}).get("high", {}).get("url")
                or snippet.get("thumbnails", {}).get("medium", {}).get("url")
                or ""
            )

            duration = detail.get("contentDetails", {}).get("duration", "PT0S")
            view_count = str(detail.get("statistics", {}).get("viewCount", "0"))
            has_captions = (
                detail.get("contentDetails", {}).get("caption", "false") == "true"
            )

            results.append(
                YouTubeVideoItem(
                    video_id=vid_id,
                    title=snippet.get("title", ""),
                    channel_name=snippet.get("channelTitle", ""),
                    channel_id=snippet.get("channelId", ""),
                    thumbnail_url=thumbnail,
                    published_at=snippet.get("publishedAt", ""),
                    duration=duration,
                    view_count=view_count,
                    has_captions=has_captions,
                    description=snippet.get("description", "")[:500],
                )
            )

        return results

    async def batch_search_with_queries(
        self,
        query_pairs: list[tuple[str, str]],
        language: Language,
        proficiency: ProficiencyLevel = ProficiencyLevel.A2,
        max_per_query: int = 5,
    ) -> list[tuple[YouTubeVideoItem, str]]:
        """Like batch_search but preserves the topic tag for each video."""
        tasks = [
            (self.search_videos(q, language, max_per_query, proficiency), topic)
            for q, topic in query_pairs
        ]

        merged: list[tuple[YouTubeVideoItem, str]] = []
        seen_ids: set[str] = set()

        import asyncio
        results = await asyncio.gather(
            *[t for t, _ in tasks], return_exceptions=True
        )

        quota_error: YouTubeQuotaExceeded | None = None
        for (batch, topic) in zip(results, [t for _, t in tasks]):
            if isinstance(batch, YouTubeQuotaExceeded):
                quota_error = batch
                continue
            if isinstance(batch, Exception):
                print(f"[YouTube] ERROR batch task: {batch}")
                continue
            for video in batch:
                if video.video_id not in seen_ids:
                    seen_ids.add(video.video_id)
                    merged.append((video, topic))

        # Surface quota error whenever it was hit and no usable videos came back.
        # YouTube sometimes returns 200+empty instead of 429 when quota is exhausted,
        # so we raise even if only some queries returned quota errors (others may have
        # returned [] silently rather than 429).
        if quota_error and not merged:
            raise quota_error

        print(f"[YouTube] batch_search_with_queries: {len(merged)} unique videos")
        return merged

    async def batch_search(
        self,
        queries: list[str],
        language: Language,
        proficiency: ProficiencyLevel = ProficiencyLevel.A2,
        max_per_query: int = 5,
    ) -> list[YouTubeVideoItem]:

        tasks = [
            self.search_videos(q, language, max_per_query, proficiency)
            for q in queries
        ]

        batches = await asyncio.gather(*tasks, return_exceptions=True)

        merged: list[YouTubeVideoItem] = []
        seen_ids: set[str] = set()

        for batch in batches:
            if isinstance(batch, Exception):
                print(f"[YouTube] ERROR batch task: {batch}")
                continue
            for video in batch:
                if video.video_id not in seen_ids:
                    seen_ids.add(video.video_id)
                    merged.append(video)

        print(f"[YouTube] batch_search total unique videos: {len(merged)}")
        return merged

    async def close(self) -> None:
        await self._client.aclose()
