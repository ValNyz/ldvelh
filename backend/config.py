"""
LDVELH - Configuration
"""

import os
from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Configuration de l'application"""

    # Database
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql://user:pass@localhost:5432/ldvelh"
    )

    # Anthropic
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")

    # Models
    model_main: str = "claude-sonnet-4-5"
    model_extraction_heavy: str = "claude-sonnet-4-5"  # Entités, Engagements
    model_extraction_light: str = "claude-haiku-4-5"  # Faits, Relations, État, etc.
    model_summary: str = "claude-haiku-4-5"

    # API Config
    max_tokens_init: int = 10000
    max_tokens_light: int = 4000
    max_tokens_extraction_heavy: int = 3000
    max_tokens_extraction_light: int = 1500
    max_tokens_summary: int = 500
    temperature: float = 0.8
    temperature_extraction: float = 0.3

    # App
    debug: bool = os.getenv("DEBUG", "false").lower() == "true"

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Constants
STATS_DEFAUT = {"energie": 4.0, "moral": 3.0, "sante": 5.0, "credits": 1400}
