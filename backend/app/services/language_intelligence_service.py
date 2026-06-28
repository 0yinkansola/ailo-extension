"""
AILO Language Intelligence Service — AI-powered YouTube content analysis.

Uses GPT-4o-mini to evaluate each video for language acquisition value using
Krashen's Comprehensible Input hypothesis (i+1):

  Optimal input is one step above the learner's current level.
  Too easy → no acquisition. Too hard → incomprehensible.

Each video is scored on four dimensions:
  comprehensibility — how well the content matches the learner's i+1 level
  speech_clarity    — how standard/followable the speech is (accent, pace)
  vocabulary_richness — quality of vocabulary exposure for this CEFR level
  cultural_density  — idioms, slang, references a foreigner wouldn't know

Final acquisition_score = weighted sum of these four dimensions.

Results are cached by (video_id, user_level) so the same video is never
analyzed twice per server session. Falls back to a neutral score if OpenAI
is unavailable or times out.
"""

from __future__ import annotations

import asyncio
import json
import re

from ..core.config import settings
from ..models.schemas import ProficiencyLevel

_CEFR_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2"]

_LANG_NAMES: dict[str, str] = {"fr": "French", "es": "Spanish"}

_PROMPT = """\
You are a language acquisition expert (CEFR framework). Analyze this {lang} YouTube video for a learner at CEFR {level}.

Title: {title}
Description: {desc}

Return ONLY valid JSON, no markdown or explanation:
{{"estimated_cefr":"A1|A2|B1|B2|C1|C2","speech_clarity":0.0,"vocabulary_richness":0.0,"cultural_density":0.0,"key_vocabulary":["word1","word2"],"acquisition_value":0.0}}

Definitions:
speech_clarity — how standard and followable the {lang} speech is (1.0 = clear standard accent, moderate pace; 0.0 = heavy dialect, very fast slang-heavy speech)
vocabulary_richness — how well the vocabulary serves a {level} learner (1.0 = ideal blend: enough familiar words to anchor meaning, 1-3 new words per sentence; 0.0 = all too basic or all incomprehensible)
cultural_density — richness of cultural content a foreigner wouldn't know: idioms, customs, slang, local references (1.0 = deeply cultural; 0.0 = generic/neutral)
key_vocabulary — 3-5 specific {lang} words or phrases this learner would encounter and benefit from
acquisition_value — overall: how much {lang} a {level} learner would actually acquire from this content (0-1)\
"""


def _comprehensibility(content_cefr: str, user_cefr: str) -> float:
    """i+1 model: content one step above user level scores 1.0."""
    try:
        ci = _CEFR_ORDER.index(content_cefr)
        ui = _CEFR_ORDER.index(user_cefr)
    except ValueError:
        return 0.5
    diff = ci - ui
    if diff == 1:  return 1.00  # perfect i+1
    if diff == 0:  return 0.85  # at level — good for fluency consolidation
    if diff == 2:  return 0.55  # challenging but possible
    if diff == -1: return 0.45  # slightly below — comprehensible, limited growth
    if diff < -1:  return 0.15  # too easy
    return 0.05                 # too far above — overwhelming


class ContentAnalysis:
    __slots__ = (
        "estimated_cefr", "speech_clarity", "vocabulary_richness",
        "cultural_density", "key_vocabulary", "acquisition_value",
        "comprehensibility", "acquisition_score",
    )

    def __init__(
        self,
        estimated_cefr: str,
        speech_clarity: float,
        vocabulary_richness: float,
        cultural_density: float,
        key_vocabulary: list[str],
        acquisition_value: float,
        comprehensibility: float,
    ) -> None:
        self.estimated_cefr = estimated_cefr
        self.speech_clarity = speech_clarity
        self.vocabulary_richness = vocabulary_richness
        self.cultural_density = cultural_density
        self.key_vocabulary = key_vocabulary
        self.acquisition_value = acquisition_value
        self.comprehensibility = comprehensibility
        # Composite acquisition score used in ranking
        self.acquisition_score: float = (
            0.40 * comprehensibility
            + 0.25 * speech_clarity
            + 0.20 * vocabulary_richness
            + 0.15 * cultural_density
        )


def _fallback(user_cefr: str) -> ContentAnalysis:
    comp = _comprehensibility("B1", user_cefr)
    return ContentAnalysis("B1", 0.6, 0.5, 0.4, [], 0.5, comp)


class LanguageIntelligenceService:

    def __init__(self) -> None:
        # (video_id, user_level) → ContentAnalysis
        self._cache: dict[str, ContentAnalysis] = {}

    async def analyze_video(
        self,
        video_id: str,
        title: str,
        description: str,
        language: str,
        user_level: str,
    ) -> ContentAnalysis:
        key = f"{video_id}:{user_level}"
        if key in self._cache:
            return self._cache[key]

        result = await self._query(title, description, language, user_level)
        self._cache[key] = result
        return result

    async def analyze_batch(
        self,
        videos: list[tuple[str, str, str]],  # (video_id, title, description)
        language: str,
        user_level: str,
    ) -> list[ContentAnalysis]:
        return list(await asyncio.gather(*(
            self.analyze_video(vid, title, desc, language, user_level)
            for vid, title, desc in videos
        )))

    async def _query(
        self,
        title: str,
        description: str,
        language: str,
        user_level: str,
    ) -> ContentAnalysis:
        if not settings.openai_api_key:
            return _fallback(user_level)

        lang_name = _LANG_NAMES.get(language, language)
        prompt = _PROMPT.format(
            lang=lang_name,
            level=user_level,
            title=title,
            desc=description[:350],
        )

        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=settings.openai_api_key)
            resp = await asyncio.wait_for(
                client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0,
                    max_tokens=250,
                ),
                timeout=8.0,
            )
            raw = resp.choices[0].message.content or ""
            return self._parse(raw, user_level)
        except Exception:
            return _fallback(user_level)

    def _parse(self, text: str, user_cefr: str) -> ContentAnalysis:
        try:
            text = re.sub(r"```[a-z]*\n?", "", text).strip()
            data = json.loads(text)
            cefr = data.get("estimated_cefr", "B1")
            if cefr not in _CEFR_ORDER:
                cefr = "B1"
            return ContentAnalysis(
                estimated_cefr=cefr,
                speech_clarity=float(data.get("speech_clarity", 0.6)),
                vocabulary_richness=float(data.get("vocabulary_richness", 0.5)),
                cultural_density=float(data.get("cultural_density", 0.4)),
                key_vocabulary=list(data.get("key_vocabulary", []))[:5],
                acquisition_value=float(data.get("acquisition_value", 0.5)),
                comprehensibility=_comprehensibility(cefr, user_cefr),
            )
        except Exception:
            return _fallback(user_cefr)


# Singleton
language_intelligence_service = LanguageIntelligenceService()
