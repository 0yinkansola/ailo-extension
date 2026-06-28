"""
AILO Admin API — protected by X-Admin-Key header.

Endpoints:
  GET    /api/admin/status                 — system health + config status
  GET    /api/admin/textbooks              — list textbook slots
  POST   /api/admin/textbooks/{slot}       — upload PDF to slot (1-5)
  DELETE /api/admin/textbooks/{slot}       — clear a slot
  GET    /api/admin/catalog/{lang}         — list artists for a language
  POST   /api/admin/catalog/{lang}         — add an artist
  DELETE /api/admin/catalog/{lang}/{id}    — remove an artist
  GET    /api/admin/users                  — list registered users
  GET    /api/admin/content/preview        — today's content for both languages
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ...core.config import settings

router = APIRouter(prefix="/api/admin", tags=["admin"])

# ── Paths ─────────────────────────────────────────────────────────────────────

_DATA        = Path(__file__).parent.parent.parent / "data"
_TEXTBOOKS   = _DATA / "textbooks"
_MANIFEST    = _TEXTBOOKS / "manifest.json"
_CATALOG     = _DATA / "artist_catalog.json"

_TEXTBOOKS.mkdir(parents=True, exist_ok=True)

# ── Auth dependency ───────────────────────────────────────────────────────────

def _require_admin(x_admin_key: str = Header(default="")) -> None:
    if x_admin_key != settings.admin_key:
        raise HTTPException(status_code=401, detail="Invalid admin key.")

Auth = Depends(_require_admin)


# ── Manifest helpers ──────────────────────────────────────────────────────────

def _load_manifest() -> list[dict]:
    if not _MANIFEST.exists():
        return [{"slot": i, "title": None, "filename": None, "uploaded_at": None}
                for i in range(1, 6)]
    data = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    # Ensure 5 slots always present
    by_slot = {s["slot"]: s for s in data}
    return [by_slot.get(i, {"slot": i, "title": None, "filename": None, "uploaded_at": None})
            for i in range(1, 6)]


def _save_manifest(slots: list[dict]) -> None:
    _MANIFEST.write_text(json.dumps(slots, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Status ────────────────────────────────────────────────────────────────────

@router.get("/status", dependencies=[Auth])
async def get_status() -> dict:
    from ...services.ml_scoring_service import ml_scoring_service
    from ...services.user_service import user_service

    api_keys = {
        "spotify":  bool(settings.spotify_client_id and settings.spotify_client_secret),
        "openai":   bool(settings.openai_api_key),
        "youtube":  bool(settings.youtube_api_key),
    }
    models = {
        "spotify": ml_scoring_service._spotify is not None,
        "youtube": ml_scoring_service._youtube is not None,
    }

    return {
        "status": "ok",
        "timestamp": time.time(),
        "version": "0.2.0",
        "api_keys": api_keys,
        "models": models,
        "textbook_slots": sum(1 for s in _load_manifest() if s["filename"]),
    }


# ── Textbooks ─────────────────────────────────────────────────────────────────

@router.get("/textbooks", dependencies=[Auth])
async def list_textbooks() -> list[dict]:
    return _load_manifest()


@router.post("/textbooks/{slot}", dependencies=[Auth])
async def upload_textbook(slot: int, file: UploadFile = File(...)) -> dict:
    if slot < 1 or slot > 5:
        raise HTTPException(status_code=400, detail="Slot must be 1–5.")
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    slots = _load_manifest()
    entry = slots[slot - 1]

    # Remove old file if replacing
    if entry.get("filename"):
        old = _TEXTBOOKS / entry["filename"]
        if old.exists():
            old.unlink()

    safe_name = f"slot{slot}_{file.filename.replace(' ', '_')}"
    dest = _TEXTBOOKS / safe_name
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    title = file.filename.replace(".pdf", "").replace("_", " ")
    slots[slot - 1] = {
        "slot": slot,
        "title": title,
        "filename": safe_name,
        "uploaded_at": int(time.time()),
    }
    _save_manifest(slots)
    return slots[slot - 1]


@router.delete("/textbooks/{slot}", dependencies=[Auth])
async def delete_textbook(slot: int) -> dict:
    if slot < 1 or slot > 5:
        raise HTTPException(status_code=400, detail="Slot must be 1–5.")

    slots = _load_manifest()
    entry = slots[slot - 1]
    if entry.get("filename"):
        old = _TEXTBOOKS / entry["filename"]
        if old.exists():
            old.unlink()

    slots[slot - 1] = {"slot": slot, "title": None, "filename": None, "uploaded_at": None}
    _save_manifest(slots)
    return {"slot": slot, "cleared": True}


# ── Catalog ───────────────────────────────────────────────────────────────────

def _load_catalog() -> dict:
    return json.loads(_CATALOG.read_text(encoding="utf-8"))


def _save_catalog(data: dict) -> None:
    _CATALOG.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


@router.get("/catalog/{lang}", dependencies=[Auth])
async def get_catalog(lang: str) -> list[dict]:
    if lang not in ("fr", "es"):
        raise HTTPException(status_code=400, detail="lang must be 'fr' or 'es'.")
    cat = _load_catalog()
    artists = cat.get(lang, [])
    return [
        {
            "id":            a.get("id"),
            "name":          a.get("name"),
            "genres":        a.get("genres", []),
            "moods":         a.get("moods", []),
            "energy_level":  a.get("energy_level"),
            "valence":       a.get("valence"),
            "danceability":  a.get("danceability"),
            "proficiency_friendly": a.get("proficiency_friendly", []),
            "spotify_id":    a.get("spotify_id", ""),
        }
        for a in artists
    ]


class ArtistCreate(BaseModel):
    id: str
    name: str
    spotify_id: str = ""
    genres: list[str] = []
    moods: list[str] = []
    energy_level: float = 0.5
    valence: float = 0.5
    acousticness: float = 0.3
    danceability: float = 0.6
    proficiency_friendly: list[str] = ["B1", "B2"]
    comparable_english: list[str] = []
    description: str = ""
    lyric_complexity: str = "medium"
    slang_density: str = "medium"
    explicit: bool = False


@router.post("/catalog/{lang}", dependencies=[Auth])
async def add_artist(lang: str, artist: ArtistCreate) -> dict:
    if lang not in ("fr", "es"):
        raise HTTPException(status_code=400, detail="lang must be 'fr' or 'es'.")
    cat = _load_catalog()
    if any(a["id"] == artist.id for a in cat.get(lang, [])):
        raise HTTPException(status_code=409, detail=f"Artist id '{artist.id}' already exists.")
    entry = {**artist.model_dump(), "language": lang, "country": lang.upper()}
    cat.setdefault(lang, []).append(entry)
    _save_catalog(cat)
    return entry


@router.delete("/catalog/{lang}/{artist_id}", dependencies=[Auth])
async def delete_artist(lang: str, artist_id: str) -> dict:
    if lang not in ("fr", "es"):
        raise HTTPException(status_code=400, detail="lang must be 'fr' or 'es'.")
    cat = _load_catalog()
    before = len(cat.get(lang, []))
    cat[lang] = [a for a in cat.get(lang, []) if a["id"] != artist_id]
    if len(cat[lang]) == before:
        raise HTTPException(status_code=404, detail=f"Artist '{artist_id}' not found.")
    _save_catalog(cat)
    return {"deleted": artist_id}


# ── Users ─────────────────────────────────────────────────────────────────────

@router.get("/users", dependencies=[Auth])
async def list_users() -> list[dict]:
    from ...services.user_service import user_service
    return [
        {
            "user_id":          u.user_id[:8] + "...",
            "target_language":  u.target_language.value,
            "proficiency_level": u.proficiency_level.value,
            "interests":        [i.value for i in u.interests],
            "created_at":       u.created_at,
        }
        for u in user_service._users.values()
    ]


# ── Content preview ───────────────────────────────────────────────────────────

@router.get("/content/preview", dependencies=[Auth])
async def content_preview() -> dict:
    from ...services.content_service import content_service
    from ...models.schemas import Language, ProficiencyLevel

    result: dict[str, Any] = {}
    for lang_code in ("fr", "es"):
        lang = Language(lang_code)
        bundle = content_service.get_daily_content(lang, ProficiencyLevel.B1)
        result[lang_code] = {
            "word":   bundle.word_of_the_day.word,
            "fact":   bundle.daily_fact.title,
            "prompt": bundle.journal_prompt.prompt,
        }
    return result


# ── Public textbook listing (used by study page) ──────────────────────────────

@router.get("/textbooks/public")
async def public_textbook_list() -> list[dict]:
    """No auth required — study page uses this to show persistent books."""
    return [s for s in _load_manifest() if s["filename"]]


@router.get("/textbooks/file/{filename}")
async def serve_textbook(filename: str) -> FileResponse:
    """Serve a textbook PDF. No auth — students need to read their books."""
    path = _TEXTBOOKS / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    # Prevent path traversal
    if _TEXTBOOKS not in path.resolve().parents and path.resolve() != _TEXTBOOKS.resolve():
        raise HTTPException(status_code=400, detail="Invalid path.")
    return FileResponse(str(path), media_type="application/pdf")
