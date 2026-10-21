"""Tooltips and annotations (spec §4.9): what the player may read of the entities a
narration mentions, by id.

Annotations are the stored mentions (`entity_mentions`) of the latest narrator messages,
on the live entity (merges followed), labelled with what the player may read
(display_for_player, never a secret name). A tooltip is read by id: an NPC the
protagonist has not identified shows its descriptor and observable details only (species,
mood, ambient), never its occupation, description or relations; an entity with nothing
readable shows the language pack's unknown label and nothing else. An id that is no entity
nor arc of the game is the only "not found".
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from uuid import UUID

from config import get_identity_config
from packs.loader import load_lang
from repos import entities
from repos.entities import TooltipRow

CHARACTER = "character"
ARC = "arc"

TYPE_ICONS = {
    "character": "👤",
    "protagonist": "👤",
    "companion": "👤",
    "location": "📍",
    "organization": "🏢",
    "object": "📦",
    ARC: "📖",
}
_UNKNOWN_ICON = "❓"
_AMBIENT = "ambient"

# The detail lines of a tooltip, per entity type: (detail key, label), a free text (no
# label) cut at FREE_TEXT_CHARS characters.
_TOOLTIP_INFOS = {
    "character": (
        ("occupation", "Métier"),
        ("species", "Espèce"),
        ("mood", "Humeur"),
        (_AMBIENT, None),
    ),
    "location": (
        ("location_type", "Type"),
        ("sector", "Secteur"),
        ("atmosphere", "Ambiance"),
    ),
    "organization": (("org_type", "Type"), ("domain", "Domaine")),
    "object": (("category", "Catégorie"), ("description", None)),
    ARC: (("domain", "Domaine"),),
}
FREE_TEXT_CHARS = 80
# A species not worth a line: the default one.
_DEFAULT_SPECIES = "human"
# What the tooltip of an NPC the protagonist has not identified may show: what anyone
# can observe (spec §4.9); its occupation, description and relations may name it.
_OBSERVABLE = frozenset({"species", "mood", _AMBIENT})


@dataclass(frozen=True)
class Tooltip:
    """A tooltip as the frontend shows it."""

    icon: str
    name: str
    type: str
    infos: list[str] = field(default_factory=list)
    relation: str | None = None


def _infos(entity_type: str, details: dict, shown: frozenset[str] | None) -> list[str]:
    """The detail lines of `details` for the type (`shown`: the keys allowed, None for
    all of them)."""
    infos = []
    for key, label in _TOOLTIP_INFOS.get(entity_type, ()):
        value = details.get(key)
        if shown is not None and key not in shown:
            continue
        if not value or (key == "species" and value == _DEFAULT_SPECIES):
            continue
        infos.append(f"{label}: {value}" if label else value[:FREE_TEXT_CHARS])
    return infos


def _identified(row: TooltipRow) -> bool:
    """A character the protagonist knows by its true name, which is no secret name."""
    details = row.details
    return bool(
        details.get("known_by_protagonist")
        and details.get("true_name")
        and not row.label_secret
    )


def _entity_tooltip(row: TooltipRow, unknown_label: str) -> Tooltip:
    """The tooltip of a live entity, by the visibility rules of spec §4.9."""
    icon = TYPE_ICONS.get(row.entity_type, _UNKNOWN_ICON)
    if row.label is None:
        # Nothing readable (a whole secret): neither its name nor any detail.
        return Tooltip(icon, unknown_label, row.entity_type)
    if row.entity_type != CHARACTER or _identified(row):
        return Tooltip(
            icon,
            row.label,
            row.entity_type,
            _infos(row.entity_type, row.details, None),
            row.relation_type if row.entity_type == CHARACTER else None,
        )
    shown = _OBSERVABLE - {_AMBIENT} if row.ambient_names_hidden else _OBSERVABLE
    return Tooltip(
        icon, row.label, row.entity_type, _infos(CHARACTER, row.details, shown)
    )


async def _unknown_label(conn, game_id: UUID) -> str:
    language, _ = await entities.game_language(conn, game_id)
    return load_lang(
        language or get_identity_config().default_language
    ).unknown_character_label


async def get_entity_details(conn, entity_id: UUID, *, game_id: UUID) -> dict | None:
    """The tooltip of the entity or arc `entity_id` of the game (a merge tombstone gives
    the entity it was merged into), as a dict; None when the id is neither."""
    row = await entities.tooltip_row(conn, game_id, entity_id)
    if row is not None:
        unknown = await _unknown_label(conn, game_id) if row.label is None else ""
        return asdict(_entity_tooltip(row, unknown))
    arc = await entities.arc_tooltip_row(conn, game_id, entity_id)
    if arc is None:
        return None
    return asdict(Tooltip(TYPE_ICONS[ARC], arc["title"], ARC, _infos(ARC, arc, None)))


async def message_annotations(conn, game_id: UUID, limit: int) -> list[dict]:
    """The annotated narrator messages, latest first: {message_id, sequence,
    annotations: [{start, end, entity_id, entity_type, label}]}; a mention with nothing
    readable is left out, and so is a message left without any."""
    recent = await entities.annotated_messages(conn, game_id, limit)
    mentions = await entities.mentions_for_messages(
        conn, game_id, [message_id for message_id, _ in recent]
    )
    messages = []
    for message_id, sequence in recent:
        annotations = [
            {
                "start": m.start_pos,
                "end": m.end_pos,
                "entity_id": m.entity_id,
                "entity_type": m.entity_type,
                "label": m.label,
            }
            for m in mentions.get(message_id, [])
            if m.label is not None
        ]
        if annotations:
            messages.append(
                {
                    "message_id": message_id,
                    "sequence": sequence,
                    "annotations": annotations,
                }
            )
    return messages
