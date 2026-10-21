"""Tooltips and annotations (spec §4.9): what the player may read of the entities a
narration mentions, by id.

Annotations are the stored mentions (`entity_mentions`) of the latest narrator messages,
on the live entity (merges followed), labelled with what the player may read
(display_for_player, never a secret name). A tooltip is read by id: an NPC the
protagonist has not identified shows its descriptor and observable details only (species,
mood, ambient), never its occupation, description or relations; a detail whose text holds
one of the entity's hidden names is left out, whatever the entity; an entity with nothing
readable shows the language pack's unknown label and nothing else. An id that is no entity
nor arc of the game is the only "not found". Line labels and unknown labels come from the
game's language pack, the species not worth a line from its genre pack (else the identity
config).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from uuid import UUID

from config import get_identity_config
from packs.loader import load_genre, load_lang
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
_SPECIES = "species"
_DESCRIPTION = "description"

# The detail keys of a tooltip, per entity type, in display order. A free-text detail
# (_FREE_TEXT) is printed cut at FREE_TEXT_CHARS characters; another one under its label
# (the language pack's tooltip_labels).
_TOOLTIP_INFOS = {
    "character": ("occupation", _SPECIES, "mood", _AMBIENT),
    "location": ("location_type", "sector", "atmosphere"),
    "organization": ("org_type", "domain"),
    "object": ("category", _DESCRIPTION),
    ARC: ("domain",),
}
_FREE_TEXT = frozenset({_AMBIENT, _DESCRIPTION})
FREE_TEXT_CHARS = 80
# Every detail key a tooltip may print: each is checked against the entity's hidden names.
CHECKED_FIELDS = sorted({key for keys in _TOOLTIP_INFOS.values() for key in keys})
# Shown as is although it may hold a hidden name: an object's description (ruling R49.5,
# left to PR 4 task 26 by the user).
_UNFILTERED = frozenset({("object", _DESCRIPTION)})
# What the tooltip of an NPC the protagonist has not identified may show: what anyone
# can observe (spec §4.9); its occupation, description and relations may name it.
_OBSERVABLE = frozenset({_SPECIES, "mood", _AMBIENT})


@dataclass(frozen=True)
class Tooltip:
    """A tooltip as the frontend shows it."""

    icon: str
    name: str
    type: str
    infos: list[str] = field(default_factory=list)
    relation: str | None = None


@dataclass(frozen=True)
class Display:
    """What the packs of a game give a tooltip: line labels, the unknown labels (a
    character, any other entity) and the species not worth a line."""

    labels: dict[str, str]
    unknown_character: str
    unknown_entity: str
    default_species: str

    @classmethod
    def for_packs(cls, language: str | None, genre: str | None) -> Display:
        lang = load_lang(language or get_identity_config().default_language)
        return cls(
            labels=lang.tooltip_labels,
            unknown_character=lang.unknown_character_label,
            unknown_entity=lang.unknown_entity_label,
            default_species=load_genre(genre).default_species
            or get_identity_config().default_species,
        )

    def infos(
        self,
        entity_type: str,
        details: dict,
        shown: frozenset[str] | None = None,
        hidden: frozenset[str] = frozenset(),
    ) -> list[str]:
        """The detail lines of `details` for the type: `shown` the keys allowed (None:
        all of them), `hidden` the keys holding a hidden name (left out unless
        _UNFILTERED)."""
        infos = []
        for key in _TOOLTIP_INFOS.get(entity_type, ()):
            value = details.get(key)
            if shown is not None and key not in shown:
                continue
            if key in hidden and (entity_type, key) not in _UNFILTERED:
                continue
            if not value or (key == _SPECIES and value == self.default_species):
                continue
            if key in _FREE_TEXT:
                infos.append(value[:FREE_TEXT_CHARS])
            else:
                infos.append(f"{self.labels[key]}: {value}")
        return infos


def _identified(row: TooltipRow) -> bool:
    """A character the protagonist knows by its true name, which is no secret name."""
    details = row.details
    return bool(
        details.get("known_by_protagonist")
        and details.get("true_name")
        and not row.label_secret
    )


def entity_tooltip(row: TooltipRow, display: Display) -> Tooltip:
    """The tooltip of a live entity, by the visibility rules of spec §4.9."""
    icon = TYPE_ICONS.get(row.entity_type, _UNKNOWN_ICON)
    if row.label is None:
        # Nothing readable (a whole secret): neither its name nor any detail.
        unknown = (
            display.unknown_character
            if row.entity_type == CHARACTER
            else display.unknown_entity
        )
        return Tooltip(icon, unknown, row.entity_type)
    hidden = row.hidden_fields
    if row.entity_type != CHARACTER or _identified(row):
        return Tooltip(
            icon,
            row.label,
            row.entity_type,
            display.infos(row.entity_type, row.details, hidden=hidden),
            row.relation_type if row.entity_type == CHARACTER else None,
        )
    infos = display.infos(CHARACTER, row.details, _OBSERVABLE, hidden)
    return Tooltip(icon, row.label, row.entity_type, infos)


async def get_entity_details(conn, entity_id: UUID, *, game_id: UUID) -> dict | None:
    """The tooltip of the entity or arc `entity_id` of the game (a merge tombstone gives
    the entity it was merged into), as a dict; None when the id is neither."""
    display = Display.for_packs(*await entities.game_language(conn, game_id))
    row = await entities.tooltip_row(conn, game_id, entity_id, CHECKED_FIELDS)
    if row is not None:
        return asdict(entity_tooltip(row, display))
    arc = await entities.arc_tooltip_row(conn, game_id, entity_id)
    if arc is None:
        return None
    infos = display.infos(ARC, arc)
    return asdict(Tooltip(TYPE_ICONS[ARC], arc["title"], ARC, infos))


async def message_annotations(conn, game_id: UUID, limit: int) -> list[dict]:
    """The annotated narrator messages, latest first: {message_id, sequence,
    annotations: [{start, end, entity_id, entity_type, label}]}; a mention with nothing
    readable is left out (annotated_messages only counts messages with a readable one)."""
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
