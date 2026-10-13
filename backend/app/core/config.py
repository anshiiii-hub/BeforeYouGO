from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["development", "test", "production"] = Field("development", alias="BYG_ENV")
    database_url: str = Field(
        "postgresql+psycopg://byg:byg_dev_password@localhost:5432/beforeyougo", alias="DATABASE_URL"
    )
    secret_key: str | None = Field(None, alias="SECRET_KEY")
    access_token_minutes: int = Field(480, alias="ACCESS_TOKEN_MINUTES")
    cors_origins: str = Field("http://localhost:5173,http://127.0.0.1:5173", alias="CORS_ORIGINS")

    upload_dir: Path = Field(BACKEND_DIR / "storage" / "uploads", alias="UPLOAD_DIR")
    max_upload_mb: int = Field(10, alias="MAX_UPLOAD_MB")

    enable_scheduler: bool = Field(True, alias="ENABLE_SCHEDULER")
    sync_interval_hours: int = Field(12, alias="SYNC_INTERVAL_HOURS")
    sync_on_startup: bool = Field(False, alias="SYNC_ON_STARTUP")
    sync_max_attempts: int = Field(3, alias="SYNC_MAX_ATTEMPTS")
    sync_backoff_base_seconds: float = Field(2.0, alias="SYNC_BACKOFF_BASE_SECONDS")

    # ---- LLM configuration (all optional; deterministic fallback always available)
    llm_provider: Literal["auto", "anthropic", "openai_compatible", "none"] = Field("auto", alias="LLM_PROVIDER")
    anthropic_api_key: str | None = Field(None, alias="ANTHROPIC_API_KEY")
    anthropic_base_url: str = Field("https://api.anthropic.com", alias="ANTHROPIC_BASE_URL")
    anthropic_model: str = Field("claude-sonnet-5-5", alias="ANTHROPIC_MODEL")
    openai_api_key: str | None = Field(None, alias="OPENAI_API_KEY")
    openai_base_url: str = Field("https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    openai_model: str = Field("gpt-4o-mini", alias="OPENAI_MODEL")
    llm_timeout_seconds: float = Field(30.0, alias="LLM_TIMEOUT_SECONDS")
    llm_max_retries: int = Field(2, alias="LLM_MAX_RETRIES")
    llm_max_input_chars: int = Field(24000, alias="LLM_MAX_INPUT_CHARS")

    # ---- outbound fetch safety
    fetch_user_agent: str = Field("BeforeYouGo/0.1 (+event-intelligence; respectful-bot)", alias="FETCH_USER_AGENT")
    fetch_timeout_seconds: float = Field(15.0, alias="FETCH_TIMEOUT_SECONDS")
    fetch_max_bytes: int = Field(4_000_000, alias="FETCH_MAX_BYTES")
    allow_private_fetch: bool = Field(False, alias="ALLOW_PRIVATE_FETCH")  # tests only

    # ---- optional operator-configured feeds (comma separated URLs)
    ics_feed_urls: str = Field("", alias="ICS_FEED_URLS")

    stale_after_days: int = Field(14, alias="STALE_AFTER_DAYS")  # freshness policy for retrieved data
    participant_threshold: int = Field(3, alias="PARTICIPANT_CONFIRMATION_THRESHOLD")
    unverified_grace_days: int = Field(14, alias="UNVERIFIED_GRACE_DAYS")
    min_outcome_responses: int = Field(3, alias="MIN_OUTCOME_RESPONSES")

    rate_limit_per_minute_expensive: int = Field(20, alias="RATE_LIMIT_EXPENSIVE_PER_MIN")
    rate_limit_per_minute_auth: int = Field(10, alias="RATE_LIMIT_AUTH_PER_MIN")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def ics_feed_url_list(self) -> list[str]:
        return [u.strip() for u in self.ics_feed_urls.split(",") if u.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
