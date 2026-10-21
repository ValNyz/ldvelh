"""
LDVELH - Tooltips API Routes
Entity annotations for inline tooltips + entity detail lookup, by entity id (spec §4.9).
"""

from uuid import UUID
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from api.dependencies import get_pool, get_current_user
from services import tooltips
from services.game_service import GameService

router = APIRouter(tags=["tooltips"])


# =============================================================================
# RESPONSE MODELS
# =============================================================================


class TooltipInfo(BaseModel):
    """Formatted tooltip for frontend display"""

    icon: str
    name: str
    type: str
    infos: list[str]
    relation: Optional[str] = None


class AnnotationEntry(BaseModel):
    """A stored mention in a message: offsets in the raw text, the live entity, and
    `label`, what the player may read for it (display_for_player, never a secret name)."""

    start: int
    end: int
    entity_id: UUID
    entity_type: str
    label: str


class MessageAnnotations(BaseModel):
    """Annotations for one assistant message"""

    message_id: UUID
    sequence: int
    annotations: list[AnnotationEntry]


# =============================================================================
# ROUTES
# =============================================================================


@router.get("/tooltips/annotations")
async def get_annotations(
    game_id: UUID = Query(..., alias="gameId"),
    limit: int = Query(default=10, le=50),
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """Return the stored mentions of the latest annotated assistant messages.

    The frontend polls this after each turn: the mentions are written by the resolver.
    """
    await GameService(pool).verify_ownership(game_id, user["id"])
    async with pool.acquire() as conn:
        messages = await tooltips.message_annotations(conn, game_id, limit)
    return {"messages": [MessageAnnotations(**m).model_dump() for m in messages]}


@router.get("/tooltips/entity")
async def get_entity_tooltip(
    game_id: UUID = Query(..., alias="gameId"),
    entity_id: UUID = Query(..., alias="id"),
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """Return the tooltip of an entity (or arc) of the game, by id. `found` is false only
    when the id is no entity nor arc of the game."""
    await GameService(pool).verify_ownership(game_id, user["id"])
    async with pool.acquire() as conn:
        tooltip = await tooltips.get_entity_details(conn, entity_id, game_id=game_id)
    if tooltip is None:
        return {"found": False}
    return {"found": True, "tooltip": TooltipInfo(**tooltip).model_dump()}
