"""The knowledge graph written by entity id (#153, spec §4.6 C1-C14, §4.10, §4.11): every
creation goes through IdentityService, every reference is resolved before the write, and
an unresolved one is counted (`ref_dropped`), never dropped silently nor guessed."""

import json
from uuid import UUID

import pytest

from llm.session import LLMSession
from tests.prompt_examples import WORLD_GENERATION_EXAMPLE
from tests.test_llm_session import FakeProvider

pytestmark = pytest.mark.integration


async def _world(test_pool, test_user, edit=None) -> UUID:
    """A game populated from the canonical world example (`edit` changes its data)."""
    from schema import WorldGeneration
    from services.game_service import GameService

    data = json.loads(WORLD_GENERATION_EXAMPLE)
    if edit:
        edit(data)
    service = GameService(test_pool)
    game_id = await service.create_game(test_user["id"])
    await service.process_init(game_id, WorldGeneration.model_validate(data))
    return game_id


async def _run(extractor_cls, test_pool, game_id, raw_result, cycle=2) -> dict:
    """One extractor through its real write path, answering `raw_result`; its stats."""
    extractor = extractor_cls(test_pool, game_id, LLMSession.from_provider(FakeProvider()))

    async def fake_call(*_, **__):
        return raw_result, {"cost_usd": 0.0}

    extractor._call_llm = fake_call
    result = await extractor.run("texte", {}, cycle)
    return result["stats"]


async def _events(conn, game_id, kind) -> list[dict]:
    rows = await conn.fetch(
        "SELECT payload FROM identity_events WHERE game_id = $1 AND kind = $2",
        game_id,
        kind,
    )
    return [json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"]
            for r in rows]


def _fact(*refs, key="pnj:parle:quai"):
    return {"fact_type": "dialogue", "description": "Une conversation sur le quai",
            "semantic_key": key, "importance": 3,
            "participants": [{"entity_ref": ref, "role": "actor"} for ref in refs]}


async def test_unresolved_fact_participant_is_counted_not_dropped_silently(
    test_pool, test_user
):
    from services.extraction.characters import CharactersExtractor

    game_id = await _world(test_pool, test_user)
    stats = await _run(CharactersExtractor, test_pool, game_id,
                       {"facts": [_fact("PROTAGONIST", "Personne Inconnue")]})
    async with test_pool.acquire() as conn:
        facts = await conn.fetchval(
            "SELECT count(*) FROM facts WHERE game_id = $1 AND semantic_key = $2",
            game_id, "pnj:parle:quai")
        dropped = await _events(conn, game_id, "ref_dropped")
    assert stats["errors"] == [{"code": "ref_dropped", "item": "fact"}]
    assert stats["facts_created"] == 0
    # Never written without the participant it names.
    assert facts == 0
    assert dropped == [{"item": "fact", "entity_type": "any", "candidates": 0}]


async def test_unresolved_relation_end_is_an_error(test_pool, test_user):
    from services.extraction.narrative_arcs import NarrativeArcsExtractor

    game_id = await _world(test_pool, test_user)
    async with test_pool.acquire() as conn:
        before = await conn.fetchval(
            "SELECT count(*) FROM relations WHERE game_id = $1", game_id)
    stats = await _run(NarrativeArcsExtractor, test_pool, game_id, {
        "relations_created": [{"cycle": 2, "relation": {
            "source_ref": "Ossek", "target_ref": "Personne Inconnue",
            "relation_type": "knows", "level": 3}}],
        "relations_ended": [{"source_ref": "Personne Inconnue", "target_ref": "Ossek",
                             "relation_type": "knows", "cycle": 2}],
    })
    async with test_pool.acquire() as conn:
        after = await conn.fetchval(
            "SELECT count(*) FROM relations WHERE game_id = $1", game_id)
        dropped = await _events(conn, game_id, "ref_dropped")
    assert stats["errors"] == [{"code": "ref_dropped", "item": "rel_create"},
                               {"code": "ref_dropped", "item": "rel_end"}]
    assert (stats["relations_created"], stats["relations_ended"]) == (0, 0)
    assert after == before
    assert sorted(d["item"] for d in dropped) == ["rel_create", "rel_end"]


