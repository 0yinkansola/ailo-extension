# AILO — Artificial Intelligence Language Orbit

> **MVP v0.1** · YouTube Immersion Extension

Transform your YouTube homepage into an immersive feed in your target language — French or Spanish — while preserving your existing content interests.

---

## Architecture

```
ailo/
├── extension/          Chrome Extension (React + TypeScript + MV3)
└── backend/            FastAPI recommendation server
```

### Data flow

```
User visits YouTube
      │
      ▼
Content script (content/index.tsx)
  ├─ Checks user settings (chrome.storage)
  ├─ If immersion ON + homepage → hides native feed
  └─ Sends GET_RECOMMENDATIONS to Background service worker
              │
              ▼
      Background (background/index.ts)
        ├─ Checks extension-side cache (chrome.storage)
        └─ If miss → POST /recommendations to FastAPI backend
                          │
                          ▼
                  FastAPI (app/main.py)
                    ├─ In-process TTLCache check
                    └─ RecommendationService
                        ├─ Builds search queries from interest→language translations
                        ├─ Calls YouTube Data API v3 (search + videos endpoints)
                        ├─ Scores results (proficiency, subtitles, recency)
                        └─ Returns ranked VideoRecommendation list
              │
              ▼
      Content script renders ImmersionFeed (React, Shadow DOM)
```

---

## Setup

### 1. Backend

```bash
cd backend
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env — add YOUTUBE_API_KEY (required) and OPENAI_API_KEY (optional)

python run.py                   # starts on http://localhost:8000
```

#### Get a YouTube Data API key

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a project → Enable **YouTube Data API v3**
3. Create an API key → paste into `.env`

### 2. Extension

```bash
cd extension
npm install
npm run build           # or `npm run dev` for watch mode
```

Then in Chrome:
1. Navigate to `chrome://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked** → select `extension/dist/`
4. Click the AILO icon in the toolbar to open settings

---

## Usage

1. Open the AILO popup (click the extension icon)
2. Select your **target language** (French or Spanish)
3. Set your **proficiency level** (A1–C2)
4. Pick your **interests** (at least one)
5. Flip the toggle to **Active**
6. Go to [youtube.com](https://youtube.com) — the homepage now shows immersive language content

The toggle in the popup turns immersion on/off instantly. Your settings are saved across sessions.

---

## Recommendation logic

| Signal | Weight |
|---|---|
| Proficiency level match (exact) | +3 |
| Proficiency within 1 level | +2 |
| Has subtitles/CC | +1 |
| Published < 6 months ago | +1 |
| Published > 2 years ago | −1 |
| Proficiency distance > 1 level | −distance |
| Random jitter (variety) | 0–0.5 |

Results are de-duplicated and capped at the requested count (default 30).

### Caching

- **Backend**: in-process TTL cache (1 hour, 256 entries)
- **Extension**: chrome.storage cache (1 hour, keyed by language+proficiency+interests)

---

## Project structure

```
extension/
├── manifest.json               MV3 manifest
├── popup.html                  Popup entry HTML
├── src/
│   ├── background/index.ts     Service worker — message router + API bridge
│   ├── content/
│   │   ├── index.tsx           Main content script — bootstraps immersion
│   │   ├── feed-replacer.ts    YouTube DOM manipulation utilities
│   │   └── components/
│   │       ├── ImmersionFeed.tsx   Main feed container
│   │       ├── VideoCard.tsx       Individual video card
│   │       ├── LoadingState.tsx    Skeleton loader
│   │       └── EmptyState.tsx      Error / empty view
│   ├── popup/
│   │   ├── index.tsx           Popup React entry
│   │   └── Popup.tsx           Settings UI
│   └── shared/
│       ├── types.ts            Shared TypeScript types
│       ├── storage.ts          chrome.storage wrapper
│       └── api.ts              Backend API client

backend/
├── app/
│   ├── main.py                 FastAPI app + CORS
│   ├── core/config.py          Pydantic settings from .env
│   ├── api/routes/
│   │   └── recommendations.py  POST /recommendations endpoint
│   ├── models/schemas.py       Pydantic request/response models
│   ├── services/
│   │   ├── youtube_service.py  YouTube Data API v3 wrapper
│   │   ├── recommendation_service.py  Scoring + ranking pipeline
│   │   └── classification_service.py  Proficiency level inference
│   └── data/
│       └── topic_translations.json  Interest → search query mappings
└── run.py                      Uvicorn server entry point
```

---

## Future modules (AILO Ecosystem)

- **Music module** — target-language playlist curation
- **Film module** — movie/cartoon recommendations with subtitle support
- **Journal module** — daily handwritten prompts
- **Foundations module** — 1,000 most common words + phrases
- **Cultural module** — idiom and cultural context lessons

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `YOUTUBE_API_KEY` | ✅ | YouTube Data API v3 key |
| `OPENAI_API_KEY` | ⬜ | For GPT-based level classification (optional) |
| `CACHE_TTL_SECONDS` | ⬜ | Backend cache TTL (default: 3600) |
| `MAX_RESULTS_PER_TOPIC` | ⬜ | YouTube results per search query (default: 5) |
