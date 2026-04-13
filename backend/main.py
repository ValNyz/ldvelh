"""
LDVELH - FastAPI Application
Point d'entrée principal
"""

import asyncio
import json
import os
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings

import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def _seed_dev_user(pool: asyncpg.Pool, settings) -> None:
    """Create a dev user if it doesn't already exist (debug mode only)."""
    from services.auth_service import hash_password

    email = settings.dev_user_email
    password = settings.dev_user_password
    async with pool.acquire() as conn:
        existing = await conn.fetchval(
            "SELECT id FROM users WHERE email = $1", email
        )
        if existing:
            logger.info(f"[STARTUP] Dev user already exists: {email}")
            return
        pw_hash = hash_password(password)
        await conn.execute(
            """INSERT INTO users (email, password_hash, display_name, email_verified)
               VALUES ($1, $2, $3, true)""",
            email, pw_hash, "dev",
        )
        logger.info(f"[STARTUP] Dev user created: {email} / {password}")


# Pool de connexions global
db_pool: asyncpg.Pool | None = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestion du cycle de vie de l'application"""
    global db_pool

    settings = get_settings()

    # Validate JWT_SECRET in production
    if not settings.debug and settings.jwt_secret == "dev-secret-change-me-in-production!!":
        raise RuntimeError(
            "JWT_SECRET is still the default dev value. "
            "Set the JWT_SECRET env variable before running in production."
        )

    # Startup: créer le pool de connexions
    print("[STARTUP] Connexion à la base de données...")

    async def _init_connection(conn):
        await conn.set_type_codec(
            "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
        )

    db_pool = await asyncpg.create_pool(
        settings.database_url, min_size=2, max_size=10,
        command_timeout=60, init=_init_connection,
    )
    print("[STARTUP] Pool de connexions créé")

    # Seed dev user if debug mode is enabled
    if settings.debug:
        await _seed_dev_user(db_pool, settings)

    yield

    # Shutdown: fermer le pool
    print("[SHUTDOWN] Fermeture du pool de connexions...")
    if db_pool:
        await db_pool.close()
    print("[SHUTDOWN] Terminé")


# Création de l'application
app = FastAPI(
    title="LDVELH API",
    description="API pour le jeu de rôle narratif LDVELH",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS
_settings = get_settings()
_origins = [o.strip() for o in _settings.cors_origins.split(",")]
print(f"[STARTUP] CORS origins: {_origins}")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


def get_db_pool() -> asyncpg.Pool:
    """Récupère le pool de connexions"""
    if db_pool is None:
        raise RuntimeError("Database pool not initialized")
    return db_pool


# Import des routes après la création de l'app pour éviter les imports circulaires
from api.routes import router
from api.auth import router as auth_router
from api.tooltips import router as tooltips_router
from api.genres import router as genres_router

app.include_router(router, prefix="/api")
app.include_router(auth_router, prefix="/api/auth")
app.include_router(tooltips_router, prefix="/api")
app.include_router(genres_router, prefix="/api")


@app.get("/health")
async def health_check():
    """Health check pour Railway"""
    return {"status": "healthy", "service": "ldvelh-api"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        reload=get_settings().debug,
    )
