"""Mechanical category rules of the identity gold corpus (ANNOTATION.md § 5.1).

The decision order is partly a function of the world and the history: PC, NEW, REVEAL,
XTYPE, GAP and EASY have conditions that the code can check, so a gold category that
contradicts them is a validation error. DESC versus PART stays a human judgement.
"""

from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from evals.identity.corpus import GoldMention, Scene, WorldEntity

PC_TYPES = frozenset({"protagonist", "companion"})
PERSON_TYPES = PC_TYPES | {"character"}
GAP_DISTANCE = 5
# Alias kinds that are names (shared names make XTYPE); descriptors are not names.
NAME_KINDS = frozenset(
    {"true_name", "label", "short", "title", "nickname", "former_name"}
)
_DETERMINERS = {
    "le", "la", "les", "un", "une", "des", "du", "ce", "cet", "cette", "ces",
    "mon", "ma", "mes", "ton", "ta", "tes", "son", "sa", "ses",
    "notre", "nos", "votre", "vos", "leur", "leurs",
}  # fmt: skip


# Personal pronouns are never mentions (documented departure from spec § 3.2, ANNOTATION § 4.1).
PERSONAL_PRONOUNS = frozenset({
    "je", "j'", "tu", "il", "elle", "on", "nous", "vous", "ils", "elles",
    "me", "m'", "te", "t'", "se", "s'", "le", "la", "les", "lui", "leur", "eux",
    "moi", "toi", "soi",
})  # fmt: skip
# Indefinite and demonstrative pronouns a resolver could link or create from: always SKIP.
INDEFINITE_PRONOUNS = frozenset({
    "quelqu'un", "quiconque", "personne", "l'un", "l'une", "l'autre", "les autres",
    "chacun", "chacune", "celui-ci", "celle-ci", "ceux-ci", "celles-ci",
    "celui-là", "celle-là", "ceux-là", "celles-là",
})  # fmt: skip
# The unambiguous ones (never a determiner or a noun): every occurrence must be annotated.
_UNAMBIGUOUS_PRONOUN_RE = re.compile(
    r"(?<![\w'’-])(quelqu['’]un|quiconque|ce(?:lui|lle|ux|lles)-(?:ci|là))(?![\w-])",
    re.IGNORECASE,
)


def _pronoun_key(surface: str) -> str:
    return surface.strip().replace("’", "'").casefold()


def pronoun_error(m: GoldMention) -> str | None:
    key = _pronoun_key(m.surface)
    if key in PERSONAL_PRONOUNS:
        return "a personal pronoun is never a mention (ANNOTATION § 4.1)"
    if key in INDEFINITE_PRONOUNS and (
        m.category != "SKIP" or m.parsed.decision != "SKIP"
    ):
        return (
            "an indefinite or demonstrative pronoun is always SKIP (ANNOTATION § 4.1)"
        )
    return None


def missing_pronoun_mentions(text: str, mentions: list[GoldMention]) -> list[str]:
    """Unambiguous indefinite/demonstrative pronouns of `text` that no mention covers."""
    starts = {m.start for m in mentions}
    return [
        f"pronoun {found.group(0)!r} at {found.start()} must be annotated SKIP"
        for found in _UNAMBIGUOUS_PRONOUN_RE.finditer(text)
        if found.start() not in starts
    ]


def strip_determiner(text: str) -> str:
    """Drop one leading determiner (« la », « l' », « ce »…), keep case and accents."""
    text = text.strip().replace("’", "'")
    if text[:2].lower() == "l'":
        return text[2:].lstrip()
    head, _, rest = text.partition(" ")
    return rest.lstrip() if head.lower() in _DETERMINERS and rest else text


def norm(text: str) -> str:
    """Comparison key: no leading determiner, lower case, no accents, single spaces."""
    decomposed = unicodedata.normalize("NFD", strip_determiner(text).casefold())
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", plain).strip()


def label_is_a_name(entity: WorldEntity) -> bool:
    """The label is a name when it is the true name or a `label` alias; otherwise a descriptor."""
    return entity.label == entity.true_name or any(
        a.kind == "label" and a.text == entity.label for a in entity.aliases
    )


def knows_no_name(entity: WorldEntity) -> bool:
    """True when the PC knows the entity only by a descriptor (it must then be `known: false`)."""
    return entity.true_name is None and not any(
        a.known and a.kind in NAME_KINDS for a in entity.aliases
    )


def entity_names(entity: WorldEntity) -> set[str]:
    """Normalized names of an entity (true name, name-like aliases, label if a name; no descriptor)."""
    names = {a.text for a in entity.aliases if a.kind in NAME_KINDS}
    names |= {n for n in (entity.true_name,) if n}
    if label_is_a_name(entity):
        names.add(entity.label)
    return {norm(n) for n in names}


