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
from config import get_identity_config
from packs.loader import load_lang
from repos import entities as entity_repo
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
    """A single entity span in a message.

    `label` is what the player may read for the entity (display_for_player). A span whose
    label no longer resolves keeps the resolver's label, except a character's: that label
    may be a hidden true name, so it becomes the language pack's unknown label.
    `entity_id`/`handle` identify the entity (None when unresolved); `surface` is the text
    of the span in the narration, which the client tags.
    """

    start: int
    end: int
    label: str
    entity_type: str
    entity_id: UUID | None = None
    handle: int | None = None
    surface: str | None = None


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
    await GameService(pool).verify_ownership(game_id, user["id"])
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, sequence, content, narrator_context
               FROM messages
               WHERE game_id = $1
                 AND role = 'assistant'
                 AND narrator_context IS NOT NULL
               ORDER BY sequence DESC
               LIMIT $2""",
            game_id, limit,
        )

    parsed = []
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
        spans = [ann for ann in raw if isinstance(ann, list) and len(ann) >= 4]
        if spans:
            parsed.append((row, spans))

    async with pool.acquire() as conn:
        resolved = await _resolve_spans(
            conn, game_id, [(ann[2], ann[3]) for _, spans in parsed for ann in spans]
        )
        language, _ = await entity_repo.game_language(conn, game_id)
    unknown_label = load_lang(
        language or get_identity_config().default_language
    ).unknown_character_label

    messages = []
    for row, spans in parsed:
        annotations = [
            _annotation(row["content"], ann, resolved, unknown_label) for ann in spans
        ]
        messages.append(MessageAnnotations(
            message_id=row["id"],
            sequence=row["sequence"],
            annotations=annotations,
        ))

    return {"messages": [m.model_dump() for m in messages]}


def _annotation(
    content: str, ann: list, resolved: dict, unknown_label: str
) -> AnnotationEntry:
    """One span. A character's stored label is never sent (it may be a hidden true name):
    unresolved, it reads `unknown_label`."""
    start, end, ref, entity_type = ann[0], ann[1], ann[2], ann[3]
    found = resolved.get((ref, entity_type)) or {}
    fallback = unknown_label if entity_type == "character" else ref
    surface = None
    if isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(content):
        surface = content[start:end]
    return AnnotationEntry(
        start=start, end=end,
        label=found.get("label") or fallback, entity_type=entity_type,
        entity_id=found.get("entity_id"), handle=found.get("handle"), surface=surface,
    )


async def _resolve_spans(
    conn, game_id: UUID, refs: list[tuple[str, str]]
) -> dict[tuple[str, str], dict]:
    """{(resolver label, type): {label, entity_id, handle}} of the annotation refs. A
    resolved ref reads display_for_player; an unresolved character ref the pack's unknown
    label (never the stored label: it may be a hidden true name)."""
    pairs = list({(r, t) for r, t in refs if isinstance(r, str) and isinstance(t, str)})
    if not pairs:
        return {}
    rows = await conn.fetch(
        """SELECT ref.name, ref.entity_type, found.id AS entity_id, er.handle,
                  COALESCE(display_for_player(found.id),
                           CASE WHEN ref.entity_type = 'character'
                                THEN ldvelh_lang_params($1) ->> 'unknown_character_label'
                           END) AS label
           FROM unnest($2::text[], $3::text[]) AS ref (name, entity_type)
           CROSS JOIN LATERAL (SELECT find_entity($1, ref.name, ref.entity_type) AS id)
                AS found
           LEFT JOIN entity_registry AS er ON er.id = found.id""",
        game_id, [p[0] for p in pairs], [p[1] for p in pairs],
    )
    return {
        (r["name"], r["entity_type"]): {
            "label": r["label"], "entity_id": r["entity_id"], "handle": r["handle"],
        }
        for r in rows
    }


# Columns a tooltip reads, per entity type (the table is the type's).
_TOOLTIP_COLUMNS = {
    "character": (
        "characters",
        "occupation, species, mood, ambient, description, known_by_protagonist, true_name",
    ),
    "location": ("locations", "location_type, sector, atmosphere, ambient, description"),
    "organization": ("organizations", "org_type, domain, description, ambient"),
    "object": ("objects", "category, description"),
}


@router.get("/tooltips/entity")
async def get_entity_tooltip(
    game_id: UUID = Query(..., alias="gameId"),
    name: str = Query(...),
    entity_type: str = Query(..., alias="entityType"),
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """Return tooltip details for the entity of a type that `name` refers to.

    `name` is resolved by find_entity (label, true name, descriptor, alias, handle), the
    row is read by id; the tooltip's name is what the player may read (display_for_player).
    """
    await GameService(pool).verify_ownership(game_id, user["id"])
    details = {}
    display_name = name
    async with pool.acquire() as conn:
        entity_id = None
        if entity_type in _TOOLTIP_COLUMNS:
            entity_id = await entity_repo.find_entity(conn, game_id, name, entity_type)
        if entity_id is not None:
            table, columns = _TOOLTIP_COLUMNS[entity_type]
            row = await conn.fetchrow(
                f"""SELECT {columns} FROM {table}
                    WHERE game_id = $1 AND id = $2 AND removed_cycle IS NULL""",
                game_id, entity_id,
            )
            if row:
                details = dict(row)
                display_name = await entity_repo.display_for_player(conn, entity_id)
            if row and entity_type == "character":
                # Free text that may name a character the PC has not identified (§4.9).
                if not (details.pop("known_by_protagonist") and details.pop("true_name")):
                    details.pop("occupation", None)
                    details.pop("ambient", None)
                details.pop("true_name", None)
            if row and entity_type == "character":
                rel = await conn.fetchrow(
                    """SELECT r.type::text as relation_type
                       FROM relations r
                       WHERE r.game_id = $1 AND r.source_id = $2
                         AND r.end_cycle IS NULL
                       LIMIT 1""",
                    game_id, entity_id,
                )
                if rel:
                    details["relation_type"] = rel["relation_type"]

    if not details:
        return {"found": False, "name": name, "type": entity_type}

    tooltip = _build_tooltip_info(display_name, entity_type, details)
    return {
        "found": True,
        "tooltip": tooltip.model_dump(),
    }
