"""
LDVELH - Configuration
"""

import os
from functools import lru_cache

from pydantic import AliasChoices, Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROLLBACK_ENGINES = ("journal", "cycle")


class Settings(BaseSettings):
    """Configuration de l'application"""

    # Database
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql://user:pass@localhost:5432/ldvelh"
    )

    # Anthropic
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")

    # Mistral
    mistral_api_key: str = os.getenv("MISTRAL_API_KEY", "")

    # wandb Inference
    wandb_api_key: str = os.getenv("WANDB_API_KEY", "")

    # Nebius Token Factory
    nebius_api_key: str = os.getenv("NEBIUS_API_KEY", "")

    # Nous Research
    nous_api_key: str = os.getenv("NOUS_API_KEY", "")

    # Model catalog refresh (scripts/refresh_model_catalog.py)
    # Player account whose saved API keys are used when the server has no key.
    catalog_keys_user_email: str = ""
    # Providers whose newly working, priced models are enabled automatically
    # (comma list). Anthropic never auto-enables: its discoveries stay pending.
    catalog_auto_enable: str = "mistral,wandb,nebius,nous"

    # API Config
    max_tokens_init: int = 10000
    max_tokens_narration: int = 4000
    max_tokens_extraction: int = 3000
    max_tokens_summary: int = 500
    max_tokens_mechanical: int = 500
    max_tokens_world_enhance: int = 3000
    temperature: float = 0.8
    temperature_extraction: float = 0.3
    temperature_mechanical: float = 0.2

    # Encryption (for API key storage)
    encryption_key: str = os.getenv("ENCRYPTION_KEY", "")

    # Auth
    jwt_secret: str = ""  # JWT_SECRET, required: checked by startup_checks at startup
    jwt_algorithm: str = "HS256"
    jwt_expiry_hours: int = 72
    # Absolute session lifetime: refreshing never extends a session past this (#83).
    jwt_session_max_hours: int = 720
    registration_enabled: bool = os.getenv("REGISTRATION_ENABLED", "true").lower() == "true"
    dev_user_email: str = os.getenv("DEV_USER_EMAIL", "dev@ldvelh.local")
    dev_user_password: str = os.getenv("DEV_USER_PASSWORD", "devpassword")

    # Email (Resend)
    resend_api_key: str = os.getenv("RESEND_API_KEY", "")
    email_from: str = os.getenv("EMAIL_FROM", "noreply@yourdomain.com")
    frontend_url: str = os.getenv("FRONTEND_URL", "http://localhost:3000")

    # Reverse proxies in front of the backend that append to X-Forwarded-For (Traefik
    # on Coolify: 1). 0 ignores the header: the client IP is the TCP peer (#82).
    trusted_proxy_hops: int = 0

    # CORS
    cors_origins: str = os.getenv("CORS_ORIGINS", "http://localhost:3000")

    # Entity resolution (Phase 1 — pre-extraction disambiguation)
    max_tokens_resolution: int = 1000
    resolution_context_window: int = 10

    # Background job supervisor (#19, #94)
    # Read from their env var when Settings() is built (checked by the validators below).
    supervisor_max_running_games: int = Field(
        default=3,
        validation_alias=AliasChoices("SUPERVISOR_MAX_GAMES", "supervisor_max_running_games"))
    supervisor_drain_timeout: float = Field(
        default=20.0,
        validation_alias=AliasChoices("SUPERVISOR_DRAIN_TIMEOUT", "supervisor_drain_timeout"))
    supervisor_cancel_timeout: float = Field(
        default=10.0,
        validation_alias=AliasChoices("SUPERVISOR_CANCEL_TIMEOUT", "supervisor_cancel_timeout"))

    # Rollback (#22): "journal" replays the turn journal; "cycle" is the legacy cycle-based
    # rollback, kept one release.
    rollback_engine: str = Field(
        "journal", validation_alias=AliasChoices("ROLLBACK_ENGINE", "rollback_engine"))

    # App
    debug: bool = os.getenv("DEBUG", "false").lower() == "true"
    # Dump the narrator prompts and generated JSON at DEBUG (story text: off by default).
    log_prompts: bool = os.getenv("LOG_PROMPTS", "false").lower() == "true"

    model_config = SettingsConfigDict(env_file=".env")

    @field_validator("supervisor_max_running_games")
    @classmethod
    def _at_least_one_game(cls, value: int) -> int:
        # A zero limit would block every background job silently.
        if value < 1:
            raise ValueError(f"SUPERVISOR_MAX_GAMES must be at least 1, got {value}")
        return value

    @field_validator("supervisor_drain_timeout", "supervisor_cancel_timeout")
    @classmethod
    def _positive_timeout(cls, value: float, info: ValidationInfo) -> float:
        if not value > 0:  # also rejects NaN
            env_var = info.field_name.upper()  # these env vars match their field names
            raise ValueError(f"{env_var} must be greater than 0, got {value}")
        return value

    @field_validator("rollback_engine")
    @classmethod
    def _known_rollback_engine(cls, value: str) -> str:
        if value not in ROLLBACK_ENGINES:
            raise ValueError(
                f"ROLLBACK_ENGINE must be one of {', '.join(ROLLBACK_ENGINES)}, got {value!r}")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Constants
DEFAULT_STATS = {"energy": 4.0, "morale": 3.0, "health": 5.0, "credits": 1400}
