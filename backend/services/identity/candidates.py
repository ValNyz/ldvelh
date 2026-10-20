"""Candidate blocking of the resolver v2 (spec §4.5.2): SQL, no LLM.

The six generators run over the whole text of a turn (the LLM finds the mentions and picks
in one call): exact forms of the text, pg_trgm on rich aliases, shared words, typos,
the scene's context and occupations. No type is excluded (the card shows it, the LLM
decides); a secret alias is never matched nor shown without an open disclosure. Every
threshold comes from IdentityConfig, every word list from the language pack.

Ranking: the best similarity a lexical generator gives (exact: 1), then the strongest
context source (CONTEXT_ORDER; the protagonist, in every scene, last), then the recency of
a mention, then the handle. `turn` holds the lexical candidates, at most
`max_candidates`; `context` the scene's entities not already in `turn`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from config import IdentityConfig
from domain.identity import Candidate, CandidateAlias, CandidateSet, SceneContext
from repos import entities
from services.identity.lexicon import Lexicon
from services.identity.normalize import Normalizer

EXACT = "exact"
TRGM = "trgm"
TOKENS = "tokens"
LEVENSHTEIN = "levenshtein"
OCCUPATION = "occupation"
# Context sources, by how strongly they tie an entity to the turn (ranking order).
CONTEXT_ORDER = (
    "present",
    "reveal",
    "location",
    "mentioned",
    "homonym",
    "planned",
    "disclosed",
    "companion",
    "protagonist",
)
_REVEAL, _PLANNED, _PROTAGONIST = "reveal", "planned", "protagonist"


@dataclass
class _Found:
    score: float = 0
    sources: set[str] = field(default_factory=set)
    context_rank: int = len(CONTEXT_ORDER)
    recency: int = 0


def _forms(text: str, max_words: int) -> list[str]:
    """Every run of at most `max_words` words of `text`: what an alias may be exactly."""
    words = text.split()
    return [
        " ".join(words[start:end])
        for start in range(len(words))
        for end in range(start + 1, min(start + max_words, len(words)) + 1)
    ]


async def block(
    conn,
    game_id: UUID,
    text: str,
    scene: SceneContext,
    *,
    config: IdentityConfig,
    normalizer: Normalizer,
    lexicon: Lexicon,
) -> CandidateSet:
    """Candidates of the entities `text` may name, and of the scene's entities."""
    disclosed = list(scene.open_disclosure_ids)
    found: dict[UUID, _Found] = {}

    def add(entity_id: UUID, source: str, score: float) -> None:
        entry = found.setdefault(entity_id, _Found())
        entry.score = max(entry.score, score)
        entry.sources.add(source)

    text_norm = await entities.norm_for_game(conn, game_id, text)
    tokens = normalizer.tokens(text, lexicon)
    max_words = await entities.alias_max_words(conn, game_id)
    exact_ids: dict[str, set[UUID]] = {}
    for entity_id, norm in await entities.candidates_exact(
        conn, game_id, _forms(text, max_words), disclosed=disclosed
    ):
        add(entity_id, EXACT, 1)
        exact_ids.setdefault(norm, set()).add(entity_id)
    for entity_id, score in await entities.candidates_trgm(
        conn, game_id, text_norm, config, disclosed=disclosed
    ):
        add(entity_id, TRGM, score)
    for entity_id, score in await entities.candidates_tokens(
        conn, game_id, tokens, disclosed=disclosed
    ):
        add(entity_id, TOKENS, score)
    for entity_id, score in await entities.candidates_levenshtein(
        conn, game_id, tokens, config, disclosed=disclosed
    ):
        add(entity_id, LEVENSHTEIN, score)
    for entity_id, score in await entities.candidates_occupation(
        conn, game_id, text_norm, config
    ):
        add(entity_id, OCCUPATION, score)
    lexical_ids = set(found)
    for entity_id, source, recency in await _context(conn, game_id, scene):
        entry = found.setdefault(entity_id, _Found())
        entry.sources.add(source)
        rank = CONTEXT_ORDER.index(source)
        if rank < entry.context_rank:
            entry.context_rank, entry.recency = rank, recency
    # The protagonist is in every scene: being present tells nothing about it.
    if (protagonist := found.get(scene.protagonist_id)) is not None:
        protagonist.context_rank = CONTEXT_ORDER.index(_PROTAGONIST)

    cards = await _cards(conn, game_id, found, disclosed)

    ranked = _ranked(found, cards)
    turn = [cards[i] for i in ranked if i in lexical_ids][: config.max_candidates]
    in_turn = {c.entity_id for c in turn}
    context = [
        cards[i]
        for i in ranked
        if i not in in_turn and found[i].context_rank < len(CONTEXT_ORDER)
    ]
    exact = {
        norm: cards[next(iter(ids))]
        for norm, ids in exact_ids.items()
        if len(ids) == 1 and next(iter(ids)) in cards
    }
    return CandidateSet(turn=turn, context=context, exact=exact)


def _ranked(found: dict[UUID, _Found], cards: dict[UUID, Candidate]) -> list[UUID]:
    """Entities with a card, best first: score, context source, recency, handle."""

    def key(entity_id: UUID) -> tuple:
        entry = found[entity_id]
        return (
            -entry.score,
            entry.context_rank,
            entry.recency,
            cards[entity_id].handle,
        )

    return sorted((i for i in found if i in cards), key=key)


async def _context(conn, game_id: UUID, scene: SceneContext):
    refs = [(_REVEAL, r) for r in scene.reveal_refs]
    refs += [(_PLANNED, r) for r in scene.planned_npc_handles]
    return await entities.candidates_context(
        conn,
        game_id,
        location_id=scene.location_id,
        present_ids=scene.present_ids,
        recent_message_ids=scene.recent_message_ids,
        refs=[(source, ref) for source, ref in refs if ref and ref.strip()],
        disclosed=scene.open_disclosure_ids,
        protagonist_id=scene.protagonist_id,
        companion_id=scene.companion_id,
    )


async def _cards(
    conn, game_id: UUID, found: dict[UUID, _Found], disclosed: list[UUID]
) -> dict[UUID, Candidate]:
    """The card of each live entity found (an id of another game or a tombstone has none)."""
    ids = list(found)
    aliases: dict[UUID, list[CandidateAlias]] = {}
    for row in await entities.candidate_aliases(
        conn, game_id, ids, disclosed=disclosed
    ):
        aliases.setdefault(row.entity_id, []).append(
            CandidateAlias(row.alias, row.alias_norm, row.kind, row.known, row.secret)
        )
    return {
        row.entity_id: Candidate(
            entity_id=row.entity_id,
            handle=row.handle,
            entity_type=row.entity_type,
            label=row.label,
            aliases=aliases.get(row.entity_id, []),
            occupation=row.occupation,
            usual_location=row.usual_location,
            last_seen_turn=row.last_seen_turn,
            description_line=row.description_line,
            score=found[row.entity_id].score,
            sources=set(found[row.entity_id].sources),
        )
        for row in await entities.candidate_cards(conn, game_id, ids)
    }
