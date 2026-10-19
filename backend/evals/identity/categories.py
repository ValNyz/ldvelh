"""Mechanical category rules of the identity gold corpus (ANNOTATION.md § 5.1).

The decision order is partly a function of the world and the history: PC, NEW, REVEAL,
XTYPE, GAP and EASY have conditions that the code can check, so a gold category that
contradicts them is a validation error. DESC versus PART stays a human judgement.
"""

from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING

from evals.identity.lexicon import Lexicon, load_lexicon

if TYPE_CHECKING:
    from evals.identity.corpus import GoldMention, Scene, WorldEntity

PC_TYPES = frozenset({"protagonist", "companion"})
PERSON_TYPES = PC_TYPES | {"character"}
THING_TYPES = frozenset({"location", "organization", "object"})
NAMEABLE_TYPES = THING_TYPES | {"character"}  # not arcs: their label is a title
GAP_DISTANCE = 5
# Alias kinds that are names (shared names make XTYPE); descriptors are not names.
NAME_KINDS = frozenset(
    {"true_name", "label", "short", "title", "nickname", "former_name"}
)
# What the surface of a repeat of an entity born in the turn can be (ANNOTATION § 5.1).
SAME_CATEGORIES = ("EASY", "PART", "DESC")


def lexicon_of(scene: Scene) -> Lexicon:
    return load_lexicon(scene.language)


def pronoun_error(m: GoldMention, lexicon: Lexicon) -> str | None:
    key = lexicon.key(m.surface)
    if key in lexicon.personal_pronouns:
        return "a personal pronoun is never a mention (ANNOTATION § 4.1)"
    if key in lexicon.indefinite_pronouns and (
        m.category != "SKIP" or m.parsed.decision != "SKIP"
    ):
        return (
            "an indefinite or demonstrative pronoun is always SKIP (ANNOTATION § 4.1)"
        )
    return None


def missing_pronoun_mentions(
    text: str, mentions: list[GoldMention], lexicon: Lexicon
) -> list[str]:
    """Unambiguous indefinite/demonstrative pronouns of `text` that no mention covers."""
    pattern = lexicon.unambiguous_pronoun_re
    if pattern is None:
        return []
    starts = {m.start for m in mentions}
    return [
        f"pronoun {found.group(0)!r} at {found.start()} must be annotated SKIP"
        for found in pattern.finditer(text)
        if found.start() not in starts
    ]


def norm(text: str, lexicon: Lexicon) -> str:
    """Comparison key: no leading determiner, lower case, no accents, single spaces."""
    decomposed = unicodedata.normalize("NFD", lexicon.strip_determiner(text).casefold())
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


def entity_names(entity: WorldEntity, lexicon: Lexicon) -> set[str]:
    """Normalized names of an entity (true name, name-like aliases, label if a name; no descriptor)."""
    names = {a.text for a in entity.aliases if a.kind in NAME_KINDS}
    names |= {n for n in (entity.true_name,) if n}
    if label_is_a_name(entity):
        names.add(entity.label)
    return {norm(n, lexicon) for n in names}


def known_names(entity: WorldEntity, lexicon: Lexicon) -> set[str]:
    """Normalized names the PC already knows (known name-like aliases, a named label)."""
    names = {a.text for a in entity.aliases if a.known and a.kind in NAME_KINDS}
    if entity.known and entity.true_name:
        names.add(entity.true_name)
    if entity.known and label_is_a_name(entity):
        names.add(entity.label)
    return {norm(n, lexicon) for n in names}


def exact_names(entity: WorldEntity, lexicon: Lexicon) -> set[str]:
    """Full names an EASY surface must equal (determiner aside): true name, or label for things."""
    kinds = {"true_name"} if entity.type in PERSON_TYPES else {"true_name", "label"}
    names = {a.text for a in entity.aliases if a.kind in kinds}
    names |= {n for n in (entity.true_name,) if n}
    if entity.type not in PERSON_TYPES and label_is_a_name(entity):
        names.add(entity.label)
    return {lexicon.strip_determiner(n) for n in names}


