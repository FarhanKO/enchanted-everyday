"""All runtime settings, read from the environment (or .env). No secret has a default."""

from __future__ import annotations

from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # runtime
    env: str = "dev"
    dry_run: bool = True
    timezone: str = "Asia/Dhaka"
    daily_run_cron: str = "0 5 * * *"
    approval_cutoff_hour: int = 12
    log_level: str = "INFO"

    # database
    database_url: str = "postgresql+psycopg://engine:engine@localhost:5432/engine"

    # content
    brand_dir: str = "brand"  # story bible, production style, slate
    content_language: str = "en"

    # llm
    anthropic_api_key: SecretStr | None = None
    llm_model: str = "claude-opus-5-5"
    llm_effort: str = "medium"
    daily_spend_cap_usd: float = 2.00

    # storage
    r2_account_id: str = ""
    r2_access_key_id: SecretStr | None = None
    r2_secret_access_key: SecretStr | None = None
    r2_bucket: str = "content-engine"
    r2_public_base_url: str = ""

    # telegram
    telegram_bot_token: SecretStr | None = None
    telegram_owner_id: int | None = None

    # platforms
    youtube_upload_enabled: bool = False

    # monitoring
    healthcheck_ping_url: str = ""

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@lru_cache
def get_settings() -> Settings:
    return Settings()