def exact_names(entity: WorldEntity) -> set[str]:
    """Full names an EASY surface must equal (determiner aside): true name, or label for things."""
    kinds = {"true_name"} if entity.type in PERSON_TYPES else {"true_name", "label"}
    names = {a.text for a in entity.aliases if a.kind in kinds}
    names |= {n for n in (entity.true_name,) if n}
    if entity.type not in PERSON_TYPES and label_is_a_name(entity):
        names.add(entity.label)
    return {strip_determiner(n) for n in names}


def revealed_before(scene: Scene, m: GoldMention, entity_id: str) -> bool:
    """A REVEAL of `entity_id` precedes `m` in the narration (the entity is reintroduced)."""
    return any(
        g.category == "REVEAL" and g.parsed.entity_id == entity_id and g.start < m.start
        for g in scene.gold
    )


def is_shared_name(scene: Scene, surface: str) -> bool:
    key = norm(surface)
    return sum(key in entity_names(e) for e in scene.world) >= 2


def gap_blocker(scene: Scene, entity: WorldEntity) -> str | None:
    """Why the GAP condition does not hold for `entity` (None when it holds)."""
    if scene.turn is None:
        return "GAP needs the scene turn"
    if (
        entity.last_seen_turn is None
        or entity.last_seen_turn > scene.turn - GAP_DISTANCE
    ):
        return (
            f"GAP needs last_seen_turn <= turn - {GAP_DISTANCE} "
            f"(turn {scene.turn}, last_seen_turn {entity.last_seen_turn})"
        )
    in_history = any(
        m.parsed.entity_id == entity.id for h in scene.history for m in h.mentions
    )
    return "GAP target is mentioned in the history" if in_history else None


def _easy_error(scene: Scene, m: GoldMention, entity: WorldEntity) -> str | None:
    names = exact_names(entity)
    if m.parsed.alias_kind == "true_name":
        names |= {
            r.real_name
            for r in scene.gold_effects.reveals
            if r.ref == entity.id and r.real_name
        }
    if strip_determiner(m.surface) in names:
        return None
    return f"EASY needs the exact name or label of {entity.id!r}, determiner aside (PART otherwise)"


def _linked_category_error(
    scene: Scene, m: GoldMention, entity: WorldEntity, *, history: bool
) -> str | None:
    """XTYPE, GAP and EASY rules for a mention linked to `entity` (not PC, NEW, SKIP)."""
    shared = is_shared_name(scene, m.surface)
    if m.category == "XTYPE":
        return (
            None
            if shared
            else "XTYPE needs a name carried by at least two world entities"
        )
    if m.category in ("REVEAL", "GAP") and history:
        return f"history mentions cannot be {m.category}"
    if m.category == "REVEAL":
        return None
    if shared:
        return (
            f"category {m.category} on a name shared by several world entities (XTYPE)"
        )
    reintroduced = not history and revealed_before(scene, m, entity.id)
    if m.category == "GAP":
        if reintroduced:
            return "GAP is not allowed after a REVEAL of the same entity in the turn"
        return gap_blocker(scene, entity)
    if not history and not reintroduced and gap_blocker(scene, entity) is None:
        return f"category {m.category} but the GAP conditions hold (GAP)"
    return _easy_error(scene, m, entity) if m.category == "EASY" else None


def category_error(
    scene: Scene, m: GoldMention, *, history: bool = False
) -> str | None:
    """The first mechanical rule `m.category` breaks, or None (history: MATCH/SKIP golds only)."""
    pronoun = pronoun_error(m)
    if pronoun:
        return pronoun
    expected = m.parsed
    if expected.decision == "SKIP":
        return (
            None
            if m.category == "SKIP"
            else f"category {m.category} on a SKIP gold (SKIP)"
        )
    if m.category == "SKIP":
        return f"category SKIP on a linked gold {m.expected!r}"
    if (expected.decision == "NEW") != (m.category == "NEW"):
        return f"category {m.category} and expected {m.expected!r} disagree (NEW <=> NEW <type>)"
    if expected.decision == "NEW":
        return None
    entity = next((e for e in scene.world if e.id == expected.entity_id), None)
    if entity is None:
        return None  # reported as an unknown id
    if (entity.type in PC_TYPES) != (m.category == "PC"):
        return f"category {m.category} on a {entity.type} target (PC <=> protagonist or companion)"
    if m.category == "PC":
        return None
    return _linked_category_error(scene, m, entity, history=history)
