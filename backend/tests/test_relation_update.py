"""#135: relations_updated filters on relation_type and reports a no-match as a failed item."""

import pytest

from schema import PROTAGONIST_REF
from tests.test_protagonist_ref import (
    populate_kira,
    protagonist_relations,
    run_extractor,
)

pytestmark = pytest.mark.integration


async def run_arcs(test_pool, game_id, payload: dict, cycle: int = 3) -> dict:
    from services.extraction.narrative_arcs import NarrativeArcsExtractor

    result, _ = await run_extractor(NarrativeArcsExtractor, test_pool, game_id, payload, cycle)
    return result["stats"]  # `success` is False as soon as one item failed


def created(source: str, target: str, rel_type: str, level: int, context: str) -> dict:
    return {"cycle": 2, "relation": {"source_ref": source, "target_ref": target,
                                     "relation_type": rel_type, "level": level,
                                     "context": context}}


async def two_relations(test_pool, test_user):
    game_id, world_gen = await populate_kira(test_pool, test_user)
    npc = world_gen.characters[0].name
    await run_arcs(test_pool, game_id, {"relations_created": [
        created(PROTAGONIST_REF, npc, "friend_of", 3, "ami"),
        created(PROTAGONIST_REF, npc, "colleague_of", 5, "collegue")]}, cycle=2)
    return game_id, npc


async def levels(test_pool, game_id, npc: str) -> dict:
    async with test_pool.acquire() as conn:
        out = {}
        for rel_type in ("friend_of", "colleague_of"):
            rows = await protagonist_relations(conn, game_id, npc, rel_type)
            out[rel_type] = [(r["level"], r["context"]) for r in rows]
        return out


async def test_update_touches_only_the_named_type(test_pool, test_user):
    game_id, npc = await two_relations(test_pool, test_user)
    stats = await run_arcs(test_pool, game_id, {"relations_updated": [
        {"source_ref": PROTAGONIST_REF, "target_ref": npc,
         "relation_type": "friend_of", "new_level": 8, "new_context": "meilleur ami"}]})
    assert stats["relations_updated"] == 1 and stats["errors"] == []
    assert await levels(test_pool, game_id, npc) == {
        "friend_of": [(8, "meilleur ami")], "colleague_of": [(5, "collegue")]}


async def test_update_normalises_the_relation_type_synonym(test_pool, test_user):
    game_id, npc = await two_relations(test_pool, test_user)
    stats = await run_arcs(test_pool, game_id, {"relations_updated": [
        {"source_ref": PROTAGONIST_REF, "target_ref": npc,
         "relation_type": "Friend", "new_level": 9}]})
    assert stats["relations_updated"] == 1 and stats["errors"] == []
    assert (await levels(test_pool, game_id, npc))["friend_of"] == [(9, "ami")]


async def test_update_with_unknown_ref_is_a_failed_item(test_pool, test_user):
    game_id, npc = await two_relations(test_pool, test_user)
    stats = await run_arcs(test_pool, game_id, {"relations_updated": [
        {"source_ref": PROTAGONIST_REF, "target_ref": "Personne Inconnue",
         "relation_type": "friend_of", "new_level": 1}]})
    assert stats["relations_updated"] == 0
    assert stats["errors"] == [{"code": "ref_dropped", "item": "rel_update"}]
    assert (await levels(test_pool, game_id, npc))["friend_of"] == [(3, "ami")]


async def test_update_of_a_missing_relation_is_a_failed_item(test_pool, test_user):
    game_id, npc = await two_relations(test_pool, test_user)
    stats = await run_arcs(test_pool, game_id, {"relations_updated": [
        {"source_ref": PROTAGONIST_REF, "target_ref": npc,
         "relation_type": "enemy_of", "new_level": 1},
        {"source_ref": PROTAGONIST_REF, "target_ref": npc,
         "relation_type": "colleague_of", "new_level": 7}]})
    assert stats["relations_updated"] == 1  # the failure does not block the next item
    assert len(stats["errors"]) == 1 and stats["errors"][0].startswith("rel_update")
    assert (await levels(test_pool, game_id, npc))["colleague_of"] == [(7, "collegue")]


async def test_update_of_an_ended_relation_is_a_failed_item(test_pool, test_user):
    game_id, npc = await two_relations(test_pool, test_user)
    await run_arcs(test_pool, game_id, {"relations_ended": [
        {"source_ref": PROTAGONIST_REF, "target_ref": npc, "relation_type": "friend_of",
         "cycle": 3}]})
    stats = await run_arcs(test_pool, game_id, {"relations_updated": [
        {"source_ref": PROTAGONIST_REF, "target_ref": npc,
         "relation_type": "friend_of", "new_level": 1}]}, cycle=4)
    assert stats["relations_updated"] == 0 and len(stats["errors"]) == 1


async def test_end_of_a_missing_relation_is_a_failed_item(test_pool, test_user):
    game_id, npc = await two_relations(test_pool, test_user)
    stats = await run_arcs(test_pool, game_id, {"relations_ended": [
        {"source_ref": PROTAGONIST_REF, "target_ref": npc, "relation_type": "enemy_of",
         "cycle": 3},
        {"source_ref": PROTAGONIST_REF, "target_ref": "Personne Inconnue",
         "relation_type": "friend_of", "cycle": 3},
        {"source_ref": PROTAGONIST_REF, "target_ref": npc, "relation_type": "Friend",
         "cycle": 3}]})
    assert stats["relations_ended"] == 1  # only the synonym "Friend" matched friend_of
    # No active enemy_of: an item failure; an unknown end: a counted unresolved ref.
    [no_relation, unresolved] = stats["errors"]
    assert no_relation.startswith("rel_end") and "Personne Inconnue" not in no_relation
    assert unresolved == {"code": "ref_dropped", "item": "rel_end"}
    async with test_pool.acquire() as conn:
        [colleague] = await protagonist_relations(conn, game_id, npc, "colleague_of")
        [friend] = await protagonist_relations(conn, game_id, npc, "friend_of")
    assert colleague["end_cycle"] is None and friend["end_cycle"] == 3
