"""
LDVELH - FastAPI Dependencies
"""

from collections.abc import AsyncGenerator
from uuid import UUID

import asyncpg
import jwt
from fastapi import Depends, Header, HTTPException, Query

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


async def get_current_user(
    authorization: str | None = Header(None),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """Extract and validate JWT from Authorization header. Returns user dict."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")

    token = authorization[7:]  # Strip "Bearer "
    try:
        from services.auth_service import decode_token
        payload = decode_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, email, display_name, email_verified FROM users WHERE id = $1",
            UUID(user_id),
        )
    if not row:
        raise HTTPException(status_code=401, detail="User not found")

    return {
        "id": row["id"],
        "email": row["email"],
        "display_name": row["display_name"],
        "email_verified": row["email_verified"],
    }


async def validate_game_id(game_id: UUID = Query(..., alias="gameId")) -> UUID:
    """Valide et retourne l'ID de partie"""
    return game_id


async def validate_optional_game_id(game_id: UUID | None = Query(None, alias="gameId")) -> UUID | None:
    """Valide et retourne l'ID de partie optionnel"""
    return game_id
