"""
LDVELH - Genre API Routes
CRUD for game genres (presets + user-created)
"""

from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.dependencies import get_pool, get_current_user
from repos import genres as genre_repo

router = APIRouter(tags=["genres"])


class GenreResponse(BaseModel):
    id: UUID
    slug: str
    label: str
    is_preset: bool
    tone_style: str
    friction_flavor: str
    atmosphere_guidelines: str | None
    world_type: str | None
    arrival_prompt: str | None


class GenreListItem(BaseModel):
    id: UUID
    slug: str
    label: str
    is_preset: bool
    world_type: str | None


@router.get("/genres")
async def list_genres(
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """List available genres (presets + user's custom ones)."""
    async with pool.acquire() as conn:
        genres = await genre_repo.visible_genres(conn, user["id"])
    return {"genres": genres}


@router.get("/genres/{genre_id}")
async def get_genre(
    genre_id: UUID,
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """Get full genre details."""
    async with pool.acquire() as conn:
        genre = await genre_repo.visible_genre(conn, user["id"], genre_id)
    if not genre:
        raise HTTPException(status_code=404, detail="Genre introuvable.")
    return genre