def revealed_before(scene: Scene, m: GoldMention, entity_id: str) -> bool:
    """A REVEAL of `entity_id` precedes `m` in the narration (the entity is reintroduced)."""
    return any(
        g.category == "REVEAL" and g.parsed.entity_id == entity_id and g.start < m.start
        for g in scene.gold
    )


def is_shared_name(scene: Scene, surface: str) -> bool:
    lexicon = lexicon_of(scene)
    key = norm(surface, lexicon)
    return sum(key in entity_names(e, lexicon) for e in scene.world) >= 2


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
    lexicon = lexicon_of(scene)
    names = exact_names(entity, lexicon)
    if m.parsed.alias_kind == "true_name":
        names |= {
            lexicon.strip_determiner(r.real_name)
            for r in scene.gold_effects.reveals
            if r.ref == entity.id and r.real_name
        }
    if lexicon.strip_determiner(m.surface) in names:
        return None
    return f"EASY needs the exact name or label of {entity.id!r}, determiner aside (PART otherwise)"


def _form_error(
    scene: Scene, m: GoldMention, entity: WorldEntity, *, reintroduced: bool
) -> str | None:
    """Rulings on name forms (ANNOTATION § 13): nameless targets, revealed and new names."""
    expected = m.parsed
    lexicon = lexicon_of(scene)
    if (
        m.category == "PART"
        and entity.type in NAMEABLE_TYPES
        and not entity.known
        and not reintroduced
    ):
        return (
            f"PART on {entity.id!r}, whose name the PC does not know: "
            "a designation of a nameless entity is DESC"
        )
    if (
        m.category == "PART"
        and reintroduced
        and norm(m.surface, lexicon) not in known_names(entity, lexicon)
        and (
            expected.decision != "ALIAS"
            or expected.alias_kind != "short"
            or f"MATCH {entity.id}" not in m.accept_also
        )
    ):
        return (
            "a form of a name revealed earlier in the turn is "
            f"ALIAS {entity.id} short with accept_also MATCH {entity.id}"
        )
    if expected.alias_kind == "label" and m.category == "DESC":
        return "a new label (renamed entity) is PART, not DESC"
    if expected.alias_kind == "nickname" and m.category == "PART":
        return "a fresh nickname is DESC, not PART (it uses no part of a name)"
    return None


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
    form = _form_error(scene, m, entity, reintroduced=reintroduced)
    if form:
        return form
    return _easy_error(scene, m, entity) if m.category == "EASY" else None


def _same_error(scene: Scene, m: GoldMention) -> str | None:
    """`SAME <start>`: a repeat of the NEW entity born at an earlier mention of the turn."""
    start = m.parsed.same_start
    target = next((g for g in scene.gold if g.start == start), None)
    if target is None:
        return f"{m.expected!r}: no narration gold mention starts at {start}"
    if target.start >= m.start:
        return f"{m.expected!r} must point at an earlier mention of the narration"
    if target.parsed.decision != "NEW":
        return (
            f"{m.expected!r} points at {target.surface!r}, which is not a NEW mention"
        )
    if m.category not in SAME_CATEGORIES:
        return (
            f"category {m.category} on a SAME gold "
            f"({', '.join(SAME_CATEGORIES)} by the nature of its surface)"
        )
    return None


def category_error(
    scene: Scene, m: GoldMention, *, history: bool = False
) -> str | None:
    """The first mechanical rule `m.category` breaks, or None (history: MATCH/SKIP golds only)."""
    pronoun = pronoun_error(m, lexicon_of(scene))
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
    if expected.decision == "SAME":
        return _same_error(scene, m)
    entity = next((e for e in scene.world if e.id == expected.entity_id), None)
    if entity is None:
        return None  # reported as an unknown id
    if (entity.type in PC_TYPES) != (m.category == "PC"):
        return f"category {m.category} on a {entity.type} target (PC <=> protagonist or companion)"
    if m.category == "PC":
        return None
    return _linked_category_error(scene, m, entity, history=history)