async def test_companion_can_be_a_fact_participant(test_pool, test_user):
    """F17: the companion is in the registry, so a fact or a relation can name it (by its
    name or the reserved COMPANION)."""
    from services.extraction.characters import CharactersExtractor
    from services.extraction.narrative_arcs import NarrativeArcsExtractor

    game_id = await _world(test_pool, test_user)
    stats = await _run(CharactersExtractor, test_pool, game_id,
                       {"facts": [_fact("Célimène", "PROTAGONIST", key="ia:conseille:pc")]})
    rel = await _run(NarrativeArcsExtractor, test_pool, game_id, {"relations_created": [
        {"cycle": 2, "relation": {"source_ref": "COMPANION", "target_ref": "Ossek",
                                  "relation_type": "knows", "level": 2}}]})
    async with test_pool.acquire() as conn:
        types = await conn.fetch(
            """SELECT er.entity_type FROM fact_participants fp
               JOIN facts f ON f.id = fp.fact_id
               JOIN entity_registry er ON er.id = fp.entity_id
               WHERE f.game_id = $1 AND f.semantic_key = $2""",
            game_id, "ia:conseille:pc")
        companion_relations = await conn.fetchval(
            """SELECT count(*) FROM relations r
               JOIN entity_registry er ON er.id = r.source_id
               WHERE r.game_id = $1 AND er.entity_type = 'companion'""", game_id)
    assert (stats["errors"], rel["errors"]) == ([], [])
    assert sorted(r["entity_type"] for r in types) == ["companion", "protagonist"]
    assert companion_relations == 1


async def test_world_gen_registers_every_entity_with_true_name_and_descriptor(
    test_pool, test_user
):
    from repos import entities

    def describe(data):
        data["characters"][0]["descriptor"] = "la femme au manteau gris"

    game_id = await _world(test_pool, test_user, describe)
    data = json.loads(WORLD_GENERATION_EXAMPLE)
    async with test_pool.acquire() as conn:
        registry = {
            (r["entity_type"], r["name"])
            for r in await conn.fetch(
                "SELECT entity_type, identity_bare_label(id) AS name FROM entity_registry"
                " WHERE game_id = $1 AND merged_into IS NULL", game_id)
        }
        justine = await conn.fetchrow(
            "SELECT id, true_name, descriptor, known_by_protagonist FROM characters"
            " WHERE game_id = $1 AND true_name = $2", game_id, "Justine Lépicier")
        aliases = {(a.alias, a.kind, a.source)
                   for a in await entities.list_aliases(conn, game_id, justine["id"])}
        by_descriptor = await entities.find_entity(
            conn, game_id, "la femme au manteau gris", "character")
        log = await conn.fetchrow(
            "SELECT entities_modified, errors FROM extraction_logs"
            " WHERE game_id = $1 AND cycle = 0", game_id)
    expected = {("location", data["world"]["name"]),
                ("protagonist", data["protagonist"]["name"]),
                ("companion", data["companion"]["name"])}
    expected |= {("character", c["name"]) for c in data["characters"]}
    expected |= {("location", loc["name"]) for loc in data["locations"]}
    expected |= {("organization", o["name"]) for o in data["organizations"]}
    expected |= {("object", o["name"]) for o in data["inventory"]}
    assert registry == expected
    assert (justine["true_name"], justine["descriptor"], justine["known_by_protagonist"]) \
        == ("Justine Lépicier", "la femme au manteau gris", False)
    # The derived aliases of the true name, written by the world generation.
    assert {("Lépicier", "short", "world_gen"), ("Justine", "short", "world_gen")} <= aliases
    assert by_descriptor == justine["id"]
    assert log["entities_modified"] == len(expected)
    errors = log["errors"]
    assert (json.loads(errors) if isinstance(errors, str) else errors) == []


