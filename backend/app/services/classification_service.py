"""
Classify a video's proficiency level based on its title/description.

For MVP we use two strategies:
  1. Keyword heuristics — fast, no API call, works offline
  2. OpenAI GPT-4o-mini — more accurate, used when OPENAI_API_KEY is set

The result is a ProficiencyLevel (A1–C2).
"""

import re

from ..core.config import settings
from ..models.schemas import ProficiencyLevel, Language


# ─── Keyword heuristics ───────────────────────────────────────────────────────
# Words in video titles that strongly indicate a proficiency range.

_LEVEL_KEYWORDS: dict[ProficiencyLevel, list[str]] = {
    ProficiencyLevel.A1: [
        "débutant", "beginner", "para principiantes", "très facile", "muy fácil",
        "super easy", "first words", "premiers mots", "primeras palabras",
        "pour les nuls", "slow french", "slow spanish",
    ],
    ProficiencyLevel.A2: [
        "facile", "easy", "fácil", "slow", "lent", "lento",
        "simple", "basic", "básico", "A1 A2", "elementary",
    ],
    ProficiencyLevel.B1: [
        "intermédiaire", "intermediate", "intermedio",
        "conversational", "everyday", "quotidien", "cotidiano",
        "B1", "B2",
    ],
    ProficiencyLevel.B2: [
        "avancé", "advanced", "avanzado", "upper intermediate",
        "fluent", "fluide", "fluido", "natural speech",
    ],
    ProficiencyLevel.C1: [
        "natif", "native", "nativo", "authentique", "auténtico",
        "C1", "C2", "argot", "slang", "jerga",
    ],
    ProficiencyLevel.C2: [
        "C2", "mastery", "maîtrise", "maestría",
        "académique", "académico", "academic",
    ],
}

# Flatten to (pattern, level) pairs, ordered from specific → general
_COMPILED_RULES: list[tuple[re.Pattern[str], ProficiencyLevel]] = []
for _lvl in (
    ProficiencyLevel.A1,
    ProficiencyLevel.A2,
    ProficiencyLevel.B1,
    ProficiencyLevel.B2,
    ProficiencyLevel.C1,
    ProficiencyLevel.C2,
):
    for kw in _LEVEL_KEYWORDS[_lvl]:
        _COMPILED_RULES.append((re.compile(re.escape(kw), re.IGNORECASE), _lvl))


def classify_by_keywords(text: str) -> ProficiencyLevel | None:
    for pattern, level in _COMPILED_RULES:
        if pattern.search(text):
            return level
    return None


# ─── Proficiency level inference ──────────────────────────────────────────────

# When we can't determine the level from keywords, we assign a default
# based on the requested level — i.e., trust that the search query already
# targeted the right proficiency band.
def infer_level(
    title: str,
    requested_level: ProficiencyLevel,
) -> ProficiencyLevel:
    kw_level = classify_by_keywords(title)
    if kw_level is not None:
        return kw_level
    # Fall back to the user's requested level
    return requested_level


# ─── OpenAI batch classification (optional, future enhancement) ───────────────
# Left as a stub — enable when you want richer per-video level scoring.

async def classify_batch_openai(
    titles: list[str],
    language: Language,
) -> list[ProficiencyLevel]:
    """Classify a batch of video titles using GPT-4o-mini."""
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)

    titles_block = "\n".join(f"{i+1}. {t}" for i, t in enumerate(titles))
    system_prompt = (
        f"You are a language proficiency expert for {language.value}. "
        "Given a list of YouTube video titles, classify each as one of: A1, A2, B1, B2, C1, C2. "
        "Return ONLY a JSON array of strings, one per title, in the same order. "
        "Example: [\"A2\", \"B1\", \"C1\"]"
    )

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": titles_block},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )

    import json
    content = response.choices[0].message.content or "[]"
    # The model returns {"levels": [...]} or similar — handle both
    parsed = json.loads(content)
    levels_raw: list[str] = parsed if isinstance(parsed, list) else list(parsed.values())[0]

    return [
        ProficiencyLevel(lvl) if lvl in ProficiencyLevel._value2member_map_ else ProficiencyLevel.B1
        for lvl in levels_raw[:len(titles)]
    ]
