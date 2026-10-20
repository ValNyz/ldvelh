"""
LDVELH - FastAPI Dependencies
"""

from collections.abc import AsyncGenerator
from uuid import UUID

import asyncpg
import jwt
from fastapi import Depends, Header, HTTPException, Query, Request

from config import Settings, get_settings


async def get_pool(request: Request) -> asyncpg.Pool:
    """Récupère le pool de connexions posé sur app.state par le lifespan"""
    pool = getattr(request.app.state, "pool", None)
    if pool is None:
        raise RuntimeError("Database pool not initialized")
    return pool


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
        raise HTTPException(status_code=401, detail="Jeton manquant ou invalide.")

    token = authorization[7:]  # Strip "Bearer "
    from services.auth_service import InvalidSession, decode_token, session_claims
    try:
        user_id, version, session_start = session_claims(decode_token(token))
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Jeton expiré.")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Jeton invalide.")
    except InvalidSession:
        raise HTTPException(status_code=401, detail="Session expirée. Reconnecte-toi.")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT id, email, display_name, email_verified, token_version
               FROM users WHERE id = $1""",
            user_id,
        )
    if not row:
        raise HTTPException(status_code=401, detail="Utilisateur introuvable.")
    if row["token_version"] != version:  # password changed or logged out since (#83)
        raise HTTPException(status_code=401, detail="Session révoquée. Reconnecte-toi.")

    return {
        "id": row["id"],
        "email": row["email"],
        "display_name": row["display_name"],
        "email_verified": row["email_verified"],
        "token_version": version,
        "session_start": session_start,
    }


async def validate_game_id(game_id: UUID = Query(..., alias="gameId")) -> UUID:
    """Valide et retourne l'ID de partie"""
    return game_id


async def validate_optional_game_id(game_id: UUID | None = Query(None, alias="gameId")) -> UUID | None:
    """Valide et retourne l'ID de partie optionnel"""
    return game_id
