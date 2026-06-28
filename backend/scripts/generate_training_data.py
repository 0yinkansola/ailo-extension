"""
Generate a realistic YouTube training dataset for AILO's watch-probability model.

Key design goals:
  - interest_category == video_category is the single strongest predictor
  - subtitle_available is a major positive signal (language learners need CC)
  - engagement_score reflects real channel quality
  - Duration and speech speed are CEFR-appropriate
  - Realistic noise so the model doesn't overfit to the synthetic signal

Run from the backend/ directory:
  py -3.12 scripts/generate_training_data.py

Writes: ../../text files/youtube_training_dataset.xlsx
"""

from __future__ import annotations

import math
import random
from pathlib import Path

import openpyxl

# ── Config ────────────────────────────────────────────────────────────────────

N_ROWS   = 6000
RNG_SEED = 42

_OUT = Path(__file__).parent.parent.parent / "text files" / "youtube_training_dataset.xlsx"

# ── Domain knowledge ──────────────────────────────────────────────────────────

CATEGORIES = [
    'animation', 'arts', 'beauty', 'comedy', 'cooking',
    'education', 'fashion', 'fitness', 'gaming', 'lifestyle',
    'music', 'news', 'sports', 'technology', 'travel',
]

CEFR_LEVELS = ['A1', 'A2', 'B1', 'B2', 'C1', 'C2']
LANGUAGES   = ['fr', 'es']

# Semantically adjacent pairs — user with interest A may enjoy topic B
ADJACENT: dict[str, set[str]] = {
    'animation':  {'gaming', 'comedy', 'arts'},
    'arts':       {'music', 'education', 'animation'},
    'beauty':     {'fashion', 'lifestyle'},
    'comedy':     {'animation', 'gaming', 'lifestyle'},
    'cooking':    {'lifestyle', 'travel'},
    'education':  {'technology', 'news'},
    'fashion':    {'beauty', 'lifestyle'},
    'fitness':    {'sports', 'lifestyle'},
    'gaming':     {'technology', 'animation', 'comedy'},
    'lifestyle':  {'cooking', 'travel', 'fashion', 'fitness'},
    'music':      {'arts', 'lifestyle'},
    'news':       {'education', 'sports'},
    'sports':     {'fitness', 'news'},
    'technology': {'education', 'gaming'},
    'travel':     {'lifestyle', 'cooking'},
}

# CEFR → ideal video duration in minutes (sweet spot for comprehension + attention)
IDEAL_DURATION: dict[str, float] = {
    'A1': 3.5, 'A2': 7.0, 'B1': 12.0, 'B2': 18.0, 'C1': 25.0, 'C2': 32.0,
}

# CEFR → speech speed ceiling (words per minute) — videos above this feel fast
SPEED_CEILING: dict[str, float] = {
    'A1': 96.0, 'A2': 112.0, 'B1': 128.0, 'B2': 144.0, 'C1': 160.0, 'C2': 176.0,
}

# ── Watch-probability formula ─────────────────────────────────────────────────

def watch_probability(
    interest: str, video_cat: str, cefr: str,
    duration_min: float, speech_speed: float,
    subtitle: int, engagement: float,
    video_lang: str, target_lang: str,
    rng: random.Random,
) -> float:
    p = 0.18  # base

    # ── Interest match: biggest driver ──
    if video_cat == interest:
        p += 0.40
    elif video_cat in ADJACENT.get(interest, set()):
        p += 0.13
    else:
        p -= 0.06

    # ── Subtitles: essential for language learning ──
    if subtitle:
        p += 0.22

    # ── Language match ──
    if video_lang == target_lang:
        p += 0.10
    else:
        p -= 0.22

    # ── Duration score: rewards CEFR-appropriate length ──
    ideal = IDEAL_DURATION[cefr]
    dur_score = max(0.0, 1.0 - abs(duration_min - ideal) / 16.0)
    p += dur_score * 0.12

    # ── Speech speed: penalise videos faster than CEFR ceiling ──
    ceiling = SPEED_CEILING[cefr]
    overspeed = max(0.0, speech_speed - ceiling)
    p -= min(0.16, overspeed / 75.0)

    # ── Engagement: channel quality / view popularity ──
    p += engagement * 0.13

    # ── Realistic noise ──
    p += rng.gauss(0.0, 0.07)
    return max(0.03, min(0.97, p))


# ── Generator ─────────────────────────────────────────────────────────────────