async def test_seen_object_is_not_added_to_inventory_unless_acquired(test_pool, test_user):
    """F18: an object an extractor lists in entities_created exists, but only `acquired`
    puts it in the inventory."""
    from kg.specialized_populator import ExtractionPopulator
    from schema import EntityCreation
    from services.extraction.inventory import InventoryExtractor

    game_id = await _world(test_pool, test_user)
    populator = ExtractionPopulator(test_pool, game_id)

    async def owned(conn):
        return await conn.fetchval(
            """SELECT count(*) FROM inventory i JOIN objects o ON o.id = i.object_id
               WHERE i.game_id = $1 AND o.name = 'Clé à molette'""", game_id)

    async with test_pool.acquire() as conn:
        seen = await populator.create_extracted_entity(
            conn, [], EntityCreation(entity_type="object", name="Clé à molette"), 2)
        assert seen is not None
        assert await owned(conn) == 0
    stats = await _run(InventoryExtractor, test_pool, game_id, {"inventory_changes": [
        {"action": "acquire", "object_ref": "Clé à molette", "quantity_delta": 1}]})
    async with test_pool.acquire() as conn:
        assert await owned(conn) == 1
    assert stats["errors"] == []


async def test_extractor_update_by_descriptor_hits_the_entity(test_pool, test_user):
    """F12: an update naming a character by its descriptor writes that character."""
    from services.extraction.characters import CharactersExtractor

    game_id = await _world(test_pool, test_user)
    created = await _run(CharactersExtractor, test_pool, game_id, {"entities_created": [
        {"name": "Mara Ilen", "descriptor": "la docker balafrée",
         "data": {"mood": "calme"}}]})
    updated = await _run(CharactersExtractor, test_pool, game_id, {"entities_updated": [
        {"entity_ref": "La docker balafrée", "changes": {"mood": "furieuse"}}]}, cycle=3)
    async with test_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT true_name, mood, known_by_protagonist FROM characters"
            " WHERE game_id = $1 AND descriptor = $2", game_id, "la docker balafrée")
    assert (created["errors"], updated["errors"]) == ([], [])
    assert updated["entities_updated"] == 1
    assert tuple(row) == ("Mara Ilen", "furieuse", False)


async def test_stale_cache_cannot_drop_reveal_fact_participants(test_pool, test_user):
    """F11: a reveal and a fact naming the revealed name, in the same run: the fact's
    participant is the revealed character (resolution reads the transaction, no cache)."""
    from services.extraction.characters import CharactersExtractor

    game_id = await _world(test_pool, test_user)
    await _run(CharactersExtractor, test_pool, game_id, {"entities_created": [
        {"name": "La Kethari âgée", "known_by_protagonist": False}]})
    stats = await _run(CharactersExtractor, test_pool, game_id, {
        "entities_updated": [{"entity_ref": "la Kethari âgée", "now_known": True,
                              "real_name": "Nahle Irun-Sa"}],
        "facts": [_fact("Nahle Irun-Sa", key="nahle:se:presente")],
    }, cycle=3)
    async with test_pool.acquire() as conn:
        kethari = await conn.fetchval(
            "SELECT id FROM characters WHERE game_id = $1 AND descriptor = $2",
            game_id, "La Kethari âgée")
        participants = await conn.fetch(
            """SELECT fp.entity_id FROM fact_participants fp JOIN facts f ON f.id = fp.fact_id
               WHERE f.game_id = $1 AND f.semantic_key = $2""",
            game_id, "nahle:se:presente")
    assert stats["errors"] == []
    assert [r["entity_id"] for r in participants] == [kethari]


async def test_director_participant_unresolved_is_counted(test_pool, test_user):
    from schema.director import ArcUpdate, DirectorOutput
    from services.director_apply import apply_director_plan

    game_id = await _world(test_pool, test_user)
    plan = DirectorOutput(tension_level=3, narrator_guidance="g", arc_updates=[
        ArcUpdate(action="create", title="La dette d'Ossek", description="Une dette",
                  intensity=2, involved_entities=["Ossek", "Personne Inconnue"])])
    async with test_pool.acquire() as conn:
        assert await apply_director_plan(conn, game_id, plan, cycle=1, ig_time="10h00",
                                         source_message_id=None, turn_id=None)
        participants = await conn.fetch(
            """SELECT identity_bare_label(ap.entity_id) AS name FROM arc_participants ap
               JOIN narrative_arcs a ON a.id = ap.arc_id
               WHERE a.game_id = $1 AND a.title = $2""", game_id, "La dette d'Ossek")
        dropped = await _events(conn, game_id, "ref_dropped")
    assert [r["name"] for r in participants] == ["Ossek"]
    assert dropped == [{"item": "arc participant", "entity_type": "any", "candidates": 0}]
