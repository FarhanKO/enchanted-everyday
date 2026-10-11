"""All runtime settings, read from the environment (or .env). No secret has a default."""

from __future__ import annotations

from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# the story agents (role prompts in engine/llm/prompts/)
AGENT_ROLES = ("story_architect", "script_writer", "visual_director", "packager", "critic")
EFFORTS = ("low", "medium", "high", "xhigh", "max")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # runtime
    env: str = "dev"
    dry_run: bool = True
    timezone: str = "Asia/Dhaka"
    daily_run_cron: str = "0 5 * * *"
    login_check_cron: str = "0 10 * * *"  # engine.tokens: Meta and YouTube login health
    login_warn_days: int = 3  # warn this many days before Meta's data access runs out
    approval_cutoff_hour: int = 12
    log_level: str = "INFO"

    # database
    database_url: str = "postgresql+psycopg://engine:engine@localhost:5432/engine"

    # content
    brand_dir: str = "brand"  # story bible, production style, slate
    content_language: str = "en"

    # llm
    # OpenRouter (Claude through its Anthropic-compatible API) wins when both keys are set
    openrouter_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    llm_model: str = "claude-opus-5-5"
    llm_effort: str = "medium"
    # per-agent overrides, as JSON in the env, e.g. LLM_MODELS={"packager": "claude-sonnet-5-5"}
    llm_models: dict[str, str] = {}
    llm_efforts: dict[str, str] = {"script_writer": "high", "critic": "high"}
    daily_spend_cap_usd: float = 2.00

    # embeddings (local, for the near-duplicate story check)
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_cache_dir: str = ""  # empty: the library's default temp dir

    # storage
    r2_account_id: str = ""
    r2_access_key_id: SecretStr | None = None
    r2_secret_access_key: SecretStr | None = None
    r2_bucket: str = "content-engine"
    r2_public_base_url: str = ""

    # media (Phase 2): images and voice through OpenRouter, rendered locally with ffmpeg
    work_dir: str = "work"  # per-day media, and the cache that stops a retry paying twice
    image_model: str = "google/gemini-nano-banana-2.1"
    image_fallback_model: str = "google/gemini-3.1-flash-image"  # Nano Banana 2
    music_dir: str = "templates/music"  # licensed tracks + library.toml; empty means no music
    render_fps: int = 30
    render_crf: int = 20  # x264 quality for the master file; the Telegram preview is smaller

    # telegram
    telegram_bot_token: SecretStr | None = None
    telegram_owner_id: int | None = None

    # platforms
    youtube_upload_enabled: bool = False
    youtube_client_id: str = ""
    youtube_client_secret: SecretStr | None = None
    youtube_refresh_token: SecretStr | None = None  # scripts/youtube_auth.py
    meta_page_id: str = ""
    meta_ig_user_id: str = ""
    meta_page_access_token: SecretStr | None = None  # scripts/meta_tokens.py

    # monitoring
    healthcheck_ping_url: str = ""

    @field_validator("llm_models", "llm_efforts")
    @classmethod
    def _known_roles(cls, v: dict[str, str]) -> dict[str, str]:
        if unknown := set(v) - set(AGENT_ROLES):
            raise ValueError(f"unknown agent roles {sorted(unknown)}; known: {AGENT_ROLES}")
        return v

    @field_validator("llm_effort")
    @classmethod
    def _effort(cls, v: str) -> str:
        if v not in EFFORTS:
            raise ValueError(f"effort must be one of {EFFORTS}")
        return v

    @field_validator("llm_efforts")
    @classmethod
    def _efforts(cls, v: dict[str, str]) -> dict[str, str]:
        if bad := {r: e for r, e in v.items() if e not in EFFORTS}:
            raise ValueError(f"effort must be one of {EFFORTS}; got {bad}")
        return v

    def llm_for(self, role: str | None) -> tuple[str, str]:
        """(model, effort) for one agent: its override, else the default."""
        if role is None:
            return self.llm_model, self.llm_effort
        return self.llm_models.get(role, self.llm_model), self.llm_efforts.get(
            role, self.llm_effort
        )

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def llm_api_key(self) -> SecretStr | None:
        """Whichever LLM key is in use (engine.flows.build_llm)."""
        return self.openrouter_api_key or self.anthropic_api_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
