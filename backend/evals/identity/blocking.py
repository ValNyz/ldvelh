"""Blocking candidates of each gold mention of a scene, for C@10 (#154, spec §3.4, §4.5.2).

The resolver blocks once per turn, on the whole narration, and sees every candidate of
the turn. C@10 asks for the first 10 candidates of a mention: the candidates found by
blocking on the mention's own surface (its lexical matches), then the scene's context,
then the entities the narration names exactly elsewhere (a descriptor often names an
entity the text also names), then the turn's other candidates. Each list holds world ids, best first.
"""

from __future__ import annotations

from uuid import UUID

from domain.identity import Candidate, CandidateSet
from evals.identity.corpus import Scene
from evals.identity.scorer import LINKS
from evals.identity.world_loader import scene_context
from services.identity import candidates
from services.identity.service import IdentityService


def mention_ranking(mention: CandidateSet, turn: CandidateSet) -> list[Candidate]:
    """The mention's lexical candidates, the scene's context, the entities the narration
    names exactly, then the turn's other candidates, each once."""
    named = [c for c in turn.turn if candidates.EXACT in c.sources]
    ranked, seen = [], set()
    for candidate in [*mention.turn, *mention.context, *named, *turn.turn]:
        if candidate.entity_id not in seen:
            seen.add(candidate.entity_id)
            ranked.append(candidate)
    return ranked


async def candidates_by_mention(
    conn, game_id: UUID, scene: Scene, ids: dict[str, UUID]
) -> tuple[dict[int, list[str | None]], list[str | None]]:
    """({gold start: world ids} for the gold mentions naming an existing entity, the
    world ids of the turn's candidate set) of a scene `load_world` loaded in `game_id`."""
    service = await IdentityService.for_game(conn, game_id)
    context = scene_context(scene, ids)
    world_id = {uuid: key for key, uuid in ids.items()}

    async def block(text: str) -> CandidateSet:
        return await candidates.block(
            conn,
            game_id,
            text,
            context,
            config=service.config,
            normalizer=service.normalizer,
            lexicon=service.lexicon,
        )

    turn = await block(scene.narration)
    by_mention = {}
    for mention in scene.gold:
        if mention.parsed.decision in LINKS:
            ranked = mention_ranking(await block(mention.surface), turn)
            by_mention[mention.start] = [world_id.get(c.entity_id) for c in ranked]
    return by_mention, [world_id.get(c.entity_id) for c in turn.ranked()]
