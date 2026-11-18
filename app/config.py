"""Application configuration via environment variables / .env.

Design note — Configuration Object pattern:
  Centralize env-driven settings so services never read os.environ directly.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Always resolve .env from the project root (parent of app/), not the process cwd.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"
_DEFAULT_DB = _PROJECT_ROOT / "data" / "replicon_dashboard.db"


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables and optional .env file."""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Replicon Timesheet Dashboard"
    secret_key: str = "change-me-in-production-use-a-long-random-string"
    database_url: str = f"sqlite:///{_DEFAULT_DB.as_posix()}"

    # Optional global fallback for unit tests / legacy JSON API only.
    # Dashboard users store their own token (encrypted) in SQLite.
    replicon_base_url: str = "https://na5.replicon.com"
    replicon_access_token: str = ""
    replicon_timeout_seconds: float = 30.0

    session_cookie_name: str = "replicon_session"
    session_max_age_seconds: int = 60 * 60 * 24 * 14  # 14 days

    def normalized_base_url(self) -> str:
        """Return base URL without a trailing slash."""
        return self.replicon_base_url.rstrip("/")

    def require_access_token(self) -> str:
        """Return the global access token or raise (legacy / tests only)."""
        token = (self.replicon_access_token or "").strip()
        if not token:
            raise ValueError(
                "REPLICON_ACCESS_TOKEN is required for the legacy JSON API. "
                f"Dashboard users configure a personal token instead. "
                f"Set it in the environment or in {_ENV_FILE}."
            )
        return token


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (singleton via lru_cache)."""
    return Settings()
