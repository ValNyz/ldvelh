"""
LDVELH - Tooltips API Routes
Entity annotations for inline tooltips + entity detail lookup, by entity id (spec §4.9).
"""

from uuid import UUID
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.dependencies import get_pool, get_current_user
from services import tooltips
from services.game_service import GameService

router = APIRouter(tags=["tooltips"])

# The most entity ids one batch tooltip request may ask for.
MAX_TOOLTIP_IDS = 100


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
    limit: int = Query(default=10, ge=1, le=50),
    before: Optional[int] = Query(default=None),
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """Return the stored mentions of the latest annotated assistant messages; with
    `before` (a sequence), of the page of older ones.

    The frontend polls this after each turn: the mentions are written by the resolver.
    It pages back with `before` to cover the older messages it shows.
    """
    await GameService(pool).verify_ownership(game_id, user["id"])
    async with pool.acquire() as conn:
        messages = await tooltips.message_annotations(conn, game_id, limit, before)
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


def _entity_ids(ids: str) -> list[UUID]:
    """The ids of a comma-separated list: at least one, at most MAX_TOOLTIP_IDS, each a
    UUID (else 422)."""
    try:
        parsed = [UUID(part) for part in ids.split(",") if part.strip()]
    except ValueError:
        raise HTTPException(status_code=422, detail="ids: not a list of UUIDs")
    if not parsed or len(parsed) > MAX_TOOLTIP_IDS:
        raise HTTPException(
            status_code=422, detail=f"ids: between 1 and {MAX_TOOLTIP_IDS} ids"
        )
    return list(dict.fromkeys(parsed))


@router.get("/tooltips/entities")
async def get_entity_tooltips(
    game_id: UUID = Query(..., alias="gameId"),
    ids: str = Query(..., description="Comma-separated entity or arc ids"),
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """Return the tooltips of several entities (or arcs) of the game in one request,
    by the id asked for (ruling R52); an id that is no entity nor arc of the game is
    absent from `tooltips`."""
    entity_ids = _entity_ids(ids)
    await GameService(pool).verify_ownership(game_id, user["id"])
    async with pool.acquire() as conn:
        found = await tooltips.get_entities_details(conn, entity_ids, game_id=game_id)
    return {
        "tooltips": {
            str(i): TooltipInfo(**tooltip).model_dump() for i, tooltip in found.items()
        }
    }
