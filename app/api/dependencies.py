"""
LDVELH - FastAPI Dependencies
Injection de dépendances
"""

from collections.abc import AsyncGenerator
from uuid import UUID

import asyncpg
from fastapi import Depends, Query

from config import Settings, get_settings


async def get_pool() -> asyncpg.Pool:
    """Récupère le pool de connexions depuis main"""
    from main import get_db_pool

    return get_db_pool()


async def get_connection(pool: asyncpg.Pool = Depends(get_pool)) -> AsyncGenerator[asyncpg.Connection, None]:
    """Fournit une connexion depuis le pool"""
    async with pool.acquire() as conn:
        yield conn


async def get_settings_dep() -> Settings:
    """Fournit les settings"""
    return get_settings()


async def validate_game_id(game_id: UUID = Query(..., alias="gameId")) -> UUID:
    """Valide et retourne l'ID de partie"""
    return game_id


async def validate_optional_game_id(game_id: UUID | None = Query(None, alias="gameId")) -> UUID | None:
    """Valide et retourne l'ID de partie optionnel"""
    return game_id
