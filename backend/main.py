"""
LDVELH - FastAPI Application
Point d'entrée principal
"""

import os
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings

import logging

logging.basicConfig(level=logging.INFO)

# Pool de connexions global
db_pool: asyncpg.Pool | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestion du cycle de vie de l'application"""
    global db_pool

    settings = get_settings()

    # Startup: créer le pool de connexions
    print("[STARTUP] Connexion à la base de données...")
    db_pool = await asyncpg.create_pool(
        settings.database_url, min_size=2, max_size=10, command_timeout=60
    )
    print("[STARTUP] Pool de connexions créé")

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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db_pool() -> asyncpg.Pool:
    """Récupère le pool de connexions"""
    if db_pool is None:
        raise RuntimeError("Database pool not initialized")
    return db_pool


# Import des routes après la création de l'app pour éviter les imports circulaires
from api.routes import router

app.include_router(router, prefix="/api")


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
