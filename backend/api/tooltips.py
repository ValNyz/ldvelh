"""
LDVELH - Tooltips API Routes
Entity annotations for inline tooltips + entity detail lookup.
"""

from uuid import UUID
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from api.dependencies import get_pool, get_current_user

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
    """A single entity span in a message"""

    start: int
    end: int
    canonical_name: str
    entity_type: str


class MessageAnnotations(BaseModel):
    """Annotations for one assistant message"""

    message_id: UUID
    sequence: int
    annotations: list[AnnotationEntry]


# =============================================================================
# HELPERS
# =============================================================================

TYPE_ICONS = {
    "character": "👤",
    "location": "📍",
    "organization": "🏢",
    "object": "📦",
    "arc": "📖",
}


def _build_tooltip_info(
    name: str, entity_type: str, details: dict
) -> TooltipInfo:
    """Build tooltip display info from entity details."""
    icon = TYPE_ICONS.get(entity_type, "❓")
    infos = []

    if entity_type == "character":
        if details.get("occupation"):
            infos.append(f"Métier: {details['occupation']}")
        if details.get("species") and details["species"] != "human":
            infos.append(f"Espèce: {details['species']}")
        if details.get("mood"):
            infos.append(f"Humeur: {details['mood']}")
        if details.get("ambient"):
            infos.append(details["ambient"][:80])
    elif entity_type == "location":
        if details.get("location_type"):
            infos.append(f"Type: {details['location_type']}")
        if details.get("sector"):
            infos.append(f"Secteur: {details['sector']}")
        if details.get("atmosphere"):
            infos.append(f"Ambiance: {details['atmosphere']}")
    elif entity_type == "organization":
        if details.get("org_type"):
            infos.append(f"Type: {details['org_type']}")
        if details.get("domain"):
            infos.append(f"Domaine: {details['domain']}")
    elif entity_type == "object":
        if details.get("category"):
            infos.append(f"Catégorie: {details['category']}")
        if details.get("description"):
            infos.append(details["description"][:80])

    # Add relation with protagonist if available
    relation = None
    if details.get("relation_type"):
        relation = details["relation_type"]

    return TooltipInfo(
        icon=icon, name=name, type=entity_type, infos=infos, relation=relation
    )


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
    """Return entity span annotations for recent assistant messages.

    The frontend polls this after each turn to get resolver results.
    Returns annotations for messages that have narrator_context set.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, sequence, narrator_context
               FROM messages
               WHERE game_id = $1
                 AND role = 'assistant'
                 AND narrator_context IS NOT NULL
               ORDER BY sequence DESC
               LIMIT $2""",
            game_id, limit,
        )

    messages = []
    for row in rows:
        raw = row["narrator_context"]
        if isinstance(raw, str):
            import json
            try:
                raw = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
        if not isinstance(raw, list):
            continue

        annotations = []
        for ann in raw:
            if isinstance(ann, list) and len(ann) >= 4:
                annotations.append(AnnotationEntry(
                    start=ann[0], end=ann[1],
                    canonical_name=ann[2], entity_type=ann[3],
                ))
        if annotations:
            messages.append(MessageAnnotations(
                message_id=row["id"],
                sequence=row["sequence"],
                annotations=annotations,
            ))

    return {"messages": [m.model_dump() for m in messages]}


@router.get("/tooltips/entity")
async def get_entity_tooltip(
    game_id: UUID = Query(..., alias="gameId"),
    name: str = Query(...),
    entity_type: str = Query(..., alias="entityType"),
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """Return tooltip details for a specific entity by name and type.

    Queries the current DB schema (characters, locations, etc.)
    """
    async with pool.acquire() as conn:
        details = {}

        if entity_type == "character":
            row = await conn.fetchrow(
                """SELECT name, occupation, species, mood, ambient,
                          known_by_protagonist, description
                   FROM characters
                   WHERE game_id = $1 AND LOWER(name) = LOWER($2)
                     AND removed_cycle IS NULL
                   LIMIT 1""",
                game_id, name,
            )
            if row:
                details = dict(row)
                # Check relation with protagonist
                rel = await conn.fetchrow(
                    """SELECT r.type::text as relation_type
                       FROM relations r
                       JOIN entity_registry e ON r.source_id = e.id
                       WHERE r.game_id = $1
                         AND LOWER(e.name) = LOWER($2)
                         AND r.end_cycle IS NULL
                       LIMIT 1""",
                    game_id, name,
                )
                if rel:
                    details["relation_type"] = rel["relation_type"]

        elif entity_type == "location":
            row = await conn.fetchrow(
                """SELECT name, location_type, sector, atmosphere, ambient,
                          description
                   FROM locations
                   WHERE game_id = $1 AND LOWER(name) = LOWER($2)
                     AND removed_cycle IS NULL
                   LIMIT 1""",
                game_id, name,
            )
            if row:
                details = dict(row)

        elif entity_type == "organization":
            row = await conn.fetchrow(
                """SELECT name, org_type, domain, description, ambient
                   FROM organizations
                   WHERE game_id = $1 AND LOWER(name) = LOWER($2)
                     AND removed_cycle IS NULL
                   LIMIT 1""",
                game_id, name,
            )
            if row:
                details = dict(row)

        elif entity_type == "object":
            row = await conn.fetchrow(
                """SELECT name, category, description
                   FROM objects
                   WHERE game_id = $1 AND LOWER(name) = LOWER($2)
                     AND removed_cycle IS NULL
                   LIMIT 1""",
                game_id, name,
            )
            if row:
                details = dict(row)

    if not details:
        return {"found": False, "name": name, "type": entity_type}

    tooltip = _build_tooltip_info(name, entity_type, details)
    return {
        "found": True,
        "tooltip": tooltip.model_dump(),
    }
