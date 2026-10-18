"""#27: an unknown enum value is rejected or mapped to an explicit fallback, never to the
enum's first member (which used to turn a vehicle into the protagonist)."""

import logging

import pytest

from schema import PROTAGONIST_REF
from schema.core import normalize_fact_type
from tests.helpers import character_names, extractor_for
from tests.test_protagonist_ref import populate_kira, protagonist_relations, run_extractor
from tests.test_relation_update import created

pytestmark = pytest.mark.integration


async def test_unknown_entity_type_rejects_the_item_only(test_pool, test_user):
    extractor, game_id = await extractor_for(test_pool, test_user, {"entities_created": [
        {"entity_type": "vehicle", "name": "Le Corbeau"},
        {"entity_type": "character", "name": "Mira"}]})
    async with test_pool.acquire() as conn:
        before = await conn.fetchval("SELECT count(*) FROM protagonists WHERE game_id = $1",
                                     game_id)
    stats = (await extractor.run("texte", {}, 1))["stats"]

    assert stats["entities_created"] == 1
    assert len(stats["errors"]) == 1
    assert stats["errors"][0].startswith("create:") and "entity_type" in stats["errors"][0]
    async with test_pool.acquire() as conn:
        after = await conn.fetchval("SELECT count(*) FROM protagonists WHERE game_id = $1",
                                    game_id)
    assert after == before
    assert "Mira" in await character_names(test_pool, game_id)


async def test_unknown_relation_type_is_rejected_not_knows(test_pool, test_user):
    from services.extraction.narrative_arcs import NarrativeArcsExtractor

    game_id, world_gen = await populate_kira(test_pool, test_user)
    npc = world_gen.characters[0].name
    payload = {"relations_created": [created(PROTAGONIST_REF, npc, "sworn_to", 3, "serment")]}
    result, _ = await run_extractor(NarrativeArcsExtractor, test_pool, game_id, payload, 2)

    stats = result["stats"]
    assert stats["relations_created"] == 0
    assert len(stats["errors"]) == 1
    assert stats["errors"][0].startswith("rel_create:") and "relation_type" in stats["errors"][0]
    async with test_pool.acquire() as conn:
        assert not await protagonist_relations(conn, game_id, npc, "knows")


async def test_unknown_fact_type_is_stored_as_other(test_pool, test_user):
    extractor, game_id = await extractor_for(test_pool, test_user, {"facts": [
        {"fact_type": "prophecy", "description": "Une voix annonce la fin.",
         "semantic_key": "voix:annonce:fin"}]})
    stats = (await extractor.run("texte", {}, 1))["stats"]

    assert stats["errors"] == []
    async with test_pool.acquire() as conn:
        stored = await conn.fetchval(
            "SELECT type FROM facts WHERE game_id = $1 AND semantic_key = 'voix:annonce:fin'",
            game_id)
    assert stored == "other"


def test_normalizer_warning_truncates_the_value(caplog):
    with caplog.at_level(logging.WARNING):
        assert normalize_fact_type("x" * 200) == "other"
    message = caplog.records[-1].getMessage()
    assert "'xxxx" in message and len(message) < 120
