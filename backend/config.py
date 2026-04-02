"""
LDVELH - Configuration
"""

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # API Config
    max_tokens_init: int = 10000
    max_tokens_narration: int = 4000
    max_tokens_extraction: int = 3000
    max_tokens_summary: int = 500
    temperature: float = 0.8
    temperature_extraction: float = 0.3

    # Encryption (for API key storage)
    encryption_key: str = os.getenv("ENCRYPTION_KEY", "")

    # Auth
    jwt_secret: str = os.getenv("JWT_SECRET", "dev-secret-change-me-in-production!!")
    jwt_algorithm: str = "HS256"
    jwt_expiry_hours: int = 72

    # Email (Resend)
    resend_api_key: str = os.getenv("RESEND_API_KEY", "")
    email_from: str = os.getenv("EMAIL_FROM", "noreply@yourdomain.com")
    frontend_url: str = os.getenv("FRONTEND_URL", "http://localhost:3000")

    # CORS
    cors_origins: str = os.getenv("CORS_ORIGINS", "http://localhost:3000")

    # Extraction
    extraction_interval_hours: float = float(os.getenv("EXTRACTION_INTERVAL_HOURS", "24.0"))

    # App
    debug: bool = os.getenv("DEBUG", "false").lower() == "true"

    model_config = SettingsConfigDict(env_file=".env")


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Constants
DEFAULT_STATS = {"energy": 4.0, "morale": 3.0, "health": 5.0, "credits": 1400}
