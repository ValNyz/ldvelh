"""Name model of the characters written before the identity schema (spec §5.2 step 3).

The old schema kept one `name` per character, sometimes a true name (« Tesk Vahrun-Oo »),
sometimes a description (« Kethari âgée », « Un client en bleu de travail »), next to the
`unknown_name` the protagonist saw. The migration keeps `name` as a provisional true name;
the backfill (scripts/identity_backfill.py) then classifies each character the protagonist
does not know with `classify_unknown_character`, and the dry-run report
(scripts/identity_migration_report.py) prints the same verdicts before the deploy: one
function, so the report shows exactly what the backfill will do. The words compared come
from the game's language and genre packs (Normalizer, Lexicon), never from this code.

`plan_classification` turns the verdicts of a game into the writes, homonyms included: a
character whose new label normalises like another live character's gets the internal
label suffix " (2)", " (3)"... (ruling R9; never shown to the player).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from services.identity.lexicon import Lexicon
from services.identity.normalize import Normalizer


@dataclass(frozen=True)
class Verdict:
    kind: Literal["true_name", "descriptor"]
    true_name: str | None
    descriptor: str | None
    # A single lower-case word: the rule may be wrong, the report asks to check it.
    to_check: bool


def classify_unknown_character(
    name: str, unknown_name: str | None, normalizer: Normalizer, lexicon: Lexicon
) -> Verdict:
    """`name` is a descriptor when it normalises like `unknown_name`, or does not look like
    a proper name (a leading determiner, a descriptor head as first word or, in a script
    with letter case, no capital after the first word); else it is the true name. A
    descriptor verdict keeps `unknown_name` as the descriptor when there is one."""
    name = " ".join(name.split())
    unknown = " ".join(unknown_name.split()) if unknown_name else None
    words = name.split()
    # Letter case only says something in a script that has it (the pack says so).
    to_check = (
        len(words) == 1
        and normalizer.pack.proper_name_uses_capitals
        and not name[:1].isupper()
    )
    same_as_seen = unknown is not None and normalizer.norm(name) == normalizer.norm(
        unknown
    )
    if same_as_seen or not normalizer.looks_like_proper_name(name, lexicon):
        return Verdict("descriptor", None, unknown or name, to_check)
    return Verdict("true_name", name, unknown, to_check)


@dataclass(frozen=True)
class LegacyCharacter:
    id: UUID
    name: str  # the provisional true name: the old schema's name, without label suffix
    descriptor: str | None
    # Nothing to classify: the PC knows the name, or the character has no true name.
    settled: bool
    label_suffix: str | None
    label_norm: str  # norm of the current label (name and suffix)


@dataclass(frozen=True)
class Reclassification:
    id: UUID
    verdict: Verdict
    label_suffix: str | None
    # The former name kept as a descriptor alias, when the new descriptor does not cover it.
    extra_descriptor: str | None


def label_of(base: str, suffix: str | None) -> str:
    """The internal label of an entity (any type): its name, then its homonym suffix."""
    return f"{base} ({suffix})" if suffix else base


def free_suffix(
    base: str,
    suffix: str | None,
    taken: dict[str, set[UUID]],
    normalizer: Normalizer,
) -> str | None:
    """`suffix` when the label it makes is free in `taken` (norm -> the other entities of
    the type holding it), else the first free homonym number: the n-th holder of a label is
    its homonym (n), the first keeps it bare (ruling R9). Shared by the backfill's
    reclassification and IdentityService's trap creations; SQL step c applies the same
    rule (identity_legacy_normalise)."""
    rank = len(taken.get(normalizer.norm(base), ())) + 1
    while taken.get(normalizer.norm(label_of(base, suffix))):
        suffix = str(rank)
        rank += 1
    return suffix


def plan_classification(
    characters: Iterable[LegacyCharacter], normalizer: Normalizer, lexicon: Lexicon
) -> list[tuple[LegacyCharacter, Verdict, Reclassification | None]]:
    """Verdict of every unknown character, oldest first, and the write it calls for (None
    when the character keeps its provisional model: a true name). Labels are checked
    against every other character's current label norm, updated as the plan goes."""
    characters = list(characters)
    taken: dict[str, set[UUID]] = {}
    for character in characters:
        taken.setdefault(character.label_norm, set()).add(character.id)
    plan = []
    for character in characters:
        if character.settled:
            continue
        verdict = classify_unknown_character(
            character.name, character.descriptor, normalizer, lexicon
        )
        if verdict.kind == "true_name":
            plan.append((character, verdict, None))
            continue
        taken[character.label_norm].discard(character.id)
        base = verdict.descriptor or character.name
        suffix = free_suffix(base, character.label_suffix, taken, normalizer)
        taken.setdefault(normalizer.norm(label_of(base, suffix)), set()).add(
            character.id
        )
        extra = (
            character.name
            if normalizer.norm(character.name) != normalizer.norm(base)
            else None
        )
        plan.append(
            (character, verdict, Reclassification(character.id, verdict, suffix, extra))
        )
    return plan
