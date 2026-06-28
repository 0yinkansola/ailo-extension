"""
AILO Backend — FastAPI application entry point.

Registers:
  - CORS middleware
  - /health endpoint
  - YouTube /recommendations router  (Chrome extension)
  - Spotify /api/spotify router      (web dashboard)
  - Content /api/content router      (daily widgets)
  - Users   /api/users router        (profiles)
"""

import time
import traceback

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.routes import recommendations
from .api.routes import spotify
from .api.routes import content
from .api.routes import users
from .api.routes import auth
from .api.routes import admin
from .core.config import settings

app = FastAPI(
    title="AILO API",
    description="Language immersion engine — YouTube recommendations, Spotify, and daily content.",
    version="0.2.0",
)


@app.exception_handler(Exception)
async def debug_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    tb = traceback.format_exc()
    try:
        print(f"\nUNHANDLED EXCEPTION on {request.method} {request.url.path}\n{tb}")
    except Exception:
        # print() itself can fail on Windows cp1252 if traceback contains non-cp1252
        # chars (e.g. emoji in video titles). Swallow silently so we still return JSON.
        pass
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "traceback": tb},
    )

# ─── CORS ─────────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Admin-Key"],
)

# ─── Routes ───────────────────────────────────────────────────────────────────

app.include_router(recommendations.router, tags=["youtube"])
app.include_router(spotify.router)
app.include_router(content.router)
app.include_router(users.router)
app.include_router(auth.router, tags=["auth"])
app.include_router(admin.router)


@app.on_event("startup")
async def startup():
    import asyncio
    from .core.database import init_db
    await asyncio.get_event_loop().run_in_executor(None, init_db)
    print("[AILO] Database initialized")


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str | float]:
    return {
        "status": "ok",
        "timestamp": time.time(),
        "version": "0.2.0",
    }
