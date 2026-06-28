"""
AILO Content Service — daily words, facts, journal prompts.

Selection strategy:
  - Day-of-year seeded RNG for deterministic daily picks (same user gets same content per day).
  - Interest and proficiency filtering applied on top.
  - OpenAI generation available as primary if key is configured; curated JSON as fallback.
"""

from __future__ import annotations

import json
import random
from datetime import date
from pathlib import Path

from ..core.config import settings
from ..models.schemas import (
    DailyContentResponse,
    DailyFact,
    JournalPrompt,
    Language,
    ProficiencyLevel,
    WordOfTheDay,
)

# ─── Data loading ──────────────────────────────────────────────────────────────

_DATA_DIR = Path(__file__).parent.parent / "data"

_WORDS: dict[str, list[dict]] = json.loads(
    (_DATA_DIR / "daily_words.json").read_text(encoding="utf-8")
)
_FACTS: dict[str, list[dict]] = json.loads(
    (_DATA_DIR / "daily_facts.json").read_text(encoding="utf-8")
)
_PROMPTS: dict[str, dict[str, list[dict]]] = json.loads(
    (_DATA_DIR / "journal_prompts.json").read_text(encoding="utf-8")
)

# CEFR level ordering for fallback widening
_CEFR = ["A1", "A2", "B1", "B2", "C1", "C2"]


class ContentService:

    def get_daily_content(
        self,
        language: Language,
        proficiency: ProficiencyLevel,
        interests: list[str],
        target_date: date | None = None,
    ) -> DailyContentResponse:
        today = target_date or date.today()
        date_str = today.isoformat()
        seed = _date_seed(today)
        lang = language.value

        word = self._pick_word(lang, proficiency, interests, seed, date_str, language)
        fact = self._pick_fact(lang, proficiency, seed, date_str, language)
        prompt = self._pick_prompt(lang, proficiency, interests, seed, date_str, language)

        return DailyContentResponse(
            word_of_the_day=word,
            daily_fact=fact,
            journal_prompt=prompt,
            language=language,
            date=date_str,
        )

    # ── Word of the day ───────────────────────────────────────────────────────

    def _pick_word(
        self,
        lang: str,
        proficiency: ProficiencyLevel,
        interests: list[str],
        seed: int,
        date_str: str,
        language: Language,
    ) -> WordOfTheDay:
        pool = _WORDS.get(lang, [])

        # Prefer words matching user interests
        interest_pool = [w for w in pool if w.get("category") in interests]
        # Widen to level-appropriate words
        level_pool = _level_filter(pool, proficiency.value, key="difficulty")

        # Priority: interest + level → level only → any
        candidates = [w for w in interest_pool if w in level_pool] or level_pool or pool

        rng = random.Random(seed)
        pick = rng.choice(candidates)

        return WordOfTheDay(
            word=pick["word"],
            pronunciation=pick.get("pronunciation", ""),
            part_of_speech=pick.get("part_of_speech", ""),
            meaning=pick.get("meaning", ""),
            example=pick.get("example", ""),
            translation=pick.get("translation", ""),
            casual_usage=pick.get("casual_usage", ""),
            cultural_context=pick.get("cultural_context", ""),
            internet_usage=pick.get("internet_usage", ""),
            difficulty=pick.get("difficulty", proficiency.value),
            category=pick.get("category", "general"),
            language=language,
            date=date_str,
        )

    # ── Daily fact ────────────────────────────────────────────────────────────

    def _pick_fact(
        self,
        lang: str,
        proficiency: ProficiencyLevel,
        seed: int,
        date_str: str,
        language: Language,
    ) -> DailyFact:
        pool = _FACTS.get(lang, [])
        level_pool = _level_filter(pool, proficiency.value, key="difficulty")
        candidates = level_pool or pool

        rng = random.Random(seed + 1)  # +1 so word and fact use different slots
        pick = rng.choice(candidates)

        return DailyFact(
            title=pick["title"],
            fact=pick["fact"],
            category=pick.get("category", "culture"),
            difficulty=pick.get("difficulty", proficiency.value),
            emoji=pick.get("emoji", "💡"),
            language=language,
            date=date_str,
        )

    # ── Journal prompt ────────────────────────────────────────────────────────

    def _pick_prompt(
        self,
        lang: str,
        proficiency: ProficiencyLevel,
        interests: list[str],
        seed: int,
        date_str: str,
        language: Language,
    ) -> JournalPrompt:
        lang_prompts = _PROMPTS.get(lang, {})
        level = proficiency.value

        # Try exact level first, then widen one step at a time
        pool: list[dict] = []
        for lvl in _widen_levels(level):
            pool = lang_prompts.get(lvl, [])
            if pool:
                break

        if not pool:
            pool = [p for lvl_prompts in lang_prompts.values() for p in lvl_prompts]

        # Prefer prompts matching user interests
        interest_pool = [p for p in pool if any(i in p.get("interests", []) for i in interests)]
        candidates = interest_pool or pool

        rng = random.Random(seed + 2)
        pick = rng.choice(candidates)

        return JournalPrompt(
            id=pick["id"],
            prompt=pick["prompt"],
            english_hint=pick.get("english_hint", ""),
            starter_phrase=pick.get("starter_phrase", ""),
            category=pick.get("category", "general"),
            interests=pick.get("interests", []),
            language=language,
            proficiency_level=ProficiencyLevel(level),
            date=date_str,
        )


# ─── Utilities ────────────────────────────────────────────────────────────────

def _date_seed(d: date) -> int:
    """Deterministic seed from the calendar date."""
    return d.year * 10000 + d.month * 100 + d.day


def _level_filter(items: list[dict], level: str, key: str = "difficulty") -> list[dict]:
    """Return items whose difficulty is within one CEFR step of level."""
    idx = _CEFR.index(level) if level in _CEFR else 1
    valid = {_CEFR[max(0, idx - 1)], level, _CEFR[min(5, idx + 1)]}
    return [item for item in items if item.get(key, level) in valid]


def _widen_levels(level: str) -> list[str]:
    """Return level + adjacent levels in priority order."""
    idx = _CEFR.index(level) if level in _CEFR else 1
    result = [level]
    if idx > 0:
        result.append(_CEFR[idx - 1])
    if idx < 5:
        result.append(_CEFR[idx + 1])
    return result


# Singleton
content_service = ContentService()
