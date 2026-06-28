from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env relative to this file so the path is correct regardless of
# which directory the server process is started from.
_ENV_FILE = Path(__file__).parent.parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Existing keys ─────────────────────────────────────────────────────────
    youtube_api_key: str = ""
    openai_api_key: str = ""

    # ── Spotify OAuth ─────────────────────────────────────────────────────────
    spotify_client_id: str = ""
    spotify_client_secret: str = ""
    spotify_redirect_uri: str = "http://127.0.0.1:3000/spotify-callback"

    # ── App ───────────────────────────────────────────────────────────────────
    frontend_url: str = "http://localhost:3000"
    allowed_origins: str = "http://localhost:3000"
    cache_ttl_seconds: int = 3600
    max_results_per_topic: int = 8

    # ── Daily content ─────────────────────────────────────────────────────────
    daily_content_seed: int = 0  # 0 = use today's date as seed

    # ── Auth / JWT ────────────────────────────────────────────────────────────
    jwt_secret_key: str = "ailo-dev-secret-change-in-prod"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    # ── Admin ─────────────────────────────────────────────────────────────────
    admin_key: str = "ailo-admin"

    @property
    def origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


settings = Settings()