def generate(n: int, seed: int) -> list[dict]:
    rng   = random.Random(seed)
    rows  = []
    cefr_weights = [0.08, 0.30, 0.30, 0.18, 0.09, 0.05]   # mostly A2/B1

    for i in range(n):
        cefr     = rng.choices(CEFR_LEVELS, weights=cefr_weights)[0]
        interest = rng.choice(CATEGORIES)
        lang     = rng.choice(LANGUAGES)

        # Video category — skewed toward matching user interest
        if rng.random() < 0.62:
            video_cat = interest
        elif rng.random() < 0.55:
            adj = list(ADJACENT.get(interest, {interest}))
            video_cat = rng.choice(adj)
        else:
            video_cat = rng.choice(CATEGORIES)

        # Language match: 94% correct
        video_lang = lang if rng.random() < 0.94 else ('es' if lang == 'fr' else 'fr')

        # Duration: mix of Shorts, medium, long
        dur_type = rng.choices(['short', 'medium', 'long'], weights=[0.18, 0.67, 0.15])[0]
        if dur_type == 'short':
            dur = rng.uniform(0.2, 1.8)
        elif dur_type == 'medium':
            ideal = IDEAL_DURATION[cefr]
            dur   = max(2.0, rng.gauss(ideal, 4.5))
        else:
            dur = rng.uniform(20.0, 65.0)

        # Speech speed: centred near CEFR ceiling with variance
        speed = max(50.0, rng.gauss(SPEED_CEILING[cefr] - 8.0, 24.0))

        subtitle   = 1 if rng.random() < 0.44 else 0
        engagement = min(1.0, max(0.0, rng.gauss(0.52, 0.22)))

        p = watch_probability(
            interest, video_cat, cefr,
            dur, speed, subtitle, engagement,
            video_lang, lang, rng,
        )
        watched = 1 if rng.random() < p else 0

        rows.append({
            'user_id':           rng.randint(1, 800),
            'video_id':          i + 1,
            'interest_category': interest,
            'target_language':   lang,
            'cefr':              cefr,
            'video_category':    video_cat,
            'video_language':    video_lang,
            'duration_minutes':  round(dur, 2),
            'speech_speed':      round(speed, 1),
            'subtitle_available': subtitle,
            'engagement_score':  round(engagement, 3),
            'watch_probability': round(p, 3),
            'watched':           watched,
        })

    return rows


# ── Write XLSX ────────────────────────────────────────────────────────────────

def write_xlsx(rows: list[dict], path: Path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    headers = list(rows[0].keys())
    ws.append(headers)
    for row in rows:
        ws.append([row[h] for h in headers])
    wb.save(str(path))


# ── Stats summary ─────────────────────────────────────────────────────────────

def summarise(rows: list[dict]) -> None:
    n       = len(rows)
    pos     = sum(r['watched'] for r in rows)
    sub_pos = sum(r['watched'] for r in rows if r['subtitle_available'])
    sub_n   = sum(r['subtitle_available'] for r in rows)
    mat_pos = sum(r['watched'] for r in rows if r['interest_category'] == r['video_category'])
    mat_n   = sum(1 for r in rows if r['interest_category'] == r['video_category'])

    print(f"  Total rows   : {n}")
    print(f"  Watched      : {pos} ({pos/n*100:.1f}%)")
    print(f"  Watch rate (interest match)    : {mat_pos/mat_n*100:.1f}%  (n={mat_n})")
    print(f"  Watch rate (subtitle=1)        : {sub_pos/sub_n*100:.1f}%  (n={sub_n})")
    no_sub = n - sub_n
    no_sub_pos = sum(r['watched'] for r in rows if not r['subtitle_available'])
    print(f"  Watch rate (subtitle=0)        : {no_sub_pos/no_sub*100:.1f}%  (n={no_sub})")

    dur_vals = [r['duration_minutes'] for r in rows]
    print(f"  Duration: min={min(dur_vals):.1f}  mean={sum(dur_vals)/n:.1f}  max={max(dur_vals):.1f}")

    cefr_dist = {c: sum(1 for r in rows if r['cefr']==c) for c in ['A1','A2','B1','B2','C1','C2']}
    print(f"  CEFR dist: {cefr_dist}")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"Generating {N_ROWS} rows ...")
    rows = generate(N_ROWS, RNG_SEED)
    print("Dataset stats:")
    summarise(rows)
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    write_xlsx(rows, _OUT)
    print(f"\n[OK] Saved -> {_OUT}")
    print("Run  py -3.12 scripts/train_models.py  to retrain.")
